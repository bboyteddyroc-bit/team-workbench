"""Bounded, DNS-pinned HTTPS fetch for public TikTok cover images. System proxy support for known TikTok image hosts."""
import http.client
import ipaddress
import re
import socket
import ssl
import threading
import time
from concurrent.futures import Future, TimeoutError
from urllib.parse import urlsplit
from urllib.request import getproxies

import httpx

MAX_BYTES = 4_000_000
MAX_SECONDS = 20
CDN_SUFFIXES = ('tiktokcdn.com', 'tiktokcdn-row.com', 'tiktokcdn-us.com',
                'tiktokcdn-eu.com', 'byteoversea.com', 'ibytedtos.com', 'muscdn.com')
_slots = threading.BoundedSemaphore(4)


def image_url(url, *, product=False):
    """Validate without network. Product details also use ByteDance's Shop image host."""
    try:
        if not isinstance(url, str) or len(url)>4096 or not re.fullmatch(r'[!-~]+',url) or '\\' in url:
            raise ValueError()
        p = urlsplit(url)
        host = p.hostname or ''
        cdn = any(host.endswith('.' + d) for d in CDN_SUFFIXES)
        shop = product and host == 'p16-oec-sg.ibyteimg.com'
        if (p.scheme != 'https' or p.username is not None or p.password is not None
                or p.port not in (None,443) or p.fragment or not p.path.startswith('/') or not (cdn or shop)):
            raise ValueError()
        return p._replace(netloc=host)
    except (ValueError, UnicodeError):
        raise ValueError('封面地址不在允许的公开 HTTPS CDN 范围') from None


def destination(url, *, product=False):
    p = image_url(url, product=product)
    try:
        def public(ip):
            address=ipaddress.ip_address(ip)
            address=getattr(address,'ipv4_mapped',None) or address
            return address.is_global and not address.is_multicast and not getattr(address,'scope_id',None)
        addresses = socket.getaddrinfo(p.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or not all(public(a[4][0]) for a in addresses):
            raise ValueError()
        return p, tuple(dict.fromkeys(a[4][0] for a in addresses))
    except (ValueError, OSError):
        raise ValueError('封面地址未解析到公开 CDN') from None


# Only these platform-owned signing endpoints may use system proxy resolution.
_PROXY_HOSTS = {
    f'p{n}-common-sign.{domain}'
    for n in (16, 19)
    for domain in ('tiktokcdn.com', 'tiktokcdn-us.com', 'tiktokcdn-eu.com', 'tiktokcdn-row.com')
}


def proxy_image(p, proxy, deadline):
    url = p._replace(netloc=p.hostname).geturl()
    with httpx.Client(proxy=proxy, trust_env=False, follow_redirects=False, timeout=5) as client:
        with client.stream('GET', url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.tiktok.com/', 'Accept-Encoding': 'identity'}) as response:
            if response.status_code != 200 or response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
                raise ValueError('封面代理未返回图片')
            body = bytearray()
            for part in response.iter_raw(16384):
                if time.monotonic() >= deadline or len(body) + len(part) > MAX_BYTES:
                    raise ValueError('封面下载超出限制')
                body.extend(part)
            if not body:
                raise ValueError('封面为空')
            return bytes(body)


def fetch(url, *, product=False):
    if not product:
        return _fetch(url, product=False)
    # OS DNS and image response headers can block; bound the caller separately.
    # The slot is released only by the actual fetch, so timeouts do not pile up.
    image_url(url, product=True)
    if not _slots.acquire(blocking=False):
        raise ValueError('封面下载繁忙，请稍后重试')
    result = Future()
    def run():
        try:
            result.set_result(_fetch(url, product=True, slot_held=True))
        except Exception as exc:
            result.set_exception(exc)
    try:
        threading.Thread(target=run, name='product-cover', daemon=True).start()
    except Exception:
        _slots.release()
        raise
    try:
        return result.result(timeout=MAX_SECONDS)
    except TimeoutError:
        raise ValueError('商品主图下载超时') from None


def _fetch(url, *, product, slot_held=False):
    if not slot_held and not _slots.acquire(blocking=False):
        raise ValueError('封面下载繁忙，请稍后重试')
    conn = None
    response = None
    try:
        deadline = time.monotonic() + MAX_SECONDS
        p, addresses = destination(url, product=product)
        if not product and p.hostname in _PROXY_HOSTS:
            proxy = getproxies().get('https')
            if proxy:
                try:
                    return proxy_image(p, proxy, deadline)
                except (httpx.HTTPError, OSError, ValueError):
                    pass  # Fall back to the pinned direct route within the same deadline.
        def remaining():
            value = deadline - time.monotonic()
            if value <= 0:
                raise ValueError('封面下载超过总时间限制')
            return value
        # HTTPSConnection still validates the original hostname and sends original
        # SNI. The actual socket connects only to an already validated IP, preventing
        # a second DNS lookup/rebinding. A proxy must not resolve an unchecked target.
        conn = http.client.HTTPSConnection(p.hostname, 443, timeout=remaining(), context=ssl.create_default_context())
        def connect_pinned(address, timeout=None, source_address=None):
            last = None
            for ip in addresses:
                try:
                    return socket.create_connection((ip, 443), timeout=remaining(), source_address=source_address)
                except OSError as exc:
                    last = exc
            raise last or OSError('No public address')
        conn._create_connection = connect_pinned
        conn.request('GET', p.path + ('?' + p.query if p.query else '') or '/',
                     headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.tiktok.com/',
                              'Accept-Encoding': 'identity', 'Connection': 'close'})
        if conn.sock:
            conn.sock.settimeout(remaining())
        response = conn.getresponse()
        # No redirects at all: a signed URL that changes hosts needs fresh metadata.
        if response.status != 200 or response.getheader('Content-Encoding', 'identity').lower() not in ('identity', ''):
            raise ValueError('封面响应或编码不在允许范围')
        length = response.getheader('Content-Length')
        if length is not None and (not length.isdigit() or int(length) > MAX_BYTES):
            raise ValueError('封面超过下载限额')
        body = bytearray()
        # HTTPConnection may detach its socket for Connection: close responses;
        # update the response's actual socket too, so a late read cannot restart
        # a fresh 20-second timeout on every chunk.
        response_socket = getattr(getattr(getattr(response, 'fp', None), 'raw', None), '_sock', None)
        while True:
            timeout = remaining()
            if conn.sock:
                conn.sock.settimeout(timeout)
            elif response_socket is not None:
                response_socket.settimeout(timeout)
            chunk = response.read1(min(16384, MAX_BYTES + 1 - len(body)))
            if not chunk:
                break
            body.extend(chunk)
            if len(body) > MAX_BYTES:
                raise ValueError('封面超过下载限额')
        remaining()
        if not body:
            raise ValueError('封面为空')
        return bytes(body)
    except (OSError, http.client.HTTPException):
        raise ValueError('封面连接失败，请稍后重试') from None
    finally:
        try:
            if response is not None:
                response.close()
        finally:
            try:
                if conn is not None:
                    conn.close()
            finally:
                _slots.release()
