import io
import json
import unittest
from unittest.mock import MagicMock, patch

import test_hub as fixtures
from test_image_fixture import png


class AssistantDataTests(unittest.TestCase):
    setUp = fixtures.HubTests.setUp
    tearDown = fixtures.HubTests.tearDown
    login = fixtures.HubTests.login

    def ask(self, client, prompt):
        self.admin.post('/api/assistant/a6-settings', json={'key': 'test-provider-key'}, headers=fixtures.H)
        tid = client.post('/api/assistant/threads', headers=fixtures.H).json()['id']
        opener = MagicMock()
        opener.open.return_value = io.BytesIO(b'{"choices":[{"message":{"content":"answer"},"finish_reason":"stop"}]}')
        with patch('assistant_chat.urllib.request.build_opener', return_value=opener):
            r = client.post('/api/assistant/threads/'+tid+'/send', headers=fixtures.H,
                            json={'text': prompt, 'request_key': 'assistant-data-test-0001'})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(opener.open.call_count, 1)
        return '\n'.join(m['content'] for m in json.loads(opener.open.call_args.args[0].data)['messages'])

    def test_account_summary_and_second_page_use_saved_statistics(self):
        owner = self.member.get('/api/me').json()['id']
        with self.hub.db() as db:
            db.execute('INSERT INTO apify_accounts(id,owner,handle) VALUES (?,?,?)', ('account-test', owner, 'storetest'))
            for i in range(9):
                video = str(780000001+i)
                db.execute("""INSERT INTO apify_snapshots(run,account,video,published,views,likes,collected)
                              VALUES('run-test','account-test',?,?,?,?,?)""", (video, i, i*100, None, i))
            db.execute("""INSERT INTO video_enrichment_jobs(id,account,video,period_start,period_end,state,created,updated,result)
                          VALUES('job-test','account-test','780000001','2026-11-01','2026-11-21','ready',1,2,?)""",
                       ('{"gmv":125.5}',))
        context = self.ask(self.member, '查 @storetest 的已采集视频和分析，第 2 页')
        self.assertIn('《中台实查数据》', context)
        self.assertIn('"tracked": 9', context)
        self.assertIn('"gmv": 125.5', context)
        self.assertIn('"likes": null', context)
        self.assertIn('https://www.tiktok.com/@storetest/video/780000001', context)
        self.assertNotIn('780000009', context)

    def test_material_subset_and_admin_gate(self):
        for client, filename in ((self.admin, 'ADMIN_PRIVATE_ONLY.png'), (self.member, 'MEMBER_VISIBLE.png')):
            uploaded = client.post('/api/assets', content=png(), headers={
                **fixtures.H,'Content-Type':'image/png','X-File-Name':filename})
            self.assertEqual(uploaded.status_code, 200, uploaded.text)
        content = self.ask(self.member, '列出我的素材和团队成员')
        self.assertIn('MEMBER_VISIBLE.png', content)
        self.assertNotIn('ADMIN_PRIVATE_ONLY.png', content)
        self.assertIn('当前账号没有权限', content)
