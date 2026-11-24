import os, tempfile, sqlite3, subprocess, shutil, unittest
from pathlib import Path
from types import SimpleNamespace
from fastapi import FastAPI
from fastapi.testclient import TestClient
import media_tools
from contextlib import contextmanager

class TestSeparation(unittest.TestCase):
    def test_real_two_stems(self):
        with tempfile.TemporaryDirectory(prefix='hub-isolated-separation-') as tmp:
            root=Path(tmp); assets=root/'assets'; assets.mkdir(); src=root/'source.wav'
            subprocess.run([shutil.which('ffmpeg'),'-v','error','-f','lavfi','-i','sine=frequency=440:duration=2.5','-ac','2','-ar','44100',str(src)],check=True)
            dbfile=root/'test.db'
            db=sqlite3.connect(dbfile); db.execute('CREATE TABLE assets (id TEXT, owner TEXT, name TEXT, mime TEXT, size INTEGER, created REAL)'); db.commit(); db.close()
            class Hub:
                def __init__(self): self.assets=assets
                @contextmanager
                def db(self):
                    con=sqlite3.connect(dbfile); con.row_factory=sqlite3.Row
                    try:
                        with con: yield con
                    finally: con.close()
            hub=Hub(); app=FastAPI(); app.state.editor=SimpleNamespace(root=root,source=lambda *args:src)
            async def body(request): return await request.json()
            media_tools.attach(app,hub,lambda request:{'id':'isolated','role':'user'},body)
            with TestClient(app) as client:
                for kind in ('vocal','background'):
                    response=client.post('/api/media/vocals',json={'source_id':'test','start':0,'end':2.5,'kind':kind})
                    self.assertEqual(response.status_code,200,response.text)
                    result=response.json(); self.assertEqual(result['kind'],kind)
                    output=assets/result['id']; self.assertTrue(output.is_file()); self.assertGreater(output.stat().st_size,1000)
                    duration,_=media_tools.probe(output); self.assertAlmostEqual(duration,2.5,delta=.1)
                cached=client.post('/api/media/vocals',json={'source_id':'test','start':0,'end':2.5,'kind':'background'}).json()
                self.assertEqual(cached['id'],result['id'])

if __name__=='__main__': unittest.main()
