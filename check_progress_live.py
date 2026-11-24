import urllib.request,urllib.error
op=urllib.request.build_opener(urllib.request.ProxyHandler({}))
for base,expected in [('http://127.0.0.1:8765',401),('http://192.168.100.10:8000',404)]:
 try:
  op.open(base+'/api/mobile/progress',timeout=5)
  raise AssertionError('Unexpected access')
 except urllib.error.HTTPError as e:
  assert e.code==expected,(base,e.code)
  print(base,'progress guard',e.code,'PASS')
