"""voice.py + aivoice_editor.py 的隔离集成测试。

不联网、不写生产 state：用临时目录建一个最小 Hub 替身。
运行：python -B -m unittest test_voice -v
"""
import json
import os
import shutil
import sqlite3
import tempfile
import time
import types
import unittest

import aivoice_editor as ave
import fishaudio as fa
import voice as vo


class Cipher:
    def encrypt(self, b):
        return b[::-1]

    def decrypt(self, b):
        return b[::-1]


class FakeHub:
    def __init__(self, root):
        self.directory = __import__('pathlib').Path(root)
        self.path = os.path.join(root, 'hub.sqlite3')
        self.cipher = Cipher()
        self.stop = None

    def db(self):
        import contextlib

        @contextlib.contextmanager
        def cm():
            c = sqlite3.connect(self.path, timeout=10)
            c.row_factory = sqlite3.Row
            try:
                with c:
                    yield c
            finally:
                c.close()
        return cm()

    def log(self, db, actor, action, target):
        pass


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='voicetest-')
        self.hub = FakeHub(self.tmp)
        with self.hub.db() as db:
            db.execute("CREATE TABLE users(id TEXT PRIMARY KEY, role TEXT, enabled INTEGER DEFAULT 1)")
            db.execute("INSERT INTO users(id,role,enabled) VALUES('u1','member',1)")
            db.execute("INSERT INTO users(id,role,enabled) VALUES('a1','admin',1)")
        self.v = vo.Voice(self.hub)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestSettings(Base):
    def test_default_unconfigured(self):
        s = self.v.settings()
        self.assertFalse(s['enabled'])
        self.assertFalse(s['has_key'])

    def test_configure_and_redact(self):
        self.v.configure('a1', api_key='secret-key', model='s2.1-pro', fmt='wav', enabled=True)
        s = self.v.settings()
        self.assertTrue(s['enabled'])
        self.assertTrue(s['has_key'])
        # 接口返回不得包含密钥本身
        self.assertNotIn('secret-key', json.dumps(s))

    def test_key_encrypted_at_rest(self):
        self.v.configure('a1', api_key='plain-secret', enabled=True)
        with self.hub.db() as db:
            blob = db.execute('SELECT api_key FROM voice_settings').fetchone()['api_key']
        self.assertNotIn(b'plain-secret', bytes(blob))

    def test_reject_bad_model(self):
        with self.assertRaises(ValueError):
            self.v.configure('a1', model='nope')

    def test_submit_blocked_without_key(self):
        with self.assertRaises(Exception):
            self.v.submit('u1', 'k1', {'text': 'hi', 'voice_id': 'x'})


class TestVoices(Base):
    def test_placeholder_voice_not_usable(self):
        vs = self.v.voices('u1')
        self.assertTrue(all(not v['usable'] for v in vs if not v['reference_id']))

    def test_admin_creates_voice(self):
        vid = self.v.save_voice('a1', {'name': '女声 A', 'reference_id': 'ref-abc',
                                       'language': 'zh-CN', 'style': '温暖'})
        vs = {v['id']: v for v in self.v.voices('u1')}
        self.assertIn(vid, vs)
        self.assertTrue(vs[vid]['usable'])
        self.assertEqual(vs[vid]['reference_id'], 'ref-abc')

    def test_voice_without_reference_hidden_from_members(self):
        vid = self.v.save_voice('a1', {'name': '空 ID', 'reference_id': '', 'enabled': True})
        ids = {v['id'] for v in self.v.voices('u1')}
        self.assertNotIn(vid, ids)
        ids_admin = {v['id'] for v in self.v.voices('a1', include_disabled=True)}
        self.assertIn(vid, ids_admin)

    def test_favorite_toggle(self):
        vid = self.v.save_voice('a1', {'name': 'V', 'reference_id': 'r1'})
        self.assertTrue(self.v.toggle_favorite('u1', vid))
        vs = {v['id']: v for v in self.v.voices('u1')}
        self.assertTrue(vs[vid]['favorite'])
        self.assertFalse(self.v.toggle_favorite('u1', vid))
        vs = {v['id']: v for v in self.v.voices('u1')}
        self.assertFalse(vs[vid]['favorite'])

    def test_favorite_is_per_user(self):
        vid = self.v.save_voice('a1', {'name': 'V', 'reference_id': 'r1'})
        self.v.toggle_favorite('u1', vid)
        v2 = {v['id']: v for v in self.v.voices('a1')}
        self.assertFalse(v2[vid]['favorite'])


class TestJobs(Base):
    def setUp(self):
        super().setUp()
        self.v.configure('a1', api_key='k', model='s2.1-pro', fmt='wav', enabled=True)
        self.vid = self.v.save_voice('a1', {'name': 'V', 'reference_id': 'ref-1'})

    def test_submit_idempotent_by_request_key(self):
        a = self.v.submit('u1', 'req-1', {'text': '你好', 'voice_id': self.vid})
        b = self.v.submit('u1', 'req-1', {'text': '你好', 'voice_id': self.vid})
        self.assertEqual(a['id'], b['id'])
        self.assertEqual(len(self.v.jobs('u1', False)), 1)

    def test_member_cannot_read_others_job(self):
        a = self.v.submit('u1', 'r1', {'text': 'x', 'voice_id': self.vid})
        with self.assertRaises(ValueError):
            self.v.job('someone-else', False, a['id'])
        # 音色库共享，成员配音任务仍属于成员本人。
        with self.assertRaises(ValueError):
            self.v.job('a1', True, a['id'])

    def test_recover_marks_running_failed_no_retry(self):
        a = self.v.submit('u1', 'r1', {'text': 'x', 'voice_id': self.vid})
        with self.hub.db() as db:
            db.execute("UPDATE voice_jobs SET state='running' WHERE id=?", (a['id'],))
        self.v.recover()
        j = self.v.job('u1', False, a['id'])
        self.assertEqual(j['state'], 'failed')
        self.assertIn('重新生成', j['error'])

    def test_no_audio_url_when_not_ready(self):
        a = self.v.submit('u1', 'r1', {'text': 'x', 'voice_id': self.vid})
        self.assertEqual(a['audio_url'], '')

    def test_unconfigured_voice_rejected(self):
        vid2 = self.v.save_voice('a1', {'name': 'no-ref', 'reference_id': '', 'enabled': True})
        with self.assertRaises(ValueError):
            self.v.submit('u1', 'r9', {'text': 'x', 'voice_id': vid2})


class TestCollectedJobFlow(Base):
    """模拟一次完整的事件流 → 落库，不联网。"""

    def setUp(self):
        super().setUp()
        self.v.configure('a1', api_key='k', model='s2.1-pro', fmt='wav', enabled=True)
        self.vid = self.v.save_voice('a1', {'name': 'V', 'reference_id': 'ref-1'})

    def test_collector_produces_captions(self):
        c = fa.StreamCollector()
        c.feed_event({'audio_base64': '', 'chunk_seq': 0, 'chunk_audio_offset_sec': 0.0,
                      'content': '你好，世界。',
                      'alignment': {'audio_duration': 2.0, 'segments': [
                          {'text': '你好，', 'start': 0.0, 'end': 1.0},
                          {'text': '世界。', 'start': 1.0, 'end': 2.0}]}})
        self.assertTrue(c.has_alignment())
        rows = fa.group_into_captions(c.timeline())
        self.assertGreaterEqual(len(rows), 1)
        self.assertEqual(rows[0]['start'], 0.0)

    def test_null_alignment_yields_no_captions(self):
        c = fa.StreamCollector()
        c.feed_event({'audio_base64': '', 'chunk_seq': 0, 'alignment': None})
        self.assertFalse(c.has_alignment())
        self.assertEqual(fa.group_into_captions(c.timeline()), [])


class TestEditorBridge(unittest.TestCase):
    def test_legacy_clip_without_source(self):
        src, key, rest = ave.normalize_audio_clip({'task_id': 't1', 'start': 1, 'end': 2})
        self.assertEqual(src, 'video')
        self.assertEqual(key, 't1')

    def test_voice_clip(self):
        src, key, rest = ave.normalize_audio_clip({'source': 'voice', 'voice_job_id': 'j1',
                                                   'at': 3, 'volume': .8})
        self.assertEqual(src, 'voice')
        self.assertEqual(key, 'j1')
        self.assertEqual(rest['at'], 3)

    def test_bad_source(self):
        with self.assertRaises(ValueError):
            ave.normalize_audio_clip({'source': 'bogus'})

    def test_merge_append_keeps_manual(self):
        existing = [{'text': '手动', 'start': 0, 'end': 1}]
        incoming = [{'text': '配音', 'start': 2, 'end': 3, 'voice_job_id': 'j1'}]
        out = ave.merge_captions(existing, incoming, 'append')
        self.assertEqual(len(out), 2)

    def test_merge_replace_only_removes_same_voice(self):
        existing = [{'text': '手动', 'start': 0, 'end': 1},
                    {'text': '旧配音', 'start': 2, 'end': 3, 'voice_job_id': 'j1'}]
        incoming = [{'text': '新配音', 'start': 2, 'end': 3, 'voice_job_id': 'j1'}]
        out = ave.merge_captions(existing, incoming, 'replace')
        texts = [c['text'] for c in out]
        self.assertIn('手动', texts)
        self.assertIn('新配音', texts)
        self.assertNotIn('旧配音', texts)

    def test_shift_linked_captions(self):
        caps = [{'text': 'a', 'start': 1, 'end': 2, 'voice_job_id': 'j1'},
                {'text': 'b', 'start': 5, 'end': 6}]
        out = ave.shift_captions(caps, 'j1', 2.0)
        self.assertEqual(out[0]['start'], 3.0)
        self.assertEqual(out[1]['start'], 5.0)   # 无关联不动

    def test_captions_to_voice_offset(self):
        rows = ave.captions_to_voice([{'text': 'x', 'start': 0, 'end': 1}], 4.0)
        self.assertEqual(rows[0]['start'], 4.0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
