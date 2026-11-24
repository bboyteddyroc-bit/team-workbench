import json, unittest
from a6_provider import build_request, ENDPOINT, MODEL

class Tests(unittest.TestCase):
 def test_portable_request(self):
  original={'model':'old','messages':[{'role':'user','content':'hello'}], 'chat_template_kwargs':{'enable_thinking':False}}
  req=build_request('test-token',original)
  body=json.loads(req.data)
  self.assertEqual(req.full_url,ENDPOINT)
  self.assertEqual(body['model'],MODEL)
  self.assertNotIn('chat_template_kwargs',body)
  self.assertEqual(original['model'],'old')
  self.assertEqual(req.get_header('Authorization'),'Bearer test-token')
 def test_reject_bad_key(self):
  with self.assertRaises(ValueError):build_request('bad\r\nkey',{'messages':[]})
if __name__=='__main__':unittest.main()
