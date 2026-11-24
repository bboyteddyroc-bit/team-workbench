import sqlite3, tempfile, unittest
from pathlib import Path
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
import media_tools

class SeparationLimitTests(unittest.TestCase):
    def test_boundaries_and_both_stems(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); assets=root/'assets'; assets.mkdir(); source=root/'source.wav'; source.write_bytes(b'source')
            dbfile=root/'db.sqlite'; db=sqlite3.connect(dbfile)
            db.execute('CREATE TABLE assets (id TEXT, owner TEXT, name TEXT, mime TEXT, size INTEGER, created REAL)'); db.commit(); db.close()
            class Hub:
                def __init__(self): self.assets=assets
                @contextmanager
                def db(self):
                    con=sqlite3.connect(dbfile); con.row_factory=sqlite3.Row
                    try:
                        with con: yield con
                    finally: con.close()
            app=FastAPI(); app.state.editor=SimpleNamespace(root=root,source=lambda *args:source)
            async def body(req): return await req.json()
            media_tools.attach(app,Hub(),lambda req:{'id':'test','role':'user'},body)
            length=[0]
            def probe(path): return (100 if Path(path)==source else length[0], [{'codec_type':'audio'}])
            def run(args,**kw):
                if 'demucs.separate' in args:
                    folder=Path(args[args.index('-o')+1])/'htdemucs'/'input';folder.mkdir(parents=True)
                    (folder/'vocals.wav').write_bytes(b'vocal');(folder/'no_vocals.wav').write_bytes(b'background')
                else: Path(args[-1]).write_bytes(b'audio')
            with patch.object(media_tools,'probe',side_effect=probe),patch.object(media_tools,'run',side_effect=run),patch.object(media_tools.shutil,'which',return_value='ffmpeg'),patch.object(Path,'is_file',return_value=True):
                # Use an existing Python path for the Demucs environment discovery.
                import sys, os
                with patch.dict(os.environ,{'HUB_DEMUCS_PYTHON':sys.executable}),TestClient(app) as client:
                    for kind in ('vocal','background'):
                        for seconds,expected in [(0.999,400),(1,200),(15.3,200),(60,200),(60.001,400)]:
                            length[0]=seconds
                            response=client.post('/api/media/vocals',json={'source_id':'test','start':0,'end':seconds,'kind':kind})
                            self.assertEqual(response.status_code,expected,(kind,seconds,response.text))
                            if expected==200: self.assertEqual(response.json()['kind'],kind)

if __name__=='__main__': unittest.main()
