import io,json,unittest
from unittest.mock import patch
from ai_edit_response import object_answer,discussion_answer,ResponseFormatError
from ai_edit_conversation import request_json,DEFAULT_BRIEF
import test_ai_edit_conversation as base
import test_hub as fixtures

class ResponseTests(unittest.TestCase):
    def test_plain_fenced_and_explanatory_json(self):
        obj={'reply':'文字中含{花括号}','ready':False}
        raw=json.dumps(obj,ensure_ascii=False)
        for value in [raw,'\ufeff'+raw,'```json\n'+raw+'\n```','这是整理的要求：\n```json\n'+raw+'\n```\n请确认。','整理如下：\n'+raw+'\n请确认。']:
            self.assertEqual(object_answer(value),obj)

    def test_invalid_ambiguous_array_and_nested_fragment_refused(self):
        for raw in ['{"a":1} {"a":2}','[{"a":1}]','{"brief":{"a":1},','{"a": True}','普通文字']:
            with self.assertRaises(ResponseFormatError):object_answer(raw)

    def test_plain_reply_never_authorizes_and_preserves_previous(self):
        context={'previous_brief':{**DEFAULT_BRIEF,'target':25},'previous_instructions':'不变项','previous_contract':{'goal':'已有目标','scope':'new'}}
        r=discussion_answer('请问你希望保留原声吗？',context)
        self.assertFalse(r['ready']);self.assertEqual(r['brief']['target'],25)
        self.assertEqual(r['instructions'],'不变项');self.assertEqual(r['contract'],context['previous_contract'])
        self.assertTrue(r['missing'])

    def test_request_does_not_retry_plain_text(self):
        envelope={'choices':[{'finish_reason':'stop','message':{'content':[{'type':'text','text':'你希望剪成多长？'}]}}]}
        with patch('asr.configured_key',return_value='fixture-key'),patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(envelope).encode())) as call:
            result=request_json(None,'test',{})
        self.assertFalse(result['ready']);self.assertEqual(call.call_count,1)

    def test_truncated_never_authorizes(self):
        envelope={'choices':[{'finish_reason':'length','message':{'content':'{"reply":"not complete'}}]}
        with patch('asr.configured_key',return_value='fixture-key'),patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(envelope).encode())) as call:
            with self.assertRaisesRegex(ValueError,'截断'):request_json(None,'test',{})
            self.assertEqual(call.call_count,1)

class ConversationResponseTests(unittest.TestCase):
    setUp=base.ConversationTests.setUp
    tearDown=base.ConversationTests.tearDown
    login=base.ConversationTests.login
    account=base.ConversationTests.account
    enqueue=base.ConversationTests.enqueue
    sample=base.ConversationTests.sample
    create=base.ConversationTests.create
    get=base.ConversationTests.get
    ready=base.ConversationTests.ready

    def test_prose_visible_answer_persisted_and_no_media_work(self):
        p=self.ready(False);service=self.app.state.ai_editing
        envelope={'choices':[{'finish_reason':'stop','message':{'content':'先确认：需要保留原声吗？'}}]}
        with patch('asr.configured_key',return_value='fixture-key'),patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(envelope).encode())) as call,patch.object(service,'analyze') as analyze:
            r=self.member.post(self.url+'/discuss',json={'message':'先帮我梳理','general_requirements':True,'revision':p['revision'],'request_key':'format-prose-request','consent':True},headers=fixtures.H)
            self.assertEqual(r.status_code,200);service.tick();service.tick()
            self.assertEqual(call.call_count,1);analyze.assert_not_called()
        p=self.get();self.assertEqual(p['jobs'][0]['state'],'ready',p)
        self.assertFalse(p['body']['requirements_ready']);self.assertEqual(p['body']['messages'][-1]['text'],'先确认：需要保留原声吗？')
        with self.hub.db() as db:
            record=db.execute('SELECT answer FROM ai_edit_answers WHERE job_id=?',(p['jobs'][0]['id'],)).fetchone()
        self.assertEqual(record['answer'],'先确认：需要保留原声吗？')
        self.assertEqual(self.admin.get(self.url).status_code,404)

if __name__=='__main__':unittest.main()
