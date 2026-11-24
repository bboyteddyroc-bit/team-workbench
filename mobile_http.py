"""Token-only LAN HTTP gateway. Never exposes Hub login/admin/editor routes."""
import ipaddress
import os
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import FastAPI
from fastapi.responses import FileResponse,JSONResponse,RedirectResponse

DEFAULT_ORIGIN='http://192.168.100.10:8000'
DEFAULT_NETWORKS='192.168.100.0/23'
PHONE_ROUTES={
 '/mobile/':{'GET'},
 '/api/mobile/session':{'GET'},
 '/api/mobile/upload':{'POST'},
 '/api/mobile/file/{eid}':{'GET'},
 '/api/mobile/zip':{'POST'},
 '/api/mobile/zip-download':{'GET'},
}

def mobile_origin():
    origin=os.getenv('HUB_MOBILE_ORIGIN',DEFAULT_ORIGIN).rstrip('/')
    parts=urlsplit(origin)
    if parts.scheme not in ('http','https') or not parts.hostname or parts.username or parts.password or parts.path or parts.query or parts.fragment:
        raise ValueError('HUB_MOBILE_ORIGIN must be an HTTP(S) origin without paths or credentials')
    if parts.scheme=='http':
        address=ipaddress.ip_address(parts.hostname)
        if not (address.is_private or address.is_loopback) or address.is_unspecified:
            raise ValueError('Mobile HTTP must bind a private LAN or loopback IP')
    return origin

def create_phone_app(hub_app,origin=None,networks=None):
    origin=origin or mobile_origin()
    expected=urlsplit(origin).netloc
    networks=networks or os.getenv('HUB_MOBILE_NETWORKS',DEFAULT_NETWORKS).split(',')
    allowed=[ipaddress.ip_network(n.strip(),strict=False) for n in networks]
    if not allowed or any(not n.is_private or n.prefixlen==0 for n in allowed):
        raise ValueError('Mobile HTTP networks must be explicit private subnets')
    phone=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
    phone.state.mobile_only=True
    @phone.middleware('http')
    async def guard(request,call_next):
        async def dispatch():
            try:peer=ipaddress.ip_address(request.client.host)
            except (ValueError,AttributeError):return JSONResponse({'detail':'仅限公司局域网访问'},403)
            if not (peer.is_loopback or any(peer in n for n in allowed)):
                return JSONResponse({'detail':'仅限公司局域网访问'},403)
            if request.headers.get('host')!=expected:
                return JSONResponse({'detail':'请使用二维码中的手机传输地址'},400)
            if request.headers.get('origin') not in (None,origin):
                return JSONResponse({'detail':'请求来源校验失败'},403)
            if request.method not in ('GET','HEAD'):
                if request.headers.get('x-hub-request')!='1':
                    return JSONResponse({'detail':'请求来源校验失败'},403)
                if request.url.path!='/api/mobile/upload':
                    size=0;chunks=[]
                    async for chunk in request.stream():
                        size+=len(chunk)
                        if size>2*1024*1024:return JSONResponse({'detail':'请求内容过大'},413)
                        chunks.append(chunk)
                    request._body=b''.join(chunks)
            return await call_next(request)
        response=await dispatch()
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response
    @phone.get('/')
    def home():return RedirectResponse('/mobile/',status_code=307)
    @phone.get('/health')
    def health():return {'ok':True,'service':'hub-mobile-transfer','transport':'http-lan','encrypted':False}
    static=Path(__file__).resolve().parent/'static'
    @phone.get('/static/mobile-receiver.js')
    def script():return FileResponse(static/'mobile-receiver.js',media_type='application/javascript')
    @phone.get('/static/mobile-transfer.css')
    def styles():return FileResponse(static/'mobile-transfer.css',media_type='text/css')
    for route in hub_app.routes:
        if route.path in PHONE_ROUTES:
            methods=PHONE_ROUTES[route.path]
            if not methods.issubset(route.methods):raise RuntimeError('Unexpected phone route methods')
            phone.add_api_route(route.path,route.endpoint,methods=sorted(methods),response_class=route.response_class)
    actual={r.path for r in phone.routes}
    if not set(PHONE_ROUTES).issubset(actual):raise RuntimeError('Missing mobile transfer handlers')
    return phone
