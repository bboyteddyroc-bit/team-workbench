"""Identify public TikTok Shop listings without browsing pages or sending credentials."""
import http.client
import ipaddress
import re
import socket
import ssl
import threading
import time
from concurrent.futures import Future, TimeoutError
from urllib.parse import parse_qs, quote, unquote, urljoin, urlsplit

SHOP_HOSTS = frozenset(('tiktok.com', 'www.tiktok.com', 'm.tiktok.com', 'shop.tiktok.com'))
SHORT_HOSTS = frozenset(('vm.tiktok.com', 'vt.tiktok.com'))
PRODUCT_PATH = re.compile(r'^/(?:(?P<locale>[a-z]{2}(?:-[a-z]{2})?)/)?(?:(?:shop|view)/)?'
                          r'(?:pdp|product|products)/(?:(?P<slug>[^/]{1,360})/)?(?P<id>[0-9]{5,32})/?$', re.I)
SHARE_PATH = re.compile(r'/t/[A-Za-z0-9_-]{1,100}/?\Z')
COMPACT_PATH = re.compile(r'/[A-Za-z0-9_-]{1,100}/?\Z')
REDIRECTS = (301, 302, 303, 307, 308)
MAX_HOPS, MAX_SECONDS = 5, 12
# A slow OS DNS call must not hold the service worker or spawn unbounded threads.
_short_slot = threading.BoundedSemaphore(1)


class LinkError(ValueError):
    pass


def parse(url):
    """Return an allowlisted, tracking-free URL and (if present) exact listing path match."""
    try:
        if not isinstance(url, str) or len(url) > 2000 or re.search(r'[\\\x00-\x20\x7f]', url):
            raise ValueError()
        p = urlsplit(url)
        if (p.scheme != 'https' or p.hostname not in SHOP_HOSTS | SHORT_HOSTS
                or p.username is not None or p.password is not None or p.port not in (None, 443)
                or re.search(r'%(?:2f|5c|[01][0-9a-f]|7f)', p.path, re.I)
                or any(segment in ('.', '..') for segment in unquote(p.path).split('/'))):
            raise ValueError()
        p = p._replace(path=quote(p.path, safe="/%!$&'()*+,;=:@-._~"))
    except (ValueError, UnicodeError):
        raise LinkError('请填写 TikTok Shop 商品完整链接或 TikTok 官方分享短链。') from None
    m = PRODUCT_PATH.fullmatch(p.path) if p.hostname in SHOP_HOSTS else None
    if not m and not (SHARE_PATH.fullmatch(p.path) or p.hostname in SHORT_HOSTS and COMPACT_PATH.fullmatch(p.path)):
        raise LinkError('链接未指向 TikTok Shop 商品；视频、店铺和个人主页不能用于商品取数。')
    # An explicit product-region query value is a consistency check, not a lookup ID.
    # Drop the rest of the query before storing a canonical URL or following a redirect.
    region = ''
    if m:
        try:
            regions = parse_qs(p.query, keep_blank_values=True, max_num_fields=250).get('region', [])
        except ValueError:
            raise LinkError('商品链接参数过多，请粘贴商品完整链接。') from None
        if regions:
            if len(regions)!=1 or not re.fullmatch('[A-Za-z]{2}', regions[0]):
                raise LinkError('商品链接的地区参数不明确，请核对链接。')
            region = 'region=' + regions[0].upper()
    return p._replace(netloc=p.hostname, query=region, fragment=''), m


def listing_parts(url, market=None):
    try:
        p, m = parse(url)
        if market:
            check_market(p, m, market)
    except LinkError:
        return '', ''
    if not m:
        return '', ''
    slug = re.sub(r'[\x00-\x1f\x7f]', ' ', unquote(m['slug'] or ''))[:240]
    return slug, m['id']


def check_market(p, m, market):
    path_region = m['locale'].split('-')[-1].upper() if m and m['locale'] else ''
    query_region = p.query.removeprefix('region=')
    if any(region and region != market for region in (path_region, query_region)):
        raise LinkError('商品链接的地区与档案市场不一致，请核对链接和市场。')


def _remaining(deadline):
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise LinkError('短链解析超时；可换成商品完整链接。')
    return seconds


def _public_addresses(host):
    addresses = tuple(dict.fromkeys(a[4][0] for a in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)))
    def public(text):
        addr = ipaddress.ip_address(text)
        addr = getattr(addr, 'ipv4_mapped', None) or addr
        return addr.is_global and not addr.is_multicast and not getattr(addr, 'scope_id', None)
    if not addresses or not all(map(public, addresses)):
        raise LinkError('短链没有解析到公开的 TikTok 地址；可换成商品完整链接。')
    return addresses


def _redirect(p, deadline):
    addresses = _public_addresses(p.hostname)
    def pinned(_destination, timeout=None, source_address=None):
        for ip in addresses:
            try:
                return socket.create_connection((ip, 443), timeout=min(3, _remaining(deadline)))
            except OSError:
                continue
        raise OSError('No public address responded')

    conn = http.client.HTTPSConnection(p.hostname, 443, timeout=_remaining(deadline), context=ssl.create_default_context())
    conn._create_connection = pinned  # Preserve TLS validation and SNI while pinning the validated IP.
    timer = None
    try:
        conn.request('GET', p.path, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'text/html', 'Connection': 'close'})
        sock = conn.sock
        def close_at_deadline():
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        timer = threading.Timer(_remaining(deadline), close_at_deadline)
        timer.daemon = True
        timer.start()
        with conn.getresponse() as r:
            values = r.headers.get_all('Location') or []
            if r.status not in REDIRECTS or len(values) != 1:
                raise LinkError('短链未跳转到公开商品页，可能已失效或受访问限制。请粘贴商品完整链接。')
            return values[0]
    except (OSError, http.client.HTTPException, ValueError) as exc:
        if isinstance(exc, LinkError):
            raise
        raise LinkError('TikTok 短链暂时无法访问；请粘贴商品完整链接。') from None
    finally:
        if timer:
            timer.cancel()
        conn.close()


def _expand(p, market, deadline):
    seen = set()
    for _ in range(MAX_HOPS):
        _remaining(deadline)
        if p.geturl() in seen:
            break
        seen.add(p.geturl())
        loc = _redirect(p, deadline)
        if not isinstance(loc, str) or len(loc) > 2000 or re.search(r'[\\\x00-\x20\x7f]', loc):
            raise LinkError('短链跳转格式异常；请粘贴商品完整链接。')
        try:
            p, m = parse(urljoin(p.geturl(), loc))
        except ValueError:
            raise LinkError('短链未跳转到受支持的 TikTok Shop 商品页；请粘贴商品完整链接。') from None
        if m:
            _remaining(deadline)
            check_market(p, m, market)
            return p.geturl(), m['id']
    raise LinkError('短链跳转次数超限或循环；请粘贴商品完整链接。')


def resolve(url, market):
    p, m = parse(url)
    if m:
        check_market(p, m, market)
        return p.geturl(), m['id']
    if not _short_slot.acquire(blocking=False):
        raise LinkError('短链解析暂时繁忙；可换成商品完整链接。')
    result = Future()
    deadline = time.monotonic() + MAX_SECONDS
    def work():
        try:
            target = _expand(p, market, deadline)
        except Exception as exc:
            _short_slot.release()
            result.set_exception(exc)
        else:
            _short_slot.release()
            result.set_result(target)
    try:
        threading.Thread(target=work, name='tiktok-shop-redirect', daemon=True).start()
    except Exception:
        _short_slot.release()
        raise
    try:
        return result.result(timeout=_remaining(deadline))
    except TimeoutError:
        raise LinkError('短链解析超时；可换成商品完整链接。') from None
