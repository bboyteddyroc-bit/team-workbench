"""Auto-return regressions for finished LibTV videos. No paid provider calls."""
import json
import subprocess
import time
import unittest
from unittest.mock import patch
import libtv_gateway as gw
import test_hub as fixtures


class AutoReturnTests(unittest.TestCase):
    setUp = fixtures.HubTests.setUp
    tearDown = fixtures.HubTests.tearDown
    login = fixtures.HubTests.login

    def job(self, state='attention', project='a' * 32, retry_at=0, stage='生成完成 · 正在下载入库'):
        jid = 'd' * 32
        uid = self.member.get('/api/me').json()['id']
        payload = json.dumps({'prompt': 'test', 'duration': 5, 'model': 'star-video2', 'resolution': '720p'})
        with self.hub.db() as db:
            db.execute("INSERT INTO libtv_jobs(id,owner,request_key,payload,state,created,updated,project,stage,retry_at) VALUES(?,?,?,?,?,0,0,?,?,?)",
                       (jid, uid, 'auto-return-fixture', payload, state, project, stage, retry_at))
        (self.hub.directory / "libtv" / jid).mkdir(parents=True,exist_ok=True)
        with self.hub.db() as db:
            db.execute("INSERT OR REPLACE INTO libtv_settings VALUES(1,?)",("test-account",))
        return jid

    def row(self, jid):
        with self.hub.db() as db:
            return dict(db.execute('SELECT * FROM libtv_jobs WHERE id=?', (jid,)).fetchone())

    # ---- diagnosis / classification -------------------------------------------------
    def test_membership_check_failure_is_transient_and_explained(self):
        text = '无法确认账号会员态，已中止：--watermark 需要与会员态核对后才能下载，请稍后重试。'
        self.assertIn('自动重试', gw.cli_failure(['download'], '', text))
        self.assertTrue(gw.retryable_download(text))

    def test_watermark_mismatch_is_not_retried(self):
        text = '当前账号是会员，下载物不带社区水印，与 --watermark true 不一致：请改传 --watermark false。'
        self.assertFalse(gw.retryable_download(text))
        self.assertIn('LIBTV_DOWNLOAD_WATERMARK', gw.cli_failure(['download'], '', text))

    def test_login_expiry_and_missing_media_are_not_retried(self):
        for text in ('用户未授权 code: 10001', '节点上没有可下载的资源', 'not found'):
            self.assertFalse(gw.retryable_download(text), text)

    def test_scrub_removes_urls_and_secrets(self):
        out = gw.scrub('(node:1) [UNDICI-EHPA] Warning\nfetch https://cdn.example.com/a/b?sig=SECRET failed\nAuthorization: Bearer abc123')
        self.assertNotIn('SECRET', out)
        self.assertNotIn('abc123', out)
        self.assertNotIn('UNDICI', out)
        self.assertIn('cdn.example.com', out)

    def test_cli_marks_download_failure_transient_and_records_excerpt(self):
        done = subprocess.CompletedProcess([], 1, b'', '网络错误 ECONNRESET https://x.example/y?token=ZZZ'.encode())
        with patch('libtv_gateway.shutil.which', return_value='libtv.exe'), patch('libtv_gateway.profile_environment',return_value={}), patch('libtv_gateway.run_bounded', return_value=done):
            with self.assertRaises(gw.Transient):
                gw.cli(['download', '-p', 'p'], self.hub.directory)
        record = json.loads((self.hub.directory / 'cli-diagnostics.jsonl').read_text(encoding='utf-8').splitlines()[-1])
        self.assertNotIn('ZZZ', record['excerpt'])
        self.assertIn('ECONNRESET', record['excerpt'])

    # ---- in-request retry -----------------------------------------------------------
    def test_download_retried_in_request_then_succeeds(self):
        jid = self.job()
        out = self.hub.directory / 'libtv' / jid / 'download'
        calls = []

        def fake(args, cwd):
            if args[0]=='account':return {'accounts':[{'isActive':True,'accountId':'test-account'}]}
            if args[0] == 'node':
                return {'data': {'url': ['https://v.example/x.mp4'], 'taskInfo': {'status': 2}}}
            calls.append(args)
            if len(calls) < 3:
                raise gw.Transient('暂时失败')
            (out / '成片.mp4').write_bytes(b'video')
            return {'download_completed': True}
        with patch('libtv_gateway.cli', side_effect=fake), patch('libtv_gateway.time.sleep'), \
                patch('editor.probe', return_value=(5, [{'codec_type': 'video'}])):
            r = self.member.post('/api/libtv/jobs/' + jid + '/recover', json={}, headers=fixtures.H)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(len(calls), 3)
        self.assertEqual(self.row(jid)['state'], 'ready')

    def test_exhausted_download_schedules_background_retry(self):
        jid = self.job()

        def fake(args, cwd):
            if args[0]=='account':return {'accounts':[{'isActive':True,'accountId':'test-account'}]}
            if args[0] == 'node':
                return {'data': {'url': ['https://v.example/x.mp4'], 'taskInfo': {'status': 2}}}
            raise gw.Transient('暂时失败')
        with patch('libtv_gateway.cli', side_effect=fake), patch('libtv_gateway.time.sleep'):
            r = self.member.post('/api/libtv/jobs/' + jid + '/recover', json={}, headers=fixtures.H)
        self.assertEqual(r.status_code, 502)
        row = self.row(jid)
        self.assertEqual(row['state'], 'attention')
        self.assertGreater(row['retry_at'], time.time())
        self.assertEqual(row['stage'], '等待自动取回')
        self.assertIn('自动重试', row['error'])

    def test_definite_failure_is_not_scheduled(self):
        jid = self.job()

        def fake(args, cwd):
            if args[0]=='account':return {'accounts':[{'isActive':True,'accountId':'test-account'}]}
            if args[0] == 'node':
                return {'data': {'url': ['https://v.example/x.mp4'], 'taskInfo': {'status': 2}}}
            raise RuntimeError('登录已失效')
        with patch('libtv_gateway.cli', side_effect=fake):
            self.member.post('/api/libtv/jobs/' + jid + '/recover', json={}, headers=fixtures.H)
        self.assertEqual(self.row(jid)['retry_at'], 0)

    # ---- background loop ------------------------------------------------------------
    def test_auto_recover_imports_due_job_without_generating(self):
        jid = self.job(retry_at=time.time() - 1, stage='等待自动取回')
        out = self.hub.directory / 'libtv' / jid / 'download'
        seen = []

        def fake(args, cwd):
            seen.append(args[0])
            if args[0]=='account':return {'accounts':[{'isActive':True,'accountId':'test-account'}]}
            if args[0] == 'node':
                return {'data': {'url': ['https://v.example/x.mp4'], 'taskInfo': {'status': 2}}}
            (out / '成片.mp4').write_bytes(b'video')
            return {'download_completed': True}
        with patch('libtv_gateway.cli', side_effect=fake), patch('editor.probe', return_value=(5, [{'codec_type': 'video'}])):
            result = self.app.state.libtv_auto_once()
        self.assertEqual(result['state'], 'ready')
        self.assertEqual(self.row(jid)['state'], 'ready')
        self.assertEqual(set(seen), {'account','node', 'download'})
        self.assertNotIn('create', [a for a in seen])

    def test_auto_recover_skips_future_and_manual_jobs(self):
        jid = self.job(retry_at=time.time() + 600)
        with patch('libtv_gateway.cli') as cli:
            self.assertIsNone(self.app.state.libtv_auto_once())
            cli.assert_not_called()
        with self.hub.db() as db:
            db.execute('UPDATE libtv_jobs SET retry_at=0 WHERE id=?', (jid,))
        with patch('libtv_gateway.cli') as cli:
            self.assertIsNone(self.app.state.libtv_auto_once())
            cli.assert_not_called()

    def test_auto_recover_gives_up_after_limit(self):
        jid = self.job(retry_at=time.time() - 1)
        with self.hub.db() as db:
            db.execute('UPDATE libtv_jobs SET auto_tries=? WHERE id=?', (gw.AUTO_RETRY_LIMIT, jid))

        def fake(args, cwd):
            if args[0]=='account':return {'accounts':[{'isActive':True,'accountId':'test-account'}]}
            if args[0] == 'node':
                return {'data': {'url': ['https://v.example/x.mp4'], 'taskInfo': {'status': 2}}}
            raise gw.Transient('暂时失败')
        with patch('libtv_gateway.cli', side_effect=fake), patch('libtv_gateway.time.sleep'):
            self.app.state.libtv_auto_once()
        row = self.row(jid)
        self.assertEqual(row['retry_at'], 0)
        self.assertEqual(row['state'], 'attention')

    # ---- still generating -------------------------------------------------------------
    def test_still_generating_after_wait_is_transient_not_failure(self):
        calls = {'n': 0}

        def fake(args, cwd):
            calls['n'] += 1
            return {'data': {'url': [], 'taskInfo': {'status': 1}}}
        with patch('libtv_gateway.cli', side_effect=fake), patch('libtv_gateway.time.sleep'):
            with self.assertRaises(gw.Transient):
                gw.ensure_output('p' * 32, self.hub.directory, lambda t: None, wait_seconds=0)


if __name__ == '__main__':
    unittest.main()
