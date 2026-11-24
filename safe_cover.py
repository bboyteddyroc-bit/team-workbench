"""Bounded HTTPS fetch for public TikTok covers, with a pinned route for Shop images."""
import http.client
import ipaddress
import re
import socket
import ssl
import threading
import time
from concurrent.futures import Future, TimeoutError
from urllib.parse import urlsplit
from urllib.request import getproxies, proxy_bypass

import httpx

MAX_BYTES = 4_000_000
MAX_SECONDS = 20
CDN_SUFFIXES = ('tiktokcdn.com', 'tiktokcdn-row.com', 'tiktokcdn-us.com',
                'tiktokcdn-eu.com', 'byteoversea.com', 'ibytedtos.com', 'muscdn.com')
_slots = threading.BoundedSemaphore(4)


class CoverFetchError(ValueError):
    """Only a controlled reason/status may reach task feedback, not a signed URL."""
    def __init__(self, reason, message, status=None):
        super().__init__(message)
        self.reason, self.status = reason, status


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
        raise CoverFetchError('CdnUrlRejected', '封面地址不在允许的公开 HTTPS CDN 范围') from None


def destination(url, *, product=False):
    p = image_url(url, product=product)
    try:
        def public(ip):
            address=ipaddress.ip_address(ip)
            address=getattr(address,'ipv4_mapped',None) or address
            return (address.is_global and not address.is_multicast and not address.is_reserved
                    and not getattr(address, 'is_site_local', False) and not getattr(address, 'scope_id', None))
        addresses = socket.getaddrinfo(p.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or not all(public(a[4][0]) for a in addresses):
            raise ValueError()
        return p, tuple(dict.fromkeys(a[4][0] for a in addresses))
    except (ValueError, OSError):
        raise CoverFetchError('CdnAddressRejected', '封面地址未解析到公开 CDN') from None


# Only these platform-owned signing endpoints may use system proxy resolution.
_PROXY_HOSTS = {
    f'p{n}-common-sign.{domain}'
    for n in (16, 19)
    for domain in ('tiktokcdn.com', 'tiktokcdn-us.com', 'tiktokcdn-eu.com', 'tiktokcdn-row.com')
}


# Known public Shop photo origins. The proxy is never used for product pages,
# redirects, or arbitrary hosts on a general TikTok CDN suffix.
_SHOP_PROXY_HOSTS = frozenset(('p16-oec-sg.ibyteimg.com', 'p16-oec-ttp.tiktokcdn-us.com',
                               'p16-oec-useast8.tiktokcdn-us.com'))


def _shop_proxy(host, addresses):
    if host not in _SHOP_PROXY_HOSTS or proxy_bypass(host):
        return None
    # HTTP CONNECT targets the exact, validated public address, not an unchecked
    # hostname. Use only a configured credential-free loopback proxy.
    ip = next((ip for ip in addresses if ipaddress.ip_address(ip).version == 4), None)
    if not ip:
        return None
    value = getproxies().get('https') or ''
    if not isinstance(value, str) or not re.fullmatch(r'http://(?:127\.0\.0\.1|\[::1\]):[1-9][0-9]{0,4}/?', value, re.I):
        return None
    proxy = urlsplit(value)
    try:
        return (proxy, ip) if proxy.port else None
    except ValueError:
        return None


class _PinnedShopTunnel(http.client.HTTPSConnection):
    def __init__(self, host, proxy, ip, *, timeout, context):
        super().__init__(proxy.hostname, proxy.port, timeout=timeout, context=context)
        self._image_host = host
        self.set_tunnel(ip, 443)

    def connect(self):
        # Use the base HTTP connection for CONNECT, then verify the certificate
        # and SNI of the actual CDN hostname rather than the IP in CONNECT.
        http.client.HTTPConnection.connect(self)
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self._image_host)


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
        raise CoverFetchError('CdnBusy', '封面下载繁忙，请稍后重试')
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
        raise CoverFetchError('CdnTimeout', '商品主图下载超时') from None


def _fetch(url, *, product, slot_held=False):
    if not slot_held and not _slots.acquire(blocking=False):
        raise CoverFetchError('CdnBusy', '封面下载繁忙，请稍后重试')
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
                raise CoverFetchError('CdnTimeout', '封面下载超过总时间限制')
            return value

        context = ssl.create_default_context()
        route = _shop_proxy(p.hostname, addresses) if product else None
        if route:
            proxy, ip = route
            conn = _PinnedShopTunnel(p.hostname, proxy, ip, timeout=remaining(), context=context)
        else:
            conn = http.client.HTTPSConnection(p.hostname, 443, timeout=remaining(), context=context)

            def connect_pinned(address, timeout=None, source_address=None):
                last = None
                for ip in addresses:
                    try:
                        return socket.create_connection((ip, 443), timeout=remaining(), source_address=source_address)
                    except OSError as exc:
                        last = exc
                raise last or OSError('No public address')

            conn._create_connection = connect_pinned
        # The request host and verified TLS name are the image origin, even when
        # the TCP peer is a local proxy and the tunnel destination is an IP.
        conn.request('GET', p.path + ('?' + p.query if p.query else '') or '/',
                     headers={'Host': p.hostname, 'User-Agent': 'Mozilla/5.0',
                              'Referer': 'https://www.tiktok.com/',
                              'Accept-Encoding': 'identity', 'Connection': 'close'})
        if conn.sock:
            conn.sock.settimeout(remaining())
        response = conn.getresponse()
        # Never follow redirects or try a different photo URL.
        if response.status != 200:
            raise CoverFetchError('CdnHttpStatus', '图片 CDN 未返回主图', response.status)
        if response.getheader('Content-Encoding', 'identity').lower() not in ('identity', ''):
            raise CoverFetchError('CdnEncodingRejected', '封面响应编码不在允许范围', response.status)
        length = response.getheader('Content-Length')
        if length is not None:
            if not re.fullmatch(r'[0-9]{1,12}', length) or int(length) > MAX_BYTES:
                raise CoverFetchError('CdnSizeRejected', '封面超过下载限额', response.status)
            length = int(length)
        body = bytearray()
        while True:
            timeout = remaining()
            # Re-read the detached socket only while its file is open. A read
            # of the last byte can close the file (and socket) before the next
            # read1() returns EOF, notably on Windows with Connection: close.
            sock = conn.sock or getattr(getattr(getattr(response, 'fp', None), 'raw', None), '_sock', None)
            if sock is not None:
                sock.settimeout(timeout)
            chunk = response.read1(min(16384, MAX_BYTES + 1 - len(body)))
            if not chunk:
                break
            body.extend(chunk)
            if len(body) > MAX_BYTES:
                raise CoverFetchError('CdnSizeRejected', '封面超过下载限额', response.status)
        remaining()
        if not body:
            raise CoverFetchError('CdnEmpty', '封面为空', response.status)
        if product and length is not None and len(body) != length:
            raise CoverFetchError('CdnTruncated', '图片 CDN 响应不完整', response.status)
        return bytes(body)
    except TimeoutError:
        raise CoverFetchError('CdnTimeout', '封面下载超时', getattr(response, 'status', None)) from None
    except ssl.SSLCertVerificationError:
        raise CoverFetchError('CdnTlsRejected', '图片 CDN 证书校验失败') from None
    except (OSError, http.client.HTTPException):
        raise CoverFetchError('CdnConnectionFailed', '封面连接失败，请稍后重试', getattr(response, 'status', None)) from None
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
