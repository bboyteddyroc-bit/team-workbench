import json
import time
import unittest

import test_hub as fixtures
import video_retention as retention


class PromptRetentionTests(unittest.TestCase):
    setUp=fixtures.HubTests.setUp
    tearDown=fixtures.HubTests.tearDown
    login=fixtures.HubTests.login
    account=fixtures.HubTests.account

    def post(self, client, url, data):
        return client.post('/api'+url, json=data, headers=fixtures.H)

    def owners(self):
        return [client.get('/api/me').json()['id'] for client in (self.admin,self.member)]

    def test_shared_template_counts_submission_and_keeps_private_data_private(self):
        account=self.account(self.admin)
        result=self.post(self.member,'/prompt-templates',{'title':'门后安装','kind':'video','prompt':'安装细节'})
        self.assertEqual(result.status_code,200,result.text)
        ident=result.json()['id']
        detail='/api/prompt-templates/'+ident
        self.assertEqual(self.admin.get(detail).status_code,404)
        self.post(self.member,'/prompt-templates/'+ident+'/update',{'title':'门后安装','prompt':'安装细节','shared':True}).raise_for_status()
        self.assertEqual(self.admin.get(detail).json()['total'],0)
        payload={'account_id':account,'request_key':'test-template-batch-key','items':[
            {'prompt':'只给自己看的参数','template_id':ident,'count':2}
        ]}
        submitted=self.post(self.member,'/tasks',payload)
        self.assertEqual(submitted.status_code,200,submitted.text)
        self.assertEqual(self.post(self.member,'/tasks',payload).json(),submitted.json())
        self.assertEqual(self.member.get('/api/prompt-templates').json()[0]['uses'],1)
        self.assertEqual(self.member.get(detail).json()['total'],2)
        self.assertNotIn('只给自己看的参数',self.admin.get(detail).text)

    def test_image_template_survives_deleting_chat_and_does_not_share_references(self):
        owner=self.owners()[1]
        thread=self.post(self.member,'/assistant/threads',{}).json()['id']
        with self.hub.db() as db:
            db.execute("INSERT INTO assets VALUES(?,?,?,?,?,?)",('b'*32,owner,'result.png','image/png',10,time.time()))
            db.execute("""INSERT INTO ai_turns(id,owner,thread,request_key,prompt,status,created,generation,images,result_asset,result_assets)
                VALUES(?,?,?,?,?,'complete',?,?,?,?,?)""",
                ('a'*32,owner,thread,'req-template-image','磨砂产品图',time.time(),
                 '{"provider":"libtv","size":"1K","ratio":"9:16","count":1}',
                 '[{"name":"my-ref.png","url":"data:image/jpeg;base64,AAA="}]','b'*32,json.dumps(['b'*32])))
        saved=self.post(self.member,'/prompt-templates',{'title':'产品图','source':'image','job':'a'*32,'shared':True})
        self.assertEqual(saved.status_code,200,saved.text)
        url='/api/prompt-templates/'+saved.json()['id']
        self.assertEqual(self.member.get(url).json()['refs'][0]['name'],'my-ref.png')
        self.assertEqual(self.admin.get(url).json()['refs'],[])
        self.post(self.member,'/assistant/threads/'+thread+'/delete',{}).raise_for_status()
        result=self.member.get(url).json()['history'][0]
        self.assertEqual(result['refs'],[{'name':'my-ref.png'}])
        self.assertEqual(result['urls'],['/api/assets/'+'b'*32])

    def test_retention_grace_and_protected_references_then_expire(self):
        account=self.account(self.admin)
        owner=self.owners()[1]
        now=time.time()
        old=now-8*86400
        task='1'*24
        export_source='2'*24
        pinned='3'*24
        libtv='4'*32
        asset='5'*32
        uploaded='6'*32
        other='7'*24
        with self.hub.db() as db:
            db.execute('UPDATE video_retention_policy SET started=?',(now,))
            for job,when in ((task,old),(export_source,old),(pinned,old),(other,now-2*86400)):
                db.execute("""INSERT INTO tasks(id,owner,account_id,prompt,state,created,updated,request_key,config)
                    VALUES(?,?,?,?,'ready',?,?,?,'{}')""",(job,owner,account,'原提示词',when,when,job))
                (self.hub.media/(job+'.mp4')).write_bytes(b'generated')
            db.execute('INSERT INTO compositions VALUES(?,?,?)',(owner,json.dumps([{'continuation':{'source_id':export_source}}]),now))
            for oid in (asset,uploaded):
                db.execute('INSERT INTO assets VALUES(?,?,?,?,?,?)',(oid,owner,'demo.mp4','video/mp4',9,old))
                (self.hub.assets/oid).write_bytes(b'video')
            db.execute("""INSERT INTO libtv_jobs(id,owner,request_key,payload,state,created,updated,asset_id)
                VALUES(?,?,?,'{"prompt":"LibTV"}','ready',?,?,?)""",(libtv,owner,libtv,old,old,asset))
            db.execute('INSERT INTO edit_versions VALUES(?,?,?,?,?)',('project-demo',1,'测试工程',
                       json.dumps({'clips':[{'task_id':libtv}]}),old))
        pin={'source':'tiktok','job':pinned,'pin':True}
        self.assertEqual(self.post(self.admin,'/video-retention',pin).status_code,404)
        self.post(self.member,'/video-retention',pin).raise_for_status()
        saved=self.post(self.member,'/prompt-templates',{'source':'tiktok','job':task,'title':'原视频模板'}).json()['id']
        self.assertEqual(retention.mark_expired(self.hub,now),0)
        with self.hub.db() as db:db.execute('UPDATE video_retention_policy SET started=?',(old,))
        self.assertEqual(retention.mark_expired(self.hub,now),1)
        retention.delete_expired_files(self.hub)
        self.assertFalse((self.hub.media/(task+'.mp4')).exists())
        self.assertEqual(self.member.get('/api/tasks/'+task+'/video').status_code,404)
        self.assertTrue((self.hub.assets/asset).is_file())
        self.assertTrue((self.hub.assets/uploaded).is_file())
        self.assertTrue((self.hub.media/(export_source+'.mp4')).is_file())
        self.assertTrue((self.hub.media/(pinned+'.mp4')).is_file())
        self.assertTrue((self.hub.media/(other+'.mp4')).is_file())
        data=self.member.get('/api/prompt-templates/'+saved).json()
        self.assertEqual(data['history'][0]['state'],'expired')
        self.assertEqual(data['history'][0]['urls'],[])
        self.assertEqual(data['prompt'],'原提示词')
        with self.hub.db() as db:db.execute("DELETE FROM edit_versions WHERE project_id='project-demo'")
        self.assertEqual(retention.mark_expired(self.hub,now),1)
        retention.delete_expired_files(self.hub)
        self.assertFalse((self.hub.assets/asset).exists())
        with self.hub.db() as db:
            self.assertEqual(db.execute('SELECT state FROM libtv_jobs WHERE id=?',(libtv,)).fetchone()[0],'expired')
            self.assertIsNone(db.execute('SELECT 1 FROM assets WHERE id=?',(asset,)).fetchone())
