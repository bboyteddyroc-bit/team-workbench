"""Fish Audio TTS 适配器：SSE 解析、音频拼接、时间戳归一化。

设计边界（与 TikTok provider.py 完全分离，不共用任务调度）：
- 本模块只负责「发请求 / 解析事件流 / 产出音频与字幕段」，不做排队。
- 排队、状态机、权限在 voice.py。
- 从不自动重试可能计费的生成请求。
"""
from __future__ import annotations

import base64
import binascii
import json
import math

# 官方端点（docs.fish.audio /api-reference/endpoint/openapi-v1/
# text-to-speech-stream-with-timestamps）
STREAM_URL = 'https://api.fish.audio/v1/tts/stream/with-timestamp'

# 模型必须显式传；不依赖服务端未知默认值。
MODELS = ('s1', 's2-pro', 's2.1-pro', 's2.1-pro-free', 'drama-3')

# 输出格式：wav 便于 FFmpeg 直接解码且无重叠窗口（mp3 的编码窗口会
# 让分块边界与时间戳快照对不齐，文档明确警告）。
FORMATS = ('wav', 'pcm', 'mp3', 'opus')

# 中台自有限制（不是上游限制，界面上要区分标注）
TEXT_CHUNK = 1800        # 分段传输大小，不限制整篇文案长度
TEXT_MIN = 1
SPEED_MIN, SPEED_MAX = 0.5, 2.0   # prosody.speed 中台约束


class StreamError(ValueError):
    """流式解析或上游返回的错误，信息可直接展示给用户。"""


# ------------------------------------------------------------------ SSE 解析

def iter_sse_events(byte_chunks):
    """把任意切分的字节块还原成标准 SSE 事件 data 负载。

    网络块 ≠ 完整事件：必须缓冲到空行才算一个事件边界。
    支持 LF / CRLF / CR，忽略注释行（冒号开头）与 field 行（event:/id:/retry:）。
    产出 raw data 字符串（多行 data 用换行拼接，符合 SSE 规范）。
    """
    buf = ''
    for chunk in byte_chunks:
        if isinstance(chunk, bytes):
            chunk = chunk.decode('utf-8', 'replace')
        buf += chunk
        while True:
            idx, seplen = _find_boundary(buf)
            if idx < 0:
                break
            block = buf[:idx]
            buf = buf[idx + seplen:]
            data = _extract_data(block)
            if data is not None:
                yield data
    tail = _extract_data(buf) if buf.strip() else None
    if tail is not None:
        raise StreamError('上游流提前结束，最后一个事件不完整')


def _find_boundary(buf):
    """返回 (index, sep_len)。空行 = 事件结束。"""
    best = (-1, 0)
    for sep in ('\r\n\r\n', '\n\n', '\r\r'):
        i = buf.find(sep)
        if i >= 0 and (best[0] < 0 or i < best[0]):
            best = (i, len(sep))
    return best


def _extract_data(block):
    lines = block.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    parts = []
    for line in lines:
        if not line or line.startswith(':'):
            continue
        if ':' in line:
            field, value = line.split(':', 1)
            if value.startswith(' '):
                value = value[1:]
        else:
            field, value = line, ''
        if field == 'data':
            parts.append(value)
    if not parts:
        return None
    return '\n'.join(parts)


# ------------------------------------------------------------------ 事件累积

class StreamCollector:
    """按文档规则累积音频与 alignment。

    - audio_base64 按事件顺序解码拼接（alignment 为 null 的事件也要拼）
    - alignment 以 chunk_seq 为键做「最新快照覆盖」，不追加
    - 全局时间 = segment.start/end + chunk_audio_offset_sec
    """

    def __init__(self):
        self.audio = bytearray()
        self.chunks = 0
        self.snapshots = {}
        self.warnings = []
        self.raw_contents = {}

    def feed_event(self, data_text):
        # 允许直接传已解析的 dict，便于测试与内部复用
        if isinstance(data_text, dict):
            event = data_text
        else:
            try:
                event = json.loads(data_text)
            except json.JSONDecodeError:
                raise StreamError('上游返回了无法解析的事件数据') from None
        if not isinstance(event, dict):
            raise StreamError('上游事件格式异常')

        # 上游显式错误
        if event.get('error'):
            raise StreamError('配音上游返回错误事件，未自动重试；请先核对原任务与用量')

        b64 = event.get('audio_base64') or ''
        if b64:
            try:
                chunk = base64.b64decode(b64, validate=True)
            except (binascii.Error, ValueError):
                raise StreamError('上游音频块 base64 无效') from None
            if not chunk:
                raise StreamError('上游音频块为空')
            self.audio.extend(chunk)
            self.chunks += 1

        seq = event.get('chunk_seq')
        alignment = event.get('alignment')

        if alignment is not None:
            if not isinstance(alignment, dict):
                raise StreamError('上游 alignment 结构异常')
            if not isinstance(seq, int) or isinstance(seq, bool):
                self.warnings.append('alignment 缺少合法 chunk_seq，已忽略该快照')
            else:
                segs = alignment.get('segments')
                if not isinstance(segs, list):
                    self.warnings.append('chunk %d 的 segments 不是数组，已忽略' % seq)
                else:
                    clean = []
                    for seg in segs:
                        if not isinstance(seg, dict):
                            continue
                        text = seg.get('text')
                        start, end = seg.get('start'), seg.get('end')
                        if not isinstance(text, str):
                            continue
                        if not _is_num(start) or not _is_num(end):
                            continue
                        start, end = float(start), float(end)
                        if end < start:
                            self.warnings.append('chunk %d 存在结束早于开始的段，已丢弃' % seq)
                            continue
                        clean.append({'text': text, 'start': start, 'end': end})
                    offset = event.get('chunk_audio_offset_sec')
                    if not _is_num(offset):
                        offset = 0.0
                    # 最新快照覆盖旧快照（文档明确要求）
                    self.snapshots[seq] = {
                        'segments': clean,
                        'offset': float(offset),
                        'audio_duration': alignment.get('audio_duration'),
                        'content': event.get('content') or '',
                    }
                    if event.get('content'):
                        self.raw_contents[seq] = event['content']

    def timeline(self):
        """全局时间轴上的词/短语级对齐段，按开始时间排序。"""
        out = []
        for seq in sorted(self.snapshots):
            snap = self.snapshots[seq]
            for seg in snap['segments']:
                out.append({
                    'text': seg['text'],
                    'start': seg['start'] + snap['offset'],
                    'end': seg['end'] + snap['offset'],
                    'chunk_seq': seq,
                })
        out.sort(key=lambda x: (x['start'], x['end']))
        return out

    def has_alignment(self):
        return bool(self.snapshots) and any(s['segments'] for s in self.snapshots.values())


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


# ------------------------------------------------------------------ 字幕分行

SENTENCE_END = tuple('。！？!?；;…')


def group_into_captions(timeline, max_chars=28, max_duration=6.0, max_gap=0.9):
    """把词/短语级对齐合并成可读字幕行。

    规则（任一满足即断行）：
      1. 累积到句末标点
      2. 超过 max_chars 字
      3. 超过 max_duration 秒
      4. 与下一段间隔超过 max_gap 秒

    返回 [{'text','start','end'}]，时间直接取自对齐段，不伪造精度。
    """
    rows = []
    buf = []
    buf_start = None
    buf_end = None
    prev_end = None

    def flush():
        nonlocal buf, buf_start, buf_end
        if buf and buf_start is not None:
            text = ''.join(buf).strip()
            if text:
                rows.append({'text': text, 'start': round(buf_start, 3), 'end': round(buf_end, 3)})
        buf = []
        buf_start = None
        buf_end = None

    for item in timeline:
        text = item['text']
        if not text.strip():
            continue
        # 间隔过大 → 先断
        if prev_end is not None and item['start'] - prev_end > max_gap:
            flush()

        # 加入前先判：并入后会不会超限。超限就先定行，保证每行 <= max_chars
        if buf:
            would_len = len(''.join(buf)) + len(text)
            would_dur = item['end'] - buf_start
            if would_len > max_chars or would_dur > max_duration:
                flush()

        if buf_start is None:
            buf_start = item['start']
        buf.append(text)
        buf_end = item['end']

        # 句末标点 → 立即断行，其余条件到下一段加入前再判
        if text.rstrip().endswith(SENTENCE_END):
            flush()

        prev_end = item['end']
    flush()
    return rows


# ------------------------------------------------------------------ 请求构造

def build_request(text, reference_id, model, speed=1.0, fmt='wav',
                  language=None, normalize=True, latency='balanced',
                  sample_rate=None):
    """构造请求体与请求头。

    - model 显式传入，绝不留空让服务端猜默认值
    - language 只影响数字/单位/日期的朗读与词级对齐，不改变口音；
      界面上不能把它标注成「口音」开关
    - 返回的 Authorization 为占位符，密钥只在调用处拼入，不落日志
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError('配音文案不能为空')
    if not isinstance(reference_id, str) or not reference_id.strip():
        raise ValueError('请选择音色')
    if model not in MODELS:
        raise ValueError('TTS 模型无效')
    if fmt not in FORMATS:
        raise ValueError('音频格式无效')
    try:
        speed = float(speed)
    except (TypeError, ValueError):
        raise ValueError('语速无效') from None
    if not (SPEED_MIN <= speed <= SPEED_MAX):
        raise ValueError('语速范围 %s–%s（中台限制）' % (SPEED_MIN, SPEED_MAX))

    body = {
        'text': text,
        'reference_id': reference_id.strip(),
        'format': fmt,
        'latency': latency,
        'normalize': bool(normalize),
        'prosody': {'speed': speed},
        'chunk_length': 200,
    }
    if language:
        body['language'] = language
    if sample_rate:
        body['sample_rate'] = int(sample_rate)

    headers = {
        'Content-Type': 'application/json',
        'model': model,
        'Accept': 'text/event-stream',
    }
    return headers, body


def split_text(text, limit=TEXT_CHUNK):
    """Split at sentence boundaries without dropping or duplicating characters."""
    if limit < 1:
        raise ValueError('Invalid chunk size')
    result=[]
    while len(text)>limit:
        cut=max((text.rfind(mark,0,limit)+1 for mark in ('。','！','？','\n','. ','! ','? ','; ','；')),default=0)
        if cut < limit//2:
            cut=limit
        result.append(text[:cut])
        text=text[cut:]
    if text:
        result.append(text)
    return result
