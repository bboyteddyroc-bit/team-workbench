import unittest
from unittest.mock import patch
from test_assistant_chat import AssistantTests

class A6SettingsTests(unittest.TestCase):
 setUp=AssistantTests.setUp
 tearDown=AssistantTests.tearDown
 login=AssistantTests.login
 def test_admin_isolated_encrypted_no_jobs(self):
  p='/api/assistant/a6-settings';h={'X-Hub-Request':'1'}; key='fixture-secret-12345'
  self.assertEqual(self.member.get(p).status_code,403)
  self.assertEqual(self.member.post(p,json={'key':key},headers=h).status_code,403)
  self.assertFalse(self.admin.get(p).json()['configured'])
  with patch('asset_classification.queue_waiting',side_effect=AssertionError('no queue')):
   r=self.admin.post(p,json={'key':key},headers=h)
  self.assertEqual(r.status_code,200,r.text);self.assertTrue(r.json()['active']);self.assertTrue(self.admin.get(p).json()['active'])
  self.assertNotIn(key,self.admin.get(p).text)
  with self.hub.db() as db:
   value=db.execute('SELECT secret FROM a6_settings').fetchone()[0]
   self.assertNotIn(key.encode(),value)
   self.assertEqual(self.hub.cipher.decrypt(value).decode(),key)
   self.assertIsNone(db.execute('SELECT secret FROM ai_settings').fetchone())
if __name__=='__main__':unittest.main()
