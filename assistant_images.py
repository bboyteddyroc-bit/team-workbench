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


def generate_libtv(hub,uid,tid,turn,prompt,images,generation):
    from libtv_gateway import cli
    import re
    work=hub.directory/'libtv'/('image-'+turn);work.mkdir(parents=True,exist_ok=True)
    with hub.db() as db:setting=db.execute('SELECT account FROM libtv_settings WHERE id=1').fetchone()
    if not setting:raise ValueError('请管理员先连接共享 LibTV 账号')
    result=cli(['account','list'],work)
    if not any(str(a.get('accountId'))==setting['account'] and a.get('isActive') for a in result.get('accounts',[])):raise ValueError('共享 LibTV 账号已变更，请管理员重新连接')
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
    cli(['node','create','图片','-p',project,'-t','image','--prompt',prompt,'-s','model=Lib Image 2.5 Fast','-s','modeType=image2image','-s','resolution='+generation['size'],'-s','ratio='+generation['ratio'],'-s','count='+str(count),*links,'--run'],work)
    return import_libtv_result(hub,uid,tid,turn,project,work)


def import_libtv_result(hub,uid,tid,turn,project,work):
    """Import an existing download first; never create or rerun a generation."""
    from libtv_gateway import cli
    output=work/'download';output.mkdir(parents=True,exist_ok=True)
    def downloaded():
        return [p for p in output.iterdir() if p.is_file() and p.suffix.lower() in ('.png','.jpg','.jpeg','.webp')]
    files=downloaded()
    if not files:
        cli(['download','-p',project,'-n','图片','-o',str(output.resolve())],work)
        files=downloaded()
    files=sorted(files)
    if not 1<=len(files)<=4 or any(not 0<p.stat().st_size<=32*1024*1024 for p in files):raise ValueError('LibTV 返回的图片数量或大小异常，请核对原任务；不会重新生成')
    result=save_result(hub,uid,tid,turn,{'data':[{'b64_json':base64.b64encode(p.read_bytes()).decode()} for p in files]})
    # Retain source pixels, including partial results, for later manual inspection.
    return result


def json_generation(generation,project):
    import json
    return json.dumps({**generation,'project':project},sort_keys=True)
