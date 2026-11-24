"""提示词长度不设限：前端输入框、保存接口、provider 载荷都不再截断或拒绝长提示词。

历史上提示词被限制在 5000 字（composer 的 maxlength、app/workspace 的保存校验、
libtv 网关与 provider 的载荷校验）。产品要求取消该限制，这里锁定行为。
"""
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import test_hub as fixtures
from app import create_app
from provider import mini_reference_payload, reference_payload

BASE = 'http://127.0.0.1:8765'
H = {'X-Hub-Request': '1', 'Origin': BASE}
PW = 'Example-test-password-123'
LONG_PROMPT = '镜头缓慢推进，人物侧身望向窗外，暖色逆光；' * 700  # 14700 字
IMAGE = {'id': 'img-1', 'name': 'a.png',
         'previewUrl': 'https://p19-creative-tool-sg.ibyteimg.com/tos-alisg-i-n2703mo9gi-sg/x.jpg'}


class FakeProvider:
    def history(self, headers):
        return {'draft_infos': []}


class PromptLengthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(self.tmp.name, FakeProvider(), worker=False)
        self.client = TestClient(self.app, base_url=BASE)
        self.assertEqual(self.client.post('/api/setup', json={'username': 'admin', 'password': PW}, headers=H).status_code, 200)
        self.assertEqual(self.client.post('/api/login', json={'username': 'admin', 'password': PW}, headers=H).status_code, 200)

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def test_compositions_keep_long_prompt(self):
        self.assertGreater(len(LONG_PROMPT), 5000)
        item = {'prompt': LONG_PROMPT, 'mode': 'omni', 'model': 'auto', 'duration': 5, 'count': 1, 'assets': []}
        response = self.client.post('/api/compositions', json={'items': [item]}, headers=H)
        self.assertEqual(response.status_code, 200, response.text)
        saved = self.client.get('/api/compositions', headers=H).json()
        self.assertEqual(saved['items'][0]['prompt'], LONG_PROMPT)

    def test_provider_payload_keeps_long_prompt(self):
        payload = mini_reference_payload(LONG_PROMPT, [IMAGE], 5, '2000009')
        self.assertEqual(payload['prompt'], LONG_PROMPT)
        self.assertEqual(json.loads(payload['settings'])['prompt'], LONG_PROMPT)

        payload = reference_payload(LONG_PROMPT, [dict(IMAGE, fileType='image')], 5, '2000004')
        self.assertEqual(payload['prompt'], LONG_PROMPT)
        self.assertEqual(json.loads(payload['settings'])['prompt'], LONG_PROMPT)

    def test_empty_prompt_still_rejected(self):
        item = {'prompt': '   ', 'mode': 'omni', 'model': 'auto', 'duration': 5, 'count': 1, 'assets': []}
        with self.assertRaises(ValueError):
            reference_payload('   ', [dict(IMAGE, fileType='image')], 5, '2000004')
        # 保存草稿接口历史上允许空提示词（创作过程中逐步输入），这里只锁定不因长度被拒。
        self.assertEqual(self.client.post('/api/compositions', json={'items': [item]}, headers=H).status_code, 200)

    def test_no_prompt_length_guard_left_in_sources(self):
        root = Path(__file__).resolve().parent
        targets = ['app.py', 'workspace.py', 'provider.py', 'libtv_gateway.py', 'static/composer.js']
        patterns = [
            re.compile(r'最多\s*5000\s*字'),
            re.compile(r'1[–-]5000\s*字'),
            re.compile(r'len\(prompt\)\s*>\s*5000'),
            re.compile(r'len\(prompt\.strip\(\)\)\s*<=\s*5000'),
            re.compile(r'maxLength\s*=\s*5000'),
        ]
        for name in targets:
            text = (root / name).read_text(encoding='utf-8')
            for pattern in patterns:
                self.assertIsNone(pattern.search(text), f'{name} 仍存在提示词长度限制：{pattern.pattern}')


class LibTVPromptLengthTests(unittest.TestCase):
    """LibTV 网关同样不再拒绝长提示词。"""

    setUp = fixtures.HubTests.setUp
    tearDown = fixtures.HubTests.tearDown
    login = fixtures.HubTests.login

    def test_long_prompt_job_accepted(self):
        def fake(args, cwd):
            if args[0] == 'account':
                return {'accounts': [{'accountId': 42, 'isActive': True}]}
            if args[0] == 'model':
                return {'schema': {'modelKey': args[1], 'modelName': 'StarVideo 2.0'}}
            if args[0] == 'project':
                return {'projectMeta': {'uuid': 'a' * 32}}
            if args[0] == 'node' and len(args) > 1 and args[1] == '成片' and '--run' not in args:
                return {'data': {'url': ['https://example.test/video.mp4']}}
            if args[0] == 'download':
                (Path(args[-1]) / 'result.mp4').write_bytes(b'video')
            return {'ok': True}

        with patch('libtv_gateway.cli', side_effect=fake), patch('editor.probe', return_value=(5, [{'codec_type': 'video'}])):
            self.assertEqual(self.member.post('/api/libtv/connect', json={}, headers=fixtures.H).status_code, 403)
            self.assertEqual(self.admin.post('/api/libtv/connect', json={}, headers=fixtures.H).status_code, 200)
            payload = {'prompt': LONG_PROMPT, 'duration': 5, 'request_key': 'libtv-long-prompt-001'}
            response = self.member.post('/api/libtv/jobs', json=payload, headers=fixtures.H)
            self.assertEqual(response.status_code, 200, response.text)
            job_id = response.json()['id']
            with self.hub.db() as db:
                stored = db.execute('SELECT payload FROM libtv_jobs WHERE id=?', (job_id,)).fetchone()['payload']
            self.assertEqual(json.loads(stored)['prompt'], LONG_PROMPT)


if __name__ == '__main__':
    unittest.main()
