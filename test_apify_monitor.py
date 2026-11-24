from test_kalodata_integration import Tests as Fixture, HEADERS
import unittest
from unittest.mock import patch
class Tests(unittest.TestCase):
    setUp=Fixture.setUp
    tearDown=Fixture.tearDown
    def test_owner_dedup_snapshot_and_recovery(self):
        self.a.post('/api/intelligence/apify/config',headers=HEADERS,json={'secret_key':'test-token-only'})
        account=self.a.post('/api/intelligence/apify/accounts',headers=HEADERS,json={'handle':'@tooltime93'}).json()['id']
        self.assertFalse(self.b.get('/api/intelligence/apify/accounts').json()[0]['is_owner'])
        self.assertEqual(self.b.post('/api/intelligence/apify/accounts/'+account+'/collect',headers=HEADERS,json={'allow_paid':True}).status_code,404)
        service=self.app.state.apify_monitor
        rid=service.queue(account)
        self.assertEqual(service.queue(account),rid)
        with patch.object(service,'request',return_value={'data':{'id':'remote1'}}) as upstream:
            service.tick();self.assertEqual(upstream.call_count,1)
        item={'id':'123456789','authorMeta':{'name':'tooltime93'},'createTime':__import__('time').time(),'text':'demo','playCount':100}
        with patch.object(service,'request',side_effect=[{'data':{'status':'SUCCEEDED','defaultDatasetId':'dataset1'}},[item]]):service.tick()
        videos=self.a.get('/api/intelligence/apify/accounts/'+account+'/videos').json()
        self.assertEqual(videos[0]['views'],100);self.assertIsNone(videos[0]['growth'])
        rid2=service.queue(account)
        item['playCount']=150
        service.ingest({'id':rid2,'account':account},[item])
        videos=self.a.get('/api/intelligence/apify/accounts/'+account+'/videos').json()
        self.assertEqual(videos[0]['growth'],50)
        rid3=service.queue(account)
        with self.hub.db() as db:db.execute("UPDATE apify_runs SET state='submitting' WHERE id=?",(rid3,))
        service.recover()
        with patch.object(service,'request') as upstream:service.tick();upstream.assert_not_called()

    def test_selection_api_owner_isolation_and_persistence(self):
        aid=self.a.post('/api/intelligence/apify/accounts',headers=HEADERS,json={'handle':'selectiontest'}).json()['id']
        path='/api/intelligence/apify/accounts/'+aid+'/selection'
        self.assertEqual(self.a.get('/api/intelligence/apify/selection').json()['accounts'],[])
        self.assertEqual(self.b.post(path,headers=HEADERS,json={'selected':True}).status_code,404)
        self.assertEqual(self.a.post(path,headers=HEADERS,json={'selected':'yes'}).status_code,400)
        self.assertEqual(self.a.post(path,headers=HEADERS,json={'selected':True}).status_code,200)
        self.assertEqual(self.a.get('/api/intelligence/apify/selection').json()['accounts'],[aid])
        self.assertEqual(self.b.get('/api/intelligence/apify/selection').json()['accounts'],[])
        self.assertEqual(self.a.post(path,headers=HEADERS,json={'selected':False}).status_code,200)
        self.assertEqual(self.a.get('/api/intelligence/apify/selection').json()['accounts'],[])

    def test_date_window_batch_and_schedule(self):
        from apify_monitor import options,window
        from datetime import datetime,timezone
        start,end=window(options({'mode':'today'}),datetime(2026,11,1,12,tzinfo=timezone.utc))
        self.assertEqual(end-start,25*3600)
        # 单次抓取不再有条数选项：残留的 limit 被丢弃，也不参与校验。
        self.assertNotIn('limit',options({'mode':'today','limit':30}))
        self.assertNotIn('limit',options({'mode':'seven','limit':7}))
        with self.assertRaises(Exception):options({'mode':'custom','start':'2026-11-04','end':'2026-11-01'})
        self.a.post('/api/intelligence/apify/config',headers=HEADERS,json={'secret_key':'test-token-only'})
        ids=[self.a.post('/api/intelligence/apify/accounts',headers=HEADERS,json={'handle':'demo'+str(i)}).json()['id'] for i in range(10)]
        data={'accounts':ids,'allow_paid':True,'options':{'mode':'today','timezone':'Asia/Shanghai','limit':100}}
        self.assertEqual(self.b.post('/api/intelligence/apify/batch',headers=HEADERS,json=data).status_code,404)
        response=self.a.post('/api/intelligence/apify/batch',headers=HEADERS,json=data)
        self.assertEqual(response.status_code,200)
        response=response.json()
        # 同一批账号重复提交会被拒绝，避免同一批账号重复计费。
        self.assertEqual(self.a.post('/api/intelligence/apify/batch',headers=HEADERS,json=data).status_code,400)
        self.assertEqual(self.a.post('/api/intelligence/apify/batch',headers=HEADERS,json={**data,'accounts':ids+['extra']}).status_code,404)
        # 勾选账号合并成一次远程任务：不再按账号逐个提交，也没有 10 个账号的上限。
        self.assertEqual(response['accounts'],10)
        self.assertEqual(response['max_charge'],10.0)
        with self.hub.db() as db:
            batches=db.execute('SELECT * FROM grouped_runs').fetchall()
            members=db.execute('SELECT COUNT(*) FROM grouped_run_members').fetchone()[0]
            runs=db.execute('SELECT COUNT(*) FROM apify_runs').fetchone()[0]
        self.assertEqual((len(batches),members,runs),(1,10,0))
        self.assertEqual(batches[0]['end_at']-batches[0]['start_at'],86400)
        path='/api/intelligence/apify/accounts/'+ids[0]+'/schedule'
        self.assertEqual(self.a.post(path,headers=HEADERS,json={'hours':6,'allow_paid':True,'options':data['options']}).status_code,200)
        rows=self.a.get('/api/intelligence/apify/accounts').json()
        self.assertIn('Asia/Shanghai',next(a for a in rows if a['id']==ids[0])['options'])

    def test_submit_ignores_item_cap_and_pulls_whole_range(self):
        import json
        from apify_monitor import MAX_ITEMS
        self.a.post('/api/intelligence/apify/config',headers=HEADERS,json={'secret_key':'test-token-only'})
        aid=self.a.post('/api/intelligence/apify/accounts',headers=HEADERS,json={'handle':'@nocap'}).json()['id']
        service=self.app.state.apify_monitor
        # 旧调用方仍带 limit 也不影响：队列里存的是「按日期全量」。
        rid=service.queue(aid,{'mode':'custom','timezone':'Asia/Shanghai','start':'2026-10-01','end':'2026-10-31','limit':30})
        with self.hub.db() as db:
            stored=json.loads(db.execute('SELECT options FROM apify_runs WHERE id=?',(rid,)).fetchone()[0])
        self.assertNotIn('limit',stored)
        with patch.object(service,'request',return_value={'data':{'id':'remote-nocap'}}) as upstream:
            service.tick()
        params=upstream.call_args.kwargs['params']
        self.assertEqual(params['maxItems'],MAX_ITEMS)
        self.assertGreaterEqual(params['maxTotalChargeUsd'],1.0)
        payload=upstream.call_args.kwargs['json']
        self.assertEqual(payload['profiles'],['nocap'])
        self.assertEqual(payload['oldestPostDateUnified'],'2026-10-01')
        self.assertEqual(payload['newestPostDate'],'2026-10-31')
        self.assertEqual(payload['resultsPerPage'],1000000)
        # 取数据集同样是全量上限，而不是 30 条。
        with patch.object(service,'request',side_effect=[{'data':{'status':'SUCCEEDED','defaultDatasetId':'d1'}},[]]) as up2:
            service.tick()
        self.assertEqual(up2.call_args_list[1].kwargs['params']['limit'],MAX_ITEMS)

    def test_fixed_times_schedule_runs_only_at_slots(self):
        import time
        from apify_monitor import SCHEDULE_TZ
        from datetime import datetime
        self.a.post('/api/intelligence/apify/config',headers=HEADERS,json={'secret_key':'test-token-only'})
        aid=self.a.post('/api/intelligence/apify/accounts',headers=HEADERS,json={'handle':'@times1'}).json()['id']
        path='/api/intelligence/apify/accounts/'+aid+'/schedule'
        service=self.app.state.apify_monitor
        # 参数校验：需要确认费用、时间必须 HH:MM（1–4 个）
        self.assertEqual(self.a.post(path,headers=HEADERS,json={'times':['08:00','17:00']}).status_code,400)
        self.assertEqual(self.a.post(path,headers=HEADERS,json={'times':['8:00'],'allow_paid':True}).status_code,400)
        self.assertEqual(self.a.post(path,headers=HEADERS,json={'times':[],'allow_paid':True}).status_code,400)
        self.assertEqual(self.a.post(path,headers=HEADERS,json={'times':['08:00','17:00'],'allow_paid':True}).status_code,200)
        rows=self.a.get('/api/intelligence/apify/accounts').json()
        me=next(a for a in rows if a['id']==aid)
        self.assertEqual(me['times'],['08:00','17:00']);self.assertEqual(me['interval_hours'],0)
        with self.hub.db() as db:
            next_at=db.execute('SELECT next_at FROM apify_accounts WHERE id=?',(aid,)).fetchone()[0]
        stamp=datetime.fromtimestamp(next_at,SCHEDULE_TZ)
        self.assertIn(stamp.strftime('%H:%M'),('08:00','17:00'))
        self.assertGreater(next_at,time.time())
        # 全局关闭时，旧定时不能创建新任务；开启后仅选中账号到点入组合队列。
        self.a.post('/api/intelligence/apify/accounts/'+aid+'/selection',headers=HEADERS,json={'selected':True})
        with self.hub.db() as db:db.execute('UPDATE apify_accounts SET next_at=? WHERE id=?',(time.time()-1,aid))
        with patch.object(service,'request') as upstream:
            service.tick();upstream.assert_not_called()
            with self.hub.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM grouped_runs').fetchone()[0],0)
            self.a.post('/api/intelligence/apify/automation',headers=HEADERS,json={'collection':True,'confirmed':True})
            service.automation_tick();upstream.assert_not_called()
        with self.hub.db() as db:
            after=db.execute('SELECT next_at,times FROM apify_accounts WHERE id=?',(aid,)).fetchone()
        self.assertGreater(after['next_at'],time.time()+60)
        self.assertIn(datetime.fromtimestamp(after['next_at'],SCHEDULE_TZ).strftime('%H:%M'),('08:00','17:00'))
        # 切回固定间隔要清掉定点，避免重复触发
        self.assertEqual(self.a.post(path,headers=HEADERS,json={'hours':12,'allow_paid':True}).status_code,200)
        self.assertIsNone(next(a for a in self.a.get('/api/intelligence/apify/accounts').json() if a['id']==aid)['times'])
        # 全局关闭会取消尚未提交的自动合并任务。
        self.a.post('/api/intelligence/apify/automation',headers=HEADERS,json={'collection':False})
        # 关闭定时
        self.assertEqual(self.a.post(path,headers=HEADERS,json={'hours':0}).status_code,200)
        with self.hub.db() as db:db.execute("UPDATE apify_runs SET state='attention' WHERE account=?",(aid,))
        with patch.object(service,'queue') as queue,patch.object(service,'request') as upstream:
            service.tick();queue.assert_not_called();upstream.assert_not_called()

    def test_schedule_locks_range_to_rolling_two_days(self):
        import json
        from datetime import datetime,timezone
        from apify_monitor import options,window
        # 滚动窗口＝昨天+今天：定时跑到点才计算，日期每跑一次都会往后挪
        day=window(options({'mode':'rolling','timezone':'Asia/Shanghai'}),datetime(2026,11,5,12,tzinfo=timezone.utc))
        self.assertEqual(day[1]-day[0],2*86400)
        self.assertEqual(datetime.fromtimestamp(day[0],timezone.utc).strftime('%m-%d %H:%M'),'11-03 16:00')
        self.assertEqual(window(options({'mode':'today','timezone':'Asia/Shanghai'}),datetime(2026,11,5,12,tzinfo=timezone.utc))[1]-window(options({'mode':'today','timezone':'Asia/Shanghai'}),datetime(2026,11,5,12,tzinfo=timezone.utc))[0],86400)
        self.a.post('/api/intelligence/apify/config',headers=HEADERS,json={'secret_key':'test-token-only'})
        aid=self.a.post('/api/intelligence/apify/accounts',headers=HEADERS,json={'handle':'@rolling1'}).json()['id']
        path='/api/intelligence/apify/accounts/'+aid+'/schedule'
        # 定时开启时即便前端传「近 7 天」，落库也必须是滚动 2 天，否则每 12 小时重买 7 天
        self.assertEqual(self.a.post(path,headers=HEADERS,json={'times':['08:00','17:00'],'allow_paid':True,'options':{'mode':'seven','timezone':'America/New_York'}}).status_code,200)
        with self.hub.db() as db:
            saved=json.loads(db.execute('SELECT options FROM apify_accounts WHERE id=?',(aid,)).fetchone()[0])
        self.assertEqual(saved['mode'],'rolling');self.assertEqual(saved['timezone'],'America/New_York')
        aid2=self.a.post('/api/intelligence/apify/accounts',headers=HEADERS,json={'handle':'@rolling2'}).json()['id']
        path2='/api/intelligence/apify/accounts/'+aid2+'/schedule'
        self.assertEqual(self.a.post(path2,headers=HEADERS,json={'hours':12,'allow_paid':True,'options':{'mode':'seven'}}).status_code,200)
        with self.hub.db() as db:
            self.assertEqual(json.loads(db.execute('SELECT options FROM apify_accounts WHERE id=?',(aid2,)).fetchone()[0])['mode'],'rolling')
        # 关掉定时把范围交还给用户：残留的 rolling 归位成今天，避免手动采集也锁死在滚动窗口
        self.assertEqual(self.a.post(path2,headers=HEADERS,json={'hours':0,'options':{'mode':'rolling'}}).status_code,200)
        with self.hub.db() as db:
            self.assertEqual(json.loads(db.execute('SELECT options FROM apify_accounts WHERE id=?',(aid2,)).fetchone()[0])['mode'],'today')
        with self.hub.db() as db:db.execute("UPDATE apify_runs SET state='attention' WHERE account IN (?,?)",(aid,aid2))

    def test_grouped_run_submits_once_and_splits_by_account(self):
        import time
        self.a.post('/api/intelligence/apify/config',headers=HEADERS,json={'secret_key':'test-token-only'})
        ids=[self.a.post('/api/intelligence/apify/accounts',headers=HEADERS,json={'handle':'mix'+str(i)}).json()['id'] for i in range(3)]
        data={'accounts':ids,'allow_paid':True,'options':{'mode':'today','timezone':'Asia/Shanghai'}}
        self.assertEqual(self.a.post('/api/intelligence/apify/batch',headers=HEADERS,json={**data,'allow_paid':False}).status_code,400)
        self.assertEqual(self.a.post('/api/intelligence/apify/batch',headers=HEADERS,json=data).status_code,200)
        service=self.app.state.apify_monitor
        # 采集窗口是「今天」，样本必须落在窗口内，否则会被窗口校验丢掉。
        published=time.time()-600
        items=[{'id':'111','authorMeta':{'name':'mix0'},'createTime':published,'playCount':10},
               {'id':'222','authorMeta':{'name':'mix1'},'createTime':published,'playCount':5}]
        with patch.object(service,'request',side_effect=[{'data':{'id':'group1'}},{'data':{'status':'SUCCEEDED','defaultDatasetId':'dd'}},items]) as upstream:
            self.assertTrue(service.group_tick())    # 提交：一次远程任务
            service.group_tick()                     # 取回：按账号拆开
        self.assertEqual(upstream.call_count,3)
        first=upstream.call_args_list[0]
        # 单次合并任务：账号全部进一个 profiles 列表，费用熔断 10 美元。
        self.assertEqual(sorted(first.kwargs['json']['profiles']),['mix0','mix1','mix2'])
        self.assertEqual(first.kwargs['params']['maxTotalChargeUsd'],10.0)
        with self.hub.db() as db:
            batch=db.execute('SELECT * FROM grouped_runs').fetchone()
            self.assertEqual(batch['state'],'ready')
            states={r[0]:r[1] for r in db.execute('SELECT account,state FROM apify_runs')}
        self.assertEqual(len(states),3)
        self.assertTrue(all(state=='ready' for state in states.values()))
        videos=self.a.get('/api/intelligence/apify/accounts/'+ids[0]+'/videos').json()
        self.assertEqual(videos[0]['video'],'111')
        # 已经完成的合并任务不会被重复提交。
        with patch.object(service,'request') as again:
            self.assertFalse(service.group_tick());again.assert_not_called()

    def test_grouped_submit_failure_never_retries(self):
        self.a.post('/api/intelligence/apify/config',headers=HEADERS,json={'secret_key':'test-token-only'})
        ids=[self.a.post('/api/intelligence/apify/accounts',headers=HEADERS,json={'handle':'fail'+str(i)}).json()['id'] for i in range(2)]
        self.a.post('/api/intelligence/apify/batch',headers=HEADERS,json={'accounts':ids,'allow_paid':True,'options':{'mode':'today'}})
        service=self.app.state.apify_monitor
        with patch.object(service,'request',side_effect=ValueError('Apify 网络异常；提交结果可能不明确，请核对控制台')) as upstream:
            service.group_tick();service.group_tick()
        self.assertEqual(upstream.call_count,1)
        with self.hub.db() as db:
            batch=db.execute('SELECT * FROM grouped_runs').fetchone()
            members=db.execute('SELECT state FROM grouped_run_members').fetchall()
        self.assertEqual(batch['state'],'attention')
        self.assertIn('未自动重试',batch['error'])
        self.assertTrue(all(r[0]=='attention' for r in members))

    def test_automation_defaults_off_and_selection_persists(self):
        self.a.post('/api/intelligence/apify/config',headers=HEADERS,json={'secret_key':'test-token-only'})
        aid=self.a.post('/api/intelligence/apify/accounts',headers=HEADERS,json={'handle':'auto1'}).json()['id']
        state=self.a.get('/api/intelligence/apify/automation').json()
        # 新自动化默认关闭：不确认就不能打开。
        self.assertEqual((state['collection'],state['enrichment'],state['selected']),(False,False,0))
        self.assertEqual(self.a.post('/api/intelligence/apify/automation',headers=HEADERS,json={'collection':True}).status_code,400)
        self.assertEqual(self.a.post('/api/intelligence/apify/automation',headers=HEADERS,json={'collection':True,'confirmed':True}).status_code,200)
        # 勾选状态落库：刷新页面仍然记得，且其他用户改不了。
        self.assertEqual(self.a.post('/api/intelligence/apify/accounts/'+aid+'/selection',headers=HEADERS,json={'selected':True}).json(),{'selected':True})
        self.assertTrue(next(a for a in self.a.get('/api/intelligence/apify/accounts').json() if a['id']==aid)['selected'])
        self.assertEqual(self.a.get('/api/intelligence/apify/automation').json()['selected'],1)
        self.assertEqual(self.b.post('/api/intelligence/apify/accounts/'+aid+'/selection',headers=HEADERS,json={'selected':True}).status_code,404)
        self.assertEqual(self.a.post('/api/intelligence/apify/accounts/'+aid+'/selection',headers=HEADERS,json={'selected':'yes'}).status_code,400)
        self.assertEqual(self.a.post('/api/intelligence/apify/accounts/'+aid+'/selection',headers=HEADERS,json={'selected':False}).json(),{'selected':False})

    def test_auto_collection_groups_only_selected_due_accounts(self):
        import time
        self.a.post('/api/intelligence/apify/config',headers=HEADERS,json={'secret_key':'test-token-only'})
        ids=[self.a.post('/api/intelligence/apify/accounts',headers=HEADERS,json={'handle':'due'+str(i)}).json()['id'] for i in range(3)]
        skipped=self.a.post('/api/intelligence/apify/accounts',headers=HEADERS,json={'handle':'duex'}).json()['id']
        for aid in ids:
            self.a.post('/api/intelligence/apify/accounts/'+aid+'/selection',headers=HEADERS,json={'selected':True})
        self.a.post('/api/intelligence/apify/automation',headers=HEADERS,json={'collection':True,'confirmed':True})
        with self.hub.db() as db:
            db.execute("UPDATE apify_accounts SET times='[\"08:00\"]',next_at=?",(time.time()-60,))
        service=self.app.state.apify_monitor
        # 到点只是合并排队，不直接发起付费请求。
        with patch.object(service,'request') as upstream:
            service.automation_tick();upstream.assert_not_called()
        with self.hub.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM grouped_runs').fetchone()[0],1)
            members={r[0] for r in db.execute('SELECT account FROM grouped_run_members')}
            self.assertEqual(len(members),3)
            self.assertNotIn(skipped,members)
            # 排队后 next_at 推到下一定点，不会每个 tick 重复排队。
            placeholders=','.join('?'*len(ids))
            self.assertGreater(db.execute('SELECT MIN(next_at) FROM apify_accounts WHERE id IN ('+placeholders+')',ids).fetchone()[0],time.time())
        service.automation_tick()
        with self.hub.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM grouped_runs').fetchone()[0],1)
