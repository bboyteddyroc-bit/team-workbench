"""TLS LAN entry point. CA trust is installed by the user/IT, never automatically."""
import argparse
import datetime
import ipaddress
import os
from pathlib import Path
import socket
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID

ROOT=Path(__file__).resolve().parent


def prepare(host):
    address=ipaddress.ip_address(host)
    if not address.is_private or address.is_loopback:
        raise ValueError('Provide a private LAN/VPN address')
    tls=ROOT/'state'/'tls';tls.mkdir(parents=True,exist_ok=True)
    now=datetime.datetime.now(datetime.timezone.utc)
    ca_key_path=tls/'ca.key';ca_path=ROOT/'seedance-hub-ca.crt'
    if not ca_key_path.exists():
        ca_key=rsa.generate_private_key(public_exponent=65537,key_size=3072)
        name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Seedance Hub - '+socket.gethostname()+' - Local CA')])
        cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(ca_key.public_key())
              .serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=5))
              .not_valid_after(now+datetime.timedelta(days=365))
              .add_extension(x509.BasicConstraints(ca=True,path_length=0),critical=True)
              .add_extension(x509.KeyUsage(False,False,False,False,False,True,True,False,False),critical=True)
              .sign(ca_key,hashes.SHA256()))
        ca_key_path.write_bytes(ca_key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        os.chmod(ca_key_path,0o600)
        ca_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    ca_key=serialization.load_pem_private_key(ca_key_path.read_bytes(),password=None)
    ca=x509.load_pem_x509_certificate(ca_path.read_bytes())
    leaf_key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    leaf=(x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,host)]))
          .issuer_name(ca.subject).public_key(leaf_key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now-datetime.timedelta(minutes=5)).not_valid_after(now+datetime.timedelta(days=90))
          .add_extension(x509.SubjectAlternativeName([x509.IPAddress(address)]),critical=False)
          .add_extension(x509.BasicConstraints(ca=False,path_length=None),critical=True)
          .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),critical=False)
          .sign(ca_key,hashes.SHA256()))
    (tls/'server.key').write_bytes(leaf_key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    os.chmod(tls/'server.key',0o600)
    (tls/'server.crt').write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    fingerprint=ca.fingerprint(hashes.SHA256()).hex(':')
    print('CA SHA256:',fingerprint)
    print('Certificate prepared. No trust store or firewall changes made.')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--host',required=True);p.add_argument('--port',type=int,default=8443);p.add_argument('--prepare-only',action='store_true');a=p.parse_args()
    if a.prepare_only:
        prepare(a.host)
    else:
        if not (ROOT/'state'/'tls'/'server.crt').exists(): raise SystemExit('Run --prepare-only first')
        os.environ['HUB_ORIGIN']=f'https://{a.host}:{a.port}'
        from app import create_app
        import uvicorn
        uvicorn.run(create_app(worker=os.getenv('HUB_WORKER','1')=='1'),host=a.host,port=a.port,proxy_headers=False,access_log=False,
                    ssl_keyfile=str(ROOT/'state'/'tls'/'server.key'),ssl_certfile=str(ROOT/'state'/'tls'/'server.crt'))
