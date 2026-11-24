"""Observed TikTok web API adapter. No shell execution, no automatic POST retry."""
import json
import re
import shlex
import urllib.parse
import urllib.request
import urllib.error

BASE = 'https://ads.tiktok.com/creative_bff_i18n/api/cue/'
QUERY = '?aid=585599&app_name=creative_aio_client&device_platform=web'


def mini_reference_payload(prompt, images, duration=5, model="2000009"):
    if model not in ("2000004", "2000009", "2000012"):
        raise ValueError("不支持的参考模型")
    """Build the observed Mini image-reference request; accepts uploaded assets only.

    Local asset IDs are not platform references. The caller must finish and verify
    the platform upload first. Video/audio, explicit mention syntax and other
    models are deliberately not inferred from this one captured request.
    """
    if not isinstance(prompt,str) or not prompt.strip():
        raise ValueError('请填写提示词')
    if type(duration) is not int or not 4<=duration<=15:
        raise ValueError('时长需为 4–15 秒')
    if not isinstance(images,list) or not 1<=len(images)<=9:
        raise ValueError('请选择 1–9 张已上传平台的图片')
    references=[]
    for index, image in enumerate(images,1):
        if not isinstance(image,dict): raise ValueError('图片引用格式有误')
        url=image.get('previewUrl',''); target=urllib.parse.urlsplit(url)
        if target.scheme!='https' or target.hostname!='p19-creative-tool-sg.ibyteimg.com' or target.port not in (None,443) or target.username or target.password or not target.path.startswith('/tos-alisg-i-n2703mo9gi-sg/'):
            raise ValueError('图片尚未取得已验证的平台引用地址')
        if not isinstance(image.get('id'),str) or not image['id'] or not isinstance(image.get('name'),str):
            raise ValueError('图片缺少平台素材信息')
        references.append(dict(id=image['id'],name=image['name'],previewUrl=url,fileType='image',label=f'image {index}'))
    return dict(prompt=prompt,duration=duration,model=model,
        settings=json.dumps(dict(images=references,prompt=prompt,aiModel=model,duration=duration),ensure_ascii=False,separators=(',',':')),
        mentions=[dict(type=1,id=image['previewUrl']) for image in references])


def reference_payload(prompt, assets, duration=5, model='2000004'):
    if model not in ('2000004','2000009','2000012') or not isinstance(prompt,str) or not prompt.strip() or type(duration) is not int or not 4<=duration<=15:
        raise ValueError('模型、提示词或时长有误')
    counts={'image':0,'video':0,'audio':0};durations={'video':0,'audio':0};images=[];mentions=[]
    for asset in assets:
        kind=asset.get('fileType','image')
        if kind not in counts:raise ValueError('素材类型不支持')
        counts[kind]+=1
        if kind=='image':
            item=json.loads(mini_reference_payload(prompt,[asset],duration,model)['settings'])['images'][0]
            item['label']=f'image {counts[kind]}'
            images.append(item);mentions.append(dict(type=1,id=item['previewUrl']))
        else:
            seconds=float(asset.get('duration',0))
            if not 2<=seconds<=15.2 or not isinstance(asset.get('vid'),str) or not asset['vid'].isalnum():raise ValueError('视频或声音引用无效')
            durations[kind]+=seconds
            images.append({k:asset.get(k,'') for k in ('id','fileType','vid','postUrl','previewUrl')})
            mentions.append(dict(type=2 if kind=='video' else 101,id=asset['vid']))
    if counts['image']+counts['video']<1 or counts['image']>9 or counts['video']>3 or counts['audio']>3 or len(assets)>12 or any(x>15.2 for x in durations.values()):
        raise ValueError('参考素材超出平台限制：9 图、3 视频、3 声音，总数 12；视频和声音各累计不超过 15 秒，不能只有声音')
    return dict(prompt=prompt,duration=duration,model=model,settings=json.dumps(dict(images=images,prompt=prompt,aiModel=model,duration=duration),ensure_ascii=False,separators=(',',':')),mentions=mentions)


class ProviderError(Exception):
    def __init__(self, message, auth=False):
        super().__init__(message)
        self.auth = auth


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def parse_curl(source):
    if len(source) > 100000:
        raise ValueError('请求内容过长')
    args = shlex.split(source.replace('\\\r\n', '').replace('\\\n', ''))
    if not args or args.pop(0) not in ('curl', 'curl.exe'):
        raise ValueError('请使用 Copy as cURL (bash) 导出的请求')
    headers, url, body = {}, '', None
    i = 0
    while i < len(args):
        flag = args[i]
        if flag in ('--compressed', '--globoff'):
            i += 1
            continue
        if flag.startswith('https://'):
            url = flag
            i += 1
            continue
        if flag not in ('--url', '-H', '--header', '-b', '--cookie', '--data-raw', '--data', '-d', '-X', '--request', '-e', '--referer') or i + 1 >= len(args):
            raise ValueError('不支持这个 cURL 格式，请重新使用 Copy as cURL (bash)')
        val = args[i + 1]
        i += 2
        if flag == '--url':
            url = val
        elif flag in ('-H', '--header'):
            key, sep, value = val.partition(':')
            if not sep or '\r' in val or '\n' in val:
                raise ValueError('请求头格式有误')
            headers[key.lower().strip()] = value.strip()
        elif flag in ('-b', '--cookie'):
            if '=' not in val or '\n' in val or '\r' in val:
                raise ValueError('需要直接包含 Cookie 的请求')
            headers['cookie'] = val
        elif flag in ('--data-raw', '--data', '-d'):
            body = json.loads(val)
        elif flag in ('-X', '--request') and val.upper() != 'POST':
            raise ValueError('请选择创建任务的 POST 请求')
        elif flag in ('-e', '--referer'):
            headers['referer'] = val
    target = urllib.parse.urlsplit(url)
    create_path='/creative_bff_i18n/api/cue/t2v/create_generate_task'
    count_path='/creative_bff_i18n/api/cue/generating-task-count'
    if target.scheme != 'https' or target.netloc != 'ads.tiktok.com' or target.path not in (create_path,count_path):
        raise ValueError('请选择 TikTok 的任务计数或创建任务请求')
    if target.path==create_path and (not isinstance(body, dict) or str(body.get('model')) != '5000005' or type(body.get('duration')) is not int or not 4<=body['duration']<=15):
        raise ValueError('请导出 Seedance 2.0、4–15 秒的请求')
    for key in ('cookie', 'x-csrftoken', 'x-fp-id'):
        if not headers.get(key) or '<REDACTED>' in headers[key]:
            raise ValueError('请求缺少完整的本机登录信息')
    allowed = {'accept', 'accept-language', 'agw-js-conv', 'content-type', 'x-creative-source', 'x-csrftoken', 'x-fp-id', 'cookie', 'origin', 'referer', 'user-agent'}
    headers = {k:v for k,v in headers.items() if k in allowed}
    headers['content-type'] = 'application/json'
    return headers


class TikTok:
    def __init__(self, proxy='http://127.0.0.1:7890'):
        handlers = [NoRedirect()]
        if proxy:
            parsed = urllib.parse.urlsplit(proxy)
            if parsed.scheme not in ('http', 'https') or not parsed.hostname:
                raise ValueError('Invalid proxy URL')
            handlers.append(urllib.request.ProxyHandler({'https': proxy}))
        self.opener = urllib.request.build_opener(*handlers)

    def post(self, headers, operation, payload):
        if operation not in ('history/tasks', 't2v/create_generate_task','i2v/gen_r2v_video','upload/token','save_to_my_library','lego/bind_videos','i2v/create_generate_task','batch_query_generation_quota'):
            raise ValueError('Unsupported operation')
        req = urllib.request.Request(BASE + operation + QUERY, method='POST', headers={**headers, 'Content-Type':'application/json'},
                                     data=json.dumps(payload, ensure_ascii=False).encode())
        from task_feedback import current
        observed=current()
        try:
            with self.opener.open(req, timeout=45) as response:
                if observed:observed.http(getattr(response,'status',None))
                data = json.loads(response.read(8_000_000))
        except urllib.error.HTTPError as exc:
            if observed:observed.http(exc.code)
            raise ProviderError(f'平台 HTTP {exc.code}，请检查账号连接', exc.code in (401,403)) from None
        except json.JSONDecodeError:
            if observed:observed.error_type('JSONDecodeError')
            raise ProviderError('平台响应不是有效 JSON，未取得有效结果') from None
        except TimeoutError:
            if observed:observed.error_type('TimeoutError')
            raise ProviderError('平台请求超时，未取得有效响应') from None
        except urllib.error.URLError as exc:
            if observed:observed.error_type(type(exc.reason).__name__)
            raise ProviderError('连接平台失败，请检查本机网络或代理') from None
        except Exception:
            raise ProviderError('平台响应读取异常，未取得有效结果') from None
        if not isinstance(data, dict) or data.get('code') != 0:
            raw = data.get('code') if isinstance(data, dict) else None
            if observed:observed.code(raw)
            code = str(raw) if type(raw) in (str,int) and re.fullmatch(r'-?[0-9]{1,12}',str(raw)) else '未提供'
            raise ProviderError(f'平台接口 {operation} 返回错误码 {code}，未取得成功结果')
        return data.get('data') or {}

    def history(self, headers):
        return self.post(headers, 'history/tasks', dict(pageOffset=0,pageLimit=12,edited=False,sorted=2,
            start_time='1761566400',mini_app_type=[2,3,11,13,18,19],parseSettings=True,showPlayInfo=True))

    def find(self, headers, task_id, draft_id=None):
        for page in range(10):
            data = self.post(headers, 'history/tasks', dict(pageOffset=12*page,pageLimit=12,edited=False,sorted=2,
                start_time='1761566400',mini_app_type=[2,3,11,13,18,19],parseSettings=True,showPlayInfo=True))
            for draft in data.get('draft_infos', []):
                if str(draft.get('taskId')) == str(task_id) or (draft_id and str(draft.get('id')) == str(draft_id)):
                    return draft
            if (page+1)*12 >= data.get('total', 0):
                break
        return None

    def create(self, headers, prompt, duration=5):
        if type(duration) is not int or not 4 <= duration <= 15:
            raise ValueError('时长需为 4–15 秒')
        return self.post(headers, 't2v/create_generate_task', dict(duration=duration,model='5000005',gokuModel='5000005',
            prompt=prompt,settings=json.dumps(dict(aiModel='5000005',duration=duration,prompt=prompt),ensure_ascii=False)))

    def create_mini_reference(self, headers, prompt, uploaded_images, duration=5):
        payload=mini_reference_payload(prompt,uploaded_images,duration)
        scoped=dict(headers)
        scoped['x-creative-source']='cue/avatar'
        return self.post(scoped,'i2v/gen_r2v_video',payload)

    def create_reference(self, headers, prompt, uploaded_images, duration=5, model='5000005'):
        model_id={'auto':'2000004','5000005':'2000004','mini':'2000009','fast':'2000012'}[model]
        payload=reference_payload(prompt,uploaded_images,duration,model_id)
        scoped=dict(headers, **{'x-creative-source':'cue/avatar'})
        return self.post(scoped,'i2v/gen_r2v_video',payload)

    def account_info(self, headers, listing=False):
        endpoint='ClientGetAccountList' if listing else 'ClientGetAccountInfo'
        req=urllib.request.Request('https://ads.tiktok.com/CreativeOne/Client/'+endpoint+QUERY,headers=headers)
        try:
            with self.opener.open(req,timeout=30) as response:data=json.loads(response.read(2_000_000))
        except urllib.error.HTTPError as exc:
            raise ProviderError(f'子账号接口 HTTP {exc.code}',exc.code in (401,403)) from None
        except (urllib.error.URLError,TimeoutError):
            raise ProviderError('子账号接口网络连接失败，请检查服务器代理；未判定为登录失效') from None
        except (ValueError,TypeError):
            raise ProviderError('子账号接口返回格式异常') from None
        base=data.get('BaseResp',{}) if isinstance(data,dict) else {}
        if not isinstance(base,dict):raise ProviderError('子账号接口返回格式异常')
        code=base.get('StatusCode')
        if code!=0:
            auth=code==38001001 or base.get('StatusMessage')=='InvalidLogin'
            raise ProviderError('TikTok 登录凭据已失效（38001001），请重新登录并同步账号池' if auth else f'子账号接口拒绝请求（状态码 {code}）',auth)
        result=data.get('accounts' if listing else 'account')
        if not isinstance(result,list if listing else dict):raise ProviderError('子账号接口返回结构变化，未更新账号')
        return result

    def scoped_account(self, headers, identity):
        if not isinstance(identity,str) or not identity.isdigit():raise ValueError('子账号 ID 无效')
        cookies=[part.strip() for part in headers.get('cookie','').split(';') if part.strip() and part.strip().partition('=')[0]!='s_aio_client_id']
        return dict(headers,cookie='; '.join(cookies+['s_aio_client_id='+identity]))

    def quotas(self, headers):
        targets=[dict(source='CreativeStudio/MiniApp/TextToVideo',strategy_id='5000005')]+[dict(source='CreativeStudio/ReferenceToVideo/ReferenceToVideo',strategy_id=m) for m in ('2000009','2000012')]
        result=self.post(headers,'batch_query_generation_quota',{'targets':targets})
        return {r['target']['strategy_id']:r.get('quota',{}) for r in result.get('results',[])}

    def get_cue(self, headers, operation, params):
        if operation!='video_info':raise ValueError('Unsupported operation')
        request=urllib.request.Request(BASE+operation+QUERY+'&'+urllib.parse.urlencode(params),headers=headers)
        with self.opener.open(request,timeout=45) as response:data=json.loads(response.read(8_000_000))
        if data.get('code')!=0:raise ProviderError('素材信息读取失败')
        return data.get('data') or {}

    def create_frames(self, headers, prompt, images, duration=5):
        checked=json.loads(mini_reference_payload(prompt,images,duration)['settings'])['images']
        if not 1<=len(checked)<=2:raise ValueError('首尾帧需要 1–2 张图')
        settings=dict(rawImage=checked[0]['previewUrl'],image=checked[0]['previewUrl'],images=checked,aiModel='4000005',imageIndex=0,animationType='prompt',duration=duration,isBgGenerated=False,prompt=prompt)
        payload=dict(image=settings['image'],images=[i['previewUrl'] for i in checked],prompt=prompt,duration=duration,model='4000005',settings=json.dumps(settings,ensure_ascii=False))
        return self.post(dict(headers,**{'x-creative-source':'cue/avatar'}),'i2v/create_generate_task',payload)

    def upload_media(self, headers, content, name, media_type):
        from media_upload import upload_media
        return upload_media(self,headers,content,name,media_type)

    def upload_image(self, headers, content, name):
        from image_upload import upload_image
        return upload_image(self,headers,content,name)

    def download(self, url, target, user_agent='Mozilla/5.0'):
        p = urllib.parse.urlsplit(url)
        if p.scheme != 'https' or not p.hostname or not any(p.hostname.endswith('.'+d) for d in ('tiktokcdn-row.com','tiktokcdn.com')):
            raise ProviderError('平台视频地址域名不在已验证范围内')
        # Deliberately send no account cookies or CSRF token to media hosts.
        temp = target.with_suffix('.part')
        from task_feedback import current
        observed=current()
        try:
            request = urllib.request.Request(url,headers={'User-Agent':user_agent,'Referer':'https://ads.tiktok.com/','Accept':'*/*'})
            with self.opener.open(request, timeout=60) as response, temp.open('wb') as out:
                if observed:observed.http(getattr(response,'status',None))
                total = 0
                first = True
                while chunk := response.read(1024*1024):
                    if first and b'ftyp' not in chunk[:128]:
                        raise ProviderError('视频地址未返回 MP4 文件')
                    first = False
                    total += len(chunk)
                    if total > 512*1024*1024:
                        raise ProviderError('视频超过本机缓存大小上限')
                    out.write(chunk)
                if not total:
                    raise ProviderError('视频文件为空')
            temp.replace(target)
        except Exception as exc:
            if observed and isinstance(exc,urllib.error.HTTPError):observed.http(exc.code)
            temp.unlink(missing_ok=True)
            raise ProviderError('视频已生成，缓存下载失败；稍后可重新同步') from None
