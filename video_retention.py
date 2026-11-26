"""Expire only generated video files after the retention window."""
import logging
import re
import time

from fastapi import HTTPException, Request


WEEK = 7 * 86400
ID = re.compile(r'[0-9a-f]{24,32}')
LOGGER = logging.getLogger(__name__)


def initialize(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS video_retention_policy(id INTEGER PRIMARY KEY CHECK(id=1),started REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS retained_videos(
        source TEXT NOT NULL,job TEXT NOT NULL,owner TEXT NOT NULL,PRIMARY KEY(source,job)
    );
    CREATE TABLE IF NOT EXISTS expired_videos(
        source TEXT NOT NULL,job TEXT NOT NULL,asset TEXT NOT NULL,expired REAL NOT NULL,
        cleaned INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(source,job)
    );
    """)
    db.execute('CREATE INDEX IF NOT EXISTS expired_videos_job ON expired_videos(job)')
    db.execute("CREATE INDEX IF NOT EXISTS expired_videos_asset ON expired_videos(asset) WHERE asset<>''")
    db.execute('INSERT OR IGNORE INTO video_retention_policy VALUES(1,?)', (time.time(),))


def assert_available(db, data):
    """Recheck under the same write lock used by the expiration transition."""
    import json
    row = db.execute("""SELECT 1 FROM json_tree(?) j JOIN expired_videos e
        ON j.atom=e.job OR (e.asset<>'' AND j.atom=e.asset)
        WHERE j.type='text' LIMIT 1""", (json.dumps(data),)).fetchone()
    if row:
        raise HTTPException(409,'草稿含已过期的生成视频，请移除或重新选择素材')


def protected_ids(db):
    """Include saved versions and live consumers, independent of who owns the project."""
    references = (
        ('compositions','content','1'),
        ('edit_projects','body','1'),
        ('edit_versions','body','1'),
        ('edit_exports','body',"state IN ('queued','rendering')"),
        ('tasks','config',"state IN ('queued','submitting','running','unknown','attention')"),
        ('libtv_jobs','payload',"state IN ('queued','running','importing')"),
        ('ai_edit_jobs','input',"state IN ('queued','running','retry_wait')"),
    )
    ids = set()
    for table,column,condition in references:
        for row in db.execute(f"""SELECT DISTINCT j.atom FROM {table} a,
              json_tree(CASE WHEN json_valid(a.{column}) THEN a.{column} ELSE '{{}}' END) j
              WHERE {condition} AND j.type='text' AND length(j.atom) IN (24,32)
                AND j.key IN ('source_id','relay_task','task_id','asset_id','id','replacement_task_id',
                              'picture_task_id','video_task_id','source_task')"""):
            if ID.fullmatch(row[0]):
                ids.add(row[0])
    return ids


def mark_expired(hub, now=None):
    now = time.time() if now is None else now
    border = now - WEEK
    with hub.db() as db:
        db.execute('BEGIN IMMEDIATE')
        started = db.execute('SELECT started FROM video_retention_policy WHERE id=1').fetchone()[0]
        if border < started:
            return 0
        protected = protected_ids(db)
        candidates = db.execute("""
          SELECT 'tiktok' AS source,t.id,t.owner,'' AS asset,t.updated AS ready
          FROM tasks t WHERE t.state='ready' AND t.updated<=?
          UNION ALL
          SELECT 'libtv',j.id,j.owner,j.asset_id,MAX(j.updated,a.created)
          FROM libtv_jobs j JOIN assets a ON a.id=j.asset_id AND a.owner=j.owner AND a.mime='video/mp4'
          WHERE j.state='ready' AND j.updated<=? AND a.created<=?
          ORDER BY ready,id""", (border,border,border))
        eligible = []
        pins = {(r[0],r[1]) for r in db.execute('SELECT source,job FROM retained_videos')}
        for src,job,owner,asset,_ in candidates:
            if job in protected or (asset and asset in protected) or (src,job) in pins:
                continue
            if not ID.fullmatch(job) or (asset and not ID.fullmatch(asset)):
                continue
            eligible.append((src,job,owner,asset))
            if len(eligible) == 50:
                break
        for src,job,owner,asset in eligible:
            db.execute('INSERT INTO expired_videos(source,job,asset,expired) VALUES(?,?,?,?)', (src,job,asset,now))
            if src == 'tiktok':
                db.execute("UPDATE tasks SET state='expired' WHERE id=? AND owner=?", (job,owner))
            else:
                db.execute("UPDATE libtv_jobs SET state='expired',stage='成片已过期' WHERE id=? AND owner=?", (job,owner))
                for table in ('asset_labels','asset_classification','platform_images'):
                    db.execute(f'DELETE FROM {table} WHERE asset_id=?', (asset,))
                db.execute('DELETE FROM assets WHERE id=? AND owner=?', (asset,owner))
        return len(eligible)


def delete_expired_files(hub):
    with hub.db() as db:
        rows = db.execute('SELECT source,job,asset FROM expired_videos WHERE cleaned=0 ORDER BY expired LIMIT 200').fetchall()
    for src,job,asset in rows:
        if not ID.fullmatch(job) or (src=='libtv' and not ID.fullmatch(asset)):
            continue
        path = hub.media/(job+'.mp4') if src=='tiktok' else hub.assets/asset
        try:
            path.unlink(missing_ok=True)
        except OSError:
            # Open Windows media handles can keep a file busy. Retry next sweep.
            continue
        with hub.db() as db:
            db.execute('UPDATE expired_videos SET cleaned=1 WHERE source=? AND job=?', (src,job))


def loop(hub):
    while not hub.stop.wait(60):
        try:
            pending = mark_expired(hub)
            delete_expired_files(hub)
        except Exception:
            LOGGER.exception('Generated video retention sweep failed')
            pending = 0
        if not pending and hub.stop.wait(240):
            return


def attach(app, hub, user, body):
    with hub.db() as db:
        initialize(db)

    @app.get('/api/video-retention')
    def listing(request:Request):
        owner=user(request)['id']
        with hub.db() as db:
            return {'pinned':[row['source']+':'+row['job'] for row in db.execute(
                'SELECT source,job FROM retained_videos WHERE owner=?', (owner,))]}

    @app.post('/api/video-retention')
    async def toggle(request:Request):
        owner=user(request)['id'];data=await body(request)
        source,job,pin=data.get('source'),data.get('job'),data.get('pin')
        if source not in ('tiktok','libtv') or not isinstance(job,str) or not ID.fullmatch(job) or type(pin) is not bool:
            raise HTTPException(400,'保留设置无效')
        table='tasks' if source=='tiktok' else 'libtv_jobs'
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute(f"SELECT 1 FROM {table} WHERE id=? AND owner=? AND state='ready'", (job,owner)).fetchone():
                raise HTTPException(404,'成片不存在、已过期或无权操作')
            if pin:
                db.execute('INSERT OR IGNORE INTO retained_videos VALUES(?,?,?)', (source,job,owner))
            else:
                db.execute('DELETE FROM retained_videos WHERE source=? AND job=? AND owner=?', (source,job,owner))
        return {'pinned':pin}
