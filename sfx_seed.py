"""Download the bundled royalty-free sound-effect seeds into state/sfx.

Content: Mixkit sound effects (Mixkit Free License: commercial use allowed, no
attribution required). Source URLs are recorded per item so the library can show
provenance. Run with:  .venv/Scripts/python.exe sfx_seed.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / 'state' / 'sfx'
INDEX = TARGET / 'index.json'
UA = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/126.0 Safari/537.36',
}
LICENSE = 'Mixkit 免费音效许可：可商用、无需署名，不可单独转售或再分发原文件'
CATEGORIES = [
    ('transition', '转场'),
    ('impact', '打击'),
    ('notice', '提示'),
    ('riser', '起势'),
    ('tech', '科技'),
    ('ambient', '环境'),
]

# (id, 中文名, 原名, category, tags, 分类页)
SEEDS = [
    ('air-woosh', '空气掠过', 'Air woosh', 'transition', ['whoosh', '轻'], 'whoosh'),
    ('cinematic-fast-whoosh', '电影感快速转场', 'Cinematic whoosh fast transition', 'transition', ['whoosh', '转场'], 'whoosh'),
    ('fast-whoosh', '快速划转', 'Fast whoosh transition', 'transition', ['whoosh', '快'], 'whoosh'),
    ('tunnel-woosh', '隧道混响掠声', 'Cinematic tunnel reverb woosh', 'transition', ['whoosh', '空间'], 'whoosh'),
    ('stutter-whoosh', '卡点停顿掠声', 'Cinematic whoosh stutter', 'transition', ['whoosh', '卡点'], 'whoosh'),
    ('sparkle-whoosh', '魔法光点掠过', 'Magic sparkle whoosh', 'transition', ['whoosh', '魔法'], 'whoosh'),
    ('electric-whoosh', '电流掠声', 'Electric whoosh', 'transition', ['whoosh', '科技'], 'whoosh'),
    ('title-woosh-impact', '片头掠声冲击', 'Movie whoosh impact presentation', 'transition', ['whoosh', '片头'], 'whoosh'),
    ('big-impact', '电影大冲击', 'Big cinematic impact', 'impact', ['impact', '重'], 'impact'),
    ('trailer-impact', '预告史诗撞击', 'Movie trailer epic impact', 'impact', ['impact', '预告'], 'impact'),
    ('deep-impact', '深沉撞击', 'Cinematic whoosh deep impact', 'impact', ['impact', '低音'], 'impact'),
    ('punches', '连续拳击', 'Strong punches to the body', 'impact', ['打击', '动作'], 'impact'),
    ('wood-hit', '木头重击', 'Wood hard hit', 'impact', ['打击', '木头'], 'impact'),
    ('metal-hammer', '金属锤击', 'Metal hammer hit', 'impact', ['打击', '金属'], 'impact'),
    ('zoom-impact', '快速推近重击', 'Quick zoom impact', 'impact', ['impact', '卡点'], 'impact'),
    ('long-pop', '长气泡', 'Long pop', 'notice', ['pop', '轻'], 'notification'),
    ('message-pop', '消息提示', 'Message pop alert', 'notice', ['提示', '消息'], 'notification'),
    ('bell-notify', '铃声提示', 'Bell notification', 'notice', ['提示', '铃'], 'notification'),
    ('positive-notify', '正向提示', 'Positive notification', 'notice', ['提示', '成功'], 'notification'),
    ('fail-notify', '错误提示', 'Wrong answer fail notification', 'notice', ['提示', '失败'], 'notification'),
    ('correct-tone', '正确提示', 'Correct answer tone', 'notice', ['提示', '正确'], 'notification'),
    ('scifi-click', '科幻点击', 'Sci fi click', 'notice', ['click', '科技'], 'notification'),
    ('ui-select', '界面选择', 'Interface option select', 'notice', ['click', '界面'], 'notification'),
    ('trailer-riser', '预告起势', 'Cinematic trailer riser', 'riser', ['riser', '预告'], 'riser'),
    ('drama-riser', '剧情起势', 'Cinematic drama riser', 'riser', ['riser', '剧情'], 'riser'),
    ('synth-riser', '合成器起势', 'Cinematic synth riser', 'riser', ['riser', '合成'], 'riser'),
    ('choir-riser', '科技人声起势', 'Tech choir cinematic riser', 'riser', ['riser', '人声'], 'riser'),
    ('space-stutter-riser', '短促太空起势', 'Short space stutter intro riser', 'riser', ['riser', '太空'], 'riser'),
    ('glitch-static', '故障电流', 'Glitch static', 'tech', ['glitch', '故障'], 'glitch'),
    ('scifi-rewind', '科幻倒带', 'Glitch sci fi rewind transition', 'tech', ['glitch', '倒带'], 'glitch'),
    ('virtual-glitch', '虚拟故障', 'Virtual quick glitch', 'tech', ['glitch', '数字'], 'glitch'),
    ('short-glitch', '短故障', 'Glitch short', 'tech', ['glitch', '短'], 'glitch'),
    ('electric-glitch', '小电流故障', 'Small electric glitch', 'tech', ['glitch', '电流'], 'glitch'),
    ('urban-ambient', '城市环境', 'Urban ambient sound', 'ambient', ['环境', '城市'], 'ambient'),
    ('desert-ambient', '沙漠环境', 'Ambient sound in the desert', 'ambient', ['环境', '空旷'], 'ambient'),
    ('rain-thunder', '雨声雷声', 'Rain ambien and thunder', 'ambient', ['环境', '雨'], 'ambient'),
    ('crowd-ambient', '人群欢呼', 'Ambient sports crowd sound', 'ambient', ['环境', '人群'], 'ambient'),
]

PAGE = 'https://mixkit.co/free-sound-effects/{}/'


def probe_duration(path: Path) -> float:
    tool = shutil.which('ffprobe')
    if not tool:
        raise RuntimeError('ffprobe 不可用')
    out = subprocess.run([tool, '-v', 'error', '-show_entries', 'format=duration', '-of', 'json', str(path)],
                         capture_output=True, text=True, timeout=60)
    data = json.loads(out.stdout or '{}')
    return round(float(data.get('format', {}).get('duration', 0)), 3)


def catalog(category: str) -> dict[str, str]:
    """Map lowercase title -> preview url for one Mixkit category page."""
    import re
    url = PAGE.format(category)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=40) as response:
        html = response.read().decode('utf-8', 'replace')
    titles = re.findall(r'class="item-grid-card__title"[^>]*>\s*([^<]+?)\s*<', html)
    audios = re.findall(r'data-audio-player-preview-url-value="([^"]+)"', html)
    result = {}
    for index, audio in enumerate(audios):
        if index < len(titles):
            result[titles[index].strip().lower()] = audio
    return result


def download(url: str, path: Path) -> None:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as response:
        data = response.read()
    if not (data.startswith(b'ID3') or data[:2] in (b'\xff\xfb', b'\xff\xf3', b'\xff\xf2')):
        raise RuntimeError(f'返回内容不是 MP3：{url}')
    if len(data) < 2000:
        raise RuntimeError(f'文件过小：{url}')
    path.write_bytes(data)


def main() -> int:
    TARGET.mkdir(parents=True, exist_ok=True)
    caches: dict[str, dict[str, str]] = {}
    items, failures = [], []
    for seed_id, name, name_en, category, tags, page in SEEDS:
        target = TARGET / f'{seed_id}.mp3'
        if not target.is_file() or target.stat().st_size < 2000:
            cache = caches.setdefault(page, catalog(page))
            url = cache.get(name_en.lower())
            if not url:
                failures.append((seed_id, '目录页未找到同名条目'))
                continue
            try:
                download(url, target)
            except Exception as error:  # noqa: BLE001 - report and continue seeding
                failures.append((seed_id, str(error)))
                continue
        try:
            duration = probe_duration(target)
        except Exception as error:  # noqa: BLE001
            failures.append((seed_id, f'时长探测失败 {error}'))
            continue
        items.append({
            'id': seed_id,
            'name': name,
            'name_en': name_en,
            'category': category,
            'tags': ['音效', name_en.lower(), *tags],
            'file': target.name,
            'duration': duration,
            'bytes': target.stat().st_size,
            'source': 'Mixkit',
            'source_url': PAGE.format(page),
            'license': LICENSE,
        })
        print(f'{seed_id:22s} {duration:6.2f}s  {target.stat().st_size/1024:7.1f} KB  {name}', flush=True)

    payload = {
        'version': 1,
        'generated': int(time.time()),
        'license': LICENSE,
        'source': 'https://mixkit.co/free-sound-effects/',
        'categories': [{'key': key, 'label': label} for key, label in CATEGORIES],
        'items': items,
    }
    INDEX.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'\n登记 {len(items)} 个音效 -> {INDEX}')
    for seed_id, error in failures:
        print(f'失败 {seed_id}: {error}')
    return 0 if items else 1


if __name__ == '__main__':
    sys.exit(main())
