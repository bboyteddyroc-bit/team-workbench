import unittest
from test_hub import HubTests,H,PW
class ResetTests(unittest.TestCase):
 setUp=HubTests.setUp
 tearDown=HubTests.tearDown
 login=HubTests.login
 def test_reset_permissions_session_and_change(self):
  uid=self.member.get('/api/me').json()['id'];aid=self.admin.get('/api/me').json()['id']
  path='/api/users/'+uid+'/reset-password';payload={'password':'temporary-password-123'}
  self.assertEqual(self.member.post(path,headers=H,json=payload).status_code,403)
  self.assertEqual(self.admin.post('/api/users/'+aid+'/reset-password',headers=H,json=payload).status_code,400)
  self.assertEqual(self.admin.post(path,headers=H,json={'password':'short'}).status_code,400)
  self.assertEqual(self.admin.post(path,headers=H,json=payload).status_code,200)
  self.assertEqual(self.member.get('/api/me').status_code,401)
  self.assertEqual(self.member.post('/api/login',headers=H,json={'username':'member','password':PW+'new'}).status_code,401)
  r=self.member.post('/api/login',headers=H,json={'username':'member',**payload});self.assertEqual(r.status_code,200);self.assertTrue(r.json()['must_change'])
  self.assertEqual(self.member.get('/api/feishu/status').status_code,403)
  self.assertEqual(self.member.post('/api/password',headers=H,json={'old':payload['password'],'new':'new-member-password-123'}).status_code,200)
  self.assertFalse(self.member.get('/api/me').json()['must_change'])
  with self.hub.db() as db:
   self.assertEqual(db.execute("SELECT count(*) FROM audit WHERE action='user_password_reset'").fetchone()[0],1)
if __name__=='__main__':unittest.main()
