"""Isolated classification regression tests. No real keys, assets or HTTP calls."""
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image
from app import create_app
import asset_classification as classification

BASE = 'http://127.0.0.1:8765'
HEADERS = {'X-Hub-Request': '1', 'Origin': BASE}


class ClassificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(self.tmp.name, worker=False)
        self.hub = self.app.state.hub
        self.client = TestClient(self.app, base_url=BASE)
        password = 'classification-test-password-123'
        self.client.post('/api/setup', json={'username': 'admin', 'password': password}, headers=HEADERS).raise_for_status()
        self.client.post('/api/login', json={'username': 'admin', 'password': password}, headers=HEADERS).raise_for_status()

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def upload(self, mime='image/png'):
        stream = io.BytesIO()
        if mime.startswith('image/'):
            Image.new('RGB', (12, 8), (20, 150, 170)).save(stream, format='PNG')
            content = stream.getvalue()
        else:
            content = b'RIFF' + b'\0' * 4 + b'WAVE' + b'\0' * 32
        response = self.client.post('/api/assets', content=content, headers={**HEADERS, 'Content-Type': mime, 'X-File-Name': 'test.png'})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['id']

    def configure(self):
        response = self.client.post('/api/assistant/a6-settings', json={'key': 'fake-classification-key'}, headers=HEADERS)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def state(self, aid):
        with self.hub.db() as db:
            return dict(db.execute('SELECT * FROM asset_classification WHERE asset_id=?', (aid,)).fetchone())

    def label(self, aid, category='scene'):
        response = self.client.post('/api/workspace/materials/' + aid, json={'name': 'manual.png', 'category': category}, headers=HEADERS)
        self.assertEqual(response.status_code, 200, response.text)

    def test_settings_promote_waiting_and_worker_updates_folder(self):
        aid = self.upload()
        self.assertEqual(self.state(aid)['status'], 'waiting_model')
        self.assertTrue(self.configure()['saved'])
        self.assertEqual(self.state(aid)['status'], 'waiting_model')
        with self.hub.db() as db:self.assertEqual(classification.queue_waiting(db),1)
        with self.hub.db() as db:self.assertEqual(classification.queue_waiting(db),0)
        self.assertTrue(classification.tick(self.hub, lambda path: 'product'))
        row = self.client.get('/api/workspace/materials').json()[0]
        self.assertEqual(row['category'], 'product')
        self.assertEqual(row['classification_status'], 'classified')
        self.assertEqual(row['classification_error'], '')
        self.assertFalse(classification.tick(self.hub, lambda path: self.fail('duplicate call')))

    def test_new_upload_with_config_is_queued_and_audio_is_not(self):
        self.configure()
        aid = self.upload()
        audio = self.upload('audio/wav')
        self.assertEqual(self.state(aid)['status'], 'queued')
        self.assertEqual(self.state(audio)['source'], 'file_type')
        self.assertEqual(self.state(audio)['status'], 'classified')

    def test_failure_no_automatic_replay_and_explicit_retry_clears_error(self):
        self.configure()
        aid = self.upload()
        def failure(path):
            raise ValueError('AI 服务限流')
        classification.tick(self.hub, failure)
        self.assertEqual(self.state(aid)['status'], 'failed')
        self.assertTrue(self.configure()['saved'])
        with self.hub.db() as db:self.assertEqual(classification.queue_waiting(db),0)
        self.assertFalse(classification.tick(self.hub, lambda path: self.fail('must not retry')))
        response = self.client.post('/api/workspace/materials/' + aid + '/classify', json={}, headers=HEADERS)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['error'], '')
        classification.tick(self.hub, lambda path: 'person')
        self.assertEqual(self.state(aid)['folder'], 'person')
        self.assertEqual(self.state(aid)['error'], '')

    def throttle(self):
        with self.hub.db() as db:
            return dict(db.execute('SELECT * FROM classification_throttle WHERE id=1').fetchone())

    def test_limit_pauses_all_images_persists_and_recovers(self):
        self.configure()
        aid, other = self.upload(), self.upload()
        def limited(path):raise classification.RateLimited(180)
        with patch('asset_classification.time.time',return_value=1000):
            self.assertTrue(classification.tick(self.hub,limited))
            self.assertEqual(self.state(aid)['status'],'retry_wait')
            self.assertEqual(self.throttle()['cooldown_until'],1180)
            self.assertFalse(classification.tick(self.hub,lambda p:self.fail('cooldown bypass')))
            classification.enqueue(self.hub,aid,self.state_owner(aid))
            classification.initialize(self.hub)
            self.assertEqual(self.throttle()['cooldown_until'],1180)
        with patch('asset_classification.time.time',return_value=1180):
            classification.tick(self.hub,limited)
            self.assertEqual(self.throttle()['consecutive_limits'],2)
            self.assertEqual(self.throttle()['cooldown_until'],1360)
        with patch('asset_classification.time.time',return_value=1360):
            classification.tick(self.hub,lambda p:'product')
            self.assertEqual(self.throttle()['consecutive_limits'],0)
            self.assertEqual(self.throttle()['cooldown_until'],1365)
            self.assertFalse(classification.tick(self.hub,lambda p:self.fail('no pacing')))

    def state_owner(self,aid):
        with self.hub.db() as db:return db.execute('SELECT owner FROM assets WHERE id=?',(aid,)).fetchone()[0]

    def test_backoff_doubles_caps_and_same_asset_resumes(self):
        self.configure()
        aid=self.upload()
        now=1000
        def limited(path):raise classification.RateLimited()
        for delay in (60,120,240,480,960,1920,3600,3600):
            with patch('asset_classification.time.time',return_value=now):
                classification.tick(self.hub,limited)
                self.assertEqual(self.throttle()['cooldown_until'],now+delay)
            now+=delay
        with patch('asset_classification.time.time',return_value=now):
            classification.tick(self.hub,lambda path:'scene')
        self.assertEqual(self.state(aid)['status'],'classified')
        self.assertEqual(self.state(aid)['error'],'')

    def test_old_429_only_migrates_and_manual_wins_during_limit(self):
        self.configure()
        old, ordinary, manual = [self.upload() for _ in range(3)]
        with self.hub.db() as db:
            for aid,error in ((old,'AI 服务限流'),(ordinary,'network failure'),(manual,'AI 服务限流')):
                db.execute("UPDATE asset_classification SET status='failed',error=? WHERE asset_id=?",(error,aid))
        self.label(manual)
        classification.initialize(self.hub)
        self.assertEqual(self.state(old)['status'],'retry_wait')
        self.assertEqual(self.state(ordinary)['status'],'failed')
        self.assertEqual(self.state(manual)['status'],'manual')
        with self.hub.db() as db:db.execute('UPDATE classification_throttle SET cooldown_until=0')
        def limited(path):
            self.label(old)
            raise classification.RateLimited()
        classification.tick(self.hub,limited)
        self.assertEqual(self.state(old)['status'],'manual')

    def test_http_429_header_is_typed_without_leaking_body(self):
        from urllib.error import HTTPError
        self.configure()
        aid=self.upload()
        error=HTTPError('https://example.invalid',429,'rate limit',{'Retry-After':'900'},None)
        with patch('urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect=error
            with self.assertRaises(classification.RateLimited) as caught:
                classification.recognize(self.hub,self.hub.assets/aid)
        self.assertEqual(caught.exception.retry_after,900)
        from email.utils import formatdate
        self.assertEqual(classification.retry_after_seconds(formatdate(1600,usegmt=True),1000),600)
        for invalid in ('invalid','NaN','inf',None):
            self.assertEqual(classification.retry_after_seconds(invalid,1000),0)

    def test_manual_wins_over_inflight_recognition(self):
        self.configure()
        aid = self.upload()
        def recognize(path):
            self.label(aid, 'scene')
            return 'product'
        classification.tick(self.hub, recognize)
        self.assertEqual(self.state(aid)['status'], 'manual')
        self.assertEqual(self.state(aid)['folder'], 'scene')
        self.assertTrue(self.configure()['saved'])
        with self.hub.db() as db:self.assertEqual(classification.queue_waiting(db),0)

    def test_manual_classification_clears_old_error(self):
        aid = self.upload()
        with self.hub.db() as db:
            db.execute("UPDATE asset_classification SET status='failed',error='old error' WHERE asset_id=?", (aid,))
        self.label(aid)
        self.assertEqual(self.state(aid)['error'], '')
        self.assertEqual(self.state(aid)['status'], 'manual')

    def test_other_owner_and_anonymous_cannot_enqueue(self):
        aid = self.upload()
        response = self.client.post('/api/workspace/materials/' + aid + '/classify', json={}, headers=HEADERS)
        self.assertEqual(response.status_code, 200)
        with self.hub.db() as db:
            db.execute("UPDATE assets SET owner='another-user' WHERE id=?", (aid,))
        self.assertEqual(self.client.post('/api/workspace/materials/' + aid + '/classify', json={}, headers=HEADERS).status_code, 404)
        with TestClient(self.app, base_url=BASE) as anon:
            self.assertEqual(anon.get('/api/workspace/materials').status_code, 401)

    def test_upgrade_old_schema_promotes_only_unattempted_images(self):
        waiting, failed, manual, running = [self.upload() for _ in range(4)]
        self.label(manual)
        with self.hub.db() as db:
            db.execute("UPDATE asset_classification SET status='failed' WHERE asset_id=?", (failed,))
            db.execute("UPDATE asset_classification SET status='running' WHERE asset_id=?", (running,))
        self.configure()
        # Recreate the pre-error-column database layout observed on the real machine.
        with self.hub.db() as db:
            db.executescript('''ALTER TABLE asset_classification RENAME TO classification_old;
                CREATE TABLE asset_classification(asset_id TEXT PRIMARY KEY,status TEXT NOT NULL,folder TEXT NOT NULL,source TEXT NOT NULL,updated REAL NOT NULL);
                INSERT INTO asset_classification SELECT asset_id,status,folder,source,updated FROM classification_old;
                DROP TABLE classification_old;''')
            db.execute("UPDATE asset_classification SET status='waiting_model' WHERE asset_id=?", (waiting,))
        recovered = create_app(self.tmp.name, worker=False)
        self.assertEqual(self.state(waiting)['status'], 'waiting_model')
        self.assertEqual(self.state(failed)['status'], 'failed')
        self.assertEqual(self.state(manual)['status'], 'manual')
        self.assertEqual(self.state(running)['status'], 'running')
        self.assertEqual(self.state(waiting)['error'], '')
        recovered.state.hub.stop.set()

    def test_multimodal_request_and_response_with_no_real_network(self):
        self.configure()
        aid = self.upload()
        response = io.BytesIO(json.dumps({'choices': [{'message': {'content': 'product'}}]}).encode())
        with patch('urllib.request.build_opener') as opener:
            opener.return_value.open.return_value = response
            result = classification.recognize(self.hub, self.hub.assets / aid)
            request = opener.return_value.open.call_args.args[0]
            payload = json.loads(request.data)
        self.assertEqual(result, 'product')
        self.assertEqual(payload['model'], 'gemini-3.8-flash')
        self.assertEqual(request.full_url, 'https://api.a6api.vip/v1/chat/completions')
        self.assertEqual(payload['max_tokens'], 2048)
        self.assertNotIn('chat_template_kwargs', payload)
        self.assertTrue(payload['messages'][0]['content'][1]['image_url']['url'].startswith('data:image/jpeg;base64,'))
        self.assertNotIn(str(self.hub.assets), request.data.decode())


class ResponseFormatTests(unittest.TestCase):
    def response(self, content, reason='stop', **message):
        return {'choices': [{'finish_reason': reason, 'message': {'content': content, **message}}]}

    def test_valid_final_answer_formats(self):
        for answer in ('product', ' PRODUCT ', '"product"', '**product**', 'product.',
                       'category: product', '{"category":"product"}',
                       '```json\n{"category":"product"}\n```',
                       [{'type': 'text', 'text': 'product'}],
                       [{'type': 'output_text', 'text': '{"category":"product"}'}]):
            with self.subTest(answer=answer):
                self.assertEqual(classification.parse_response(self.response(answer)), 'product')

    def test_observed_empty_answer_with_reasoning_is_truncated(self):
        result = self.response('', 'length', reasoning_content='private reasoning')
        with self.assertRaisesRegex(ValueError, 'token 上限'):
            classification.parse_response(result)

    def test_truncated_category_is_not_accepted(self):
        with self.assertRaisesRegex(ValueError, 'token 上限'):
            classification.parse_response(self.response('person', 'length'))

    def test_reasoning_is_never_used_as_final_answer(self):
        with self.assertRaisesRegex(ValueError, '最终分类答案'):
            classification.parse_response(self.response(None, reasoning_content='product'))

    def test_refusals_and_malformed_or_ambiguous_answers_fail_closed(self):
        invalid = [None, {}, {'choices': []}, {'error': {'message': 'bad'}},
                   self.response('person or product'), self.response('not product'),
                   self.response({'category': 'product'}), self.response('{"category":"unknown"}'),
                   self.response('product', 'content_filter'), self.response('product', refusal='no'),
                   self.response([{'type': 'reasoning', 'text': 'product'}])]
        for result in invalid:
            with self.subTest(result=result), self.assertRaises(ValueError):
                classification.parse_response(result)


if __name__ == '__main__':
    unittest.main()
