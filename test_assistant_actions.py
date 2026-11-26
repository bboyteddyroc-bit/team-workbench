import unittest
from unittest.mock import patch

from assistant_actions import classify_intent
from asset_classification import tick
from test_image_fixture import png
import test_hub as fixtures


class AssistantActionTests(unittest.TestCase):
    setUp=fixtures.HubTests.setUp
    tearDown=fixtures.HubTests.tearDown
    login=fixtures.HubTests.login

    def post(self,client,path,data):
        return client.post('/api'+path,json=data,headers=fixtures.H)

    def image(self,client):
        return client.post('/api/assets',content=png(),headers={
            **fixtures.H,'Content-Type':'image/png','X-File-Name':'image.png'}).json()['id']

    def states(self):
        with self.hub.db() as db:
            return {r['asset_id']:r['status'] for r in db.execute('SELECT * FROM asset_classification')}

    def test_proposal_is_idempotent_and_confirmation_respects_account_and_existing_edits(self):
        automatic,waiting,manual,other=self.image(self.member),self.image(self.member),self.image(self.member),self.image(self.admin)
        self.post(self.member,'/workspace/materials/'+manual,{'category':'person'}).raise_for_status()
        with self.hub.db() as db:
            db.execute("UPDATE asset_classification SET status='classified',source='vision' WHERE asset_id=?",(automatic,))
        self.post(self.admin,'/assistant/a6-settings',{'key':'test-classify-non-production'}).raise_for_status()
        tid=self.post(self.member,'/assistant/threads',{}).json()['id']
        path='/assistant/threads/'+tid
        command={'text':'检查一下素材管理中的素材，并全部重新识别并重新分类','request_key':'batch-reclassify-test'}
        initial=self.states()
        with patch('assistant_chat.build_request',side_effect=AssertionError('should not call a model')):
            first=self.post(self.member,path+'/send',command)
            self.assertEqual(first.status_code,200,first.text)
            self.assertEqual(self.post(self.member,path+'/send',command).json(),first.json())
        action=first.json()['action']
        self.assertEqual(action['eligible'],2)
        self.assertEqual(action['manual'],1)
        self.assertEqual(self.states(),initial)
        self.assertEqual(self.member.get('/api'+path).json()[0]['action'],action)
        endpoint=path+'/actions/'+action['id']
        self.assertEqual(self.post(self.admin,endpoint,{'decision':'confirm'}).status_code,404)
        self.post(self.member,'/workspace/materials/'+waiting,{'category':'scene'}).raise_for_status()
        result=self.post(self.member,endpoint,{'decision':'confirm'}).json()
        self.assertEqual((result['queued'],result['active']),(1,1))
        self.assertEqual(self.post(self.member,endpoint,{'decision':'confirm'}).json(),result)
        self.assertEqual(self.states(),{automatic:'queued',waiting:'manual',manual:'manual',other:'waiting_model'})
        self.assertTrue(tick(self.hub,lambda _: 'product'))
        result=self.member.get('/api'+endpoint).json()
        self.assertEqual((result['classified'],result['active']),(1,0))

    def test_advice_and_negative_requests_dont_prepare_actions(self):
        self.assertIsNone(classify_intent('如何把素材库图片全部重新分类？'))
        self.assertIsNone(classify_intent('先不要把素材库全部重新识别'))
        self.assertEqual(classify_intent('把素材库待处理的图片重新分类'),('classify_materials',False))
