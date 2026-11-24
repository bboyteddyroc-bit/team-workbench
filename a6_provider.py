"""A6API request builder; this module does not activate or submit requests."""
import json
import urllib.request

BASE_URL = 'https://api.a6api.vip/v1'
MODEL = 'gemini-3.8-flash'
ENDPOINT = BASE_URL + '/chat/completions'

def build_request(key, payload):
    if not isinstance(key,str) or not key.strip() or '\n' in key or '\r' in key:
        raise ValueError('A6API 密钥无效')
    if not isinstance(payload,dict) or not isinstance(payload.get('messages'),list):
        raise ValueError('AI 请求格式无效')
    data=dict(payload)
    data['model']=MODEL
    # Provider-specific Agnes extensions are not part of the portable protocol.
    data.pop('chat_template_kwargs',None)
    return urllib.request.Request(ENDPOINT,data=json.dumps(data,ensure_ascii=False).encode('utf-8'),
        headers={'Content-Type':'application/json','Authorization':'Bearer '+key.strip()},method='POST')
