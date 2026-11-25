"""Account selection for the assistant's image lane, independent of video generation."""
from argparse import ArgumentParser
from contextlib import closing
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sqlite3


LEGACY = 'legacy'


@dataclass(frozen=True)
class ImageAccount:
    profile: str
    account: str
    name: str


def initialize(db):
    # Created under the caller's schema write barrier, including old databases.
    db.execute('''CREATE TABLE IF NOT EXISTS assistant_image_settings(
        id INTEGER PRIMARY KEY CHECK(id=1), profile TEXT NOT NULL)''')
    columns = {r[1] for r in db.execute('PRAGMA table_info(ai_turns)')}
    for name, default in (('image_profile', LEGACY), ('image_account', '')):
        if name not in columns:
            db.execute(f"ALTER TABLE ai_turns ADD COLUMN {name} TEXT NOT NULL DEFAULT '{default}'")


def selected_profile(db):
    row = db.execute('SELECT profile FROM assistant_image_settings WHERE id=1').fetchone()
    return row[0] if row else LEGACY


def resolve_account(db, profile=None):
    if profile is None:
        profile = selected_profile(db)
    if profile == LEGACY:
        row = db.execute("SELECT account,'原共享账号' FROM libtv_settings WHERE id=1").fetchone()
    elif isinstance(profile, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,64}', profile):
        row = db.execute('SELECT account,name FROM libtv_profiles WHERE id=? AND enabled=1', (profile,)).fetchone()
    else:
        return None
    return ImageAccount(profile, row[0], row[1]) if row and row[0].strip() else None


def select_account(db, target, expected_profile, verified_account):
    """With BEGIN IMMEDIATE held, change only the assistant selector. Never call LibTV here."""
    route = resolve_account(db, target)
    if not route or route.account != verified_account:
        raise ValueError('目标账号未启用、未授权或身份已变化；未切换。')
    current = selected_profile(db)
    if current == route.profile:
        return False
    if current != expected_profile:
        raise ValueError('助手生图账号已由其他操作更改；请先核对当前设置。')
    db.execute('''INSERT INTO assistant_image_settings(id,profile) VALUES(1,?)
        ON CONFLICT(id) DO UPDATE SET profile=excluded.profile''', (route.profile,))
    return True


def main():
    parser = ArgumentParser(description='只管理 AI 助手生图的 LibTV 账号，不提交任务。')
    actions = parser.add_subparsers(dest='action', required=True)
    actions.add_parser('show')
    switch = actions.add_parser('select')
    switch.add_argument('--profile', required=True)
    switch.add_argument('--expect', required=True, help='上一次确认的助手生图 profile ID')
    switch.add_argument('--account', required=True, help='已用官方只读检查核对的目标 account ID')
    args = parser.parse_args()
    path = Path(__file__).resolve().parent/'state'/'hub.sqlite3'
    selecting = args.action == 'select'
    with closing(sqlite3.connect(path.as_uri()+'?mode='+('rw' if selecting else 'ro'),uri=True,timeout=10)) as db, db:
        changed = False
        if selecting:
            from libtv_isolation import profile_dir
            if not (profile_dir(args.profile)/'credentials.json').is_file():
                raise SystemExit('目标 LibTV 授权文件不可用；未切换。')
            db.execute('BEGIN IMMEDIATE')
            try:
                changed = select_account(db,args.profile,args.expect,args.account)
            except ValueError as exc:
                raise SystemExit(str(exc)) from None
        else:
            db.execute('BEGIN')
        route = resolve_account(db)
        result = {'changed':changed, 'profile':selected_profile(db), 'configured':route is not None,
                  'name':route.name if route else ''}
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
