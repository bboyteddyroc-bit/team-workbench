import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import test_hub as fixtures


class AssistantVoiceTests(unittest.TestCase):
    setUp = fixtures.HubTests.setUp
    tearDown = fixtures.HubTests.tearDown
    login = fixtures.HubTests.login

    def post(self, client, content=b'recording', mime='audio/webm;codecs=opus'):
        return client.post('/api/assistant/dictation', content=content,
                           headers={**fixtures.H, 'Content-Type': mime})

    def test_dictation_requires_login_and_does_not_create_chat_history(self):
        with patch('assistant_voice.ready', return_value=True), patch(
            'assistant_voice.recognize', return_value='检查素材库'
        ) as recognize:
            with TestClient(self.app, base_url=fixtures.BASE) as anonymous:
                self.assertEqual(self.post(anonymous).status_code, 401)
            self.assertEqual(self.post(self.member, mime='text/plain').status_code, 415)
            self.assertEqual(self.post(self.member, content=b'').status_code, 400)
            self.assertEqual(self.post(self.member).json(), {'text': '检查素材库'})
            recognize.assert_called_once_with(b'recording', 'matroska')
        self.assertEqual(self.member.get('/api/assistant/threads').json(), [])

    def test_speech_requires_login_and_serves_local_wav(self):
        with patch('assistant_voice.synthesize', return_value=b'RIFF-test') as synthesize:
            path = '/api/assistant/speech'
            with TestClient(self.app, base_url=fixtures.BASE) as anonymous:
                self.assertEqual(anonymous.post(path, json={'text': 'Hello', 'language': 'en'}, headers=fixtures.H).status_code, 401)
            self.assertEqual(self.member.post(path, json={'text': 'Hello', 'language': 'xx'}, headers=fixtures.H).status_code, 400)
            response = self.member.post(path, json={'text': 'Hello', 'language': 'en'}, headers=fixtures.H)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['Content-Type'], 'audio/wav')
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            self.assertEqual(response.content, b'RIFF-test')
            synthesize.assert_called_once_with('Hello', 'en')

    def test_recording_is_removed_after_local_transcription(self):
        from assistant_voice import recognize

        with tempfile.TemporaryDirectory() as root:
            recorded = []

            def convert(args, **kwargs):
                output = args[-1]
                self.assertEqual(output.parent.joinpath('recording').read_bytes(), b'voice')
                output.write_bytes(b'x' * 256)
                recorded.append(output.parent)

            with patch('assistant_voice.TemporaryDirectory', side_effect=lambda **kwargs: tempfile.TemporaryDirectory(dir=root, **kwargs)), patch(
                'asr._ffmpeg', side_effect=convert
            ), patch('asr.transcribe', return_value=('en', [{'text': 'Hello.'}, {'text': 'Test next.'}])) as transcribe:
                self.assertEqual(recognize(b'voice', 'matroska'), 'Hello. Test next.')
                transcribe.assert_called_once_with(Path(recorded[0]) / 'voice.wav', local_only=True, word_timestamps=False)
            self.assertFalse(recorded[0].exists())
