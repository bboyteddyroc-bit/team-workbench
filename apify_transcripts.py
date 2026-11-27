"""Ingest TikTok subtitle files already returned by the scheduled Apify scrape."""
import html
import json
import re
import time
from urllib.parse import unquote, urlsplit

import httpx


DOWNLOAD_MODE = 'DOWNLOAD_SUBTITLES'
MAX_BYTES = 600_000
MAX_TEXT = 30_000
CAPTION_PATH = re.compile(r'/v2/key-value-stores/[A-Za-z0-9_-]{1,128}/records/[A-Za-z0-9_.-]{1,250}\.vtt\Z')
CUE = re.compile(
    r'^(?P<start>(?:\d{2,}:)?\d{2}:\d{2}\.\d{3})\s+-->\s+'
    r'(?P<end>(?:\d{2,}:)?\d{2}:\d{2}\.\d{3})(?:\s.*)?$')


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS apify_video_transcripts(
        video TEXT PRIMARY KEY, run TEXT NOT NULL, binding TEXT NOT NULL, resource TEXT NOT NULL,
        language TEXT NOT NULL, state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
        updated REAL NOT NULL, transcript TEXT NOT NULL DEFAULT '', cues TEXT NOT NULL DEFAULT '[]')''')
    db.execute('CREATE INDEX IF NOT EXISTS apify_transcripts_pending ON apify_video_transcripts(state,updated)')


def subtitle_resource(url):
    try:
        parsed=urlsplit(url or '')
        if parsed.netloc!='api.apify.com' or parsed.scheme!='https' or parsed.fragment:
            return ''
        path=unquote(parsed.path,errors='strict')
        return path[3:] if CAPTION_PATH.fullmatch(path) else ''
    except (ValueError, UnicodeError, AttributeError, TypeError):
        return ''


def subtitle(item):
    meta=item.get('videoMeta')
    links=meta.get('subtitleLinks') if isinstance(meta,dict) else None
    if not isinstance(links,list):
        return None
    choices=[]
    for link in links:
        if not isinstance(link,dict):
            continue
        source=str(link.get('source') or '').upper()
        if source=='MT' or 'translation' in str(link.get('sourceUnabbreviated') or '').casefold():
            continue
        resource=subtitle_resource(link.get('downloadLink'))
        language=str(link.get('language') or '')
        if resource:
            choices.append((source!='ASR',resource,language if re.fullmatch(r'[A-Za-z0-9-]{1,24}',language) else ''))
    if not choices:
        return None
    _, resource, language=min(choices,key=lambda row:row[0])
    return resource,language


def register(db, video, run, binding, discovered):
    if not discovered:
        return
    resource, language=discovered
    db.execute('''INSERT INTO apify_video_transcripts(video,run,binding,resource,language,state,updated)
        VALUES(?,?,?,?,?,'queued',?) ON CONFLICT(video) DO UPDATE SET
        run=excluded.run,binding=excluded.binding,resource=excluded.resource,language=excluded.language,
        state='queued',updated=excluded.updated
        WHERE apify_video_transcripts.state='attention' AND apify_video_transcripts.attempts<3
          AND apify_video_transcripts.resource<>excluded.resource''',(video,run,binding,resource,language,time.time()))


def parse_caption(raw):
    text=raw.decode('utf-8-sig').replace('\r\n','\n').replace('\r','\n')
    if not text.startswith('WEBVTT'):
        raise ValueError('Apify 字幕格式无效')

    def seconds(stamp):
        return round(sum(float(part)*60**i for i,part in enumerate(reversed(stamp.split(':')))),3)

    rows=[]
    for block in re.split(r'\n[ \t]*\n',text):
        lines=block.splitlines()
        if not lines or lines[0].startswith(('NOTE','STYLE','REGION','WEBVTT')):
            continue
        for index,line in enumerate(lines[:2]):
            match=CUE.fullmatch(line.strip())
            if not match:
                continue
            start,end=seconds(match['start']),seconds(match['end'])
            phrase=html.unescape(re.sub(r'<[^>]*>','',' '.join(lines[index+1:])))
            phrase=' '.join(phrase.split())
            if phrase and 0<=start<end and (not rows or (phrase,start,end)!=(rows[-1]['text'],rows[-1]['start'],rows[-1]['end'])):
                rows.append({'start':start,'end':end,'text':phrase})
            break
    rows.sort(key=lambda row:row['start'])
    transcript=' '.join(row['text'] for row in rows)
    if not transcript or len(transcript)>MAX_TEXT:
        raise ValueError('Apify 字幕为空或超出长度限制')
    return transcript,rows


def download(config, binding, resource):
    if not CAPTION_PATH.fullmatch('/v2'+resource):
        raise ValueError('无效字幕资源')
    pool=getattr(config,'pool',None)
    token=pool.token(binding) if pool and binding else config.secret()
    if not token:
        raise ValueError('任务关联的 Apify 密钥不可用')
    deadline=time.monotonic()+15
    with httpx.Client(timeout=5,follow_redirects=False) as client:
        with client.stream('GET','https://api.apify.com/v2'+resource,
                           headers={'Authorization':'Bearer '+token,'Accept-Encoding':'identity'}) as response:
            if response.status_code==429 and pool:
                pool.cool_down(response.headers.get('Retry-After'))
            if response.status_code!=200 or response.headers.get('Content-Encoding','identity').casefold()!='identity':
                raise ValueError('原任务字幕文件暂不可读')
            result=bytearray()
            for chunk in response.iter_raw(16384):
                if time.monotonic()>deadline or len(result)+len(chunk)>MAX_BYTES:
                    raise ValueError('字幕文件读取超限')
                result.extend(chunk)
            return bytes(result)


def tick(hub, config):
    now=time.time()
    with hub.db() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute("""UPDATE apify_video_transcripts SET state='attention',updated=?
            WHERE state='running' AND updated<?""",(now,now-90))
        row=db.execute("""SELECT video,binding,resource FROM apify_video_transcripts
            WHERE state='queued' ORDER BY updated,video LIMIT 1""").fetchone()
        if not row:
            return
        db.execute("UPDATE apify_video_transcripts SET state='running',attempts=attempts+1,updated=? WHERE video=?",(now,row['video']))
    try:
        transcript,cues=parse_caption(download(config,row['binding'],row['resource']))
    except (ValueError, UnicodeError, httpx.HTTPError):
        with hub.db() as db:
            db.execute("UPDATE apify_video_transcripts SET state='attention',updated=? WHERE video=? AND state='running'",(time.time(),row['video']))
        return
    with hub.db() as db:
        db.execute("""UPDATE apify_video_transcripts SET state='ready',transcript=?,cues=?,resource='',binding='',updated=?
            WHERE video=? AND state='running'""",(transcript,json.dumps(cues,ensure_ascii=False),time.time(),row['video']))
