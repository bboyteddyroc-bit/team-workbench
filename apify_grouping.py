"""Pure helpers for planning grouped Apify runs; no network or database side effects.

Not wired into the live scheduler. Empty/ambiguous results require review rather
than being treated as proof of a completed account scrape.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def group_by_options(accounts):
    """Group normalized accounts by owner and exact window/timezone, preserving order.

    Each item contains owner, handle, start_at, end_at and timezone. Account
    selection, timing, locking and permission checks remain the caller's duty.
    """
    groups = {}
    seen = set()
    for account in accounts:
        owner, handle = account['owner'], str(account['handle']).strip().lstrip('@').lower()
        start, end, zone = account['start_at'], account['end_at'], account['timezone']
        if not owner or not handle or not zone or start is None or end is None or start >= end:
            raise ValueError('invalid account or collection window')
        identity = (owner, handle)
        if identity in seen:
            raise ValueError('duplicate account')
        seen.add(identity)
        key = (owner, start, end, zone)
        groups.setdefault(key, []).append(account)
    return list(groups.values())


def partition_results(handles, items):
    """Partition returned records; surface unassignable rows and empty accounts.

    Presence of records does not establish completeness; callers must separately
    inspect remote status, charging/cap signals, window and pagination.
    """
    names = [str(h).strip().lstrip('@').lower() for h in handles]
    if any(not h for h in names) or len(set(names)) != len(names):
        raise ValueError('invalid or duplicate handles')
    if not isinstance(items, list):
        raise ValueError('invalid dataset')
    result = {name: [] for name in names}
    unassigned = []
    for item in items:
        meta = item.get('authorMeta') if isinstance(item, dict) else None
        name = str(meta.get('name') or '').strip().lstrip('@').lower() if isinstance(meta, dict) else ''
        video = str(item.get('id') or '') if isinstance(item, dict) else ''
        if name not in result or not video.isdigit():
            unassigned.append(item)
        else:
            result[name].append(item)
    return {'accounts': result, 'unassigned': unassigned,
            'empty_accounts': [name for name, rows in result.items() if not rows]}


def build_request(group, max_items=5000, max_charge=10.0):
    """Prepare one bounded request. The caller must confirm payment and persist first."""
    if not group or len(group_by_options(group)) != 1:
        raise ValueError('group must share owner and collection window')
    if type(max_items) is not int or not 1 <= max_items <= 1000000:
        raise ValueError('invalid safety item limit')
    if isinstance(max_charge, bool) or not isinstance(max_charge, (int, float)) or not 0 < max_charge <= 10:
        raise ValueError('invalid safety charge limit')
    first = group[0]
    tz = ZoneInfo(first['timezone'])
    start = datetime.fromtimestamp(first['start_at'], tz)
    end = datetime.fromtimestamp(first['end_at'] - 1, tz)
    return {
        'params': {'timeout': 300, 'maxItems': max_items, 'maxTotalChargeUsd': max_charge},
        'json': {'profiles': [str(a['handle']).strip().lstrip('@').lower() for a in group],
                 'resultsPerPage': 1000000, 'profileScrapeSections': ['videos'],
                 'profileSorting': 'latest', 'shouldDownloadVideos': False,
                 'shouldDownloadCovers': False,
                 'oldestPostDateUnified': start.strftime('%Y-%m-%d'),
                 'newestPostDate': end.strftime('%Y-%m-%d')},
    }
