from pathlib import Path
p=Path(__file__).with_name('video_cases.py');s=p.read_text(encoding='utf-8')
s=s.replace("ACTIVE=('queued','submitting','running')","ACTIVE=('queued','submitting','running','waiting')")
s=s.replace("state IN ('queued','submitting','running')","state IN ('queued','submitting','running','waiting')")
s=s.replace("            db.execute(\"ALTER TABLE video_case_jobs ADD COLUMN options TEXT NOT NULL DEFAULT '{}'\")","            db.execute(\"ALTER TABLE video_case_jobs ADD COLUMN options TEXT NOT NULL DEFAULT '{}'\")\n        from video_case_recovery import initialize as recovery_schema\n        recovery_schema(db)")
s=s.replace("WHERE j.state IN ('queued','running') ORDER BY j.updated LIMIT 1","WHERE (j.state='queued' OR (j.state='waiting' AND j.next_attempt<=?) OR (j.state='running' AND j.kind='metadata' AND j.remote_id IS NOT NULL)) ORDER BY j.updated LIMIT 1")
s=s.replace("ORDER BY j.updated LIMIT 1''').fetchone()","ORDER BY j.updated LIMIT 1''',(time.time(),)).fetchone()")
s=s.replace("            if job['state']=='queued':db.execute", "            if job['state']=='waiting':\n                if time.time()>=(job['wait_deadline'] or 0):\n                    from video_case_recovery import defer\n                    defer(db,job['id']);return\n                job['state']='queued'\n            if job['state']=='queued':db.execute")
s=s.replace("            self.fail(job['id'],msg)","            if isinstance(exc,QueryError) and exc.waiting_media and job['kind']=='analysis':\n                from video_case_recovery import defer\n                with self.hub.db() as db:defer(db,job['id'])\n                self.checkpoint(job['id'],'等待供应商视频缓存')\n                return\n            self.fail(job['id'],msg)")
s=s.replace("state='ready',error='',updated=? WHERE id=?","state='ready',error='',error_code='',next_attempt=NULL,updated=? WHERE id=?")
s=s.replace("SELECT id,kind,state,error,owner,created,updated FROM video_case_jobs", "SELECT id,kind,state,error,owner,created,updated,wait_count,next_attempt,wait_deadline,error_code FROM video_case_jobs")
# Cancellation is not a replay; only an unclaimed waiting job can be cancelled.
anchor="    @app.post(PREFIX+'/{cid}/refresh-local')"
s=s.replace(anchor,"""    @app.post(PREFIX+'/{cid}/jobs/{jid}/cancel-wait')
    def cancel_wait(cid:str,jid:str,request:Request):
        u=user(request)
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE');require_case(db,cid)
            job=db.execute('SELECT owner,state FROM video_case_jobs WHERE id=? AND case_id=?',(jid,cid)).fetchone()
            if not job or job['owner']!=u['id']:raise HTTPException(404,'任务不存在或不属于你')
            if job['state']=='cancelled':return {'ok':True}
            if job['state']!='waiting':raise HTTPException(409,'任务不在等待状态，未中断正在执行的请求')
            db.execute("UPDATE video_case_jobs SET state='cancelled',next_attempt=NULL,error='已停止自动检查；保留已取得的资料',updated=? WHERE id=?",(time.time(),jid))
            hub.log(db,u['id'],'video_case_cancel_wait',jid)
        return {'ok':True}
"""+anchor)
p.write_text(s,encoding='utf-8')
p=Path(__file__).with_name('video_case_analysis.py');s=p.read_text(encoding='utf-8').replace("        warnings.append(str(exc)[:300] if", "        if isinstance(exc,QueryError) and exc.waiting_media:raise\n        warnings.append(str(exc)[:300] if")
p.write_text(s,encoding='utf-8')
