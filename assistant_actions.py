"""Confirmed assistant operations, scoped to the signed-in member."""
import re
import secrets
import time

from fastapi import HTTPException, Request


CLASSIFY = 'classify_materials'
IN_FLIGHT = ('queued', 'running', 'retry_wait')
TTL = 15 * 60


def classify_intent(prompt):
    if len(prompt)>350 or not re.search(r'素材|素材库|素材管理|图片',prompt):
        return None
    if re.match(r'^\s*(?:[「“"「]|如何|怎么|能否|能不能|为什么|可不可以|是否)',prompt):
        return None
    if re.search(r'不要|别[给替帮]我|先不|如何|怎么|为什么|示例|[?？]',prompt):
        return None
    if not re.search(r'重新(?:识别|分类|归类)|(?:批量|全部|所有).{0,18}(?:分类|归类|识别)',prompt):
        return None
    full=bool(re.search(r'全部|所有|全库|全量',prompt))
    return CLASSIFY,full


def initialize(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS ai_actions(
      id TEXT PRIMARY KEY,owner TEXT NOT NULL,thread TEXT NOT NULL,kind TEXT NOT NULL,
      state TEXT NOT NULL,created REAL NOT NULL,finished REAL,eligible INTEGER NOT NULL,
      manual INTEGER NOT NULL,in_flight INTEGER NOT NULL,
      all_images INTEGER NOT NULL,queued INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS ai_actions_conversation ON ai_actions(owner,thread);
    CREATE TABLE IF NOT EXISTS ai_action_assets(
      action TEXT NOT NULL,asset TEXT NOT NULL,version REAL NOT NULL,queued INTEGER NOT NULL DEFAULT 0,outcome TEXT,
      PRIMARY KEY(action,asset)
    );
    CREATE INDEX IF NOT EXISTS ai_action_progress ON ai_action_assets(asset) WHERE queued=1 AND outcome IS NULL;
    CREATE TRIGGER IF NOT EXISTS ai_action_classification_finish AFTER UPDATE OF status ON asset_classification
    WHEN NEW.status IN ('classified','failed','manual')
    BEGIN
      UPDATE ai_action_assets SET outcome=NEW.status WHERE asset=NEW.asset_id AND queued=1 AND outcome IS NULL;
    END;
    CREATE TRIGGER IF NOT EXISTS ai_action_classification_delete AFTER DELETE ON asset_classification
    BEGIN
      UPDATE ai_action_assets SET outcome='missing' WHERE asset=OLD.asset_id AND queued=1 AND outcome IS NULL;
    END;
    """)


def candidates(db,owner,full):
    rows=db.execute("""SELECT a.id,c.status,c.source,c.updated FROM assets a
        JOIN asset_classification c ON c.asset_id=a.id
        WHERE a.owner=? AND a.mime LIKE 'image/%'
        ORDER BY a.created DESC,a.id""",(owner,)).fetchall()
    manual=sum(row['source']=='manual' for row in rows)
    already=sum(row['status'] in IN_FLIGHT for row in rows)
    eligible=[row for row in rows if row['source']!='manual' and row['status'] not in IN_FLIGHT
              and (full or row['status'] in ('waiting_model','failed'))]
    return eligible,manual,already


def action_view(db,owner,thread,ident):
    row=db.execute('SELECT * FROM ai_actions WHERE id=? AND owner=? AND thread=?',(ident,owner,thread)).fetchone()
    if not row:
        return None
    state=row['state']
    if state=='proposed' and row['created']+TTL<=time.time():
        state='expired'
    result={k:row[k] for k in ('id','kind','eligible','manual','in_flight','all_images','queued')}
    result['state']=state
    if state=='queued':
        counts={r[0]:r[1] for r in db.execute("""SELECT coalesce(p.outcome,c.status,'missing'),count(*)
            FROM ai_action_assets p LEFT JOIN assets a ON a.id=p.asset AND a.owner=?
            LEFT JOIN asset_classification c ON c.asset_id=a.id WHERE p.action=? AND p.queued=1 GROUP BY coalesce(p.outcome,c.status,'missing')""",
            (owner,ident))}
        result.update(classified=counts.get('classified',0),failed=counts.get('failed',0),
                      active=sum(counts.get(s,0) for s in IN_FLIGHT),
                      changed=counts.get('manual',0)+counts.get('missing',0))
    return result


def propose(hub,owner,thread,key,prompt,command):
    kind,full=command
    now=time.time()
    with hub.db() as db:
        db.execute('BEGIN IMMEDIATE')
        if not db.execute('SELECT 1 FROM ai_threads WHERE id=? AND owner=?',(thread,owner)).fetchone():
            raise HTTPException(404,'对话不存在')
        old=db.execute('SELECT id,prompt,answer,thread FROM ai_turns WHERE owner=? AND request_key=?',(owner,key)).fetchone()
        if old:
            existing=action_view(db,owner,thread,old['id'])
            if old['thread']!=thread or old['prompt']!=prompt or not existing:
                raise HTTPException(409,'请求标识冲突')
            return {'id':old['id'],'status':'complete','answer':old['answer'],'action':existing}
        rows,manual,already=candidates(db,owner,full)
        ident=secrets.token_hex(16)
        state='proposed' if rows else 'empty'
        scope='当前账号的图片素材' if full else '当前账号中待识别或识别失败的图片'
        answer=f'{scope}有 {len(rows)} 张可以重新识别。已手动分类的 {manual} 张会保留。已在识别队列的 {already} 张不会重复提交。'
        if rows:
            answer+=' 确认后，符合条件的图片会加入识别队列，并使用已配置的 AI 额度。'
        else:
            answer+=' 本次没有可提交的图片。'
        db.execute('INSERT INTO ai_turns(id,owner,thread,request_key,prompt,answer,status,created) VALUES(?,?,?,?,?,?,?,?)',
                   (ident,owner,thread,key,prompt,answer,'complete',now))
        db.execute("""INSERT INTO ai_actions(id,owner,thread,kind,state,created,eligible,manual,in_flight,all_images)
            VALUES(?,?,?,?,?,?,?,?,?,?)""",(ident,owner,thread,kind,state,now,len(rows),manual,already,int(full)))
        db.executemany('INSERT INTO ai_action_assets(action,asset,version) VALUES(?,?,?)',
                       ((ident,row['id'],row['updated']) for row in rows))
        db.execute('UPDATE ai_threads SET title=CASE WHEN title=? THEN ? ELSE title END,updated=? WHERE owner=? AND id=?',
                   ('新对话',prompt[:40],now,owner,thread))
        return {'id':ident,'status':'complete','answer':answer,'action':action_view(db,owner,thread,ident)}


def drop_thread(db,owner,thread):
    db.execute('DELETE FROM ai_action_assets WHERE action IN (SELECT id FROM ai_actions WHERE owner=? AND thread=?)',(owner,thread))
    db.execute('DELETE FROM ai_actions WHERE owner=? AND thread=?',(owner,thread))


def attach(app,hub,user,body):
    with hub.db() as db:
        initialize(db)

    @app.get('/api/assistant/threads/{thread}/actions/{ident}')
    def read_action(thread:str,ident:str,request:Request):
        owner=user(request)['id']
        with hub.db() as db:
            action=action_view(db,owner,thread,ident)
            if action is None:
                raise HTTPException(404,'操作不存在')
            return action

    @app.post('/api/assistant/threads/{thread}/actions/{ident}')
    async def decide(thread:str,ident:str,request:Request):
        owner=user(request)['id']
        data=await body(request)
        decision=data.get('decision')
        if decision not in ('confirm','cancel'):
            raise HTTPException(400,'操作无效')
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            action=action_view(db,owner,thread,ident)
            if action is None:
                raise HTTPException(404,'操作不存在')
            if action['state']!='proposed':
                return action
            now=time.time()
            if decision=='cancel':
                db.execute("UPDATE ai_actions SET state='cancelled',finished=? WHERE id=?",(now,ident))
            elif action['kind']==CLASSIFY:
                if not db.execute('SELECT 1 FROM a6_settings WHERE id=1 AND length(secret)>0').fetchone():
                    raise HTTPException(409,'请先配置图片识别模型，未加入队列')
                total=0
                for target in db.execute('SELECT asset,version FROM ai_action_assets WHERE action=?',(ident,)).fetchall():
                    changed=db.execute("""UPDATE asset_classification SET status='queued',source='pending',error='',updated=?
                        WHERE asset_id=? AND updated=? AND source<>'manual' AND status NOT IN ('queued','running','retry_wait')
                        AND EXISTS (SELECT 1 FROM assets WHERE id=asset_classification.asset_id AND owner=? AND mime LIKE 'image/%')""",
                        (now,target['asset'],target['version'],owner)).rowcount
                    if changed:
                        db.execute('UPDATE ai_action_assets SET queued=1 WHERE action=? AND asset=?',(ident,target['asset']))
                        total+=1
                db.execute("UPDATE ai_actions SET state='queued',queued=?,finished=? WHERE id=?",(total,now,ident))
                hub.log(db,owner,'assistant_material_classification_queued',str(total))
            else:
                raise HTTPException(409,'该操作当前不可用')
            return action_view(db,owner,thread,ident)
