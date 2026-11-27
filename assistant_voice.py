"""Temporary, server-local speech-to-text for the signed-in assistant."""
import json
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import BoundedSemaphore

from fastapi import HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

import asr


DURATION = 60
MAX_BYTES = 1536 * 1024
FORMATS = {'audio/webm': 'matroska', 'audio/ogg': 'ogg', 'audio/mp4': 'mov'}
_slot = BoundedSemaphore(1)
_speech_slot = BoundedSemaphore(2)
MAX_SPEECH_CHARS = 3600


def ready():
    try:
        return (asr.model_dir() / 'model.bin').is_file() and asr.available()
    except OSError:
        return False


def recognize(data, container):
    with TemporaryDirectory(prefix='hub-dictation-') as directory:
        audio = Path(directory) / 'voice.wav'
        recorded = Path(directory) / 'recording'
        recorded.write_bytes(data)
        try:
            asr._ffmpeg(['ffmpeg', '-hide_banner', '-nostdin', '-loglevel', 'error',
                         '-protocol_whitelist', 'file,pipe', '-f', container, '-i', recorded,
                         '-map', '0:a:0', '-vn', '-ac', '1', '-ar', '16000',
                         '-c:a', 'pcm_s16le', '-t', str(DURATION), audio], timeout=15)
        except ValueError:
            raise HTTPException(422, '录音无法读取，请重新录音') from None
        if audio.stat().st_size <= 128:
            raise HTTPException(422, '没有录到可识别的语音')
        try:
            language, segments = asr.transcribe(audio, local_only=True, word_timestamps=False)
        except ValueError:
            raise HTTPException(503, '本地语音识别暂不可用，请稍后重试') from None
        text = ' '.join(segment['text'] for segment in segments)
        if language in ('zh', 'ja'):
            text = ''
            for segment in segments:
                text = asr._join(text, segment['text'])
        if not text.strip():
            raise HTTPException(422, '没有识别到语音，请靠近麦克风后再试')
        return text.strip()


# Text goes through UTF-8 stdin, never into the PowerShell command.
_WINDOWS_SPEECH = r"""
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
$data = [Console]::In.ReadToEnd() | ConvertFrom-Json
Add-Type -AssemblyName System.Speech
$speaker = [System.Speech.Synthesis.SpeechSynthesizer]::new()
try {
    $voice = $speaker.GetInstalledVoices() | Where-Object {
        $_.Enabled -and $_.VoiceInfo.Culture.TwoLetterISOLanguageName -eq $data.language
    } | Select-Object -First 1
    if (-not $voice) { exit 3 }
    $speaker.SelectVoice($voice.VoiceInfo.Name)
    $audio = [IO.MemoryStream]::new()
    try {
        $speaker.SetOutputToWaveStream($audio)
        $speaker.Speak([string]$data.text)
        $output = [Console]::OpenStandardOutput()
        $audio.WriteTo($output)
        $output.Flush()
    } finally { $audio.Dispose() }
} finally { $speaker.Dispose() }
"""


def synthesize(text, language):
    if os.name != 'nt':
        raise HTTPException(503, '中台没有可用的 Windows 朗读服务')
    powershell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe'
    try:
        result = subprocess.run(
            [str(powershell), '-NoProfile', '-NonInteractive', '-Command', _WINDOWS_SPEECH],
            input=json.dumps({'text': text, 'language': language}, ensure_ascii=False).encode('utf-8'),
            capture_output=True, timeout=25, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        raise HTTPException(503, '中台朗读暂不可用，可继续查看文字') from None
    if result.returncode == 3:
        raise HTTPException(503, '中台缺少所需语言的本地音色，可继续查看文字')
    if result.returncode or not result.stdout.startswith(b'RIFF'):
        raise HTTPException(503, '中台朗读失败，可继续查看文字')
    return result.stdout

def attach(app, user, body):
    @app.post('/api/assistant/speech')
    async def speech(request: Request):
        user(request)
        data = await body(request)
        text = data.get('text')
        language = data.get('language')
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_SPEECH_CHARS or language not in ('zh', 'en'):
            raise HTTPException(400, '朗读内容或语言无效')
        if not _speech_slot.acquire(blocking=False):
            raise HTTPException(429, '中台正在朗读，请稍后再试')
        try:
            audio = await run_in_threadpool(synthesize, text, language)
        finally:
            _speech_slot.release()
        return Response(audio, media_type='audio/wav', headers={'Cache-Control': 'no-store'})
    @app.post('/api/assistant/dictation')
    async def dictation(request: Request):
        user(request)
        mime = request.headers.get('content-type', '').split(';', 1)[0].strip().lower()
        if mime not in FORMATS:
            raise HTTPException(415, '当前录音格式不受支持')
        data = await request.body()
        if not data:
            raise HTTPException(400, '没有收到录音')
        if len(data) > MAX_BYTES:
            raise HTTPException(413, '录音太长，请分段输入')
        if not ready():
            raise HTTPException(503, '中台本地语音识别模型未就绪')
        if not _slot.acquire(blocking=False):
            raise HTTPException(429, '中台正在识别另一段语音，请稍后再试')
        try:
            text = await run_in_threadpool(recognize, data, FORMATS[mime])
        finally:
            _slot.release()
        return {'text': text}
