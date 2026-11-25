"""The image-only switch must not rebind production videos or existing image tasks."""
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from assistant_image_accounts import initialize, resolve_account, select_account, selected_profile
from libtv_isolation import environment
from test_assistant_chat import AssistantTests
from test_hub import BASE


class AssistantImageAccountTests(unittest.TestCase):
    setUp = AssistantTests.setUp
    tearDown = AssistantTests.tearDown
    login = AssistantTests.login
    post = AssistantTests.post

    def prepare(self):
        with self.hub.db() as db:
            db.execute('INSERT INTO libtv_settings VALUES (1,?)', ('42',))
            db.executemany('INSERT INTO libtv_profiles VALUES (?,?,?,?)', (
                ('image-b', '生图备用账号', '73', 1), ('image-c', '制作账号', '91', 1),
                ('disabled', '暂停账号', '99', 0)))
        tid = self.post(self.member, '/threads', {}).json()['id']
        return tid, self.member.get('/api/me').json()['id']

    def choose(self, profile, previous, account):
        with self.hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            return select_account(db, profile, previous, account)

    def image(self, tid, **extra):
        return self.post(self.member, '/threads/'+tid+'/send', {
            'text': 'mock image', 'mode': 'image', 'request_key': 'image-profile-request-001', **extra})

    def recovery(self, tid, turn):
        return self.post(self.member, f'/threads/{tid}/turns/{turn}/recover', {})

    def assert_profile(self, cwd, profile):
        self.assertEqual(json.loads((Path(cwd)/'hub-libtv-profile.json').read_text())['profile'],profile)

    def save_download(self, args):
        Image.new('RGB',(9,12),'white').save(Path(args[-1])/'result.png')

    def test_config_is_scoped_read_only_for_members_and_uses_compare_and_set(self):
        self.prepare()
        profiles=self.member.get('/api/libtv/profiles').json()
        status=lambda: self.member.get('/api/assistant/status').json()
        self.assertEqual(status()['image_account_label'],'原共享账号')
        with patch('libtv_gateway.cli') as cli:
            self.assertTrue(self.choose('image-b','legacy','73'))
            self.assertFalse(self.choose('image-b','legacy','73'))
            with self.assertRaises(ValueError):self.choose('image-c','legacy','91')
            with self.assertRaises(ValueError):self.choose('disabled','image-b','99')
            with self.assertRaises(ValueError):self.choose('image-c','image-b','73')
            cli.assert_not_called()
        self.assertEqual(status()['image_account_label'],'生图备用账号')
        self.assertNotIn('image_account',status())
        self.assertNotIn('image_profile',status())
        self.assertEqual(self.member.get('/api/libtv/profiles').json(),profiles)
        with self.hub.db() as db:
            self.assertEqual(db.execute('SELECT account FROM libtv_settings WHERE id=1').fetchone()[0],'42')
        with TestClient(self.app,base_url=BASE) as anon:
            self.assertEqual(anon.get('/api/assistant/status').status_code,401)

    def test_generation_uses_only_chosen_cli_profile_and_keeps_idempotence_across_switch(self):
        tid,_=self.prepare()
        self.choose('image-b','legacy','73')
        self.enterContext(patch('libtv_isolation.ROOT',self.hub.directory/'isolated-profiles'))
        from libtv_isolation import profile_dir
        for name in ('legacy','image-b'):
            path=profile_dir(name);path.mkdir(parents=True);(path/'credentials.json').write_bytes(b'{}')
        calls=[]
        def fake(args,cwd):
            self.assert_profile(cwd,'image-b')
            self.assertEqual(Path(environment(cwd)['LIBTV_CONFIG_DIR']),profile_dir('image-b'))
            calls.append(args)
            if args==['account','list']:
                self.assertTrue(self.choose('legacy','image-b','42'))  # Switch mid-flight.
                return {'accounts':[{'accountId':73,'isActive':True}]}
            if args[0]=='model':return {'schema':{'modelKey':'lib-image-2.5-f'}}
            if args[0]=='project':return {'projectMeta':{'uuid':'a'*32}}
            if args[0]=='download':self.save_download(args)
            return {}
        with patch('libtv_gateway.cli',side_effect=fake):
            result=self.image(tid,libtv_profile='legacy',image_account='42')
            self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(self.image(tid).json()['result_asset'],result.json()['result_asset'])
        self.assertEqual(sum('--run' in args for args in calls),1)
        with self.hub.db() as db:
            row=db.execute('SELECT image_profile,image_account FROM ai_turns WHERE id=?',(result.json()['id'],)).fetchone()
            self.assertEqual(tuple(row),('image-b','73'))

    def test_old_task_recovers_via_legacy_after_switch(self):
        tid,uid=self.prepare();turn='b'*32;project='f'*32
        with self.hub.db() as db:
            db.execute('''INSERT INTO ai_turns(id,owner,thread,request_key,prompt,status,created,generation)
                VALUES (?,?,?,?,?,'failed',1,?)''',(turn,uid,tid,'old-failed-request-001','test',json.dumps({'provider':'libtv','project':project})))
        self.choose('image-b','legacy','73')
        def fake(args,cwd):
            self.assert_profile(cwd,'legacy')
            if args==['account','list']:return {'accounts':[{'accountId':42,'isActive':True}]}
            self.assertEqual(args[:3],['download','-p',project]);self.save_download(args);return {}
        with patch('libtv_gateway.cli',side_effect=fake) as cli:
            r=self.recovery(tid,turn)
            self.assertEqual(r.status_code,200,r.text)
            self.assertEqual([call.args[0][0] for call in cli.call_args_list],['account','download'])
        self.assertEqual(self.admin.get('/api/assets/'+r.json()['result_asset']).status_code,404)

    def test_failed_new_task_recovers_under_original_config_even_after_next_switch(self):
        tid,_=self.prepare();self.choose('image-b','legacy','73')
        project='d'*32
        def submit(args,cwd):
            self.assert_profile(cwd,'image-b')
            if args[0]=='account':return {'accounts':[{'accountId':73,'isActive':True}]}
            if args[0]=='model':return {'schema':{'modelKey':'lib-image-2.5-f'}}
            if args[0]=='project':return {'projectMeta':{'uuid':project}}
            if '--run' in args:raise RuntimeError('outcome unknown')
            self.fail('Unexpected repeat or download during submission')
        with patch('libtv_gateway.cli',side_effect=submit) as cli:
            self.assertEqual(self.image(tid).status_code,502)
            self.assertEqual(sum('--run' in c.args[0] for c in cli.call_args_list),1)
        turn=self.member.get('/api/assistant/threads/'+tid).json()[0]['id']
        self.choose('image-c','image-b','91')
        def download(args,cwd):
            self.assert_profile(cwd,'image-b')
            if args==['account','list']:return {'accounts':[{'accountId':73,'isActive':True}]}
            self.assertEqual(args[:3],['download','-p',project]);self.save_download(args);return {}
        with patch('libtv_gateway.cli',side_effect=download) as cli:
            r=self.recovery(tid,turn)
            self.assertEqual(r.status_code,200,r.text)
            self.assertEqual([call.args[0][0] for call in cli.call_args_list],['account','download'])

    def test_mismatched_or_ambiguous_active_identity_cannot_submit(self):
        tid,_=self.prepare();self.choose('image-b','legacy','73')
        for index,identities in enumerate(((42,), (73,42))):
            with self.subTest(identities=identities):
                result={'accounts':[{'accountId':a,'isActive':True} for a in identities]}
                with patch('libtv_gateway.cli',return_value=result) as cli:
                    self.assertEqual(self.image(tid,request_key=f'image-ambiguous-test-{index:02}').status_code,502)
                    self.assertEqual(cli.call_count,1)
                    self.assertEqual(cli.call_args.args[0],['account','list'])
                    self.assert_profile(cli.call_args.args[1],'image-b')

    def test_disabled_selected_profile_does_not_fallback_to_shared(self):
        tid,_=self.prepare();self.choose('image-b','legacy','73')
        with self.hub.db() as db:db.execute("UPDATE libtv_profiles SET enabled=0 WHERE id='image-b'")
        self.assertFalse(self.member.get('/api/assistant/status').json()['image_configured'])
        with patch('libtv_gateway.cli') as cli:
            r=self.image(tid);self.assertEqual(r.status_code,409,r.text);cli.assert_not_called()
        self.assertEqual(self.member.get('/api/assistant/threads/'+tid).json(),[])

    def test_mismatched_saved_account_cannot_download_but_local_pixels_survive(self):
        tid,uid=self.prepare();turn='c'*32
        with self.hub.db() as db:
            db.execute('''INSERT INTO ai_turns(id,owner,thread,request_key,prompt,status,created,generation,image_profile,image_account)
                VALUES (?,?,?,?,?,'failed',1,?,?,?)''',(turn,uid,tid,'old-wrong-identity-001','test',json.dumps({'provider':'libtv','project':'f'*32}),'image-b','13'))
        with patch('libtv_gateway.cli') as cli:
            self.assertEqual(self.recovery(tid,turn).status_code,502)
            output=self.hub.directory/'libtv'/('image-'+turn)/'download'
            Image.new('RGB',(10,12),'white').save(output/'local.png')
            self.assertEqual(self.recovery(tid,turn).status_code,200)
            cli.assert_not_called()


class AssistantImageSchemaTests(unittest.TestCase):
    def test_migration_preserves_legacy_turns_and_can_repeat(self):
        db=sqlite3.connect(':memory:');self.addCleanup(db.close)
        db.executescript('''CREATE TABLE ai_turns(id TEXT PRIMARY KEY, generation TEXT);
            INSERT INTO ai_turns VALUES ('old','{"project":"old_project"}');
            CREATE TABLE libtv_settings(id INTEGER PRIMARY KEY,account TEXT NOT NULL);
            INSERT INTO libtv_settings VALUES (1,'42');''')
        for _ in range(2):
            with db:
                db.execute('BEGIN IMMEDIATE');initialize(db)
        self.assertEqual(db.execute('SELECT * FROM ai_turns').fetchone(),('old','{"project":"old_project"}','legacy',''))
        self.assertEqual(selected_profile(db),'legacy');self.assertEqual(resolve_account(db).account,'42')


if __name__=='__main__':
    unittest.main()
