import sqlite3, pathlib, json, collections, datetime
con = sqlite3.connect(pathlib.Path('state/hub.sqlite3')); con.row_factory = sqlite3.Row
rows = con.execute("SELECT video, period_start, period_end, state, result FROM video_enrichment_jobs WHERE account='e3b1abc8dd634f6caffe6fd67c3052d1'").fetchall()
tot = 0.0; units = 0.0; by_day = collections.defaultdict(lambda: [0.0, 0.0, 0])
snap = {r['video']: r for r in con.execute("SELECT video, published, title FROM apify_snapshots WHERE account='e3b1abc8dd634f6caffe6fd67c3052d1' GROUP BY video")}
for r in rows:
    if r['state'] != 'ready' or not r['result']: continue
    d = json.loads(r['result'])
    gmv = d.get('gmv') or 0; u = d.get('units') or 0
    tot += gmv; units += u
    p = snap.get(r['video'])
    day = datetime.datetime.fromtimestamp(p['published']).strftime('%m/%d') if p else '??'
    by_day[day][0] += gmv; by_day[day][1] += u; by_day[day][2] += 1
print('ready jobs', sum(1 for r in rows if r['state']=='ready'), 'gmv total', round(tot,2), 'units', units)
for day in sorted(by_day): print(day, round(by_day[day][0],2), by_day[day][1], by_day[day][2])
