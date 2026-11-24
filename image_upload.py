"""ImageX upload flow reconstructed from the user's own successful web capture."""
import datetime
import hashlib
import hmac
import json
import secrets
import urllib.parse
import urllib.request
import uuid
import zlib

PROXY_PATH='/creative/creativestudio/upload-proxy'


def sign_upload(method, query, payload, credentials, timestamp=None, service='imagex'):
    timestamp=timestamp or datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    headers={'x-amz-date':timestamp,'x-amz-security-token':credentials['SessionToken']}
    digest=hashlib.sha256(payload or b'').hexdigest()
    if method=='POST': headers['x-amz-content-sha256']=digest
    signed=';'.join(sorted(headers))
    canonical_query='&'.join(urllib.parse.quote(str(k),safe='-_.~')+'='+urllib.parse.quote(str(v),safe='-_.~') for k,v in sorted(query.items()))
    canonical='\n'.join([method,PROXY_PATH,canonical_query,''.join(k+':'+headers[k]+'\n' for k in sorted(headers)),signed,digest])
    scope=timestamp[:8]+'/i18n/'+service+'/aws4_request'
    to_sign='\n'.join(['AWS4-HMAC-SHA256',timestamp,scope,hashlib.sha256(canonical.encode()).hexdigest()])
    key=('AWS4'+credentials['SecretAccessKey']).encode()
    for part in [timestamp[:8],'i18n',service,'aws4_request']:key=hmac.new(key,part.encode(),hashlib.sha256).digest()
    signature=hmac.new(key,to_sign.encode(),hashlib.sha256).hexdigest()
    headers['authorization']=f"AWS4-HMAC-SHA256 Credential={credentials['AccessKeyId']}/{scope}, SignedHeaders={signed}, Signature={signature}"
    return headers


def upload_image(provider, headers, content, name):
    from provider import ProviderError
    if not content or len(content)>64*1024*1024:raise ProviderError('图片为空或超过中台 64 MB 上限')
    scoped=dict(headers);scoped['x-creative-source']='cue/avatar'
    credentials=provider.post(scoped,'upload/token',{})

    def proxy(action,body=None):
        query={'Action':action,'Version':'2018-08-01','ServiceId':'n2703mo9gi'}
        method='POST' if body is not None else 'GET'
        if body is None:query.update(FileSize=str(len(content)),s=secrets.token_hex(6),device_platform='web')
        payload=json.dumps(body,separators=(',',':')).encode() if body is not None else None
        request_headers={**scoped,**sign_upload(method,query,payload,credentials)}
        request=urllib.request.Request('https://ads.tiktok.com'+PROXY_PATH+'?'+urllib.parse.urlencode(query),data=payload,headers=request_headers,method=method)
        try:
            with provider.opener.open(request,timeout=45) as response:result=json.loads(response.read(2_000_000))
        except Exception:raise ProviderError('平台图片上传申请或确认失败；尚未提交视频生成') from None
        if result.get('ResponseMetadata',{}).get('Error') or not result.get('Result'):
            raise ProviderError('平台未批准图片上传；尚未提交视频生成')
        return result['Result']

    applied=proxy('ApplyImageUpload')
    try:
        address=applied['UploadAddress'];store=address['StoreInfos'][0];host=address['UploadHosts'][0];uri=store['StoreUri']
        parsed=urllib.parse.urlsplit('https://'+host)
        if parsed.hostname!=host or not host.endswith('.tiktokcdn.com') or parsed.port is not None or not uri.startswith('tos-alisg-i-n2703mo9gi-sg/') or '?' in uri or '#' in uri or '..' in uri:
            raise ValueError()
        # Upload authorization is scoped by ImageX to this object. Never send login
        # cookies, CSRF, or temporary signing credentials to the storage host.
        upload_headers={'Authorization':store['Auth'],'Content-Type':'application/octet-stream',
            'Content-CRC32':format(zlib.crc32(content)&0xffffffff,'08x'),'Content-Disposition':'attachment; filename="undefined"',
            'X-Storage-U':'ad_creative_tools_unknown_user','Origin':'https://ads.tiktok.com','Referer':'https://ads.tiktok.com/',
            'User-Agent':headers.get('user-agent','Mozilla/5.0')}
        request=urllib.request.Request('https://'+host+'/upload/v1/'+uri,method='POST',data=content,headers=upload_headers)
        with provider.opener.open(request,timeout=90) as response:uploaded=json.loads(response.read(100_000))
        if uploaded.get('code')!=2000 or str(uploaded.get('data',{}).get('crc32','')).lower()!=upload_headers['Content-CRC32']:
            raise ValueError()
    except Exception:raise ProviderError('图片文件上传失败；尚未提交视频生成') from None
    committed=proxy('CommitImageUpload',{'SessionKey':address['SessionKey']})
    if not any(r.get('Uri')==uri and r.get('UriStatus')==2000 for r in committed.get('Results',[])):
        raise ProviderError('平台未确认图片写入成功；尚未提交视频生成')
    url='https://p19-creative-tool-sg.ibyteimg.com/'+uri+'~tplv-n2703mo9gi-webp:1280:1280.image'
    saved=provider.post(scoped,'save_to_my_library',{'assets':[{'assetType':'image','content':url,'fileName':name}]})
    assets=saved.get('assets',[])
    if not assets or assets[0].get('content')!=url:raise ProviderError('平台素材保存失败；尚未提交视频生成')
    return {'id':str(uuid.uuid4()),'name':name,'previewUrl':url,'fileType':'image'}
