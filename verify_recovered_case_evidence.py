"""Read-only verification of recovered case media + draft. Never requests any provider."""
from pathlib import Path
import json,sqlite3,subprocess
root=Path(__file__).resolve().parent;cid='2d9151c8a5844d73905644031f330ee7'
with sqlite3.connect('file:'+(root/'state/hub.sqlite3').as_posix()+'?mode=ro',uri=True) as db:
    db.row_factory=sqlite3.Row;r=db.execute('SELECT human,ai,transcript FROM video_cases WHERE id=?',(cid,)).fetchone()
    ai=json.loads(r['ai']);fields=ai.get('fields',{})
    print(json.dumps({'human':json.loads(r['human']),'fields':fields,'basis':ai.get('basis'),'uncertainties':ai.get('uncertainties'),'transcript_chars':len(r['transcript'] or '')},ensure_ascii=False,indent=2))
    assert json.loads(r['human'])=={}
    assert ai.get('generated_at')
    assert not fields.get('merchant_visible')
    if not r['transcript']:assert not fields.get('hook_example') and not fields.get('transcript_en') and not fields.get('transcript_zh')
media=root/'state/case-analysis'/cid/'source.mp4';ffprobe=root/'tools/ffmpeg-7.1.1/ffmpeg-7.1.1-essentials_build/bin/ffprobe.exe'
info=json.loads(subprocess.check_output([str(ffprobe),'-v','error','-protocol_whitelist','file,pipe','-f','mov','-show_format','-show_streams','-of','json',str(media)],timeout=30))
assert 0<float(info['format']['duration'])<=1200
print(json.dumps({'verified_media':True,'bytes':media.stat().st_size,'duration':info['format']['duration'],'streams':[s['codec_type'] for s in info['streams']],'frame_files':[str(media.parent/f'frame-{i}.jpg') for i in (0,4,8)]},ensure_ascii=False,indent=2))
