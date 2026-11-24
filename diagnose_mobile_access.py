"""Read-only mobile reachability and certificate diagnostics; no tokens/private keys."""
from pathlib import Path
import ssl,urllib.request,datetime,psutil
from cryptography import x509
from cryptography.hazmat.primitives import hashes
root=Path(__file__).resolve().parent
for name,path in [('server',root/'state/tls/server.crt'),('CA',root/'seedance-hub-ca.crt')]:
 cert=x509.load_pem_x509_certificate(path.read_bytes())
 print(name,'subject=',cert.subject.rfc4514_string(),'issuer=',cert.issuer.rfc4514_string(),flush=True)
 print(name,'valid=',cert.not_valid_before_utc.isoformat(),cert.not_valid_after_utc.isoformat(),flush=True)
 if name=='server':print('SAN',cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value,flush=True)
 print(name,'SHA256=',cert.fingerprint(hashes.SHA256()).hex(':'),flush=True)
for con in psutil.net_connections(kind='tcp'):
 if con.status=='LISTEN' and con.laddr.port==8443:
  p=psutil.Process(con.pid)
  env=p.environ()
  print('LIVE',p.pid,'executable=',p.exe(),'origin=',env.get('HUB_ORIGIN','set by run_service.py'),'mobile_origin=',env.get('HUB_MOBILE_ORIGIN','default 192.168.100.10:8443'),flush=True)
for custom in (True,False):
 context=ssl.create_default_context(cafile=str(root/'seedance-hub-ca.crt')) if custom else ssl.create_default_context()
 op=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=context))
 try:
  with op.open('https://192.168.100.10:8443/mobile/',timeout=8) as r:
   print('HTTPS','project-CA' if custom else 'system-default','status',r.status,'bytes',len(r.read()),flush=True)
 except Exception as e:print('HTTPS','project-CA' if custom else 'system-default',type(e).__name__,str(e),flush=True)
