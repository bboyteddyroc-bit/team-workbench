"""把已完成的 Apify 数据集里的视频封面地址读回本地快照。

只做 GET：不新建 actor 任务、不调用 Kalodata、不产生付费请求。
数据集读取本身不计费，因此历史视频也能补上缩略图。
用法：python backfill_covers.py [--dry-run]
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault('HUB_STATE', str(ROOT / 'state'))

import httpx  # noqa: E402

from app import Hub  # noqa: E402
from apify_config import ApifyConfig  # noqa: E402
from apify_monitor import cover_url  # noqa: E402


def api(token, path, **params):
    with httpx.Client(timeout=60, trust_env=False) as client:
        response = client.get('https://api.apify.com/v2' + path,
                              headers={'Authorization': 'Bearer ' + token}, params=params)
    if response.status_code >= 400:
        raise SystemExit('Apify 读取失败：HTTP %s（未写入任何数据）' % response.status_code)
    return response.json()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    hub = Hub(os.environ['HUB_STATE'])
    config = ApifyConfig(hub)
    with hub.db() as db:
        columns = {row[1] for row in db.execute('PRAGMA table_info(apify_snapshots)')}
        has_cover = 'cover' in columns
        if not has_cover:
            if args.dry_run:
                print('快照表缺少 cover 列（服务重启时会自动补齐）')
            else:
                db.execute('ALTER TABLE apify_snapshots ADD COLUMN cover TEXT')
                has_cover = True
        accounts = [dict(row) for row in db.execute('SELECT id,handle FROM apify_accounts')]

    token = config.secret()
    if not token:
        raise SystemExit('没有可用的 Apify 密钥，无法读取历史数据集；未做任何修改')

    print('账号 %d 个，模式：%s' % (len(accounts), '试运行' if args.dry_run else '写入'))
    for account in accounts:
        with hub.db() as db:
            runs = [dict(row) for row in db.execute(
                "SELECT id,remote_id,dataset FROM apify_runs WHERE account=? AND remote_id IS NOT NULL "
                "AND state IN ('ready','attention') ORDER BY updated DESC", (account['id'],))]
            missing = db.execute(
                'SELECT video FROM apify_snapshots WHERE account=?' + (' AND cover IS NULL' if has_cover else ''),
                (account['id'],)).fetchall()
        pending = {row['video'] for row in missing}
        if not pending:
            print('- %s：已有封面，跳过' % account['handle'])
            continue

        found = {}
        for run in runs:
            dataset = run['dataset']
            if not dataset:
                try:
                    detail = api(token, '/actor-runs/' + run['remote_id'])['data']
                except SystemExit as exc:
                    print('  %s：%s' % (account['handle'], exc))
                    continue
                dataset = detail.get('defaultDatasetId')
                if dataset and not args.dry_run:
                    with hub.db() as db:
                        db.execute('UPDATE apify_runs SET dataset=? WHERE id=?', (dataset, run['id']))
            if not dataset:
                continue
            try:
                items = api(token, '/datasets/' + dataset + '/items', clean='true', limit=1000)
            except SystemExit as exc:
                print('  %s：%s' % (account['handle'], exc))
                continue
            for item in items if isinstance(items, list) else []:
                video = str(item.get('id', ''))
                if video in pending and video not in found:
                    url = cover_url(item)
                    if url:
                        found[video] = url
            if len(found) >= len(pending):
                break

        print('- %s：待补 %d 条，数据集命中 %d 条' % (account['handle'], len(pending), len(found)))
        if found and not args.dry_run:
            with hub.db() as db:
                db.executemany('UPDATE apify_snapshots SET cover=? WHERE account=? AND video=?',
                               [(url, account['id'], video) for video, url in found.items()])

    if has_cover:
        with hub.db() as db:
            total, covered = db.execute('SELECT COUNT(*), COALESCE(SUM(cover IS NOT NULL),0) FROM apify_snapshots').fetchone()
        print('快照合计 %d 条，其中 %d 条有封面（%s）' % (total, covered, time.strftime('%H:%M:%S')))
    else:
        print('试运行结束：cover 列尚未创建，未写入任何数据（%s）' % time.strftime('%H:%M:%S'))


if __name__ == '__main__':
    main()
