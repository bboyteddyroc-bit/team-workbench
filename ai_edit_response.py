"""Local-only JSON extraction. Never eval, execute, repair semantics, or re-request AI."""
import json,re

class ResponseFormatError(ValueError):pass

def object_answer(answer):
    if not isinstance(answer,str) or not answer.strip():raise ResponseFormatError('模型回答为空')
    answer=answer.lstrip('\ufeff').strip()
    if len(answer)>200000:raise ResponseFormatError('模型回答超过本地解析上限')
    try:
        value=json.loads(answer)
        if not isinstance(value,dict):raise ResponseFormatError('模型回答不是JSON对象')
        return value
    except json.JSONDecodeError:pass
    # Prefer fenced content; do not mistake braces in explanatory prose for a second answer.
    fences=re.findall(r'```(?:json|JSON)?\s*\n?(.*?)```',answer,re.S)
    candidates=[];decoder=json.JSONDecoder()
    for block in fences or [answer]:
        cursor=0
        while cursor<len(block):
            at=block.find('{',cursor)
            if at<0:break
            try:value,end=decoder.raw_decode(block,at)
            except json.JSONDecodeError:
                # Do not accept a nested fragment from a malformed outer object.
                raise ResponseFormatError('回答含不完整或无效JSON，未猜测修补') from None
            if isinstance(value,dict):candidates.append(value)
            cursor=end
    if len(candidates)!=1:raise ResponseFormatError('未找到唯一完整JSON对象')
    return candidates[0]

def discussion_answer(answer,context):
    try:return object_answer(answer)
    except ResponseFormatError:
        # Plain prose is useful conversation, not an executable contract. JSON-looking failures
        # are retained but explicitly marked rather than silently using an inner object.
        from ai_edit_conversation import DEFAULT_BRIEF
        result={'reply':answer.strip()[:5800],'brief':context.get('previous_brief') or dict(DEFAULT_BRIEF),'instructions':context.get('previous_instructions',''),'missing':['本次回复尚未形成可执行需求总结，请继续确认；未开始剪辑。'],'ready':False}
        if context.get('previous_contract') is not None:result['contract']=context['previous_contract']
        else:
            result['contract']={'goal':'','kind':'通用剪辑','scope':'new','captions':'none','titles':False,'pending':['需继续确认制作要求']}
        return result
