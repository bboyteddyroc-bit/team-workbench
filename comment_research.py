"""Versioned comment signals for evidence reports. The model labels; the program counts."""
import json
import unicodedata

VERSION=1
SIGNALS={
    'looking':'明确在寻找商品或解决办法',
    'bought':'自称已经购买或下单（未经订单验证）',
    'used':'自述实际使用体验',
    'people':'明说自己或使用者属于哪类人',
    'scene':'明说遇到的问题场景、条件或时点',
    'pain':'明确吐槽或不满意点',
    'barrier':'可识别的购买阻力（适配、价格、运费、耐用性等）',
    'question':'尚在询问的具体信息（不要判断视频有没有讲）',
    'buy_intent':'认真了解如何购买、价格、规格、运送等（不是成交）',
    'reaction':'只有泛娱乐反应或普通感叹，不带评估或购买信号',
}


def pack(value,rows):
    """Called once on a fresh inference. Empty evidence is valid, missing schema is not."""
    if not isinstance(value,dict) or set(value)!=set(SIGNALS):raise ValueError('comment research keys')
    out={};used={}
    for key,groups in value.items():
        if not isinstance(groups,list) or len(groups)>5:raise ValueError('comment research groups')
        seen=set();out[key]=[];used[key]=set()
        for entry in groups:
            if not isinstance(entry,dict) or set(entry)!={'label','ids'}:raise ValueError('comment research group fields')
            label=entry['label'];ids=entry['ids']
            if not isinstance(label,str) or not 1<=len(label.strip())<=72 or not isinstance(ids,list) or not ids or len(ids)>100:
                raise ValueError('comment research label/ids')
            if any(type(i) is not int or not 1<=i<=len(rows) for i in ids):raise ValueError('comment research index')
            name=' '.join(unicodedata.normalize('NFKC',label).casefold().split())
            if name in seen:raise ValueError('duplicate group')
            seen.add(name);chosen=set(ids);used[key].update(chosen)
            out[key].append({'label':label.strip(),'ids':[rows[i-1]['cid'] for i in sorted(chosen)]})
    if used['reaction'] & (used['buy_intent']|used['looking']|used['bought']|used['used']|used['question']|used['barrier']|used['pain']):
        raise ValueError('pure reaction must not contain substantive evidence')
    return {'v':VERSION,'sample_ids':[r['cid'] for r in rows],'signals':out}


def read_pack(raw,rows):
    """Do not reuse an annotation on a changed set or with broken references."""
    try:
        obj=json.loads(raw) if isinstance(raw,str) else raw
        ranks={r['cid']:i for i,r in enumerate(rows,1)}
        ids=obj['sample_ids'];sig=obj['signals']
        if obj['v']!=VERSION or len(ids)!=len(ranks) or set(ids)!=set(ranks) or not ranks:return None
        again={key:[{'label':e['label'],'ids':[ranks[c] for c in e['ids']]} for e in groups] for key,groups in sig.items()}
        checked=pack(again,rows)
        texts=obj.get('translations')
        if isinstance(texts,dict):
            checked['translations']={c:t for c,t in texts.items() if c in ranks and isinstance(t,str) and 0<len(t)<=1000}
        return checked
    except (KeyError,TypeError,ValueError,AttributeError,IndexError):
        return None


def bucket(hits,total):
    return {'hits':hits,'total':total,'pct':round(hits*100/total,1) if total else None}


def row_counts(ids,rows):
    mains={r['cid'] for r in rows if not r['parent']};replies={r['cid'] for r in rows if r['parent']}
    return {'comments':bucket(len(ids&mains),len(mains)),'replies':bucket(len(ids&replies),len(replies))}
