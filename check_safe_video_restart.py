"""Refuse restart while local work may have an unknown paid-call outcome."""
import sqlite3,json
from pathlib import Path
root=Path(__file__).resolve().parent
with sqlite3.connect((root/'state'/'hub.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
    checks={
      'submitting':db.execute("SELECT count(*) FROM tasks WHERE state='submitting'").fetchone()[0],
      'libtv_active':db.execute("SELECT count(*) FROM libtv_jobs WHERE state IN ('running','importing')").fetchone()[0],
      'assistant_pending':db.execute("SELECT count(*) FROM ai_turns WHERE status='pending'").fetchone()[0],
      'exports_active':db.execute("SELECT count(*) FROM edit_exports WHERE state='running'").fetchone()[0],
      'voice_active':db.execute("SELECT count(*) FROM voice_jobs WHERE state='running'").fetchone()[0],
      'classification_active':db.execute("SELECT count(*) FROM asset_classification WHERE status='running'").fetchone()[0],
    }
print(json.dumps(checks))
raise SystemExit(1 if any(checks.values()) else 0)
