"""Bounded completion from already-downloaded videos; one AI submission per case receipt.
Never requests Kalodata. Existing successful answers are locally revalidated, not resubmitted.
"""
from pathlib import Path
import json,os,time,uuid
from app import create_app
from video_case_analysis import prepare,request,clean,save_answer
import asr
root=Path(__file__).resolve().parent
ffbin=root/'tools/ffmpeg-7.1.1/ffmpeg-7.1.1-essentials_build/bin'
os.environ['PATH']=str(ffbin)+os.pathsep+os.environ.get('PATH','')
app=create_app(root/'state',worker=False);hub=app.state.hub;cases=app.state.video_cases
class NoProvider:
    def post(self,*args,**kwargs):raise RuntimeError('No new Kalodata calls authorized by cached completion')
for video in ('7708328890967608590',):
    with hub.db() as db:
        db.execute('BEGIN IMMEDIATE');row=dict(db.execute('SELECT * FROM video_cases WHERE video=?',(video,)).fetchone())
        key='cached-schema-completion-20261116:'+row['id']
        old=db.execute('SELECT id,state FROM video_case_jobs WHERE request_key=?',(key,)).fetchone()
        if old:
            print(json.dumps({'video':video,'existing':dict(old),'no_replay':True}),flush=True);continue
        if db.execute("SELECT 1 FROM video_case_jobs WHERE case_id=? AND state IN ('queued','running','submitting')",(row['id'],)).fetchone():raise RuntimeError('Case active; no duplicate')
        if not (hub.directory/'case-analysis'/row['id']/'source.mp4').is_file():raise RuntimeError('No cached video; refusing provider call')
        jid=uuid.uuid4().hex;now=time.time()
        db.execute("INSERT INTO video_case_jobs(id,case_id,owner,kind,state,request_key,created,updated,options) VALUES(?,?,?,'analysis','submitting',?,?,?,?)",(jid,row['id'],row['created_by'],key,now,now,json.dumps({'consent':'user requested 全部做完','cached_video_only':True})))
    try:
        checkpoint=lambda text:cases.checkpoint(jid,text)
        prepared=prepare(hub,NoProvider(),row,jid,checkpoint)
        human=json.loads(row['human']);source=json.loads(row['source']);transcript=human.get('transcript') or prepared['transcript'];title=human.get('title') or source.get('title','')
        if not prepared['images'] and not transcript and not title:raise ValueError('No evidence; AI not called')
        key_ai=asr.configured_key(hub)
        if not key_ai:raise ValueError('No configured AI; not submitted')
        checkpoint('复用本地视频；AI分析提交中，未知结果不重提')
        raw=request({'title':title,'kalodata':source.get('kalodata',{}),'transcript':transcript,'warnings':prepared['warnings'],'image_count':len(prepared['images'])},prepared['images'],key_ai,answer_path=hub.directory/'case-analysis'/row['id']/(jid+'-answer.txt'))
        save_answer(hub,row['id'],jid,raw)
        fields,evidence,uncertain=clean(raw,transcript,bool(prepared['images']))
        packed={'fields':fields,'evidence':evidence,'uncertainties':prepared['warnings']+uncertain,'generated_at':time.time(),'basis':'Kalodata视频9帧采样'+(' + 本地ASR' if transcript else '；未取得口播'),'policy':'case-review-v2'}
        with hub.db() as db:
            now=time.time();db.execute('UPDATE video_cases SET ai=?,updated=? WHERE id=?',(json.dumps(packed,ensure_ascii=False),now,row['id']))
            if prepared['transcript']:db.execute("UPDATE video_cases SET transcript=?,transcript_source=? WHERE id=? AND length(trim(transcript))=0",(prepared['transcript'],prepared['transcript_source'],row['id']))
            db.execute("UPDATE video_case_jobs SET state='ready',updated=?,error='' WHERE id=?",(now,jid))
        checkpoint('AI初填完成，待人工审核')
        print(json.dumps({'video':video,'job':jid,'ready':True,'images':len(prepared['images']),'transcript_length':len(transcript),'filled_fields':[k for k,v in fields.items() if v]},ensure_ascii=True),flush=True)
    except Exception as exc:
        cases.fail(jid,str(exc) if isinstance(exc,ValueError) else 'Cached completion failed; inspect local receipt, never replay blindly')
        print(json.dumps({'video':video,'job':jid,'state':'attention','reason':str(exc) if isinstance(exc,ValueError) else type(exc).__name__},ensure_ascii=True),flush=True)
