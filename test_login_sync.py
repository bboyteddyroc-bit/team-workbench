import io,json,unittest,urllib.error
from unittest.mock import Mock,patch
from test_hub import HubTests,H
from provider import TikTok,ProviderError

class LoginSyncTests(unittest.TestCase):
    setUp=HubTests.setUp
    tearDown=HubTests.tearDown
    login=HubTests.login
    def test_sync_permissions_and_atomic_validation(self):
        payload={'headers':{'cookie':'session=fake','x-csrftoken':'fake','x-fp-id':'fake'}}
        self.assertEqual(self.member.post('/api/accounts/sync-login',headers=H,json=payload).status_code,403)
        self.assertEqual(self.admin.post('/api/accounts/sync-login',json=payload).status_code,403)
        with patch.object(self.provider,'account_info',create=True,side_effect=[[{'aioClientID':'1'},{'aioClientID':'2'}],{'aioClientID':'1'},ProviderError('invalid',True)]), patch.object(self.provider,'scoped_account',create=True,return_value=payload['headers']):
            self.assertEqual(self.admin.post('/api/accounts/sync-login',headers=H,json=payload).status_code,400)
        self.assertEqual(self.admin.get('/api/accounts').json(),[])
        with patch.object(self.provider,'account_info',create=True,side_effect=[[{'aioClientID':'1'},{'aioClientID':'2'}],{'aioClientID':'1'},{'aioClientID':'2'}]), patch.object(self.provider,'scoped_account',create=True,return_value=payload['headers']):
            r=self.admin.post('/api/accounts/sync-login',headers=H,json=payload)
            self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['count'],2)
        self.assertNotIn('session=fake',self.admin.get('/api/accounts').text)

class ProviderErrors(unittest.TestCase):
    def test_auth_network_and_format(self):
        provider=TikTok(proxy=None)
        for body,auth in [({'BaseResp':{'StatusCode':38001001,'StatusMessage':'InvalidLogin'}},True),({'BaseResp':{'StatusCode':42}},False),({'BaseResp':[]},False)]:
            with patch.object(provider.opener,'open',return_value=io.BytesIO(json.dumps(body).encode())):
                with self.assertRaises(ProviderError) as result:provider.account_info({},True)
                self.assertEqual(result.exception.auth,auth)
        with patch.object(provider.opener,'open',side_effect=urllib.error.URLError('timeout')):
            with self.assertRaises(ProviderError) as result:provider.account_info({},True)
            self.assertFalse(result.exception.auth)

if __name__=='__main__':unittest.main()

