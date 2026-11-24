"""Opt-in script processing: snapshot matching, bounded rechecks, local ASR.
No network access takes place until an owner explicitly enables rechecks or ASR.
"""
import json
import logging
import math
import shutil
import subprocess
import sys
import importlib.util
import tempfile
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi import HTTPException, Request
from script_library import matches

log = logging.getLogger(__name__)
DAY = 86400
MAX_AUDIO_BYTES = 150 * 1024 * 1024

def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS script_auto_config(owner TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0,
        recheck INTEGER NOT NULL DEFAULT 0, transcribe INTEGER NOT NULL DEFAULT 0,
        likes REAL, collects REAL, comments REAL, updated REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS script_auto_seen(account TEXT NOT NULL, video TEXT NOT NULL, collected REAL NOT NULL,
        PRIMARY KEY(account,video));
    CREATE TABLE IF NOT EXISTS script_rechecks(account TEXT NOT NULL, video TEXT NOT NULL, stage INTEGER NOT NULL,
        due REAL NOT NULL, state TEXT NOT NULL, run TEXT, PRIMARY KEY(account,video,stage));
    CREATE TABLE IF NOT EXISTS script_transcriptions(item TEXT PRIMARY KEY, account TEXT NOT NULL, owner TEXT NOT NULL,
        state TEXT NOT NULL, error TEXT, updated REAL NOT NULL);
    ''')

def local_asr_ready():
    import asr
    s=asr.status()
    return bool(s['installed'] and s['model_ready'] and shutil.which('ffmpeg') and importlib.util.find_spec('yt_dlp'))

def transcribe(handle, video):
    """Only a canonical TikTok URL is accepted; subprocess gets no cookies or arbitrary input URL."""
    import asr
    if not video.isdigit() or not handle or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789._' for c in handle):
        raise ValueError('视频地址无效')
    if not local_asr_ready(): raise ValueError('缺少 yt-dlp、FFmpeg 或本地语音模型，请联系管理员')
    with tempfile.TemporaryDirectory(prefix='script-asr-') as directory:
        template=str(Path(directory)/'source.%(ext)s')
        command=[sys.executable,'-m','yt_dlp','--ignore-config','--no-playlist','--no-progress','--socket-timeout','30','--retries','0',
                 '--max-filesize',str(MAX_AUDIO_BYTES),'-f','bestaudio/best','-o',template,
                 'https://www.tiktok.com/@'+handle+'/video/'+video]
        try:
            result=subprocess.run(command,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,
                                  timeout=240,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except (OSError,subprocess.TimeoutExpired): raise ValueError('视频音频下载超时或不可用；请人工检查') from None
        paths=[p for p in Path(directory).iterdir() if p.is_file() and not p.name.endswith(('.part','.ytdl'))]
        if result.returncode or len(paths)!=1: raise ValueError('无法读取公开视频音频；可能被限制、下架或需要登录')
        source=paths[0]
        if source.stat().st_size>MAX_AUDIO_BYTES: raise ValueError('视频音频超过大小限制')
        # ASR consumes a local file; a ready model is mandatory to prevent implicit downloads.
        segments,info=asr.engine().transcribe(str(source),beam_size=5,vad_filter=True)
        text=' '.join(segment.text.strip() for segment in segments if segment.text.strip()).strip()
        if not text: raise ValueError('未识别到可用语音，请人工核查')
        if len(text)>30000: raise ValueError('识别结果超过长度限制，请人工核查')
        return text, 'faster-whisper '+asr.model_name()+'；语言 '+str(getattr(info,'language','未知'))

class Automation:
    def __init__(self,hub,monitor):
        self.hub,self.monitor=hub,monitor
        with hub.db() as db: initialize(db)

    def recover(self):
        with self.hub.db() as db:
            db.execute("UPDATE script_transcriptions SET state='attention',error='识别期间服务重启，请手动重新排队',updated=? WHERE state='running'",(time.time(),))
            db.execute("UPDATE script_enrichment SET state='attention',error='处理期间服务重启，结果未知，请人工复核',updated=? WHERE state='running'",(time.time(),))

    def scan(self):
        now=time.time()
        with self.hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("""UPDATE script_rechecks SET state=COALESCE((SELECT CASE state WHEN 'ready' THEN 'ready' WHEN 'attention' THEN 'attention' WHEN 'cancelled' THEN 'cancelled' ELSE 'queued' END FROM apify_runs WHERE id=script_rechecks.run),'attention') WHERE state='queued' AND run IS NOT NULL""")
            rows=db.execute('''SELECT s.*, a.handle,a.owner,c.likes AS lim_likes,c.collects AS lim_collects,c.comments AS lim_comments,c.recheck,c.transcribe
              FROM apify_snapshots s JOIN apify_accounts a ON a.id=s.account
              JOIN users u ON u.id=a.owner AND u.enabled=1
              JOIN script_auto_config c ON c.owner=a.owner AND c.enabled=1
              JOIN auto_collection_selection sel ON sel.account=a.id AND sel.owner=a.owner AND sel.selected=1
              LEFT JOIN script_auto_seen seen ON seen.account=s.account AND seen.video=s.video
              WHERE a.deleted_at IS NULL AND (seen.collected IS NULL OR s.collected>seen.collected)
              AND s.rowid=(SELECT t.rowid FROM apify_snapshots t WHERE t.account=s.account AND t.video=s.video ORDER BY t.collected DESC,t.rowid DESC LIMIT 1)
              ORDER BY s.collected LIMIT 200''').fetchall()
            for raw in rows:
                row=dict(raw); thresholds={key:row['lim_'+key] for key in ('likes','collects','comments')}; reasons=matches(row,thresholds)
                db.execute('INSERT INTO script_auto_seen VALUES(?,?,?) ON CONFLICT(account,video) DO UPDATE SET collected=excluded.collected',(row['account'],row['video'],row['collected']))
                if reasons:
                    old=db.execute('SELECT id,removed_at FROM script_library WHERE video=?',(row['video'],)).fetchone()
                    if old and old['removed_at'] is not None:continue
                    ident=old['id'] if old else uuid.uuid4().hex
                    snapshot={k:row[k] for k in ('views','likes','collects','comments','shares','collected')}
                    snapshot['thresholds']=thresholds
                    if not old:
                        url='https://www.tiktok.com/@'+row['handle']+'/video/'+row['video'] if row['video'].isdigit() else ''
                        db.execute('''INSERT INTO script_library(id,video,account_handle,video_url,published,description,cover,snapshot,reasons,transcript_status,created,updated,created_by,updated_by)
                          VALUES(?,?,?,?,?,?,?,?,?,'未提取',?,?,?,?)''',(ident,row['video'],row['handle'],url,row['published'],row['title'],row['cover'],json.dumps(snapshot),json.dumps(reasons,ensure_ascii=False),now,now,row['owner'],row['owner']))
                    db.execute("UPDATE script_rechecks SET state='cancelled' WHERE account=? AND video=? AND state='waiting'",(row['account'],row['video']))
                    if row['transcribe'] and not db.execute('SELECT 1 FROM script_transcriptions WHERE item=?',(ident,)).fetchone():
                        item=db.execute('SELECT transcript_original FROM script_library WHERE id=?',(ident,)).fetchone()
                        if not item['transcript_original']:
                            db.execute("INSERT INTO script_transcriptions VALUES(?,?,?,'queued',NULL,?)",(ident,row['account'],row['owner'],now))
                            db.execute("UPDATE script_library SET transcript_status='待提取' WHERE id=?",(ident,))
                elif row['recheck'] and row['published'] and 0<=now-row['published']<3*DAY:
                    for stage in (2,3):
                        due=row['published']+stage*DAY
                        if due>now:
                            db.execute("INSERT OR IGNORE INTO script_rechecks VALUES(?,?,?,?,'waiting',NULL)",(row['account'],row['video'],stage,due))

    def recheck_tick(self):
        now=time.time()
        with self.hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('''SELECT r.*,a.owner,a.handle FROM script_rechecks r JOIN apify_accounts a ON a.id=r.account
                JOIN script_auto_config c ON c.owner=a.owner AND c.enabled=1 AND c.recheck=1
                JOIN users u ON u.id=a.owner AND u.enabled=1
                JOIN auto_collection_selection s ON s.account=a.id AND s.owner=a.owner AND s.selected=1
                WHERE r.state='waiting' AND r.due<=? AND a.deleted_at IS NULL ORDER BY r.due LIMIT 1''',(now,)).fetchone()
            if not row:return
            row=dict(row)
            if now-row['due']>DAY:
                db.execute("UPDATE script_rechecks SET state='expired' WHERE account=? AND video=? AND stage=?",(row['account'],row['video'],row['stage']));return
            if not self.monitor.config.secret():return
            if db.execute("SELECT 1 FROM apify_runs WHERE account=? AND state IN ('queued','submitting','running')",(row['account'],)).fetchone():return
            if db.execute("SELECT 1 FROM grouped_run_members WHERE account=? AND state IN ('queued','submitting','running')",(row['account'],)).fetchone():return
            # Existing actor uses a profile + date window, not a per-video endpoint: one day may contain other posts.
            published=db.execute('SELECT published FROM apify_snapshots WHERE account=? AND video=? ORDER BY collected DESC LIMIT 1',(row['account'],row['video'])).fetchone()
            if not published or not published[0]:return
            d=datetime.fromtimestamp(published[0],timezone.utc).date();start=datetime(d.year,d.month,d.day,tzinfo=timezone.utc).timestamp()
            rid=uuid.uuid4().hex; settings={'mode':'custom','timezone':'UTC','start':d.isoformat(),'end':d.isoformat()}
            db.execute("INSERT INTO apify_runs(id,account,state,created,updated,options,start_at,end_at) VALUES(?,?,'queued',?,?,?,?,?)",(rid,row['account'],now,now,json.dumps(settings),start,start+DAY))
            db.execute("""UPDATE script_rechecks SET state='queued',run=? WHERE account=? AND state='waiting' AND due<=? AND due>? AND video IN
                (SELECT video FROM apify_snapshots WHERE account=? AND published>=? AND published<?)""",(rid,row['account'],now,now-DAY,row['account'],start,start+DAY))

    def transcription_tick(self):
        with self.hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('''SELECT t.*,l.video,a.handle FROM script_transcriptions t JOIN script_library l ON l.id=t.item
                JOIN script_auto_config c ON c.owner=t.owner AND c.enabled=1 AND c.transcribe=1
                JOIN apify_accounts a ON a.id=t.account AND a.deleted_at IS NULL
                JOIN users u ON u.id=t.owner AND u.enabled=1
                JOIN auto_collection_selection s ON s.owner=t.owner AND s.account=t.account AND s.selected=1
                WHERE t.state='queued' ORDER BY t.updated LIMIT 1''').fetchone()
            if not row:return
            row=dict(row)
            db.execute("UPDATE script_transcriptions SET state='running',updated=? WHERE item=? AND state='queued'",(time.time(),row['item']))
            db.execute("UPDATE script_library SET transcript_status='提取中' WHERE id=?",(row['item'],))
        try:
            import task_feedback as feedback
            with feedback.bound(self.hub,'script_transcript',row['item']):
                with feedback.step('transcript'):
                    text,source=transcribe(row['handle'],row['video'])
                with feedback.step('data_save'), self.hub.db() as db:
                    db.execute("UPDATE script_library SET transcript_original=?,transcript_source=?,transcript_status='已提取',updated=? WHERE id=? AND transcript_original IS NULL",(text,source,time.time(),row['item']))
                    db.execute("UPDATE script_transcriptions SET state='ready',error=NULL,updated=? WHERE item=?",(time.time(),row['item']))
        except Exception as exc:
            error=str(exc)[:200] if isinstance(exc,ValueError) else '提取失败，请检查本地环境和视频可访问性'
            with self.hub.db() as db:
                db.execute("UPDATE script_transcriptions SET state='attention',error=?,updated=? WHERE item=?",(error,time.time(),row['item']))
                db.execute("UPDATE script_library SET transcript_status='提取失败' WHERE id=?",(row['item'],))

    def tick(self):
        self.scan();self.recheck_tick();self.transcription_tick()
        import script_enrichment
        script_enrichment.tick(self.hub)

    def loop(self):
        while not self.hub.stop.is_set():
            try:self.tick()
            except Exception:log.exception('文案自动化检查失败')
            self.hub.stop.wait(10)

def attach(app,hub,user,body):
    service=Automation(hub,app.state.apify_monitor);app.state.script_automation=service
    @app.get('/api/intelligence/scripts/automation')
    def settings(request:Request):
        u=user(request)
        with hub.db() as db:
            row=db.execute('SELECT enabled,recheck,transcribe,likes,collects,comments FROM script_auto_config WHERE owner=?',(u['id'],)).fetchone()
            counts={r['state']:r['n'] for r in db.execute('SELECT state,COUNT(*) n FROM script_transcriptions WHERE owner=? GROUP BY state',(u['id'],))}
            failures=[dict(r) for r in db.execute("SELECT t.item,l.video,t.error FROM script_transcriptions t JOIN script_library l ON l.id=t.item WHERE t.owner=? AND t.state='attention' ORDER BY t.updated DESC LIMIT 20",(u['id'],))]
            rechecks={r['state']:r['n'] for r in db.execute('SELECT r.state,COUNT(*) n FROM script_rechecks r JOIN apify_accounts a ON a.id=r.account WHERE a.owner=? GROUP BY r.state',(u['id'],))}
            ai_failures=[dict(r) for r in db.execute("SELECT e.item,l.video,e.error FROM script_enrichment e JOIN script_library l ON l.id=e.item WHERE e.owner=? AND e.state='attention' ORDER BY e.updated DESC LIMIT 20",(u['id'],))]
        return {'config':dict(row) if row else {'enabled':0,'recheck':0,'transcribe':0,'likes':None,'collects':None,'comments':None},'asr_ready':local_asr_ready(),'counts':counts,'rechecks':rechecks,'failures':failures,'ai_failures':ai_failures}

    @app.post('/api/intelligence/scripts/enrichment-consent')
    async def enrichment_consent(request:Request):
        u=user(request); data=await body(request)
        if data.get('confirm') is not True: raise HTTPException(400,'请确认使用 A6API Gemini 3.8 Flash 处理文案并承担可能的费用')
        with hub.db() as db:
            db.execute('INSERT INTO script_enrichment_consent VALUES(?,1,?) ON CONFLICT(owner) DO UPDATE SET enabled=1,updated=excluded.updated',(u['id'],time.time()))
        return {'ok':True}

    @app.post('/api/intelligence/scripts/automation')
    async def save_settings(request:Request):
        u=user(request); data=await body(request)
        enabled,recheck,asr=(data.get(k) for k in ('enabled','recheck','transcribe'))
        if any(type(x) is not bool for x in (enabled,recheck,asr)):raise HTTPException(400,'开关格式无效')
        if (recheck or asr) and not enabled:raise HTTPException(400,'请先启用自动入选')
        if (recheck or asr) and data.get('confirm_automation') is not True:raise HTTPException(400,'请确认自动化会产生采集费用和视频下载流量')
        if asr and not local_asr_ready():raise HTTPException(400,'缺少 yt-dlp、FFmpeg 或本地语音模型；未开启提取')
        thresholds=[]
        for key in ('likes','collects','comments'):
            value=data.get(key)
            if value is not None and (type(value) not in (int,float) or not math.isfinite(value) or not 0<value<=100):raise HTTPException(400,'互动率须大于 0 且不超过 100，未设置留空')
            thresholds.append(value)
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('''INSERT INTO script_auto_config VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(owner) DO UPDATE SET
                enabled=excluded.enabled,recheck=excluded.recheck,transcribe=excluded.transcribe,likes=excluded.likes,collects=excluded.collects,comments=excluded.comments,updated=excluded.updated''',(u['id'],int(enabled),int(recheck),int(asr),*thresholds,time.time()))
            # 这里与 recheck_tick 共用写锁：保存后才排队，删除所见记录后才能重新判定。
            db.execute("""UPDATE apify_runs SET state='cancelled',updated=? WHERE state='queued' AND id IN (
                SELECT rc.run FROM script_rechecks rc JOIN apify_accounts a ON a.id=rc.account
                LEFT JOIN users u ON u.id=a.owner LEFT JOIN script_auto_config c ON c.owner=a.owner
                LEFT JOIN auto_collection_selection s ON s.owner=a.owner AND s.account=a.id
                WHERE a.deleted_at IS NOT NULL OR COALESCE(u.enabled,0)<>1 OR COALESCE(c.enabled,0)<>1
                  OR COALESCE(c.recheck,0)<>1 OR COALESCE(s.selected,0)<>1)""",(time.time(),))
            db.execute('DELETE FROM script_auto_seen WHERE account IN (SELECT id FROM apify_accounts WHERE owner=?)',(u['id'],))
            if enabled and recheck:
                db.execute("DELETE FROM script_rechecks WHERE state IN ('cancelled','expired') AND account IN (SELECT id FROM apify_accounts WHERE owner=?)",(u['id'],))
                # 已处于 due 但尚未排队的复查，保存后下一轮立即排队；跳过的中间轮次不再补发。
                db.execute("UPDATE script_rechecks SET due=? WHERE state='waiting' AND due<? AND account IN (SELECT id FROM apify_accounts WHERE owner=?)",(time.time(),time.time(),u['id']))
            if not enabled or not recheck:
                # 尚未提交的排队复查可以安全取消；已提交的任务保持原状，费用不追回。
                db.execute("UPDATE script_rechecks SET state='cancelled' WHERE state IN ('waiting','queued') AND account IN (SELECT id FROM apify_accounts WHERE owner=?)",(u['id'],))
            hub.log(db,u['id'],'script_automation_settings',str(int(enabled)))
        return {'ok':True}

    @app.post('/api/intelligence/scripts/automation/retry/{item_id}')
    def retry(item_id:str,request:Request):
        u=user(request)
        with hub.db() as db:
            changed=db.execute("""UPDATE script_transcriptions SET state='queued',error=NULL,updated=? WHERE item=? AND owner=? AND state='attention'
              AND EXISTS (SELECT 1 FROM script_auto_config c JOIN apify_accounts a ON a.owner=c.owner
                JOIN auto_collection_selection s ON s.owner=c.owner AND s.account=a.id AND s.selected=1
                JOIN users u ON u.id=c.owner AND u.enabled=1 WHERE c.owner=script_transcriptions.owner
                AND a.id=script_transcriptions.account AND a.deleted_at IS NULL AND c.enabled=1 AND c.transcribe=1)""",(time.time(),item_id,u['id'])).rowcount
            if not changed:raise HTTPException(404,'没有可重试的失败任务')
            db.execute("UPDATE script_library SET transcript_status='待提取' WHERE id=?",(item_id,))
        return {'ok':True}
