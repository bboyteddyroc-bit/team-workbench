import shutil
import unittest
from urllib.parse import quote

from editor import probe, run
from test_editor import EditorTests
import test_hub as fixtures


class AudioFormatTests(unittest.TestCase):
    """Audio assets beyond MP3/WAV: the editor drops them in as m4a/aac/ogg/flac."""

    setUp = EditorTests.setUp
    tearDown = EditorTests.tearDown
    login = EditorTests.login
    account = EditorTests.account
    enqueue = EditorTests.enqueue
    sample = EditorTests.sample

    def tone(self, name, *codec):
        path = self.hub.directory / name
        run([shutil.which('ffmpeg'), '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1.2', *codec, str(path)])
        return path

    def upload(self, path, mime, name=None):
        return self.member.post('/api/assets', content=path.read_bytes(), headers={**fixtures.H, 'Content-Type': mime, 'X-File-Name': quote(name or path.name)})

    def test_m4a_upload_and_timeline_track(self):
        path = self.tone('tone.m4a', '-c:a', 'aac', '-b:a', '96k')
        response = self.upload(path, 'audio/mp4', '录音.m4a')
        self.assertEqual(response.status_code, 200, response.text)
        asset = response.json()
        self.assertEqual(asset['mime'], 'audio/mp4')
        self.assertEqual(probe(self.hub.assets / asset['id'])[0] > 1, True)
        body = {'clips': [], 'captions': [], 'audio_clips': [{'source': 'asset', 'asset_id': asset['id'], 'start': 0, 'end': 1.2, 'at': .5, 'volume': 1, 'locked': False, 'track': 'audio-0'}]}
        saved = self.member.post('/api/editor/projects', json={'title': 'M4A', 'body': body}, headers=fixtures.H)
        self.assertEqual(saved.status_code, 200, saved.text)
        clip = saved.json()['body']['audio_clips'][0]
        self.assertEqual(clip['track'], 'audio-0')
        tracks = [t['id'] for t in saved.json()['body']['tracks']]
        self.assertIn('audio-0', tracks)

    def test_empty_mime_falls_back_to_extension_mime(self):
        path = self.tone('tone.ogg', '-c:a', 'libvorbis')
        self.assertEqual(self.upload(path, 'audio/ogg').status_code, 200)

    def test_rejects_fake_audio_payload(self):
        response = self.member.post('/api/assets', content=b'not audio at all', headers={**fixtures.H, 'Content-Type': 'audio/mp4', 'X-File-Name': 'fake.m4a'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('音频', response.json()['detail'])

    def test_m4a_export_mixes_audio(self):
        path = self.tone('mix.m4a', '-c:a', 'aac', '-b:a', '96k')
        asset = self.upload(path, 'audio/mp4').json()
        body = {'clips': [], 'captions': [], 'audio_clips': [{'source': 'asset', 'asset_id': asset['id'], 'start': 0, 'end': 1.2, 'at': 0, 'volume': 1, 'locked': False}]}
        saved = self.member.post('/api/editor/projects', json={'title': 'M4A export', 'body': body}, headers=fixtures.H).json()
        job = self.member.post('/api/editor/projects/' + saved['id'] + '/export', json={'version': saved['version'], 'request_key': 'm4a-export-000001'}, headers=fixtures.H)
        self.assertEqual(job.status_code, 200, job.text)
        self.app.state.editor.tick()
        result = next(j for j in self.member.get('/api/editor/exports').json() if j['id'] == job.json()['id'])
        self.assertEqual(result['state'], 'ready', result)
        self.assertAlmostEqual(probe(self.app.state.editor.root / (result['id'] + '.mp4'))[0], 1.2, delta=.15)


if __name__ == '__main__':
    unittest.main()
