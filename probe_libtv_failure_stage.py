import sqlite3,json,datetime
from pathlib import Path
p=Path(__file__).resolve().parent
c=sqlite3.connect('file:'+str(p/'state/hub.sqlite3')+'?mode=ro',uri=True)
for state,stage,updated,project,error in c.execute('SELECT state,stage,updated,project,error FROM libtv_jobs ORDER BY updated DESC LIMIT 6'):
 print(json.dumps({'state':state,'stage':stage,'updated':datetime.datetime.fromtimestamp(updated).isoformat(),'has_project':bool(project),'account_check_failure':'账号检查' in (error or ''),'EACCES':'EACCES' in (error or '')},ensure_ascii=False))
