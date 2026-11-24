"""Offline media boundary and paid-queue revocation contracts."""
import io
import unittest
from unittest.mock import patch
from PIL import Image
from test_hub import HubTests,H
from test_image_fixture import png

class Images(unittest.TestCase):
    setUp=HubTests.setUp
    tearDown=HubTests.tearDown
    login=HubTests.login
    def test_corrupt_image_rejected_before_storage(self):
        with self.hub.db() as db:before=db.execute('SELECT COUNT(*) FROM assets').fetchone()[0]
        for content,mime in [(b'\x89PNG\r\n\x1a\nfixture','image/png'),(png(),'image/jpeg'),(b'RIFF1234WEBPnotimage','image/webp')]:
            r=self.member.post('/api/assets',headers={**H,'Content-Type':mime},content=content)
            self.assertEqual(r.status_code,400,r.text)
        with self.hub.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM assets').fetchone()[0],before)
        self.assertEqual(list(self.hub.assets.iterdir()),[])
    def test_valid_image_roundtrip_and_pixel_guard(self):
        r=self.member.post('/api/assets',headers={**H,'Content-Type':'image/png'},content=png())
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.member.get('/api/assets/'+r.json()['id']).content,png())
        with patch('image_validation.MAX_PIXELS',10):
            r=self.member.post('/api/assets',headers={**H,'Content-Type':'image/png'},content=png())
            self.assertEqual(r.status_code,400)
    def test_multiple_frame_image_rejected(self):
        from image_validation import validate
        stream=io.BytesIO();Image.new('RGB',(4,4),'red').save(stream,format='WEBP',save_all=True,append_images=[Image.new('RGB',(4,4),'blue')],duration=100,loop=0)
        with self.assertRaises(ValueError):validate(stream.getvalue(),'image/webp')

class PaidQueue(unittest.TestCase):
    def run_disabled(self,group):
        from test_apify_monitor import Tests
        from test_kalodata_integration import HEADERS
        f=Tests();f.setUp()
        try:
            f.a.post('/api/intelligence/apify/config',headers=HEADERS,json={'secret_key':'offline-token'})
            aid=f.a.post('/api/intelligence/apify/accounts',headers=HEADERS,json={'handle':'auditdisabled'}).json()['id']
            service=f.app.state.apify_monitor;uid=f.a.get('/api/me').json()['id']
            if group:
                with f.hub.db() as db:accounts=[dict(db.execute('SELECT * FROM apify_accounts WHERE id=?',(aid,)).fetchone())]
                jid=service.enqueue_group(uid,accounts,{'mode':'today','timezone':'UTC'})
            else:jid=service.queue(aid)
            with f.hub.db() as db:db.execute('UPDATE users SET enabled=0 WHERE id=?',(uid,))
            with patch.object(service,'request') as remote:
                service.group_tick() if group else service.tick()
                remote.assert_not_called()
            with f.hub.db() as db:row=db.execute('SELECT state FROM '+('grouped_runs' if group else 'apify_runs')+' WHERE id=?',(jid,)).fetchone()
            self.assertEqual(row['state'],'cancelled')
        finally:f.tearDown()
    def test_disabled_group_has_no_paid_post(self):self.run_disabled(True)
    def test_disabled_legacy_has_no_paid_post(self):self.run_disabled(False)

if __name__=='__main__':unittest.main()
