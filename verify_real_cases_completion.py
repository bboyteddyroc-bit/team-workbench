"""Read-only verification: real downloaded videos and persisted AI drafts, no external calls."""
from pathlib import Path
import json,sqlite3,subprocess
root=Path(__file__).resolve().parent
probe=root/'tools/ffmpeg-7.1.1/ffmpeg-7.1.1-essentials_build/bin/ffprobe.exe'
result=[]
with sqlite3.connect('file:'+(root/'state/hub.sqlite3').as_posix()+'?mode=ro',uri=True) as db:
    db.row_factory=sqlite3.Row
    for video in ('7704642505480129822','7708328890967608590'):
        row=db.execute('SELECT * FROM video_cases WHERE video=?',(video,)).fetchone();ai=json.loads(row['ai']);human=json.loads(row['human']);base=root/'state/case-analysis'/row['id'];media=base/'source.mp4'
        assert media.is_file() and media.stat().st_size>0
        info=json.loads(subprocess.check_output([str(probe),'-v','error','-show_format','-show_streams','-of','json',str(media)],timeout=20))
        assert len(list(base.glob('frame-*.jpg')))==9
        assert ai.get('generated_at') and ai['fields'].get('summary') and ai['fields'].get('replication_actions')
        assert (root/'state/case-covers'/(row['id']+'.img')).read_bytes().startswith(b'\xff\xd8\xff')
        latest=db.execute("SELECT id,state,error FROM video_case_jobs WHERE case_id=? AND kind='analysis' ORDER BY created DESC LIMIT 1",(row['id'],)).fetchone();assert latest['state']=='ready'
        result.append({'video':video,'case_id':row['id'],'duration_seconds':float(info['format']['duration']),'bytes':media.stat().st_size,'frame_count':9,'has_audio_stream':any(s['codec_type']=='audio' for s in info['streams']),'transcript_chars':len(row['transcript']),'nonempty_ai_fields':[k for k,v in ai['fields'].items() if v],'human_preserved':not bool(human),'latest_job':dict(latest),'status':'待人工审核','kalodata_metrics_present':bool(json.loads(row['source']).get('kalodata'))})
(root/'verification/cases-real-completion-verified.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=True,indent=2),flush=True)
