"""A6 Gemini native inline-video transport; no retries and no implicit file access.

Callers must provide explicit consent, authorized local file and bounded size. This
module does not queue work or decide which media to send.
"""
import base64,json,urllib.request,urllib.error,socket
from pathlib import Path
from task_feedback import current

MODEL='gemini-3.8-flash'
ENDPOINT='https://api.a6api.vip/v1beta/models/'+MODEL+':generateContent'
MAX_BYTES=50_000_000  # 50 MB (decimal bytes), per video
MAX_RESPONSE=2*1024*1024

class VideoOutcomeUnknown(ValueError):
    pass

def is_mp4(path):
    p=Path(path)
    if not p.is_file():return False
    with p.open('rb') as f:header=f.read(12)
    return len(header)>=12 and header[4:8]==b'ftyp' and header[8:12] not in (b'qt  ',b'heic',b'heix',b'avif')

def build_video_request(key,path,prompt,consent=False):
    if consent is not True: raise ValueError('发送视频前需要明确确认画面和声音将发送至 A6API')
    if not isinstance(key,str) or not key.strip() or any(c in key for c in '\r\n'): raise ValueError('A6API 密钥无效')
    if not isinstance(prompt,str) or not prompt.strip(): raise ValueError('缺少视频分析要求')
    p=Path(path)
    if not is_mp4(p): raise ValueError('仅支持已授权且容器格式为 MP4 的本地视频')
    size=p.stat().st_size
    if not 0<size<=MAX_BYTES: raise ValueError('视频超过当前单次直读安全限额 50 MB（50,000,000 字节）或文件为空，未发送')
    content=p.read_bytes()
    if len(content)!=size or len(content)>MAX_BYTES: raise ValueError('视频读取期间发生变化，未发送')
    payload={'contents':[{'role':'user','parts':[{'text':prompt},{'inline_data':{'mime_type':'video/mp4','data':base64.b64encode(content).decode('ascii')}}]}], 'generationConfig':{'maxOutputTokens':8192,'temperature':0.1}}
    return urllib.request.Request(ENDPOINT,data=json.dumps(payload,ensure_ascii=False).encode(),headers={'Content-Type':'application/json','x-goog-api-key':key.strip()},method='POST')

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None

def read_video(key,path,prompt,consent=False,timeout=360):
    observed=current()
    try:
        req=build_video_request(key,path,prompt,consent)
    except (ValueError,OSError):
        if observed:observed.mark('blocked')
        raise
    try:
        with urllib.request.build_opener(NoRedirect).open(req,timeout=timeout) as resp:
            if observed:observed.http(getattr(resp,'status',None))
            raw=resp.read(MAX_RESPONSE+1)
    except urllib.error.HTTPError as exc:
        rejected=400<=exc.code<500
        if observed:
            observed.http(exc.code)
            observed.mark('failed' if rejected else 'unknown')
        if rejected: raise ValueError(f'视频直读被服务拒绝（HTTP {exc.code}）；未自动重试') from None
        raise VideoOutcomeUnknown(f'视频直读服务异常（HTTP {exc.code}），结果未知；未自动重试') from None
    except OSError as exc:
        reason=getattr(exc,'reason',exc)
        if observed:
            observed.mark('unknown');observed.error_type(type(reason).__name__)
        kind='等待响应超时' if isinstance(reason,TimeoutError) else '网络连接异常（'+type(reason).__name__+'）'
        raise VideoOutcomeUnknown('视频直读'+kind+'，结果未知；未自动重试') from None
    if observed:observed.move('ai_validate')
    if len(raw)>MAX_RESPONSE: raise ValueError('视频直读返回过大，未自动重试')
    try:
        data=json.loads(raw); candidate=data['candidates'][0]
        if candidate.get('finishReason') not in ('STOP',None): raise ValueError('视频直读未完整结束，未自动重试')
        parts=candidate['content']['parts']
        answer=''.join(p.get('text','') for p in parts if isinstance(p,dict) and isinstance(p.get('text',''),str)).strip()
        if not answer: raise ValueError('视频直读未返回文本，未自动重试')
        return answer
    except (KeyError,IndexError,TypeError,json.JSONDecodeError): raise ValueError('视频直读响应格式无效，未自动重试') from None
