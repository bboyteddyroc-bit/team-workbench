"""Read-only projection for the team script board and traceable script analysis."""
import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit

from fastapi import HTTPException, Request

from video_case_fields import projection
from video_case_presentation import metric_projection, numeric


PHASES = ('opening', 'pain', 'demo', 'proof', 'cta')
COUNTS = ('views', 'likes', 'collects', 'comments', 'shares')
TOKENS = re.compile(r"[a-z0-9]+(?:'[a-z]+)?|[\u3400-\u9fff]")


def tokens(text):
    return TOKENS.findall(unicodedata.normalize('NFKC', text).casefold().replace('’', "'"))


def json_value(raw, default):
    try:
        value = json.loads(raw or '')
    except (ValueError, TypeError):
        return default
    return value if isinstance(value, type(default)) else default


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS script_board_evidence (
        source TEXT NOT NULL, item TEXT NOT NULL, transcript_hash TEXT NOT NULL,
        timing TEXT NOT NULL DEFAULT '[]', components TEXT NOT NULL DEFAULT '[]',
        PRIMARY KEY(source,item,transcript_hash))''')


def save_evidence(db, source, item, transcript, *, timing=None, components=None):
    column, value = ('timing', timing) if timing is not None else ('components', components)
    db.execute(f'''INSERT INTO script_board_evidence(source,item,transcript_hash,{column})
        VALUES(?,?,?,?) ON CONFLICT(source,item,transcript_hash) DO UPDATE SET {column}=excluded.{column}''',
        (source, item, digest(transcript), json.dumps(value or [], ensure_ascii=False)))


def timed_transcript(segments, limit=30000):
    rows = []
    size = 0
    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        remaining = limit - size - bool(rows)
        if remaining <= 0:
            break
        rows.append({'text': text[:remaining], 'start':round(segment.start, 2), 'end':round(segment.end, 2)})
        size += len(rows[-1]['text']) + (len(rows) > 1)
        if len(text) > remaining:
            break
    return ' '.join(row['text'] for row in rows), rows


def vetted_components(raw, transcript):
    """Only verbatim evidence may enter the script groups as a quoted AI component."""
    if not isinstance(raw, list):
        return []
    original = tokens(transcript)
    original_text = ' ' + ' '.join(original) + ' '
    found = {}
    for row in raw[:15]:
        if not isinstance(row, dict):
            continue
        phase, text = row.get('phase'), row.get('text')
        if phase not in PHASES or not isinstance(text, str) or not 1 <= len(text.strip()) <= 500:
            continue
        phrase = ' '.join(tokens(text))
        if phrase and (' '+phrase+' ') in original_text:
            found.setdefault(phase, {'phase':phase, 'text':text.strip(), 'source':'口播原句'})
    return sorted(found.values(), key=lambda row: original_text.find(' '+' '.join(tokens(row['text']))+' '))


def locate(component, timing):
    expected = tokens(component['text'])
    flattened, owners = [], []
    for index, row in enumerate(timing):
        words = tokens(row['text'])
        flattened.extend(words)
        owners.extend([index]*len(words))
    matches = [index for index, word in enumerate(flattened)
               if expected and word == expected[0] and flattened[index:index+len(expected)] == expected]
    if len(matches) != 1:
        return component
    start = timing[owners[matches[0]]]['start']
    end = timing[owners[matches[0]+len(expected)-1]]['end']
    return {**component, 'start':start, 'end':end, 'timing_source':'语音识别分段'}


def public_link(value):
    try:
        url = urlsplit(value or '')
        if (url.scheme == 'https' and not url.username and not url.password and url.port is None and
                url.hostname in ('tiktok.com','www.tiktok.com','vm.tiktok.com','vt.tiktok.com')):
            return url.geturl()
    except ValueError:
        pass
    return ''


def key_for(platform, video, fallback):
    return platform.casefold() + ':' + video if video else fallback


def library_rows(db, directory):
    from apify_cover_cache import existing

    rows = {}
    saved = {r['video']:dict(r) for r in db.execute('SELECT * FROM script_library WHERE video IS NOT NULL')}
    for r in db.execute('''SELECT * FROM (
        SELECT s.*,a.handle, row_number() OVER(PARTITION BY s.video ORDER BY s.collected DESC,s.rowid DESC) AS rank
        FROM apify_snapshots s JOIN apify_accounts a ON a.id=s.account JOIN users u ON u.id=a.owner
        WHERE a.deleted_at IS NULL AND u.enabled=1) WHERE rank=1'''):
        if not r['video'].isascii() or not r['video'].isdigit():
            continue
        ident = 'tiktok:' + r['video']
        rows[ident] = dict(id=ident, account=r['handle'], description=r['title'], published=r['published'],
            url=public_link(f"https://www.tiktok.com/@{quote(r['handle'] or '')}/video/{r['video']}"),
            metrics={key:numeric(r[key]) for key in COUNTS}, metric_source='Apify 累计快照',
            gm=None, currency=None, cover=(f"/api/intelligence/apify/accounts/{quote(r['account'])}/cover/{r['video']}"
                if r['cover'] or existing(directory/'apify-covers',r['video']) else None))

    cases = {}
    for r in db.execute('''SELECT c.* FROM video_cases c WHERE c.removed_at IS NULL AND EXISTS (
          SELECT 1 FROM video_case_members m JOIN users u ON u.id=m.owner AND u.enabled=1 WHERE m.case_id=c.id)
          ORDER BY c.updated,c.id'''):
        row = dict(r)
        for field in ('human','source','ai'):
            row[field] = json_value(row[field], {})
        ident = key_for(row['platform'], row['video'], 'case:'+row['id'])
        cases[ident] = row
        base = rows.setdefault(ident, dict(id=ident, metrics={}, gm=None, currency=None))
        fields = projection(row)
        kd = row['source'].get('kalodata') or {}
        base.update(case_id=row['id'], url=public_link(row['url']) or base.get('url',''),
            account=row['handle'] or base.get('account',''), description=fields['title']['value'] or base.get('description'),
            published=base.get('published') or row['source'].get('published') or fields['published_at']['value'],
            cover=('/api/intelligence/cases/'+row['id']+'/cover'
                if row['source'].get('cover') or (directory/'case-covers'/(row['id']+'.img')).is_file() else base.get('cover')))
        if not any(value is not None for value in base['metrics'].values()):
            source = row['source']
            if numeric(source.get('views')) is not None:
                base.update(metrics={key:numeric(source.get(key)) for key in COUNTS},metric_source='公开视频累计快照')
            elif numeric(kd.get('period_views')) is not None:
                base.update(metrics={key:numeric(kd.get('period_views' if key=='views' else key)) for key in COUNTS},metric_source='Kalodata 区间快照')
        gm = next(m for m in metric_projection(row) if m['key']=='gmv')
        base.update(gm=gm['value'], currency=gm['currency'], gm_scope=gm['scope'])

    standalone = [dict(r) for r in db.execute('SELECT * FROM script_library WHERE video IS NULL AND removed_at IS NULL')]
    case_keys = {c['library_id']:key for key,c in cases.items() if c['library_id']}
    for r in [*saved.values(),*standalone]:
        if r['removed_at'] is not None:
            continue
        ident = case_keys.get(r['id']) or key_for('tiktok',r['video'],'archive:'+r['id'])
        base = rows.setdefault(ident, dict(id=ident, metrics={}, gm=None, currency=None))
        if not any(value is not None for value in base['metrics'].values()):
            snap = json_value(r['snapshot'],{})
            base.update(metrics={key:numeric(snap.get(key)) for key in COUNTS},metric_source='文案档案快照')
        base.update(archive_id=r['id'], account=base.get('account') or r['account_handle'], description=base.get('description') or r['description'],
            published=base.get('published') or r['published'], url=base.get('url') or public_link(r['video_url']))

    for r in db.execute('''SELECT * FROM (
        SELECT j.*,row_number() OVER(PARTITION BY j.video ORDER BY j.updated DESC,j.rowid DESC) AS rank
        FROM video_enrichment_jobs j JOIN apify_accounts a ON a.id=j.account JOIN users u ON u.id=a.owner
        WHERE j.state='ready' AND j.result IS NOT NULL AND a.deleted_at IS NULL AND u.enabled=1) WHERE rank=1'''):
        base = rows.get('tiktok:'+r['video'])
        if base is None or base.get('gm') is not None:
            continue
        result = json_value(r['result'],{})
        if numeric(result.get('gmv')) is not None:
            base.update(gm=numeric(result['gmv']),currency=result.get('currency'),
                        gm_scope=f"第三方区间估算 · {r['period_start']} — {r['period_end']}")

    has_evidence = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='script_board_evidence'").fetchone()
    evidence = {(r['source'],r['item'],r['transcript_hash']):r for r in db.execute('SELECT * FROM script_board_evidence')} if has_evidence else {}
    reviewed = {}
    for r in db.execute('SELECT case_id,field,claim,start,end FROM video_case_clip_reviews'):
        reviewed.setdefault(r['case_id'], {})[r['field']] = dict(r)
    has_apify_subtitles = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='apify_video_transcripts'").fetchone()
    subtitles = {('tiktok:'+r['video']):r for r in db.execute("""SELECT video,transcript,cues,language
        FROM apify_video_transcripts WHERE state='ready'""")} if has_apify_subtitles else {}
    archives = {r['id']:r for r in [*saved.values(),*standalone] if r['removed_at'] is None}
    for ident, base in rows.items():
        case = cases.get(ident,{})
        archive = archives.get(base.get('archive_id'),{})
        fields = projection(case)
        case_text = fields['transcript']['value'] or ''
        archive_text = archive.get('transcript_original') or ''
        subtitle = subtitles.get(ident)
        subtitle_text = subtitle['transcript'] if subtitle else ''
        transcript = case_text or archive_text or subtitle_text
        subtitle_source = 'TikTok 字幕 · Apify' + (' · '+subtitle['language'] if subtitle and subtitle['language'] else '')
        base.update(category=archive.get('product_category') or fields['category']['value'],
            transcript_source=fields['transcript']['source'] if case_text else archive.get('transcript_source') if archive_text else subtitle_source if subtitle_text else '',
            transcript=transcript, tags=json_value(archive.get('tags'), []))
        details = [evidence.get((source, item, digest(transcript))) for source,item in
                   (('case',case.get('id')),('archive',archive.get('id')))] if transcript else []
        timing = next((json_value(d['timing'],[]) for d in details if d and d['timing'] != '[]'),[])
        subtitle_timing = not timing and bool(subtitle_text) and transcript == subtitle_text
        if subtitle_timing:
            timing = json_value(subtitle['cues'],[])
        components = next((json_value(d['components'],[]) for d in details if d and d['components'] != '[]'),[])
        if transcript:
            existing = {'opening':fields['hook_example']['value'] or fields['opening']['value'] or archive.get('opening'),
                        'pain':archive.get('pain_point'), 'demo':fields['replication_actions']['value'],
                        'cta':fields['ending']['value'] or archive.get('ending')}
            existing = vetted_components([{'phase':phase,'text':text} for phase,text in existing.items()],transcript)
            used = {c['phase'] for c in components}
            components = vetted_components([*components, *(c for c in existing if c['phase'] not in used)],transcript)
        if not components and transcript:
            first = timing[0]['text'] if subtitle_timing and timing else re.split(r'(?<=[.!?。！？])\s+|(?<=[。！？])',transcript,maxsplit=1)[0].strip()
            if len(first) <= 250:
                components = [{'phase':'opening','text':first,'source':'首条字幕' if subtitle_timing else '逐字稿首句'}]
        for component in components:
            if component['phase'] not in ('opening','demo','cta'):
                continue
            field = {'opening':'opening','demo':'replication_actions','cta':'ending'}[component['phase']]
            review = reviewed.get(case.get('id'),{}).get(field)
            if review and review['claim']==fields[field]['value'] and tokens(review['claim'])==tokens(component['text']):
                component.update(start=review['start'],end=review['end'],timing_source='人工确认区间')
        located = [c if 'start' in c else locate(c,timing) for c in components]
        if subtitle_timing:
            for component in located:
                if component.get('timing_source') == '语音识别分段':
                    component['timing_source'] = 'TikTok 字幕时间'
        base['components'] = located
        normalized_transcript = ' '.join(tokens(transcript))
        base['exact_script'] = digest(normalized_transcript) if normalized_transcript else ''
        if case and (directory/'case-analysis'/case['id']/'source.mp4').is_file():
            base['preview'] = '/api/intelligence/cases/'+case['id']+'/preview'
    return list(rows.values())


def attach(app, hub, user):
    @app.get('/api/intelligence/script-board')
    def board(request: Request, offset: int = 0, limit: int = 400, transcript: str = ''):
        user(request)
        if offset < 0 or not 1 <= limit <= 500 or len(transcript) > 100:
            raise HTTPException(400,'筛选参数无效')
        with hub.db() as db:
            rows = library_rows(db,hub.directory)
        if transcript:
            row = next((r for r in rows if r['id']==transcript),None)
            if row is None:
                raise HTTPException(404,'视频已不可用')
            return {'text':row['transcript'], 'source':row['transcript_source']}
        rows.sort(key=lambda row:row['id'])
        for row in rows:
            row['has_transcript'] = bool(row.pop('transcript'))
        today = datetime.now(timezone.utc).date().isoformat()
        return {'items':rows[offset:offset+limit], 'total':len(rows), 'date':today}
