import io,json,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import test_hub as fixtures

class MultiImageTests(unittest.TestCase):
    setUp=fixtures.HubTests.setUp
    tearDown=fixtures.HubTests.tearDown
    login=fixtures.HubTests.login
    def post(self,path,data):return self.member.post('/api/assistant'+path,json=data,headers=fixtures.H)
    def test_four_and_idempotence(self):
        with self.hub.db() as db:db.execute('INSERT INTO libtv_settings VALUES(1,?)',('42',))
        tid=self.post('/threads',{}).json()['id'];buf=io.BytesIO();Image.new('RGB',(10,12),'red').save(buf,format='PNG');calls=[]
        def cli(args,cwd):
            calls.append(args)
            if args[0]=='account':return {'accounts':[{'accountId':42,'isActive':True}]}
            if args[0]=='model':return {'schema':{'modelKey':'lib-image-2.5-f','properties':{'count':[1,2,4]}}}
            if args[0]=='project':return {'projectMeta':{'uuid':'b'*32}}
            if args[0]=='download':
                for i in range(4):(Path(args[-1])/f'{i}.png').write_bytes(buf.getvalue())
            return {}
        data={'text':'test','mode':'image','count':4,'request_key':'test-multi-image-001'}
        with patch('libtv_gateway.cli',side_effect=cli):
            r=self.post('/threads/'+tid+'/send',data);self.assertEqual(r.status_code,200,r.text);ids=r.json()['result_assets'];self.assertEqual(len(ids),4)
            again=self.post('/threads/'+tid+'/send',data);self.assertEqual(again.json()['result_assets'],ids);self.assertEqual(sum('--run' in x for x in calls),1)
            self.assertIn('count=4',next(x for x in calls if '--run' in x));self.assertEqual(self.post('/threads/'+tid+'/send',{**data,'count':3,'request_key':'test-multi-image-002'}).status_code,400)
        turn=self.member.get('/api/assistant/threads/'+tid).json()[0];self.assertEqual(json.loads(turn['result_assets']),ids)
        for aid in ids:self.assertEqual(self.member.get('/api/assets/'+aid).status_code,200);self.assertEqual(self.admin.get('/api/assets/'+aid).status_code,404)
if __name__=='__main__':unittest.main()
