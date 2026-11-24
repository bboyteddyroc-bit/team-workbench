import asyncio,unittest
from fastapi import HTTPException
from test_mobile_transfer import MobileTests
from mobile_progress import UploadProgress

class ProgressTests(MobileTests):
 def test_stream_states_and_owner(self):
  async def scenario():
   tracker=UploadProgress(type('Hub',(),{'db':lambda _:self.db()})())
   class Request:
    headers={'content-length':'8','x-file-name':'sample.mp4'}
    async def stream(this):
     yield b'abcd'
     current=tracker.recent('a')[0];self.assertEqual(current['received'],4);self.assertEqual(current['state'],'uploading')
     yield b'efgh'
   async def upload(request,user):
    data=b''.join([x async for x in request.stream()])
    self.assertEqual(data,b'abcdefgh');self.assertEqual(tracker.recent('a')[0]['state'],'verifying')
    return {'id':'confirmed'}
   await tracker.receive(Request(),'a',upload)
   self.assertEqual(tracker.recent('a')[0]['state'],'done')
   self.assertEqual(tracker.recent('a')[0]['received'],8)
   self.assertEqual(tracker.recent('b'),[])
   async def fail(request,user):raise HTTPException(400,'invalid')
   with self.assertRaises(HTTPException):await tracker.receive(Request(),'a',fail)
   self.assertEqual(tracker.recent('a')[0]['state'],'failed')
  asyncio.run(scenario())
 def test_route_owner_scope(self):
  d=self.client.post('/api/mobile/transfers',json={'exports':[]}).json()
  r=self.client.post('/api/mobile/upload',content=b'test',headers={'X-Transfer-Token':d['url'].split('#')[1],'X-File-Name':'test.mp4'})
  self.assertEqual(r.status_code,200)
  data=self.client.get('/api/mobile/progress').json()['items']
  self.assertEqual(data[0]['received'],4);self.assertEqual(data[0]['state'],'done')
  self.assertEqual(self.client.get('/api/mobile/progress',headers={'who':'b'}).json()['items'],[])
if __name__=='__main__':unittest.main()
