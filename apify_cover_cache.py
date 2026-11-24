"""Cache signed cover images while their source URLs are fresh."""
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import safe_cover

MIME = {'.jpg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp'}
_workers = ThreadPoolExecutor(max_workers=2, thread_name_prefix='cover-cache')


def existing(directory, video):
    if not video.isascii() or not video.isdigit():
        raise ValueError('无效视频编号')
    return next((directory / (video + ext) for ext in MIME if (directory / (video + ext)).is_file()), None)


def store(directory, video, url):
    path = existing(directory, video)
    if path:
        return path
    data = safe_cover.fetch(url)
    if data.startswith(b'\xff\xd8\xff'):
        ext = '.jpg'
    elif data.startswith(b'\x89PNG\r\n\x1a\n'):
        ext = '.png'
    elif data.startswith(b'RIFF') and data[8:12] == b'WEBP':
        ext = '.webp'
    else:
        raise ValueError('封面格式不支持')
    directory.mkdir(exist_ok=True)
    path = directory / (video + ext)
    with tempfile.NamedTemporaryFile(dir=directory, suffix='.part', delete=False) as out:
        temp = Path(out.name)
        try:
            out.write(data)
            out.close()
            os.replace(temp, path)
        finally:
            out.close()
            temp.unlink(missing_ok=True)
    return path


def warm(directory, video, url):
    _workers.submit(store, directory, video, url)
