"""Per-record review of evidence tags. Stable tag keys survive automated re-analysis."""
import json
import time
import unicodedata

from fastapi import HTTPException
from product_research_methods import specific_actions
from product_research_tags import resolved_case_category, uncertain
from video_case_presentation import TAG_CATEGORIES, tag_projection


def initialize(db):
    db.execute("""CREATE TABLE IF NOT EXISTS research_tag_reviews(
        entity TEXT NOT NULL, ref TEXT NOT NULL, tag_key TEXT NOT NULL,
        decision TEXT NOT NULL CHECK(decision IN ('confirmed','rejected')),
        reviewer TEXT NOT NULL, reviewed REAL NOT NULL,
        PRIMARY KEY(entity,ref,tag_key))""")


def tag_key(kind,label):
    parts = [' '.join(unicodedata.normalize('NFKC', x).casefold().split()) for x in (kind,label)]
    return json.dumps(parts, ensure_ascii=False, separators=(',', ':'))


def review_index(db,entity):
    result = {}
    for ref,key,decision in db.execute('SELECT ref,tag_key,decision FROM research_tag_reviews WHERE entity=?',(entity,)):
        result.setdefault(ref,{})[key] = decision
    return result


def review_tags(db,entity,ref,tags):
    decisions = dict(db.execute('SELECT tag_key,decision FROM research_tag_reviews WHERE entity=? AND ref=?',(entity,ref)))
    result = []
    seen = set()
    for tag in tags:
        key = tag_key(tag['kind'],tag['label'])
        if key in seen:
            continue
        seen.add(key)
        result.append({**tag,'key':key,'decision':decisions.get(key,'pending')})
    return result


def video_tags(human,ai,listing=''):
    projection = tag_projection({'human':human,'ai':ai})
    canonical,origin,_ = resolved_case_category(human,ai,listing)
    tags = [{'kind':'细品类','label':label,'source':f'{origin} · {basis}'} for label,basis in canonical.items()]
    fields = ai.get('fields') or {}
    notes = ai.get('evidence') or {}
    for key,field_label in (('opening','开场'),('content_type','内容玩法'),('replication_actions','复用动作')):
        manual = key in human
        value = human.get(key) if manual else fields.get(key)
        if not isinstance(value,str) or not value.strip():
            continue
        note = '' if manual else notes.get(key)
        provenance = ('人工修订' if manual else 'AI 视频分析')+' · '+field_label+' · '+value
        if isinstance(note,str) and note:
            provenance += ' · '+note
        for method in specific_actions(value):
            tags.append({'kind':'内容玩法','label':method,'source':provenance})
    for group in TAG_CATEGORIES:
        for label in projection['groups'].get(group['id'],[]):
            if isinstance(label,str) and label.strip() and not uncertain(label):
                tags.append({'kind':group['label'],'label':label,
                             'source':f"{projection['origin']} · {group['label']} · {label}"})
    return tags


def set_review(db,entity,ref,tags,kind,label,decision,user_id):
    key = tag_key(kind,label)
    if not any(tag_key(t['kind'],t['label']) == key for t in tags):
        raise HTTPException(409,'标签来源已更新，请刷新后核对')
    if decision == 'pending':
        db.execute('DELETE FROM research_tag_reviews WHERE entity=? AND ref=? AND tag_key=?',(entity,ref,key))
    else:
        db.execute("""INSERT INTO research_tag_reviews VALUES(?,?,?,?,?,?)
          ON CONFLICT(entity,ref,tag_key) DO UPDATE SET decision=excluded.decision,
          reviewer=excluded.reviewer,reviewed=excluded.reviewed""",
                   (entity,ref,key,decision,user_id,time.time()))
