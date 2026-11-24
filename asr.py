"""Local speech recognition and subtitle translation for the editor.

Recognition runs offline on the machine that hosts the hub: the mixed timeline
audio is rendered to 16 kHz mono with FFmpeg and transcribed by faster-whisper.
Translation is optional and goes through the same A6API Gemini 3.8 Flash chat gateway the rest of
the hub uses; it never runs when the audio itself is transcribed.
"""
import json
import os
import re
import shutil
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

MODEL_ROOT = Path(__file__).parent / 'state' / 'models'
LANGUAGES = {
    'zh': '中文', 'en': '英文', 'ja': '日语', 'ko': '韩语', 'es': '西班牙语', 'pt': '葡萄牙语',
    'fr': '法语', 'de': '德语', 'th': '泰语', 'vi': '越南语', 'ru': '俄语', 'id': '印尼语', 'ar': '阿拉伯语',
}
MAX_SECONDS = 1200
_lock = threading.Lock()
_engines = {}


def model_name():
    return (os.getenv('HUB_ASR_MODEL') or 'small').strip()


def model_dir(name=None):
    return MODEL_ROOT / ('faster-whisper-' + (name or model_name()))


def available():
    """True when the engine package is installed. Never downloads anything."""
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def status():
    directory = model_dir()
    files = sorted(p.name for p in directory.glob('model.bin')) if directory.is_dir() else []
    return {
        'engine': 'faster-whisper',
        'installed': available(),
        'model': model_name(),
        'model_ready': bool(files),
        'languages': [{'id': k, 'label': v} for k, v in LANGUAGES.items()],
        'max_seconds': MAX_SECONDS,
    }


def engine(name=None):
    """Load and cache the local model. Raises ValueError with an actionable message."""
    name = name or model_name()
    if not available():
        raise ValueError('本机未安装语音识别引擎（faster-whisper），请联系管理员安装后再试')
    with _lock:
        if name in _engines:
            return _engines[name]
        from faster_whisper import WhisperModel
        directory = model_dir(name)
        try:
            if (directory / 'model.bin').is_file():
                created = WhisperModel(str(directory), device='cpu', compute_type='int8',
                                       cpu_threads=max(1, min(8, os.cpu_count() or 4)))
            else:
                created = WhisperModel(name, device='cpu', compute_type='int8',
                                       download_root=str(MODEL_ROOT),
                                       cpu_threads=max(1, min(8, os.cpu_count() or 4)))
        except Exception:
            raise ValueError('语音识别模型加载失败：本机还没有可用模型，请联系管理员下载后重试') from None
        _engines[name] = created
        return created


def _ffmpeg(args, timeout=1800):
    import subprocess
    try:
        done = subprocess.run([str(part) for part in args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=timeout,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError('音频提取超时，请缩短项目后重试') from None
    if done.returncode:
        detail = (done.stderr or b'').decode('utf-8', 'replace').strip().splitlines()
        reason = detail[-1][:120] if detail else '未知错误'
        raise ValueError(f'音频提取失败：{reason}')
    return done.stdout


def timeline_audio(editor, data, owner, admin, target):
    """Render the audible part of the timeline to a mono 16 kHz WAV."""
    from editor import atempo_chain, probe
    from multitrack import normalize, video_length
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise ValueError('执行机未找到 FFmpeg，无法提取音频')
    normalize(data, data)
    muted = {t['id'] for t in data.get('tracks', []) if t.get('muted')}
    args = [ffmpeg, '-v', 'error', '-y']
    filters = []
    labels = []
    index = 0
    silent = 0
    for clip in data['clips']:
        if clip['track'] in muted or not clip.get('volume'):
            continue
        try:
            path = editor.source(owner, admin, clip['task_id'])
            _, streams = probe(path)
        except ValueError:
            silent += 1
            continue
        if not any(s['codec_type'] == 'audio' for s in streams):
            silent += 1
            continue
        span = video_length(clip)
        args += ['-ss', str(clip['start']), '-t', str(clip['end'] - clip['start']), '-i', str(path)]
        chain = [f"atrim=duration={clip['end'] - clip['start']}", 'asetpts=PTS-STARTPTS']
        tempo = atempo_chain(clip.get('speed', 1))
        if tempo:
            chain.append(tempo)
        chain += [f"volume={clip['volume']}", f"adelay={round(clip['at'] * 1000)}:all=1"]
        filters.append(f"[{index}:a]" + ','.join(chain) + f"[a{index}]")
        labels.append(f'[a{index}]')
        index += 1
    sounds = [dict(s) for s in data.get('audio_clips', [])]
    if data.get('audio'):
        audio = data['audio']
        sounds.append(dict(source='asset', asset_id=audio['asset_id'], start=0, end=audio['duration'],
                           at=0, volume=audio['volume'], track=audio['track']))
    for sound in sounds:
        if sound.get('muted') or sound['track'] in muted or not sound.get('volume'):
            continue
        try:
            path = editor.audio_source(owner, admin, sound)
        except ValueError:
            silent += 1
            continue
        args += ['-i', str(path)]
        audio_filter = (f"atrim=start={sound['start']}:end={sound['end']},asetpts=PTS-STARTPTS,"
                        f"volume={sound['volume']}")
        if sound.get('fade_in'):
            audio_filter += f",afade=t=in:st=0:d={sound['fade_in']}"
        if sound.get('fade_out'):
            audio_filter += f",afade=t=out:st={sound['end'] - sound['start'] - sound['fade_out']}:d={sound['fade_out']}"
        filters.append(f"[{index}:a]{audio_filter},adelay={round(sound['at'] * 1000)}:all=1[a{index}]")
        labels.append(f'[a{index}]')
        index += 1
    if not labels:
        if silent:
            raise ValueError('时间轴上的片段都没有可识别的声音，请先加入配音或原声素材')
        raise ValueError('时间轴上没有可识别的音频：请先加入带声音的片段，或先做配音')
    filters.append(''.join(labels) + f'amix=inputs={len(labels)}:normalize=0[mix]')
    args += ['-filter_complex', ';'.join(filters), '-map', '[mix]', '-ac', '1', '-ar', '16000',
             '-c:a', 'pcm_s16le', str(target)]
    _ffmpeg(args)
    return target


def _limit(text):
    return 18 if re.search(r'[\u4e00-\u9fff]', text) else 42


def _hard(part, limit):
    """Cut an over-long run, preferring word boundaries so English stays readable."""
    out = []
    while len(part) > limit:
        cut = part.rfind(' ', 0, limit)
        if cut < limit // 2:
            cut = limit
        out.append(part[:cut].strip())
        part = part[cut:].strip()
    if part:
        out.append(part)
    return [piece for piece in out if piece]


def _split(text, limit):
    """Break a long transcript line on punctuation so subtitles stay readable."""
    if len(text) <= limit:
        return [text]
    pieces = re.findall(r'[^，。！？；、,.!?;…]+[，。！？；、,.!?;…]*', text) or [text]
    rows = []
    current = ''
    for piece in pieces:
        if len(piece) > limit:
            if current:
                rows.append(current)
                current = ''
            rows += _hard(piece, limit)
        elif len(current) + len(piece) > limit:
            rows.append(current)
            current = piece
        else:
            current += piece
    if current:
        rows.append(current)
    return [row.strip() for row in rows if row.strip()]


def _join(left, right):
    if not left:
        return right
    if re.search(r'[A-Za-z0-9]$', left) and re.match(r'[A-Za-z0-9]', right):
        return left + ' ' + right
    return left + right


def _meaningful(text):
    return bool(re.search(r'[0-9A-Za-z\u4e00-\u9fff]', text))


def sentence_groups(segments, limit=None):
    """Merge whisper fragments into whole sentences so translation sees complete meaning."""
    rows = [(segment['start'], segment['end'], (segment['text'] or '').strip()) for segment in segments]
    rows = [row for row in rows if row[2]]
    if not rows:
        return []
    limit = limit or max(90, _limit(''.join(row[2] for row in rows)) * 3)
    merged = []
    for start, end, text in rows:
        if merged:
            last = merged[-1]
            combined = _join(last['text'], text)
            if (len(combined) <= limit and start - last['end'] <= 1.2
                    and not re.search(r'[。！？.!?…]$', last['text'])):
                last['text'] = combined
                last['end'] = max(last['end'], end)
                continue
        merged.append({'start': start, 'end': end, 'text': text})
    return merged


def place_rows(groups):
    """Split each group into caption rows and spread its time span by text length."""
    result = []
    for group in groups:
        limit = _limit(group['text'])
        pieces = [piece for piece in _split(group['text'], limit) if _meaningful(piece)]
        total = sum(len(piece) for piece in pieces) or 1
        start = group['start']
        span = max(0.3, group['end'] - group['start'])
        for piece in pieces:
            share = span * len(piece) / total
            end = min(group['end'], start + share)
            result.append({'start': round(start, 2), 'end': round(max(start + 0.2, end), 2), 'text': piece})
            start = end
    return result


def timed_caption_rows(segments):
    """Keep genuine recognizer timings only where word text matches a caption exactly."""
    rows = place_rows(sentence_groups(segments))
    words = [word for segment in segments for word in segment.get('words', [])]
    cursor = 0
    for row in rows:
        matched = []
        pos = 0
        while cursor < len(words):
            word = words[cursor]
            token = word['text'].strip()
            at = row['text'].find(token, pos) if token else -1
            if at < 0:
                if matched or word['start'] >= row['end']:
                    break
                cursor += 1
                continue
            matched.append({'text': token, 'from': at, 'to': at + len(token),
                            'start': word['start'], 'end': word['end']})
            pos = at + len(token)
            cursor += 1
        if matched:
            row['start'] = min(row['start'], matched[0]['start'])
            row['end'] = max(row['end'], matched[-1]['end'])
            row['words'] = [{**w, 'start': round(w['start'] - row['start'], 3),
                             'end': round(w['end'] - row['start'], 3)} for w in matched]
    # Text-length estimates can overlap after rows are expanded to cover word timings.
    # Resolve only automatically generated adjacent rows, not user-edited/multitrack captions.
    for left, right in zip(rows, rows[1:]):
        if left['end'] <= right['start']:
            continue
        left_word_end = left['start'] + left['words'][-1]['end'] if left.get('words') else left['end']
        right_word_start = right['start'] + right['words'][0]['start'] if right.get('words') else right['start']
        boundary = round((left_word_end + right_word_start) / 2, 2)
        boundary = max(left['start'] + .01, min(right['end'] - .01, boundary))
        if not left['start'] < boundary < right['end']:
            continue
        old_right_start = right['start']
        left['end'] = boundary
        right['start'] = boundary
        for row, old_start in ((left, left['start']), (right, old_right_start)):
            span = row['end'] - row['start']
            adjusted = []
            for word in row.get('words', []):
                begin = max(0, round(old_start + word['start'] - row['start'], 3))
                end = min(span, round(old_start + word['end'] - row['start'], 3))
                if end > begin:
                    adjusted.append({**word, 'start': begin, 'end': round(end, 3)})
            if 'words' in row:
                row['words'] = adjusted
    return rows


def caption_rows(segments):
    """Merge fragments into sentence-sized captions, then split what is still long."""
    return place_rows(sentence_groups(segments))


ZH_PROMPT = '以下是普通话的句子，请用简体中文书写字幕。'


def transcribe(path, language=None):
    """Transcribe a wav file. Chinese is biased to Simplified output via a prompt."""
    from faster_whisper.audio import decode_audio
    created = engine()
    audio = decode_audio(str(path))
    if not language:
        detected, probability, _ = created.detect_language(audio, vad_filter=True)
        language = detected if probability >= 0.5 else None
    prompt = ZH_PROMPT if language == 'zh' else None
    segments, info = created.transcribe(audio, language=language, vad_filter=True, beam_size=5,
                                        condition_on_previous_text=False, initial_prompt=prompt,
                                        word_timestamps=True)
    rows = []
    for segment in segments:
        text = (segment.text or '').strip()
        if text:
            words = []
            raw_words = getattr(segment, 'words', None)
            if isinstance(raw_words, (list, tuple)):
                for word in raw_words:
                    token = (word.word or '').strip()
                    if token and word.end > word.start:
                        words.append({'text': token, 'start': round(word.start, 3), 'end': round(word.end, 3)})
            rows.append({'start': round(segment.start, 2), 'end': round(segment.end, 2), 'text': text, 'words': words})
    return info.language, rows


def _json_array(text):
    match = re.search(r'\[.*\]', text or '', re.S)
    if not match:
        raise ValueError('翻译返回的格式无法识别')
    data = json.loads(match.group(0))
    if not isinstance(data, list):
        raise ValueError('翻译返回的格式无法识别')
    return [str(item).strip() for item in data]


def configured_key(hub):
    """Return the stored A6API Gemini 3.8 Flash key, or an empty string when the hub has none."""
    try:
        with hub.db() as db:
            row = db.execute('SELECT secret FROM a6_settings WHERE id=1').fetchone()
    except Exception:
        return ''
    if not row or not row['secret']:
        return ''
    try:
        return hub.cipher.decrypt(row['secret']).decode().strip()
    except Exception:
        return ''


def translate(texts, target, key, timeout=120):
    """Translate one sentence per element. Returns exactly one string per input element."""
    from assistant_chat import ENDPOINT, MODEL
    if not key:
        raise ValueError('翻译需要在制作台配置 A6API Gemini 3.8 Flash API Key')
    label = LANGUAGES[target]
    result = []
    for start in range(0, len(texts), 12):
        batch = texts[start:start + 12]
        count = len(batch)
        prompt = (f'下面是一个 JSON 数组，共 {count} 条短视频字幕原文，每条可能是一句被切断的口语。'
                  f'请逐条翻译成{label}，必须输出 {count} 条，一条对一条，不能合并、拆分或省略。'
                  f'只输出 JSON 字符串数组，不要输出解释、编号或代码块标记；译文口语自然，'
                  f'不要添加原文没有的信息。\n' + json.dumps(batch, ensure_ascii=False))
        payload = {'model': MODEL, 'messages': [{'role': 'user', 'content': prompt}], 'max_tokens': 2000,
                   'temperature': 0, 'stream': False, 'chat_template_kwargs': {'enable_thinking': False}}
        rows = _translate_call(payload, key, timeout)
        if len(rows) != count:
            payload['messages'][0]['content'] = prompt + (
                f'\n上一次输出只有 {len(rows)} 条，不符合要求。请严格输出 {count} 条，一条不能少。')
            rows = _translate_call(payload, key, timeout)
        if len(rows) != count:
            raise ValueError(f'翻译结果条数（{len(rows)}）与原句条数（{count}）不一致，请重试或改用更短的片段')
        result += [text if text else batch[i] for i, text in enumerate(rows)]
    return result


def _translate_call(payload, key, timeout):
    from assistant_chat import ENDPOINT
    from a6_provider import build_request
    request = build_request(key,payload)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise ValueError('翻译失败：A6API Gemini 3.8 Flash API Key 无效或已过期，请在制作台重新配置') from None
        raise ValueError(f'翻译失败：A6API Gemini 3.8 Flash 接口返回 {exc.code}，未自动重试') from None
    except urllib.error.URLError:
        raise ValueError('翻译失败：无法连接 A6API Gemini 3.8 Flash 接口，未自动重试') from None
    try:
        return _json_array(data['choices'][0]['message']['content'])
    except ValueError:
        raise
    except Exception:
        raise ValueError('翻译返回的内容为空') from None


def recognize(editor, hub, data, owner, admin, language='auto', translate_to=''):
    """Transcribe the timeline audio, optionally translating into another language."""
    language = (language or 'auto').strip()
    translate_to = (translate_to or '').strip()
    if language != 'auto' and language not in LANGUAGES:
        raise ValueError('识别语种无效')
    if translate_to and translate_to != 'zh-en' and translate_to not in LANGUAGES:
        raise ValueError('翻译目标语种无效')
    if translate_to == language:
        raise ValueError('翻译目标语种不能与被识别语种相同')
    from editor import timeline_duration
    total = timeline_duration(data)
    if total <= 0:
        raise ValueError('时间轴上还没有内容')
    if total > MAX_SECONDS:
        raise ValueError(f'项目超过 {MAX_SECONDS // 60} 分钟，请分段后识别')
    key = ''
    if translate_to:
        key = configured_key(hub)
        if not key:
            raise ValueError('翻译需要先在制作台配置 A6API Gemini 3.8 Flash API Key')
    with tempfile.TemporaryDirectory(prefix='asr-', dir=editor.root) as temp:
        wav = Path(temp) / 'audio.wav'
        timeline_audio(editor, data, owner, admin, wav)
        detected, segments = transcribe(wav, None if language == 'auto' else language)
    groups = sentence_groups(segments)
    if not groups:
        raise ValueError('没有识别到可用的语音内容，请确认素材里有人声')
    if not translate_to:
        captions = timed_caption_rows(segments)
        for row in captions:
            row['lang'] = detected
        return {'language': detected, 'target': '', 'captions': captions}
    if translate_to == 'zh-en':
        original = [group['text'] for group in groups]
        # A Chinese or English source needs one translation; other source languages need both.
        chinese = original if detected == 'zh' else translate(original, 'zh', key)
        english = original if detected == 'en' else translate(original, 'en', key)
        captions = []
        for group, zh, en in zip(groups, chinese, english):
            for lang, text in (('zh', zh), ('en', en)):
                for row in place_rows([{'start': group['start'], 'end': group['end'], 'text': text}]):
                    row['lang'] = lang
                    captions.append(row)
        if not captions:
            raise ValueError('翻译结果为空，请重试')
        return {'language': detected, 'target': 'zh-en', 'captions': captions}
    translated = translate([group['text'] for group in groups], translate_to, key)
    captions = []
    for group, text in zip(groups, translated):
        rows = place_rows([{'start': group['start'], 'end': group['end'], 'text': text}])
        if not rows:
            continue
        rows[0]['source_text'] = group['text'][:300]
        for row in rows:
            row['lang'] = translate_to
        captions += rows
    if not captions:
        raise ValueError('翻译结果为空，请重试')
    return {'language': detected, 'target': translate_to, 'captions': captions}
