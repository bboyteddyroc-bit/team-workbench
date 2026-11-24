"""Export only the existing public root certificate for explicit iPhone installation."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,plistlib,ssl,socket,uuid
from cryptography import x509
from cryptography.hazmat.primitives import serialization,hashes
from cryptography.hazmat.primitives.asymmetric import padding

root=Path(__file__).resolve().parent
out=root.parents[2]/'手机传输证书'
out.mkdir(exist_ok=True)
ca=x509.load_pem_x509_certificate((root/'seedance-hub-ca.crt').read_bytes())
leaf=x509.load_pem_x509_certificate((root/'state/tls/server.crt').read_bytes())
now=datetime.now(timezone.utc)
assert ca.not_valid_before_utc<=now<=ca.not_valid_after_utc
assert leaf.not_valid_before_utc<=now<=leaf.not_valid_after_utc
assert ca.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
assert leaf.issuer==ca.subject
ca.public_key().verify(ca.signature,ca.tbs_certificate_bytes,padding.PKCS1v15(),ca.signature_hash_algorithm)
ca.public_key().verify(leaf.signature,leaf.tbs_certificate_bytes,padding.PKCS1v15(),leaf.signature_hash_algorithm)
context=ssl.create_default_context(cafile=str(root/'seedance-hub-ca.crt'))
with socket.create_connection(('192.168.100.10',8443),timeout=8) as s:
 with context.wrap_socket(s,server_hostname='192.168.100.10') as tls:
  assert tls.getpeercert(binary_form=True)==leaf.public_bytes(serialization.Encoding.DER),'Live server certificate changed'
der=ca.public_bytes(serialization.Encoding.DER)
cer=out/'Seedance-Hub-Local-CA.cer'
profile=out/'Seedance-Hub-iPhone.mobileconfig'
for p in (cer,profile):
 if p.exists():raise FileExistsError('Do not overwrite unobserved existing file: '+str(p))
cer.write_bytes(der)
payload={
 'PayloadType':'com.apple.security.root',
 'PayloadVersion':1,
 'PayloadIdentifier':'local.seedance.hub.ca',
 'PayloadUUID':str(uuid.uuid4()).upper(),
 'PayloadDisplayName':'Seedance Hub Local CA',
 'PayloadCertificateFileName':cer.name,
 'PayloadDescription':'Public local CA certificate for this Seedance Hub. No private key. Enables trust only after you explicitly enable it in iOS Settings.',
 'PayloadContent':der,
}
data={
 'PayloadType':'Configuration',
 'PayloadVersion':1,
 'PayloadIdentifier':'local.seedance.hub.iphone-certificate',
 'PayloadUUID':str(uuid.uuid4()).upper(),
 'PayloadDisplayName':'Seedance Hub - Local HTTPS Certificate',
 'PayloadDescription':'Contains ONE public root certificate only. No MDM, VPN, proxy, Wi-Fi configuration, credentials or private keys. Unsigned profile. Verify the SHA-256 fingerprint before enabling trust.',
 'PayloadOrganization':'Seedance Hub (local)',
 'PayloadRemovalDisallowed':False,
 'PayloadContent':[payload],
}
profile.write_bytes(plistlib.dumps(data,fmt=plistlib.FMT_XML))
check=plistlib.loads(profile.read_bytes())
assert check['PayloadType']=='Configuration' and len(check['PayloadContent'])==1
assert check['PayloadContent'][0]['PayloadType']=='com.apple.security.root'
assert check['PayloadContent'][0]['PayloadContent']==cer.read_bytes()
assert x509.load_der_x509_certificate(cer.read_bytes()).fingerprint(hashes.SHA256())==ca.fingerprint(hashes.SHA256())
print('VERIFIED live TLS chain and hostname; leaf matches live server.',flush=True)
print('VERIFIED profile: one public root certificate only; no MDM/VPN/proxy/private key.',flush=True)
print('CA SHA256:',ca.fingerprint(hashes.SHA256()).hex(':'),flush=True)
for p in (profile,cer):print('OUTPUT',p,'bytes',p.stat().st_size,'sha256',hashlib.sha256(p.read_bytes()).hexdigest(),flush=True)
