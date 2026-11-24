"""Invalidate open product reports when a committed evidence source changes."""
from fastapi import Request

from own_goods import PREFIX, get_goods


def attach(app, hub, user):
    with hub.db() as db:
        db.execute('CREATE TABLE IF NOT EXISTS own_report_revision(id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL)')
        db.execute('INSERT OR IGNORE INTO own_report_revision VALUES(1,0)')
        # Both server processes share these triggers and the evidence transaction.
        sources = ['video_cases', 'video_case_members', 'comment_sample_jobs', 'comment_sample_research',
                   'comment_sample_text', 'intel_goods_video', 'intel_goods', 'apify_snapshots',
                   'own_goods_links', 'own_goods_research_category', 'own_goods_research_exclusions',
                   'own_goods', 'apify_accounts', 'comment_sample_config', 'users', 'own_goods_evidence', 'own_goods_topics',
                   'research_tag_reviews']
        # Only evidence-changing writes should invalidate reports, not queue progress.
        db.execute('''CREATE TRIGGER IF NOT EXISTS own_report_lookup_ready AFTER UPDATE OF metadata ON own_goods_lookup
                     WHEN new.state='ready' BEGIN UPDATE own_report_revision SET revision=revision+1 WHERE id=1; END''')
        db.execute('''CREATE TRIGGER IF NOT EXISTS own_report_lookup_identity AFTER UPDATE OF product_id ON own_goods_lookup
                     WHEN old.product_id<>new.product_id BEGIN UPDATE own_report_revision SET revision=revision+1 WHERE id=1; END''')
        # A short link's newly verified destination is evidence; image bytes and retry state are not.
        db.execute('''CREATE TRIGGER IF NOT EXISTS own_report_cover_identity AFTER UPDATE OF resolved_url ON own_goods_cover_jobs
                     WHEN new.resolved_url<>old.resolved_url AND length(new.product_id)>0
                     BEGIN UPDATE own_report_revision SET revision=revision+1 WHERE id=1; END''')
        for table in sources:
            for event in ('INSERT', 'UPDATE', 'DELETE'):
                when = 'UPDATE OF enabled' if table == 'users' and event == 'UPDATE' else event
                db.execute(f'''CREATE TRIGGER IF NOT EXISTS own_report_{table}_{event} AFTER {when} ON {table}
                            BEGIN UPDATE own_report_revision SET revision=revision+1 WHERE id=1; END''')

    @app.get(PREFIX+'/{gid}/research/stamp')
    def report_stamp(gid: str, request: Request):
        user(request)
        with hub.db() as db:
            get_goods(db, gid)
            return {'stamp': db.execute('SELECT revision FROM own_report_revision WHERE id=1').fetchone()[0]}
