"""Temporary, server-local speech-to-text for the signed-in assistant."""
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import BoundedSemaphore

from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool

import asr


DURATION = 60
MAX_BYTES = 1536 * 1024
FORMATS = {'audio/webm': 'matroska', 'audio/ogg': 'ogg', 'audio/mp4': 'mov'}
_slot = BoundedSemaphore(1)


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
            language, segments = asr.transcribe(audio, local_only=True)
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


def attach(app, user):
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
