"""Isolated studio result fixtures and cross-channel relay regression."""
import json
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from test_own_goods import BASE, HEADERS, fixture
from test_task_feedback import seed_feedback
from workspace import validate_continuation

OWNER='fixture_a'
TIKTOK='fixture-tiktok-result'
LIBTV='fixture-libtv-result'
ASSET='fixture-libtv-video'


def seed_results(app):
    sample=Path(__file__).resolve().with_name('mobile-flow-test-input.mp4')
    if not sample.is_file():
        raise FileNotFoundError('Missing synthetic mobile-flow-test-input.mp4 fixture')
    hub=app.state.hub
    shutil.copyfile(sample,hub.media/(TIKTOK+'.mp4'))
    shutil.copyfile(sample,hub.assets/ASSET)
    now=time.time()
    def card(id,x):
        return dict(id=id,prompt='',mode='omni',model='auto',duration=5,count=1,assets=[],nextImage=1,request_key=id+'-draft',canvas_position=dict(x=x,y=0))
    cards=[card('fixture-card-tiktok',0),card('fixture-card-libtv',520)]
    with hub.db() as db:
        db.execute('INSERT INTO compositions VALUES(?,?,?)',(OWNER,json.dumps(cards),now))
        db.execute("INSERT INTO tasks(id,owner,account_id,prompt,state,created,updated,request_key,config,duration) VALUES(?,?,?,'TikTok fixture','ready',?,?,?,?,5)",(TIKTOK,OWNER,'fixture-shared',now,now,TIKTOK+'-req',json.dumps({'id':cards[0]['id']})))
        db.execute('INSERT INTO assets VALUES(?,?,?,?,?,?)',(ASSET,OWNER,'LibTV fixture.mp4','video/mp4',sample.stat().st_size,now))
        db.execute("INSERT INTO libtv_jobs(id,owner,request_key,payload,state,created,updated,asset_id) VALUES(?,?,?,?,'ready',?,?,?)",(LIBTV,OWNER,LIBTV+'-req',json.dumps(dict(prompt='LibTV fixture',model='star-video2',duration=5,composition_id=cards[1]['id'])),now,now,ASSET))


class StudioResultActionsTests(unittest.TestCase):
    def setUp(self):
        tmp=TemporaryDirectory();self.addCleanup(tmp.cleanup)
        env=patch.dict(os.environ,{'HUB_ORIGIN':BASE});env.start();self.addCleanup(env.stop)
        self.app=fixture(tmp.name);seed_feedback(self.app);seed_results(self.app);self.hub=self.app.state.hub
        def login(name):
            c=TestClient(self.app,base_url=BASE);self.addCleanup(c.close)
            r=c.post('/api/login',headers=HEADERS,json={'username':name,'password':'isolated-fixture-password'})
            self.assertEqual(r.status_code,200,r.text);return c
        self.owner=login(OWNER);self.other=login('fixture_b');self.admin=login('fixture_admin')

    def test_both_finished_results_are_local_relay_and_edit_sources(self):
        for tid in (TIKTOK,LIBTV):
            with self.subTest(tid=tid):
                r=self.owner.get('/api/media/source/'+tid);self.assertEqual(r.status_code,200,r.text)
                timepoint=max(0,r.json()['duration']-.2)
                r=self.owner.post('/api/media/extract',headers=HEADERS,json=dict(source_id=tid,kind='frame',time=timepoint))
                self.assertEqual(r.status_code,200,r.text);frame=r.json()
                self.assertTrue((self.hub.assets/frame['id']).read_bytes().startswith(b'\x89PNG'))
                item=dict(mode='omni',assets=[dict(id=frame['id'])],continuation=dict(source_id=tid,frame_id=frame['id']))
                with self.hub.db() as db:
                    validate_continuation(db,item,dict(id=OWNER,role='member'),None,self.hub)
                self.assertEqual(item['continuation']['frame_time'],frame['start'])
        self.assertTrue({TIKTOK,LIBTV}<={r['id'] for r in self.owner.get('/api/editor/library').json()['items']})
        self.assertEqual(len(self.owner.get('/api/tasks').json()),4)
        self.assertEqual(len(self.owner.get('/api/libtv/jobs').json()),4)

    def test_libtv_relay_does_not_expand_permissions_or_use_unfinished_results(self):
        for client in (self.other,self.admin):
            self.assertEqual(client.get('/api/media/source/'+LIBTV).status_code,400)
            self.assertEqual(client.post('/api/media/extract',headers=HEADERS,json=dict(source_id=LIBTV,kind='frame',time=0)).status_code,400)
        with self.hub.db() as db:
            for uid,role,tid in [('fixture_b','member',LIBTV),('fixture_admin','admin',LIBTV),(OWNER,'member','fixture-libtv-wait')]:
                with self.subTest(uid=uid,tid=tid),self.assertRaisesRegex(HTTPException,'接力来源不存在'):
                    validate_continuation(db,dict(continuation=dict(source_id=tid)),dict(id=uid,role=role),None,self.hub)
            with self.assertRaisesRegex(HTTPException,'请先从来源视频提取'):
                validate_continuation(db,dict(continuation=dict(source_id=LIBTV,frame_id='wrong')),dict(id=OWNER,role='member'),None,self.hub)
