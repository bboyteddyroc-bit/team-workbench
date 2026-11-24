"""把 voice 生成的音频接入编辑器的统一音频轨。

不修改 editor.py 的既有字段语义，只做「追加兼容」：
- audio_clips 支持 source='video'（原声，既有）与 source='voice'（AI 配音，新增）
- 旧工程没有 source 字段时按 'video' 处理，无损兼容
- 字幕新增可选 voice_job_id 关联，用于联动移动
"""
from __future__ import annotations


AUDIO_SOURCES = ('video', 'voice', 'asset')


def normalize_audio_clip(clip, default_source='video'):
    """把一条 audio_clips 归一化为带 source 的统一结构。

    返回 (source, key, rest)：
      - source='video'  → key 为 task_id
      - source='voice'  → key 为 voice_job_id
    校验由调用方（编辑器的权限层）完成。
    """
    if not isinstance(clip, dict):
        raise ValueError('音轨数据格式无效')
    source = clip.get('source') or default_source
    if source not in AUDIO_SOURCES:
        raise ValueError('音轨来源无效')
    if source == 'video':
        key = str(clip.get('task_id') or '')
        if not key:
            raise ValueError('原声音轨缺少素材 ID')
    else:
        key = str(clip.get('voice_job_id') or '')
        if not key:
            raise ValueError('配音音轨缺少任务 ID')
    rest = {k: v for k, v in clip.items() if k not in ('source', 'task_id', 'voice_job_id')}
    return source, key, rest


def merge_captions(existing, incoming, mode='append'):
    """把配音生成的字幕并入工程字幕。

    mode='append'  → 追加到现有字幕末尾
    mode='replace' → 先移除同一 voice_job_id 的旧字幕，再追加（不碰手动字幕）

    不自动覆盖用户手动添加的字幕：replace 只清理带同一关联的条目。
    """
    if mode not in ('append', 'replace'):
        raise ValueError('字幕合并方式无效')
    base = list(existing or [])
    if mode == 'replace':
        ids = {c.get('voice_job_id') for c in incoming or [] if c.get('voice_job_id')}
        if ids:
            base = [c for c in base if c.get('voice_job_id') not in ids]
    return base + list(incoming or [])


def shift_captions(captions, voice_job_id, delta):
    """整段音频移动时，联动移动关联字幕。"""
    if not delta:
        return list(captions or [])
    out = []
    for c in captions or []:
        c = dict(c)
        if voice_job_id and c.get('voice_job_id') == voice_job_id:
            c['start'] = max(0.0, float(c.get('start', 0)) + delta)
            c['end'] = max(0.0, float(c.get('end', 0)) + delta)
        out.append(c)
    return out


def captions_to_voice(job_captions, insert_at):
    """配音结果 → 时间轴字幕（叠加插入位置）。"""
    rows = []
    for c in job_captions or []:
        start = float(c.get('start', 0)) + float(insert_at or 0)
        end = float(c.get('end', 0)) + float(insert_at or 0)
        rows.append({'text': c.get('text', ''), 'start': round(start, 3), 'end': round(end, 3)})
    return rows


def validate_voice_job_for_owner(hub, voice_root, owner, job_id):
    """服务端校验配音任务归属并返回音频路径。"""
    with hub.db() as db:
        row = db.execute('SELECT * FROM voice_jobs WHERE id=?', (job_id,)).fetchone()
    if not row:
        raise ValueError('配音任务不存在')
    if row['owner'] != owner:
        raise ValueError('无权使用该配音')
    if row['state'] != 'ready':
        raise ValueError('配音尚未完成')
    if not row['audio_path']:
        raise ValueError('配音音频缺失')
    path = voice_root / 'audio' / row['audio_path']
    if not path.is_file():
        raise ValueError('配音音频文件缺失')
    return path, float(row['duration'] or 0.0)
