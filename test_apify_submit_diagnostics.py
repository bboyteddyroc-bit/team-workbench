"""Submission diagnostics with the real queue/HTTPX hooks and a mock transport only."""
import json
import os
import sqlite3
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import httpx

from apify_submit_diagnostics import SubmissionTrace
from test_kalodata_integration import HEADERS, Tests as Fixture


TOKEN = 'fixture-private-apify-token'
HANDLE = 'fixture_private_profile'
RAW = 'do-not-log-this-body-or-exception'
REMOTE = 'FixtureRemote12345'
DATASET = 'FixtureDataset12345'
CLIENT = httpx.Client


class ReadTimeoutBody(httpx.SyncByteStream):
    def __iter__(self):
        raise httpx.ReadTimeout(RAW)


class SubmissionTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'APIFY_API_TOKEN': ''})
        env.start()
        self.addCleanup(env.stop)
        Fixture.setUp(self)
        self.addCleanup(Fixture.tearDown, self)
        self.monitor = self.app.state.apify_monitor
        self.pool = self.app.state.apify_pool
        self.pool.add('fixture-pool-label', TOKEN)
        r = self.a.post('/api/intelligence/apify/accounts', headers=HEADERS, json={'handle': HANDLE})
        self.assertEqual(r.status_code, 200, r.text)
        self.account = r.json()['id']
        self.path = self.hub.directory / 'logs' / 'apify-submit.jsonl'

    @contextmanager
    def upstream(self, reply):
        seen = []

        def handle(request):
            seen.append(request)
            self.assertEqual(request.url.host, 'api.apify.com')
            self.assertEqual(request.headers.get('Authorization'), 'Bearer ' + TOKEN)
            if request.method == 'POST':
                self.assertEqual(request.url.path, '/v2/acts/clockworks~tiktok-scraper/runs')
            return reply(request)

        def client(**options):
            return CLIENT(transport=httpx.MockTransport(handle), **options)

        with patch('apify_monitor.httpx.Client', side_effect=client):
            yield seen

    def run_row(self, rid):
        with self.hub.db() as db:
            return dict(db.execute('SELECT state,remote_id,error FROM apify_runs WHERE id=?', (rid,)).fetchone())

    def events(self, local_id):
        text = self.path.read_text(encoding='utf-8')
        for sentinel in (TOKEN, HANDLE, RAW, REMOTE, DATASET, 'fixture-pool-label', 'api.apify.com', 'Authorization', 'Bearer '):
            self.assertNotIn(sentinel, text)
        events = [row for line in text.splitlines() if (row := json.loads(line))['local_id'] == local_id]
        self.assertTrue(events)
        for event in events:
            self.assertLessEqual(set(event), {'at_utc', 'kind', 'local_id', 'event', 'stage', 'dispatch_started', 'http_status', 'has_run_id', 'error_type', 'sqlite_error'})
        return events

    def failed(self, rid, stage, error_type, status=None, dispatch=True, has_id=False):
        events = self.events(rid)
        last = events[-1]
        self.assertEqual(last['event'], 'failed')
        self.assertEqual(last['stage'], stage)
        self.assertIs(last['dispatch_started'], dispatch)
        self.assertEqual(last['http_status'], status)
        self.assertIs(last['has_run_id'], has_id)
        self.assertEqual(last['error_type'], error_type)
        self.assertNotIn('run_id_saved', [e['event'] for e in events])
        return last

    def fail_single(self, reply, **expected):
        rid = self.monitor.queue(self.account)
        with self.upstream(reply) as seen:
            self.monitor.tick()
            self.monitor.tick()  # No repeat even when the returned result is ambiguous.
        self.assertEqual([r.method for r in seen], ['POST'])
        self.assertEqual((self.run_row(rid)['state'], self.run_row(rid)['remote_id']), ('attention', None))
        return rid, self.failed(rid, **expected)

    def test_key_selection_failed_before_any_send(self):
        rid = self.monitor.queue(self.account)
        with patch.object(self.pool, 'token', side_effect=sqlite3.OperationalError(RAW)), self.upstream(None) as seen:
            self.monitor.tick()
            self.monitor.tick()
        self.assertEqual(seen, [])
        self.failed(rid, 'select_key', 'OperationalError', dispatch=False)
        self.assertEqual(self.run_row(rid)['state'], 'attention')

    def test_client_construction_failure_never_reaches_dispatch(self):
        rid = self.monitor.queue(self.account)
        # Exercise HTTPX's real client initialization with a synthetic malformed proxy.
        with patch('httpx._client.get_environment_proxies', return_value={'https://': 'http://proxy.invalid:bad-port'}) as proxies, \
             patch.object(httpx.HTTPTransport, 'handle_request', side_effect=AssertionError('Unexpected network')) as transport:
            self.monitor.tick()
            self.monitor.tick()
        proxies.assert_called_once()
        transport.assert_not_called()
        self.failed(rid, 'init_client', 'InvalidURL', dispatch=False)
        self.assertNotIn('bad-port', self.path.read_text(encoding='utf-8'))
        self.assertEqual(self.run_row(rid)['state'], 'attention')

    def test_transport_failure_has_no_response_and_no_retry(self):
        def reply(request):
            raise httpx.ConnectError(RAW, request=request)

        rid, _ = self.fail_single(reply, stage='transport', error_type='ConnectError')
        self.assertEqual([e['event'] for e in self.events(rid)], ['started', 'dispatch_started', 'failed'])

    def test_http_error_retained_and_existing_pool_handling_unchanged(self):
        self.pool.add('fixture-fallback', 'fixture-fallback-token')
        # The normal selector prefers the first key for this fixture; both are enabled.
        with self.hub.db() as db:
            db.execute("UPDATE apify_keys SET usage=0,limit_usd=10 WHERE name='fixture-pool-label'")
        rid, _ = self.fail_single(lambda _: httpx.Response(402, text=RAW), stage='check_http_status', error_type='ValueError', status=402)
        self.assertEqual(self.run_row(rid)['error'], 'Apify 额度不足')
        with self.hub.db() as db:
            self.assertEqual(db.execute('SELECT k.state FROM apify_keys k JOIN apify_key_bindings b ON b.key_id=k.id WHERE b.run=?', ('run:' + rid,)).fetchone()[0], 'exhausted')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM apify_key_bindings').fetchone()[0], 1)

    def test_http_status_is_not_lost_if_pool_status_storage_fails(self):
        with patch.object(self.pool, 'mark', side_effect=sqlite3.OperationalError(RAW)):
            self.fail_single(lambda _: httpx.Response(429, text=RAW), stage='update_key_status', error_type='OperationalError', status=429)

    def test_response_read_timeout_keeps_http_status(self):
        self.fail_single(lambda _: httpx.Response(201, stream=ReadTimeoutBody()), stage='read_response', error_type='ReadTimeout', status=201)

    def test_invalid_json_envelope_and_missing_run_id_are_distinct(self):
        scenarios = [
            (httpx.Response(201, text=RAW), 'decode_json', 'JSONDecodeError'),
            (httpx.Response(201, json={'unexpected': RAW}), 'validate_response', 'KeyError'),
            (httpx.Response(201, json={'data': []}), 'validate_response', 'TypeError'),
            (httpx.Response(201, json={'data': {'error': RAW}}), 'validate_run_id', 'ValueError'),
        ]
        for response, stage, error_type in scenarios:
            with self.subTest(stage=stage, error_type=error_type):
                self.fail_single(lambda _: response, stage=stage, error_type=error_type, status=201)

    def test_automatic_script_recheck_uses_submission_diagnostics(self):
        for path, data in (
            ('/api/intelligence/apify/config', {'secret_key': TOKEN}),
            ('/api/intelligence/apify/accounts/' + self.account + '/selection', {'selected': True}),
            ('/api/intelligence/scripts/automation', {'enabled': True, 'recheck': True, 'transcribe': False, 'confirm_automation': True}),
        ):
            r = self.a.post(path, headers=HEADERS, json=data)
            self.assertEqual(r.status_code, 200, r.text)
        self.monitor.ingest({'id': 'fixture-seed', 'account': self.account}, [
            {'id': '123456789', 'authorMeta': {'name': HANDLE}, 'createTime': time.time()-3600, 'playCount': 100},
        ])
        automation = self.app.state.script_automation
        automation.scan()
        with self.hub.db() as db:
            db.execute('UPDATE script_rechecks SET due=? WHERE stage=2', (time.time()-1,))
        automation.recheck_tick()
        with self.hub.db() as db:
            rid = db.execute('SELECT run FROM script_rechecks WHERE account=? AND stage=2', (self.account,)).fetchone()[0]
        self.assertEqual(self.run_row(rid)['state'], 'queued')
        with self.upstream(lambda _: httpx.Response(201, json={'unexpected': RAW})) as seen:
            self.monitor.tick()
            automation.scan()
            automation.recheck_tick()
            self.monitor.tick()
        self.assertEqual([r.method for r in seen], ['POST'])
        self.assertEqual(self.run_row(rid)['state'], 'attention')
        self.assertEqual(self.failed(rid, 'validate_response', 'KeyError', 201)['kind'], 'run')

    def test_sqlite_failure_after_remote_id_is_recorded_but_not_replayed(self):
        with self.hub.db() as db:
            db.execute("""CREATE TRIGGER reject_fixture_remote BEFORE UPDATE OF remote_id ON apify_runs
                        WHEN NEW.remote_id IS NOT NULL BEGIN SELECT RAISE(ABORT, 'do-not-log-this-body-or-exception'); END""")
        rid, last = self.fail_single(lambda _: httpx.Response(201, json={'data': {'id': REMOTE}}),
                                     stage='persist_run_id', error_type='IntegrityError', status=201, has_id=True)
        self.assertEqual(last['sqlite_error'], 'SQLITE_CONSTRAINT_TRIGGER')
        self.assertIn('run_id_received', [e['event'] for e in self.events(rid)])

    def test_group_commit_and_polling_do_not_add_submission_events(self):
        batch = self.a.post('/api/intelligence/apify/batch', headers=HEADERS, json={'accounts': [self.account], 'allow_paid': True}).json()['batch']

        def reply(request):
            if request.method == 'POST':
                self.assertEqual(request.url.params['maxTotalChargeUsd'], '10.0')
                return httpx.Response(201, json={'data': {'id': REMOTE}})
            if '/actor-runs/' in request.url.path:
                return httpx.Response(200, json={'data': {'status': 'SUCCEEDED', 'defaultDatasetId': DATASET}})
            self.assertIn('/datasets/', request.url.path)
            return httpx.Response(200, json=[])

        with self.upstream(reply) as seen:
            self.monitor.group_tick()
            events = self.events(batch)
            self.monitor.group_tick()
            self.assertFalse(self.monitor.group_tick())
        self.assertEqual([r.method for r in seen], ['POST', 'GET', 'GET'])
        self.assertEqual(events, self.events(batch))
        self.assertEqual([e['event'] for e in events], ['started', 'dispatch_started', 'http_response', 'run_id_received', 'run_id_saved'])
        self.assertTrue(all(e['kind'] == 'group' for e in events))
        with self.hub.db() as db:
            self.assertEqual(tuple(db.execute('SELECT state,remote_id FROM grouped_runs WHERE id=?', (batch,)).fetchone()), ('ready', REMOTE))

    def test_case_uses_same_diagnostics_and_validates_id(self):
        base = '/api/intelligence/cases'
        cid = self.a.post(base, headers=HEADERS, json={'urls': ['https://www.tiktok.com/@fixture/video/123456789']}).json()['items'][0]['id']
        job = self.a.post(f'{base}/{cid}/process', headers=HEADERS, json={'kind': 'metadata', 'confirm': True, 'request_key': 'diag-case-fixture'}).json()['id']
        cases = self.app.state.video_cases
        with self.upstream(lambda _: httpx.Response(201, json={'data': {'id': 'bad!id', 'error': RAW}})) as seen:
            cases.tick('media')
            cases.tick('media')
        self.assertEqual([r.method for r in seen], ['POST'])
        last = self.failed(job, 'validate_run_id', 'ValueError', 201)
        self.assertEqual(last['kind'], 'case')
        self.assertNotIn('bad!id', self.path.read_text(encoding='utf-8'))

    def test_log_write_failure_does_not_interrupt_submission(self):
        rid = self.monitor.queue(self.account)
        with patch('apify_submit_diagnostics._append', side_effect=PermissionError(RAW)), self.assertLogs('apify_submit_diagnostics', 'WARNING') as warnings:
            with self.upstream(lambda _: httpx.Response(201, json={'data': {'id': REMOTE}})) as seen:
                self.monitor.tick()
        self.assertEqual(len(seen), 1)
        self.assertEqual((self.run_row(rid)['state'], self.run_row(rid)['remote_id']), ('running', REMOTE))
        self.assertIn('run_id_saved', warnings.output[-1])
        self.assertNotIn(RAW, '\n'.join(warnings.output))


class JournalTests(unittest.TestCase):
    def test_rotation_is_bounded_and_retains_complete_records(self):
        with tempfile.TemporaryDirectory() as tmp, patch('apify_submit_diagnostics._MAX_BYTES', 750):
            directory = Path(tmp)
            for i in range(1, 9):
                with SubmissionTrace(directory, 'run:' + f'{i:032x}') as trace:
                    trace.received_run_id()
                    trace.saved()
            path = directory / 'logs' / 'apify-submit.jsonl'
            self.assertEqual({f.name for f in path.parent.iterdir()}, {path.name, path.name + '.1'})
            for p in path.parent.iterdir():
                data = p.read_bytes()
                self.assertLessEqual(len(data), 750)
                self.assertTrue(data.endswith(b'\n'))
                self.assertTrue(all(json.loads(line)['kind'] == 'run' for line in data.splitlines()))
            self.assertEqual(json.loads(path.read_bytes().splitlines()[-1])['event'], 'run_id_saved')


if __name__ == '__main__':
    unittest.main()
