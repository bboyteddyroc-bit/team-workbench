"""Validate generated pixels and atomically publish an owner-private material."""
import base64
import io
import secrets
import time
from PIL import Image


def save_result(hub,uid,tid,turn,payload):
    import json
    entries=payload.get('data',[])
    if not 1<=len(entries)<=4:raise ValueError('未取得有效图片，请核对原任务；不会重新生成。')
    decoded=[]
    for entry in entries:
        try:
            encoded=entry['b64_json']
            if not isinstance(encoded,str) or len(encoded)>44*1024*1024:raise ValueError()
            raw=base64.b64decode(encoded,validate=True)
            with Image.open(io.BytesIO(raw)) as im:
                if im.width*im.height>26000000 or im.format not in ('PNG','JPEG','WEBP'):raise ValueError()
                im.load();out=io.BytesIO();im.convert('RGB').save(out,format='PNG');decoded.append(out.getvalue())
        except Exception:
            raise ValueError('图片校验失败，原下载文件已保留；不会重新生成。') from None
    ids=[secrets.token_hex(16) for _ in decoded];targets=[hub.assets/i for i in ids]
    try:
        for target,raw in zip(targets,decoded):target.write_bytes(raw)
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT generation FROM ai_turns WHERE id=? AND owner=? AND thread=? AND status=?',(turn,uid,tid,'pending')).fetchone()
            if not row:raise ValueError('对话已删除，生成结果未保存。')
            expected=json.loads(row['generation']).get('count',1)
            answer=f'已保存 {len(ids)} 张图片。'+(f'原请求为 {expected} 张，其余结果尚未确认，请核对 LibTV 原任务，未自动重试。' if len(ids)<expected else '')
            for asset,raw in zip(ids,decoded):
                db.execute('INSERT INTO assets VALUES(?,?,?,?,?,?)',(asset,uid,'AI生成-'+asset[:8]+'.png','image/png',len(raw),time.time()))
                db.execute("INSERT INTO asset_classification(asset_id,status,folder,source,updated) VALUES(?,'classified','other','generated',?)",(asset,time.time()))
            db.execute("UPDATE ai_turns SET answer=?,result_asset=?,result_assets=?,status='complete' WHERE id=? AND owner=?",(answer,ids[0],json.dumps(ids),turn,uid))
        return {'id':turn,'answer':answer,'status':'complete','result_asset':ids[0],'result_assets':ids}
    except Exception:
        for target in targets:target.unlink(missing_ok=True)
        raise


def verify_image_account(cli, work, expected):
    if not expected:
        raise ValueError('原生图账号未授权，无法远程取回；不会使用其他账号。')
    result=cli(['account','list'],work)
    accounts=result.get('accounts') if isinstance(result,dict) else None
    active=[a for a in accounts if isinstance(a,dict) and a.get('isActive') is True] if isinstance(accounts,list) else []
    if len(active)!=1 or str(active[0].get('accountId'))!=expected:
        raise ValueError('LibTV 生图账号身份与任务不匹配，请联系管理员；不会使用其他账号。')


def generate_libtv(hub,uid,tid,turn,prompt,images,generation,route):
    from libtv_gateway import cli
    from libtv_isolation import bind
    import re
    work=hub.directory/'libtv'/('image-'+turn);work.mkdir(parents=True,exist_ok=True)
    bind(work,route.profile)
    verify_image_account(cli,work,route.account)
    schema=cli(['model','lib-image-2.5-f'],work)
    model=schema.get('schema',{})
    if model.get('modelKey')!='lib-image-2.5-f':raise ValueError('LibTV 图片模型配置已变化')
    count=generation.get('count',1)
    supported=model.get('properties',{}).get('count')
    if supported is not None and count not in supported:raise ValueError('LibTV 当前模型不支持所选数量，未提交生图')
    result=cli(['project','create','中台生图-'+turn,'--team-id','0','-w','0'],work)
    project=(result.get('projectMeta') or {}).get('uuid')
    if not isinstance(project,str) or not re.fullmatch('[a-zA-Z0-9-]{16,64}',project):raise ValueError('无法识别 LibTV 画布，未自动重试')
    with hub.db() as db:db.execute('UPDATE ai_turns SET generation=? WHERE id=? AND owner=?',(json_generation(generation,project),turn,uid))
    links=[]
    for index,image in enumerate(images,1):
        path=work/('reference-'+str(index)+'.jpg');path.write_bytes(base64.b64decode(image['url'].split(',',1)[1],validate=True))
        try:cli(['upload','参考'+str(index),'-p',project,'-t','image','-f',str(path.resolve())],work)
        finally:path.unlink(missing_ok=True)
        links.extend(['--left','参考'+str(index)])
    try:
        cli(['node','create','图片','-p',project,'-t','image','--prompt',prompt,'-s','model=Lib Image 2.5 Fast','-s','modeType=image2image','-s','resolution='+generation['size'],'-s','ratio='+generation['ratio'],'-s','count='+str(count),*links,'--run'],work)
    except RuntimeError:
        if inspect_image_node(cli,project,work)!='output':raise
    return import_libtv_result(hub,uid,tid,turn,project,work,route.profile,route.account,verified=True)


def inspect_image_node(cli,project,work):
    """Only the original node's structured terminal state can rule out recovery."""
    from libtv_gateway import ProviderGenerationFailed
    try:
        reply=cli(['node','图片','-p',project],work)
    except (RuntimeError,OSError):
        return 'unknown'
    data=reply.get('data') if isinstance(reply,dict) else None
    if not isinstance(data,dict):return 'unknown'
    urls=data.get('url')
    if isinstance(urls,list) and any(isinstance(u,str) and u.startswith(('http://','https://')) for u in urls):return 'output'
    task=data.get('taskInfo')
    if isinstance(task,dict) and str(task.get('status'))=='3' and not urls:
        raise ProviderGenerationFailed(terminal_failure_message('积分已返还' in str(task.get('failedReason') or '')))
    return 'unknown'


def terminal_failure_message(refunded):
    return 'LibTV 已确认生图失败，没有可取回的图片。'+('平台报告积分已返还。' if refunded else '积分状态请以 LibTV 为准。')+'中台未自动重试。'


def record_image_failure(hub,uid,turn,exc):
    from libtv_gateway import ProviderGenerationFailed
    with hub.db() as db:
        if isinstance(exc,ProviderGenerationFailed):
            db.execute("UPDATE ai_turns SET status='failed',answer=?,generation=json_set(generation,'$.terminal_failure',json('true')) WHERE id=? AND owner=? AND status='pending'",(str(exc),turn,uid))
        else:
            db.execute("UPDATE ai_turns SET status='failed' WHERE id=? AND owner=? AND status='pending'",(turn,uid))


def import_libtv_result(hub,uid,tid,turn,project,work,profile,account,*,verified=False):
    """Import cached pixels first; remote recovery is limited to the original identity."""
    from libtv_gateway import cli
    from libtv_isolation import bind
    output=work/'download';output.mkdir(parents=True,exist_ok=True)
    def downloaded():
        return [p for p in output.iterdir() if p.is_file() and p.suffix.lower() in ('.png','.jpg','.jpeg','.webp')]
    files=downloaded()
    if not files:
        bind(work,profile)
        if not verified:
            verify_image_account(cli,work,account)
        try:
            cli(['download','-p',project,'-n','图片','-o',str(output.resolve())],work)
        except RuntimeError:
            if not downloaded():inspect_image_node(cli,project,work)
            raise
        files=downloaded()
        if not files:inspect_image_node(cli,project,work)
    files=sorted(files)
    if not 1<=len(files)<=4 or any(not 0<p.stat().st_size<=32*1024*1024 for p in files):raise ValueError('LibTV 返回的图片数量或大小异常，请核对原任务；不会重新生成')
    result=save_result(hub,uid,tid,turn,{'data':[{'b64_json':base64.b64encode(p.read_bytes()).decode()} for p in files]})
    # Retain source pixels, including partial results, for later manual inspection.
    return result


def json_generation(generation,project):
    import json
    return json.dumps({**generation,'project':project},sort_keys=True)
