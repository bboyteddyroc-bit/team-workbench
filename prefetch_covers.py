"""把已入库的封面地址下载到 state/apify-covers，界面上第一次打开就有缩略图。

只读取 apify_snapshots.cover 并发起普通 HTTP GET（不调用 Apify，不产生费用）。
本机访问 TikTok CDN 需要系统代理，代理不通时自动退回直连。
"""
import os
import sqlite3
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
STATE = ROOT / 'state'
CACHE = STATE / 'apify-covers'
KINDS = {'.jpg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp'}
BY_EXT = {v: k for k, v in KINDS.items()}
PROXY = os.environ.get('HTTP_PROXY') or os.environ.get('http_proxy')


def kind_of(body: bytes) -> str | None:
    if body[:3] == b'\xff\xd8\xff':
        return 'image/jpeg'
    if body[:8] == b'\x89PNG\r\n\x1a\n':
        return 'image/png'
    if body[:4] == b'RIFF' and body[8:12] == b'WEBP':
        return 'image/webp'
    return None


def download(url: str) -> tuple[str, bytes] | None:
    headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.tiktok.com/'}
    clients = []
    if PROXY:
        clients.append(lambda: httpx.Client(timeout=25, proxy=PROXY, follow_redirects=True))
    clients.append(lambda: httpx.Client(timeout=20, trust_env=False, follow_redirects=True))
    for make in clients:
        try:
            with make() as client:
                response = client.get(url, headers=headers)
            body = response.content
            kind = kind_of(body)
            if response.status_code < 400 and kind and 0 < len(body) <= 4_000_000:
                return kind, body
        except (httpx.HTTPError, OSError):
            continue
    return None


def main() -> int:
    dry = '--dry-run' in sys.argv
    CACHE.mkdir(exist_ok=True)
    connection = sqlite3.connect(STATE / 'hub.sqlite3')
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        'SELECT video, cover FROM apify_snapshots WHERE cover IS NOT NULL'
        ' GROUP BY video ORDER BY MAX(collected) DESC'
    ).fetchall()
    have = {p.stem for p in CACHE.glob('*') if p.suffix in KINDS and p.is_file()}
    todo = [r for r in rows if r['video'] not in have and r['cover'].startswith('http')]
    print(f'库内 {len(rows)} 个视频有封面地址，已缓存 {len(have)} 个，待下载 {len(todo)} 个')
    if dry:
        return 0
    ok = failed = 0
    for row in todo:
        result = download(row['cover'])
        if not result:
            failed += 1
            print(f"  失败 {row['video']}")
            continue
        kind, body = result
        (CACHE / (row['video'] + BY_EXT[kind])).write_bytes(body)
        ok += 1
    total = len({p.stem for p in CACHE.glob('*') if p.suffix in KINDS and p.is_file()})
    print(f'本次下载 {ok} 个，失败 {failed} 个；缓存合计 {total} 个')
    return 0 if not failed else 1


if __name__ == '__main__':
    raise SystemExit(main())
