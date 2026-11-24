"""Server-owned requirement ledger. Model outputs cannot grant execution authority."""
import copy,time
from ai_editing import digest

POLICY='requirement-origin-v2'
FIELDS=('goal','must_keep','forbidden','acceptance')

def ledger(contract,messages,previous=None):
    rows=[]
    for field in FIELDS:
        values=[contract.get('goal','')] if field=='goal' else contract.get(field,[])
        for i,value in enumerate(values):
            if not value:continue
            rid='goal' if field=='goal' else f'{field}:{i}'
            quotes=[{'turn':j,'quote':value,'turn_hash':digest(m['text'])} for j,m in enumerate(messages) if m.get('role')=='user' and value in m.get('text','')]
            old=next((r for r in (previous or {}).get('requirements',[]) if r.get('field')==field and r.get('text')==value),None)
            rows.append({'id':rid,'field':field,'text':value,'origin':'user_verbatim' if quotes else 'assistant_proposal','user_evidence':quotes[-3:],'first_seen':old.get('first_seen') if old else digest([field,value,messages]),'authority':'proposed','review_role':'objective' if field in ('goal','acceptance') else 'constraint'})
    for field in ('scope','captions','titles','ranges','creative','unchanged'):
        value=contract.get(field)
        if value is None:continue
        rows.append({'id':field,'field':field,'text':str(value),'origin':'assistant_proposal','user_evidence':[],'first_seen':digest([field,value]),'authority':'proposed','review_role':'constraint'})
    return {'policy':POLICY,'contract_hash':digest(contract),'requirements':rows}

def seal(body,confirmation_hash,request_key):
    contract=body.get('contract') or {}
    # Rebuild from server-stored contract/history, never accept client/model provenance.
    value=ledger(contract,body.get('messages',[]),body.get('requirement_ledger'))
    for row in value['requirements']:
        row['authority']='user_adopted_confirmation'
    value.update(confirmed_at=time.time(),confirmation_hash=confirmation_hash,request_key=request_key)
    value['seal']=digest({k:v for k,v in value.items() if k!='seal'})
    return value

def confirmed(snap):
    value=snap.get('requirement_authority') or {}
    return value.get('policy')==POLICY and value.get('contract_hash')==digest(snap.get('contract') or {}) and value.get('seal')==digest({k:v for k,v in value.items() if k!='seal'})

def review_context(snap):
    """Only authoritative requirements and primary data; never prior model verdicts."""
    contract=snap.get('contract') or {}
    return {'contract':contract,'requirement_authority':snap.get('requirement_authority'),'authority_valid':confirmed(snap),'background':{k:snap.get('brief',{}).get(k,'') for k in ('product','audience','reason','facts')},'primary_sources':snap.get('analysis',[])}

def observation_context(inspection):
    """Planner may use observations; no summary/limitations may become user rules."""
    if not inspection:return None
    return {'untrusted_observations':[{'stage':stage,'observations':copy.deepcopy((inspection.get(stage) or {}).get('observations',[]))} for stage in ('initial','detail')],'authority':'model_observation_not_user_requirement'}
