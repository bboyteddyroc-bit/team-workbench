"""Gate model review failures on explicit constraints plus grounded direct evidence.
Model reasoning remains fallible. This gate never turns an uncertainty into a pass.
"""
from ai_editing import text,finite

VERSION='requirement-origin-v2'

from ai_edit_policy_context import CONTEXT_RULES


def checklist(contract):
    """Goal remains visible as context; only enumerated confirmed constraints may block."""
    rows=[]
    if contract.get('goal'):rows.append({'id':'goal','requirement':contract['goal'],'hard':False,'origin':'goal'})
    for field in ('must_keep','forbidden','acceptance'):
        for i,value in enumerate(contract.get(field,[])):
            rows.append({'id':f'{field}:{i}','requirement':value,'hard':field!='acceptance','origin':field})
    return rows


def evidence_gate(value,raw,contract,snap):
    """Free-form blocking_issues is advisory only; fail needs matched hard rule + evidence."""
    rules={r['id']:r for r in checklist(contract)}
    sources={s['id']:s['duration'] for s in snap.get('source_info',[])}
    from ai_edit_provenance import confirmed
    authority_valid=confirmed(snap)
    advisories=list(value.get('blocking_issues',[]));blocks=[];quality=[]
    raw_blocks=list(value.get('blocking_issues',[]))
    raw_checks=raw.get('checks',[])
    for check,incoming in zip(value['checks'],raw_checks):
        rid=incoming.get('requirement_id');rule=rules.get(rid) if isinstance(rid,str) else None
        check['requirement_id']=rid if rule else ''
        check['gate']='not_failed'
        if check['status']!='fail':continue
        if rule and rule['origin'] in ('goal','acceptance'):
            quality.append({'requirement':check['requirement'],'evidence':check['evidence'],'status':'needs_human_review'})
            # Aesthetic goals stay evaluated, but do not masquerade as objective vetoes.
            check['status']='unknown';check['gate']='creative_quality'
            advisories.append('创作目标待核对：'+check['requirement']+'；'+check['evidence'])
            continue
        reason=''
        if not rule or not rule['hard'] or check['requirement']!=rule['requirement']:
            reason='不是逐字对应的已确认硬性要求（整体目标/模型风险不作拦截条件）'
        elif not authority_valid:reason='缺少与当前确认卡绑定的用户最终采纳记录'
        elif incoming.get('basis')!='direct':reason='依据为推断、主观判断或未声明直接证据'
        elif incoming.get('violation_kind')!='observed_forbidden':reason='采样只能证明明确禁用画面出现，不能证明整段缺失或主观不适合'
        elif rule['origin']!='forbidden':reason='画面禁用项必须对应用户确认的forbidden约束'
        elif not isinstance(incoming.get('relation'),dict):reason='证据关系格式缺失'
        elif incoming.get('relation',{}).get('type')!='literal_presence':reason='未提供同维度的直接出现关系'
        elif not isinstance(incoming.get('relation',{}).get('subject'),str) or incoming['relation']['subject']!=rule['requirement']:reason='证据对象没有逐字对应禁用项'
        elif any(token in rule['requirement'].lower() for token in ('原声','音频','音质','声音','口播','audio','sound','voice')):
            reason='采样画面不能证明声音不符合；音轨保留由程序检查，听感需人工预览'
        else:
            evidence=incoming.get('evidence_refs',[])
            if not isinstance(evidence,list) or not 1<=len(evidence)<=8:reason='没有可定位的直接证据'
            else:
                refs=[]
                for ref in evidence:
                    if not isinstance(ref,dict):reason='直接证据格式无效';break
                    kind=ref.get('kind')
                    if kind=='frame':
                        sid=ref.get('source_id')
                        if sid not in sources:reason='画面证据引用未授权素材';break
                        try:at=finite(ref.get('at'),0,sources[sid])
                        except ValueError:reason='画面证据时间不在素材范围';break
                        observed=snap.get('_review_observed',[])
                        if not any(o['source_id']==sid and abs(o['at']-at)<.03 for o in observed):reason='证据不是本次实际提供的采样画面';break
                        refs.append({'kind':kind,'source_id':sid,'at':at})
                    elif kind=='plan':
                        # Plan violations are checked by code outside the model gate. A model
                        # claiming field=sound is not proof of missing original audio.
                        reason='方案时长/画幅/标题/源区间/声音由程序检查，模型概括不作硬性证据';break
                    else:reason='声音缺失/品类/人物身份不能仅靠采样推断';break
                if not reason:check['evidence_refs']=refs
        if reason:
            check['status']='unknown';check['gate']='advisory'
            check['evidence']+='；未作硬性拦截：'+reason
            advisories.append(check['requirement']+'：'+reason)
        else:
            check['gate']='explicit_direct'
            blocks.append(check['requirement']+'：'+check['evidence'])
    # Do not erase reported concerns, but do not let unbound prose veto an export.
    value['blocking_issues']=list(dict.fromkeys(blocks))
    value['uncertainties']=list(dict.fromkeys(value['uncertainties']+['复核提示（非新增要求）：'+s for s in advisories]))
    value['review_policy']=VERSION
    value['quality_findings']=quality
    value['original_model_blocking_issues']=raw_blocks
    value['authority_valid']=authority_valid
    if advisories:
        value['model_summary']=value['summary']
        value['summary']=('已确认硬性要求存在有直接依据的问题，请核对。' if blocks else '未发现满足硬性拦截证据条件的问题；模型推断与未确定项已保留为提示，请预览核对。')
    return value
