"""Read-only aggregate diagnostics; never prints secrets or material names."""
import json
import sqlite3
from pathlib import Path

root = Path(__file__).resolve().parent
path = root / 'state' / 'hub.sqlite3'
result = {'database_exists': path.is_file()}
if path.is_file():
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)
    try:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        result['ai_configured'] = bool(db.execute('SELECT EXISTS(SELECT 1 FROM ai_settings WHERE id=1 AND length(secret)>0)').fetchone()[0]) if 'ai_settings' in tables else False
        if 'asset_classification' in tables:
            result['classification_counts'] = [dict(status=r[0], source=r[1], count=r[2]) for r in db.execute('SELECT status,source,count(*) FROM asset_classification GROUP BY status,source')]
            # Error strings originate from bounded application diagnostics, not raw credentials.
            columns = {r[1] for r in db.execute('PRAGMA table_info(asset_classification)')}
            result['classification_has_error_column'] = 'error' in columns
            if 'error' in columns:
                result['classification_errors'] = [dict(error=r[0],count=r[1]) for r in db.execute("SELECT error,count(*) FROM asset_classification WHERE error<>'' GROUP BY error LIMIT 10")]
        if 'classification_throttle' in tables:
            import time
            throttle=db.execute('SELECT cooldown_until,consecutive_limits FROM classification_throttle WHERE id=1').fetchone()
            result['throttle']={'seconds_until_next_attempt':max(0,round(throttle[0]-time.time())), 'consecutive_limits':throttle[1]}
        if 'assets' in tables:
            result['mime_counts'] = [dict(mime=r[0],count=r[1]) for r in db.execute('SELECT mime,count(*) FROM assets GROUP BY mime')]
    finally:
        db.close()
print(json.dumps(result, ensure_ascii=False, indent=2))
