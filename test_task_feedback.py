"""Regression and synthetic UI data for the two section-scoped feedback paths."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import task_feedback as feedback
from a6_video import VideoOutcomeUnknown, read_video
from exception_center import safe_error
from test_own_goods import BASE, CASE, HEADERS, VIDEO, fixture


EXCEPTIONS='/api/intelligence/exceptions'
STUDIO='/api/studio/task-feedback'
VIDEO_ID=VIDEO.rsplit('/',1)[1]


def issue(hub,kind,task,stage,state,http=None,code=None):
    with feedback.bound(hub,kind,task), feedback.step(stage) as observed:
        observed.http(http);observed.code(code);observed.mark(state)


def seed_feedback(app,owner='fixture_a',extra=0):
    """Synthetic tasks only. No workers, clients, downloads or vendor submission."""
    hub=app.state.hub;now=time.time()
    with hub.db() as db:
        db.executemany('INSERT INTO accounts(id,name,scope,owner,secret) VALUES(?,?,?,?,?)',[
            ('fixture-shared','示例公司账号','shared','fixture_admin',b'fixture-only'),
            ('fixture-personal','历史个人账号','personal',owner,b'fixture-only')])
        db.executemany('''INSERT INTO tasks(id,owner,account_id,prompt,state,created,updated,request_key,error)
                          VALUES(?,?,?,'隔离预览示例',?,?,?,?,?)''',[
            ('fixture-video-unknown',owner,'fixture-shared','unknown',now,now,'request-unknown','提交超时，尚未确认平台是否创建任务'),
            ('fixture-video-blocked',owner,'fixture-shared','failed',now-2,now-2,'request-blocked','当前账号额度不足；未提交生成'),
            ('fixture-video-private',owner,'fixture-personal','closed',now-4,now-4,'request-private','')])
        payload=json.dumps({'prompt':'隔离预览示例','model':'star-video2','duration':5})
        db.executemany('''INSERT INTO libtv_jobs(id,owner,request_key,payload,state,stage,created,updated,error,retry_at)
                          VALUES(?,?,?,?,?,?,?,?,?,?)''',[
            ('fixture-libtv-fail',owner,'request-libtv-fail',payload,'failed','生成失败',now-1,now-1,'LibTV 生成未通过安全审核',0),
            ('fixture-libtv-old',owner,'request-libtv-old',payload,'attention','成片校验与入库',now-3,now-3,'历史成片校验失败',0),
            ('fixture-libtv-wait',owner,'request-libtv-wait',payload,'attention','等待自动取回',now-5,now-5,'LibTV 仍在生成中，中台稍后自动取回',now+30)])
        db.execute("INSERT INTO apify_accounts(id,owner,handle) VALUES(?,?,?)",('fixture-monitor',owner,'fixture_creator'))
        db.execute("INSERT INTO apify_runs(id,account,state,created,updated,error) VALUES(?,?,'attention',?,?,?)",('fixture-apify','fixture-monitor',now+3,now+3,'Apify 额度不足'))
        db.executemany('''INSERT INTO video_case_jobs(id,case_id,owner,kind,state,request_key,created,updated,error,error_code)
                          VALUES(?,?,?,?,?,?,?,?,?,?)''',[
            ('fixture-case-ai',CASE,'fixture_a','analysis','attention','request-case-ai',now+1,now+1,'AI 请求结果未知；未自动重试',''),
            ('fixture-case-wait',CASE,'fixture_a','analysis','waiting','request-case-wait',now-6,now-6,'等待供应商缓存','1054')])
        db.executemany('''INSERT INTO comment_sample_jobs(video,url,origin,state,ai_state,created,updated,finished,error,ai_error)
                         VALUES(?,?,'case',?,?,?,?,?,?,?)''',[
            (VIDEO_ID,VIDEO,'partial','attention',now+2,now+2,now+2,'回复页请求结果未知；未自动重试','AI 返回证据编号不可验证'),
            ('999999999','https://example.invalid/not-a-case','attention','attention',now,now,now,'不应公开的非案例错误','')])
        db.execute('''INSERT INTO comment_sample_research(video,state,payload,error,updated) VALUES(?,'attention','{}',?,?)''',
                   (VIDEO_ID,'未返回可核验的多维标注',now))
        for i in range(extra):
            db.execute("INSERT INTO apify_runs(id,account,state,created,updated,error) VALUES(?,?,'attention',?,?,?)",
                       (f'fixture-history-{i:03d}','fixture-monitor',now-10-i,now-10-i,'旧采集只保留任务级报错'))
    issue(hub,'tiktok','fixture-video-unknown','submit','unknown')
    issue(hub,'tiktok','fixture-video-blocked','quota','blocked')
    issue(hub,'tiktok','fixture-video-private','poll','ok')
    issue(hub,'libtv','fixture-libtv-fail','libtv_probe','failed',code=10001)
    issue(hub,'libtv','fixture-libtv-wait','libtv_probe','unknown')
    issue(hub,'apify_run','fixture-apify','apify_response','failed',402)
    with feedback.bound(hub,'comment_collect',VIDEO_ID):
        with feedback.step('comment_page') as a:
            a.http(200);a.credits(1)
        with feedback.step('reply_page') as a:
            a.error_type('ReadTimeout');a.mark('unknown')
    issue(hub,'case_analysis','fixture-case-ai','ai_call','unknown',503)
    issue(hub,'case_analysis','fixture-case-wait','media_url','waiting',200,1054)
    issue(hub,'comment_ai',VIDEO_ID,'ai_validate','attention',200)
    issue(hub,'comment_research',VIDEO_ID,'ai_validate','attention')


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        env=patch.dict(os.environ,{'HUB_ORIGIN':BASE});env.start();self.addCleanup(env.stop)
        self.app=fixture(tmp.name);self.hub=self.app.state.hub
        self.a,self.b,self.admin,self.anon=[TestClient(self.app,base_url=BASE) for _ in range(4)]
        for c in (self.a,self.b,self.admin,self.anon):self.addCleanup(c.close)
        for c,u in ((self.a,'fixture_a'),(self.b,'fixture_b'),(self.admin,'fixture_admin')):
            self.assertEqual(c.post('/api/login',headers=HEADERS,json={'username':u,'password':'isolated-fixture-password'}).status_code,200)
        seed_feedback(self.app)

    def test_studio_access_outcome_and_legacy(self):
        path=STUDIO+'/tiktok/fixture-video-unknown'
        self.assertEqual(self.anon.get(path).status_code,401)
        self.assertEqual(self.b.get(path).status_code,404)
        for client in (self.a,self.admin):
            row=client.get(path).json()['items'][0]
            self.assertEqual((row['stage'],row['outcome'],row['http_status']),('提交视频生成','unknown',None))
        self.assertEqual(self.admin.get(STUDIO+'/tiktok/fixture-video-private').status_code,404)
        self.assertEqual(self.admin.get(STUDIO+'/libtv/fixture-libtv-fail').status_code,404)
        self.assertEqual(self.a.get(STUDIO+'/libtv/fixture-libtv-old').json(),{'items':[]})
        t={r['id']:r for r in self.a.get('/api/tasks?compact=true').json()}
        self.assertEqual(t['fixture-video-blocked']['feedback_state'],'blocked')
        self.assertEqual(t['fixture-video-unknown']['feedback_state'],'unknown')
        l={r['id']:r for r in self.a.get('/api/libtv/jobs').json()}
        self.assertEqual(l['fixture-libtv-fail']['feedback']['provider_code'],'10001')
        self.assertEqual(l['fixture-libtv-wait']['feedback_state'],'waiting')
        self.assertIsNone(l['fixture-libtv-wait']['feedback'])
        self.assertNotIn('retry_at',l['fixture-libtv-wait'])

    def test_exceptions_scope_and_partial_waiting_rules(self):
        self.assertEqual(self.anon.get(EXCEPTIONS).status_code,401)
        r=self.a.get(EXCEPTIONS);self.assertEqual(r.status_code,200,r.text)
        data=r.json();self.assertEqual(len(data['types']),16)
        self.assertIn({'type':'own_goods_lookup','kind':'自营商品取数'},data['types'])
        items={x['type']:x for x in data['items']}
        self.assertEqual(set(items),{'apify_run','case_analysis','comment_collect','comment_ai','comment_research'})
        self.assertEqual(items['apify_run']['feedback']['http_status'],402)
        self.assertEqual(items['apify_run']['feedback_state'],'failed')
        self.assertEqual((items['comment_collect']['state'],items['comment_collect']['feedback_state']),('partial','unknown'))
        self.assertEqual(items['comment_collect']['case_id'],CASE)
        self.assertEqual(items['comment_collect']['feedback']['stage'],'获取回复页')
        details=self.b.get(EXCEPTIONS+f'/comment_collect/{VIDEO_ID}/feedback')
        self.assertEqual(details.status_code,200,details.text)
        self.assertEqual([x['credits'] for x in details.json()['items']],[None,1])
        self.assertEqual(self.b.get(EXCEPTIONS+'/apify_run/fixture-apify/feedback').status_code,404)
        self.assertEqual(self.admin.get(EXCEPTIONS+'/apify_run/fixture-apify/feedback').status_code,404)
        self.assertEqual(self.b.get(EXCEPTIONS+'/case_analysis/fixture-case-ai/feedback').status_code,200)
        self.assertEqual(self.b.get(EXCEPTIONS+'/case_analysis/fixture-case-wait/feedback').status_code,404)
        with self.hub.db() as db:
            db.execute("UPDATE comment_sample_jobs SET error='' WHERE video=?",(VIDEO_ID,))
        self.assertNotIn('comment_collect',{x['type'] for x in self.a.get(EXCEPTIONS).json()['items']})
        self.assertEqual(self.b.get(EXCEPTIONS+f'/comment_collect/{VIDEO_ID}/feedback').status_code,404)
        with self.hub.db() as db:
            db.execute("UPDATE users SET enabled=0 WHERE id='fixture_a'")
        self.assertEqual(self.b.get(EXCEPTIONS).json()['items'],[])
        with self.hub.db() as db:
            db.execute("UPDATE users SET enabled=1 WHERE id='fixture_a'")
            db.execute('UPDATE video_cases SET removed_at=? WHERE id=?',(time.time(),CASE))
        self.assertEqual(self.b.get(EXCEPTIONS+'/case_analysis/fixture-case-ai/feedback').status_code,404)
        self.assertEqual(self.b.get(EXCEPTIONS+f'/comment_ai/{VIDEO_ID}/feedback').status_code,404)

    def test_record_retention_and_failed_step_not_replaced_by_waiting(self):
        hub=self.hub
        for _ in range(18):issue(hub,'tiktok','fixture-video-unknown','submit','unknown')
        for _ in range(35):issue(hub,'tiktok','fixture-video-unknown','history','waiting')
        with hub.db() as db:events=feedback.timeline(db,'tiktok','fixture-video-unknown')
        self.assertEqual(len(events),48)
        self.assertEqual(sum(x['outcome']=='waiting' for x in events),32)
        self.assertTrue(all(x['reference'].startswith('FB-') for x in events))
        rows={x['id']:x for x in self.a.get('/api/tasks').json()}
        self.assertEqual(rows['fixture-video-unknown']['feedback']['stage'],'提交视频生成')

    def test_best_effort_write_never_changes_task_and_only_stores_fixed_fields(self):
        with self.hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            issue(self.hub,'tiktok','contention','submit','unknown')
            self.assertEqual(feedback.timeline(db,'tiktok','contention'),[])
        with feedback.bound(self.hub,'tiktok','safe'), feedback.step('submit') as a:
            a.code('RAW_PROVIDER_BODY');a.error_type('private response')
        with self.hub.db() as db:
            row=feedback.timeline(db,'tiktok','safe')[0]
        self.assertEqual(row['outcome'],'ok');self.assertIsNone(row['provider_code']);self.assertIsNone(row['error_type'])
        msg=safe_error('连接失败 token=secret-value https://private.invalid/a C:\\state\\secret\n错误摘要：raw-secret')
        for secret in ('secret-value','private.invalid','C:', 'raw-secret'):
            self.assertNotIn(secret,msg)

    def test_native_ai_timeout_has_one_request_and_no_payload_in_feedback(self):
        file=Path(self.hub.directory)/'fixture.mp4';file.write_bytes(b'\x00\x00\x00\x18ftypisomprivate-fixture-media')
        with patch('urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect=TimeoutError('private transport detail')
            with self.assertRaises(VideoOutcomeUnknown):
                with feedback.bound(self.hub,'case_analysis','fixture-case-ai'), feedback.step('ai_call'):
                    read_video('fake-private-key',file,'fake-private-prompt',True)
            opener.return_value.open.assert_called_once()
        r=self.b.get(EXCEPTIONS+'/case_analysis/fixture-case-ai/feedback')
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual((r.json()['items'][0]['outcome'],r.json()['items'][0]['error_type']),('unknown','TimeoutError'))
        self.assertNotIn('private',r.text)
