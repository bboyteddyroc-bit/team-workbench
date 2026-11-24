"""Scoped upgrade: data-only lane, additive provider rows and fast status refresh.
Run once; checks anchors to avoid replaying a partial patch.
"""
from pathlib import Path
root=Path(__file__).resolve().parent
p=root/'video_cases.py';s=p.read_text(encoding='utf-8');assert '    def tick(self):' in s
s=s.replace('    def tick(self):','    def tick(self,lane=None):\n        if lane not in (None,\'data\',\'media\'):raise ValueError(\'Invalid case lane\')\n        lane_clause=" AND j.kind=\'kalodata\'" if lane==\'data\' else " AND j.kind<>\'kalodata\'" if lane==\'media\' else \'\'')
s=s.replace("WHERE (j.state='queued' OR (j.state='waiting' AND j.next_attempt<=?) OR (j.state='running' AND j.kind='metadata' AND j.remote_id IS NOT NULL)) ORDER BY j.updated LIMIT 1''',(time.time(),)).fetchone()", "WHERE (j.state='queued' OR (j.state='waiting' AND j.next_attempt<=?) OR (j.state='running' AND j.kind='metadata' AND j.remote_id IS NOT NULL))'''+lane_clause+\" ORDER BY CASE WHEN j.kind='kalodata' THEN 0 ELSE 1 END,j.updated LIMIT 1\",(time.time(),)).fetchone()")
s=s.replace("                    result=fetch_kalodata(self.kalodata,case,json.loads(job['options']))", "                    self.checkpoint(job['id'],'按视频ID获取平台指标；不等待视频下载与AI')\n                    result=fetch_kalodata(self.kalodata,case,json.loads(job['options']))")
s=s.replace("self.fail(job['id'],msg,exc.code if isinstance(exc,QueryError) else None)","self.fail(job['id'],msg,(exc.code or exc.reason) if isinstance(exc,QueryError) else None)")
s=s.replace("    def loop(self):\n        while not self.hub.stop.is_set():\n            try:self.tick()", "    def data_loop(self):\n        # Separate single serial data lane: slow media/ASR/AI cannot block the next link's metrics.\n        # 1 request at a time, <=1 new request/second; no retries/paid call in GET handlers.\n        while not self.hub.stop.is_set():\n            try:self.tick('data')\n            except Exception:logging.getLogger(__name__).exception('案例数据快通道检查失败')\n            self.hub.stop.wait(1)\n    def loop(self):\n        while not self.hub.stop.is_set():\n            try:self.tick('media')")
s=s.replace("        row['metrics']=metric_projection(row);", "        from video_case_commercial import projection as commercial_projection\n        from video_case_data_status import projection as data_status\n        row['commercial']=commercial_projection(row)\n        row['data_status']=data_status(row)\n        row['metrics']=metric_projection(row);")
s=s.replace("'已保存；新TikTok案例自动排队Kalodata取数和AI初填，重复案例不重跑'", "'已保存；正在按视频ID优先取数，返回即显示；视频下载与AI后台继续。未收录会明确提示，不保证即时有数据；重复案例不重跑'")
p.write_text(s,encoding='utf-8')
p=root/'app.py';s=p.read_text(encoding='utf-8');assert '        case_data_thread = None' not in s
s=s.replace('        case_thread = None','        case_thread = None\n        case_data_thread = None')
s=s.replace('            app.state.video_cases.recover()','            app.state.video_cases.recover()\n            case_data_thread=threading.Thread(target=app.state.video_cases.data_loop,name=\'case-data-lane\',daemon=True)\n            case_data_thread.start()')
s=s.replace('        if case_thread:\n            case_thread.join(3)','        if case_thread:\n            case_thread.join(3)\n        if case_data_thread:\n            case_data_thread.join(35)')
p.write_text(s,encoding='utf-8')
p=root/'video_case_kalodata.py';s=p.read_text(encoding='utf-8')
s=s.replace("from video_case_skill import detail_body,coerce_numbers,flatten_rich_text", "from video_case_skill import detail_body,coerce_numbers,flatten_rich_text\n    from video_case_commercial import date_text")
s=s.replace("'provider':'Kalodata','data_type':'third_party_estimate'", "'provider':'Kalodata','endpoint':'/video/detail','data_type':'third_party_estimate'")
s=s.replace("'title':flatten_rich_text(detail.get('video_title'))[:10000],'handle':handle,", "'title':flatten_rich_text(detail.get('video_title'))[:10000],'handle':handle,\n        'creator_id':str(detail.get('belonged_creator_id')) if str(detail.get('belonged_creator_id','')).isdigit() else None,\n        'publish_date':date_text(detail.get('publish_date')),'creator_debut':date_text(detail.get('creator_debut')),")
s=s.replace("('revenue_growth_rate','ads_roas','ad_revenue_ratio','ad_view_ratio')", "('ads_roas','ad_revenue_ratio','ad_view_ratio','ads_views','ads_period','ad_cpa')")
s=s.replace("    result['provider_flags']=", "    growth=number(detail.get('revenue_growth_rate'));result['extra_metrics']['revenue_growth_rate']=growth if growth is not None and abs(growth)<1e16 else None\n    for key in ('ad_view_ratio','ad_revenue_ratio'):\n        value=result['extra_metrics'][key]\n        if value is not None and value>1:result['extra_metrics'][key]=None\n    result['provider_flags']=")
s=s.replace("('ad','ai_video','creator_debut')", "('ad','ai_video')")
p.write_text(s,encoding='utf-8')
p=root/'video_case_fields.py';s=p.read_text(encoding='utf-8')
s=s.replace("facts={'title':kd.get('title'),'publisher':kd.get('handle')}", "from video_case_commercial import date_text\n    published_kd=date_text(kd.get('publish_date')) or date_text(kd.get('creator_debut'))\n    facts={'title':kd.get('title'),'publisher':kd.get('handle'),'published_at':published_kd}")
s=s.replace("value=facts[key];origin='Kalodata';evidence=", "value=facts[key];origin='Kalodata';evidence=")
s=s.replace("        elif public.get(key)","        elif public.get(key)")
s=s.replace("        if key=='merchant_visible'", "        if key=='published_at' and origin=='Kalodata':evidence+='；平台市场时间，未附UTC偏移，不擅自换算'\n        if key=='merchant_visible'")
p.write_text(s,encoding='utf-8')
