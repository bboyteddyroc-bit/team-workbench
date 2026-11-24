"""Observed merged VOD upload from the company's own browser capture."""
import json
import secrets
import urllib.parse
import urllib.request
import uuid
import zlib
from image_upload import sign_upload, PROXY_PATH
from provider import ProviderError


def upload_media(provider, headers, content, name, media_type):
    if media_type not in ('video','audio') or not content or len(content)>64*1024*1024:
        raise ProviderError('视频或声音素材无效，单文件上限 64 MB')
    scoped=dict(headers, **{'x-creative-source':'cue/avatar'})
    credentials=provider.post(scoped,'upload/token',{})
    # Both the captured video and MP3 used FileType=video in the VOD transport.
    query=dict(Action='ApplyUploadInner',Version='2020-11-19',SpaceName='ad_site',FileType='video',IsInner='1',FileSize=str(len(content)),s=secrets.token_hex(6),device_platform='web')
    request=urllib.request.Request('https://ads.tiktok.com'+PROXY_PATH+'?'+urllib.parse.urlencode(query),headers={**scoped,**sign_upload('GET',query,None,credentials,service='vod')})
    try:
        with provider.opener.open(request,timeout=45) as response:applied=json.loads(response.read(2_000_000))
        node=applied['Result']['InnerUploadAddress']['UploadNodes'][0]
        store=node['StoreInfos'][0];host=node['UploadHost'];uri=store['StoreUri']
        parsed=urllib.parse.urlsplit('https://'+host)
        if parsed.hostname!=host or not host.endswith('.tiktokcdn.com') or parsed.port is not None or not uri.startswith('tos-alisg-v-0051c001-sg/') or any(x in uri for x in ('?','#','..')):
            raise ValueError()
        boundary='----Hub'+secrets.token_hex(20)
        post_upload=dict(sts2_token=credentials['SessionToken'],sts2_secret=credentials['SecretAccessKey'],session_key=node['SessionKey'],functions=[{'name':'snapshot','input':{'snapshot_time':0,'skip_black_detect':False}}])
        body=(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="blob"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()+content+f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="post_upload_req"\r\n\r\n'.encode()+json.dumps(post_upload,separators=(',',':')).encode()+f'\r\n--{boundary}--\r\n'.encode())
        # This captured VOD protocol requires temporary STS in post_upload_req.
        # Company login cookies/CSRF never leave ads.tiktok.com.
        upload_headers={'Authorization':store['Auth'],'Content-Type':'multipart/form-data; boundary='+boundary,'Content-CRC32':format(zlib.crc32(content)&0xffffffff,'08x'),'X-Storage-U':'ad_creative_tools_unknown_user','X-Upload-With-PostUpload':'1','Origin':'https://ads.tiktok.com','Referer':'https://ads.tiktok.com/','User-Agent':headers.get('user-agent','Mozilla/5.0')}
        request=urllib.request.Request('https://'+host+'/upload/v1/'+uri,data=body,headers=upload_headers,method='POST')
        with provider.opener.open(request,timeout=120) as response:uploaded=json.loads(response.read(2_000_000))
        if uploaded.get('code')!=2000 or uploaded['data']['file_info']['crc32'].lower()!=upload_headers['Content-CRC32']:raise ValueError()
        result=uploaded['data']['post_upload_resp']['results'][0];vid=result['vid'];meta=result['video_meta']
        if meta['FileType']!=media_type or not 2<=float(meta['Duration'])<=15.2:raise ValueError()
    except Exception:
        raise ProviderError('视频/声音上传或校验失败；尚未提交生成，请确认素材时长为 2–15 秒') from None
    bound=provider.post(scoped,'lego/bind_videos',{'vids':[vid]})
    if bound.get(vid,{}).get('status_code')!=0:raise ProviderError('素材绑定失败，尚未提交生成')
    info=provider.get_cue(scoped,'video_info',{'vid':vid}).get(vid,{})
    preview=(info.get('VideoInfos') or [{}])[0].get('MainUrl','')
    if not preview:raise ProviderError('素材预览尚未就绪，尚未提交生成')
    return dict(id=str(uuid.uuid4()),name=name,fileType=media_type,vid=vid,postUrl=info.get('PosterUrl',''),previewUrl=preview,duration=float(meta['Duration']))
