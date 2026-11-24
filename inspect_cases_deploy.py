"""Read-only rolling-release checks; no credentials or member content are printed."""
import json
from pathlib import Path
import sqlite3
import time

import psutil

root=Path(__file__).resolve().parent
checks={
    'tasks': "state IN ('queued','submitting','running')", 'voice_jobs': "state IN ('queued','running')",
    'edit_exports': "state IN ('queued','rendering')", 'libtv_jobs': "state IN ('queued','running','importing')",
    'asset_classification': "status='running'", 'ai_turns': "status='pending'",
    'feishu_uploads': "state IN ('queued','uploading')", 'kalodata_jobs': "state IN ('queued','running')",
    'grouped_runs': "state IN ('queued','submitting','running')", 'apify_runs': "state IN ('queued','submitting','running')",
    'video_enrichment_jobs': "state='running'", 'script_creative_tasks': "state='generating'",
    'script_enrichment': "state='running'", 'script_transcriptions': "state='running'",
    'ai_edit_jobs': "state IN ('queued','running','planning','rendering')",
    'video_case_jobs': "state IN ('queued','submitting','running')", 'goods_jobs': "state IN ('queued','claimed')",
    'preview_proxy_jobs': "state IN ('queued','running')",
    'own_goods_lookup': "state IN ('queued','resolving','fetching')",
    'comment_sample_jobs': "state='running' OR ai_state='running'", 'comment_sample_research': "state='running'",
}


def work(db, lane='lan', horizon=120):
    """Run with the same DB write barrier used by the job selectors before stopping a lane."""
    now=time.time();due=now+horizon
    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    def count(sql,*args):return db.execute(sql,args).fetchone()[0]
    found={t:count('SELECT COUNT(*) FROM '+t+' WHERE '+where) for t,where in checks.items() if t in tables}
    if 'own_goods_lookup' in tables and 'image_state' in {r[1] for r in db.execute('PRAGMA table_info(own_goods_lookup)')}:
        from own_goods_lookup import ACTIVE_SQL
        found['own_goods_lookup']=count('SELECT COUNT(*) FROM own_goods_lookup WHERE '+ACTIVE_SQL)
    if lane!='lan':return found
    if 'mobile_transfers' in tables:
        found['active_mobile_links']=count('SELECT COUNT(*) FROM mobile_transfers WHERE revoked=0 AND expires>?',now)
    if 'mobile_upload_progress' in tables:
        found['mobile_uploads']=count("SELECT COUNT(*) FROM mobile_upload_progress WHERE state IN ('uploading','verifying') AND updated>?",now-90)
    if 'video_case_weekly_enrollment' in tables:
        found['case_weekly_due']=count("SELECT COUNT(*) FROM video_case_weekly_enrollment WHERE state='pending' AND due<=?",due)
    if 'video_case_jobs' in tables:
        found['case_waiting_due']=count("SELECT COUNT(*) FROM video_case_jobs WHERE state='waiting' AND next_attempt<=?",due)
    if {'apify_accounts','auto_collection_selection','auto_collection_config','users'}<=tables:
        found['apify_due']=count('''SELECT COUNT(*) FROM apify_accounts a JOIN users u ON u.id=a.owner AND u.enabled=1
          JOIN auto_collection_selection s ON s.owner=a.owner AND s.account=a.id AND s.selected=1
          JOIN auto_collection_config g ON g.owner=a.owner AND g.collection_enabled=1
          WHERE a.deleted_at IS NULL AND a.next_at>0 AND a.next_at<=?''',due)
    if 'script_rechecks' in tables:
        found['script_recheck_due']=count("SELECT COUNT(*) FROM script_rechecks WHERE state='waiting' AND due BETWEEN ? AND ?",now-86400,due)
        found['script_transcription_queued']=count("SELECT COUNT(*) FROM script_transcriptions WHERE state='queued'")
        found['script_enrichment_queued']=count("SELECT COUNT(*) FROM script_enrichment WHERE state='queued'")
    if 'video_enrichment_jobs' in tables:
        found['video_enrichment_due']=count('''SELECT COUNT(*) FROM video_enrichment_jobs j
          JOIN video_enrichment_config c ON c.account=j.account AND c.paused=0
          JOIN apify_accounts a ON a.id=j.account AND a.deleted_at IS NULL
          JOIN users u ON u.id=a.owner AND u.enabled=1
          JOIN auto_collection_selection s ON s.owner=a.owner AND s.account=a.id AND s.selected=1
          JOIN auto_collection_config g ON g.owner=a.owner AND g.enrichment_enabled=1
          WHERE j.state IN ('queued','waiting') AND j.next_at<=?''',due)
    if 'goods_details' in tables:
        found['goods_startup_queue']=count("""SELECT COUNT(*) FROM intel_goods g WHERE g.shop<>'' AND g.shop_name=''
          AND NOT EXISTS(SELECT 1 FROM goods_jobs j WHERE j.kind='store' AND j.key=g.shop)""")
        if not count("SELECT COUNT(*) FROM goods_details WHERE kind='migration'"):
            found['goods_startup_queue']+=count('SELECT COUNT(*) FROM intel_goods')
    if 'comment_sample_config' in tables:
        from comment_samples import CASE_VISIBLE, IN_CASE_LIBRARY
        cfg=db.execute("SELECT collect,ai,collect_error<>'',ai_error<>'',backfill_until FROM comment_sample_config WHERE id=1").fetchone()
        if cfg:
            # The current worker never claims queued records outside Content Reuse
            # or older than the configured scope. Preserve them without mistaking
            # them for due work. Any *running* record still blocks above.
            visible={'video_cases','video_case_members','users'}<=tables
            current=' AND j.created>=COALESCE((SELECT since FROM comment_sample_scope WHERE id=1),0)' if 'comment_sample_scope' in tables else ''
            scope=(f' AND {IN_CASE_LIBRARY}'+current) if visible else ''
            if cfg[0] and not cfg[2]:
                found['comment_collect_eligible']=count(f"SELECT COUNT(*) FROM comment_sample_jobs j WHERE j.state='queued'{scope}")
                if cfg[4] and visible:
                    found['comment_collect_eligible']+=count(f'''SELECT COUNT(*) FROM video_cases c WHERE {CASE_VISIBLE}
                        AND c.created<=? AND NOT EXISTS(SELECT 1 FROM comment_sample_jobs j WHERE j.video=c.video)''',cfg[4])
                elif cfg[4]:
                    found['comment_collect_eligible']+=1  # Older schema: fail closed.
            if cfg[1] and not cfg[3]:
                found['comment_ai_eligible']=count(f"SELECT COUNT(*) FROM comment_sample_jobs j WHERE j.ai_state='pending' AND j.state IN ('ready','partial'){scope}")
                if 'comment_sample_research' in tables:
                    found['comment_ai_eligible']+=count(f"""SELECT COUNT(*) FROM comment_sample_research s
                        JOIN comment_sample_jobs j USING(video) WHERE s.state='queued' AND j.ai_state='ready'{scope}""")
                    if not visible:
                        found['comment_ai_eligible']+=count("SELECT COUNT(*) FROM comment_sample_research s WHERE s.state='queued' AND NOT EXISTS(SELECT 1 FROM comment_sample_jobs j WHERE j.video=s.video AND j.ai_state='ready')")
    return found


if __name__=='__main__':
    with sqlite3.connect((root/'state/hub.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        print('Active or due work:',json.dumps(work(db)),flush=True)
    for c in psutil.net_connections(kind='tcp'):
        if c.status=='LISTEN' and c.laddr.port in (8765,8443,8000):
            p=psutil.Process(c.pid)
            print('Listener',c.laddr.port,p.pid,Path(p.cwd()).resolve()==root,p.cmdline()[-1],flush=True)
