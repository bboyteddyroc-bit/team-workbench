"""Fish Audio developer API voice catalogue; no synthesis requests here."""
import json
import os
import re
import copy
import hashlib
import threading
import time

_CATALOG_LOCK = threading.Lock()


def catalog_data(voice, params, refresh=False):
    # Per-service, bounded memory only. Never cache favorites or failed responses.
    with _CATALOG_LOCK:
        if not hasattr(voice, '_catalog_lock'):
            voice._catalog_lock = threading.Lock()
            voice._catalog_cache = {}
    key = voice._api_key()
    fingerprint = hashlib.sha256(key.encode()).digest()
    identity = (fingerprint, tuple(sorted(params.items())))
    with voice._catalog_lock:
        cache = voice._catalog_cache
        now = time.monotonic()
        for token in list(cache):
            if token[0] != fingerprint or cache[token][0] <= now:
                del cache[token]
        if not refresh and identity in cache:
            return copy.deepcopy(cache[identity][1])
        data = read_model(key, params=params)
        if len(cache) >= 32:
            del cache[next(iter(cache))]
        cache[identity] = (time.monotonic() + 60, copy.deepcopy(data))
        return data
import urllib.parse
import urllib.request
import urllib.error


def opener():
    proxy=os.getenv('HUB_VOICE_PROXY',os.getenv('HUB_PROXY','http://127.0.0.1:7890'))
    return urllib.request.build_opener(urllib.request.ProxyHandler({'https':proxy} if proxy else {}))


def read_model(key, path='', params=None):
    if not key:raise ValueError('请先由管理员配置 Fish Audio Key')
    url='https://api.fish.audio/model'+path
    if params:url+='?'+urllib.parse.urlencode(params)
    req=urllib.request.Request(url,headers={'Authorization':'Bearer '+key,'Accept':'application/json'})
    try:
        with opener().open(req,timeout=20) as r:
            raw=r.read(4*1024*1024+1)
        if len(raw)>4*1024*1024:raise ValueError('音色列表过大，请缩小搜索范围')
        return json.loads(raw)
    except urllib.error.HTTPError as e:
        raise ValueError('音色库访问失败：Key 无效或无权限，请检查服务配置' if e.code in (401,403) else '音色库暂不可用（HTTP %s），请稍后刷新'%e.code) from None
    except (urllib.error.URLError,TimeoutError):raise ValueError('音色库连接超时，请检查网络或代理后刷新') from None


def normalize(item):
    ref=str(item.get('_id',''))
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',ref):raise ValueError('音色 ID 无效')
    sample=''
    for entry in item.get('samples') or []:
        url=entry.get('audio','') if isinstance(entry,dict) else ''
        p=urllib.parse.urlsplit(url)
        if p.scheme=='https' and p.hostname and (p.hostname=='fish.audio' or p.hostname.endswith('.fish.audio')) and not p.username:
            sample=url;break
    languages=[str(x) for x in item.get('languages',[]) if isinstance(x,str)]
    usable=item.get('type')=='tts' and item.get('state')=='trained' and not item.get('dmca_taken_down')
    return dict(id='fish-'+ref,reference_id=ref,name=str(item.get('title') or '未命名音色')[:60],
                language=','.join(languages)[:35],languages=languages,style=' · '.join(str(t) for t in (item.get('tags') or [])[:3])[:80],
                has_sample=bool(sample),sample_url=sample,enabled=usable,usable=usable,official=True)


def cache_voice(voice,item):
    row=normalize(item)
    with voice.hub.db() as db:
        db.execute('''INSERT INTO voice_voices(id,name,reference_id,language,style,sample_path,created,created_by,enabled,official_sample)
                      VALUES(?,?,?,?,?,'',?,'catalog',?,?) ON CONFLICT(id) DO UPDATE SET
                      name=excluded.name,language=excluded.language,style=excluded.style,
                      enabled=excluded.enabled,official_sample=excluded.official_sample''',
                   (row['id'],row['name'],row['reference_id'],row['language'],row['style'],__import__('time').time(),int(row['usable']),row['sample_url']))
    row['sample_url']='/api/voice/voices/'+row['id']+'/sample' if row['has_sample'] else ''
    return row


def browse(voice,owner,title='',language='',page=1,refresh=False):
    params={'page_size':20,'page_number':max(1,min(100,int(page))),'sort_by':'score'}
    if title:params['title']=title[:100]
    if language:params['language']=language[:35]
    data=catalog_data(voice,params,refresh)
    rows=[cache_voice(voice,x) for x in data.get('items',[]) if x.get('type')=='tts']
    with voice.hub.db() as db:favs={r['voice_id'] for r in db.execute('SELECT voice_id FROM voice_favorites WHERE user_id=?',(owner,))}
    for row in rows:row['favorite']=row['id'] in favs
    return {'voices':rows,'page':page,'has_more':bool(data.get('has_more',len(data.get('items',[]))==20))}


def fetch_sample(url):
    """Fetch public audio on the server; never forward credentials to the CDN."""
    def valid(value):
        p=urllib.parse.urlsplit(value)
        return p.scheme=='https' and p.hostname and (p.hostname=='fish.audio' or p.hostname.endswith('.fish.audio')) and not p.username and p.port in (None,443)
    if not valid(url):raise ValueError('样音地址无效')
    class SafeRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,req,fp,code,msg,headers,newurl):
            if not valid(newurl):raise ValueError('样音跳转地址不受支持')
            return super().redirect_request(req,fp,code,msg,headers,newurl)
    client=opener();client.add_handler(SafeRedirect())
    try:
        with client.open(urllib.request.Request(url,headers={'Accept':'audio/*','User-Agent':'Mozilla/5.0'}),timeout=25) as response:
            mime=response.headers.get_content_type()
            body=response.read(20*1024*1024+1)
        if not body or len(body)>20*1024*1024:raise ValueError('样音为空或超过大小限制')
        if not (mime.startswith('audio/') or mime=='application/octet-stream'):raise ValueError('平台未返回有效音频')
        return body,mime if mime.startswith('audio/') else 'audio/mpeg'
    except (urllib.error.URLError,TimeoutError):raise ValueError('服务器获取样音失败，请检查服务器网络或代理') from None
