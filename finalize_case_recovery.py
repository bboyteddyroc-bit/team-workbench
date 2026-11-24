from pathlib import Path
root=Path(__file__).resolve().parent
p=root/'video_cases.py';s=p.read_text(encoding='utf-8')
s=s.replace("    def fail(self,jid,message):\n        with self.hub.db() as db:db.execute(\"UPDATE video_case_jobs SET state='attention',error=?,updated=? WHERE id=?\",(message[:600],time.time(),jid))", "    def fail(self,jid,message,code=None):\n        with self.hub.db() as db:db.execute(\"UPDATE video_case_jobs SET state='attention',error=?,error_code=?,next_attempt=NULL,updated=? WHERE id=?\",(message[:600],str(code or '')[:40],time.time(),jid))")
s=s.replace("            self.fail(job['id'],msg)","            self.fail(job['id'],msg,exc.code if isinstance(exc,QueryError) else None)")
s=s.replace("source=json.loads(row['source']);human=json.loads(row['human']);ai=json.loads(row['ai']).get('fields',{});iid=uuid.uuid4().hex;now=time.time();text=human.get('transcript') or row['transcript']", "source=json.loads(row['source']);human=json.loads(row['human']);ai=json.loads(row['ai']).get('fields',{});iid=uuid.uuid4().hex;now=time.time()\n            from video_case_fields import projection\n            resolved=projection({**row,'source':source,'human':human,'ai':json.loads(row['ai'])});text=resolved['transcript']['value']")
s=s.replace("source.get('title') or human.get('title','')","resolved['title']['value']")
for key,ai_key in [('category','product_category'),('content_type','content_type'),('opening','opening'),('audience_scenario','audience_scenario'),('expression','expression'),('ending','ending')]:
    s=s.replace("human.get('"+key+"') or ai.get('"+ai_key+"','')", "resolved['"+key+"']['value']")
# Metadata is an optional cumulative snapshot, never replacing range-scoped Kalodata provenance.
needle="        with self.hub.db() as db:\n            db.execute('UPDATE video_cases SET source=?,updated=? WHERE id=?',(json.dumps(source,ensure_ascii=False),time.time(),case['id']))"
s=s.replace(needle,"        with self.hub.db() as db:\n            latest=json.loads(db.execute('SELECT source FROM video_cases WHERE id=?',(case['id'],)).fetchone()[0])\n            if latest.get('kalodata'):\n                source['kalodata']=latest['kalodata'];source['primary_provider']='Kalodata'\n            db.execute('UPDATE video_cases SET source=?,updated=? WHERE id=?',(json.dumps(source,ensure_ascii=False),time.time(),case['id']))")
p.write_text(s,encoding='utf-8')
p=root/'static/video-cases.js';s=p.read_text(encoding='utf-8')
s=s.replace("function displayTitle(r){return val(r,'title')||r.source.title||", "function displayTitle(r){return (Object.hasOwn(r.human||{},'title')?r.human.title:(val(r,'title')||r.source.title))||")
s=s.replace("${j.stage?' · '+esc(j.stage):''}","${j.stage&&['queued','submitting','running','waiting'].includes(j.state)?' · '+esc(j.stage):''}")
s=s.replace("function active(){return rows.some(r=>r.latest_jobs?.some(j=>['queued','submitting','running','waiting'].includes(j.state)))}", "function active(){return rows.some(r=>r.latest_jobs?.some(j=>['queued','submitting','running','waiting'].includes(j.state)))||current?.jobs?.some(j=>['queued','submitting','running','waiting'].includes(j.state))}")
# No source/AI duplicate evidence on manually cleared fields.
p.write_text(s,encoding='utf-8')
p=root/'static/index.html';s=p.read_text(encoding='utf-8').replace('video-cases.js?v=gallery-drawer-20261117','video-cases.js?v=recovery-source-first-20261117').replace('video-cases.css?v=gallery-drawer-20261117','video-cases.css?v=recovery-source-first-20261117');p.write_text(s,encoding='utf-8')
