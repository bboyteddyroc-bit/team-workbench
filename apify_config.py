import os
import re
import time
from cryptography.fernet import InvalidToken
from fastapi import HTTPException, Request
from kalodata_integration import QueryError

class ApifyConfig:
    def __init__(self, hub):
        self.hub = hub
        with hub.db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS apify_config(id INTEGER PRIMARY KEY CHECK(id=1), secret BLOB NOT NULL, updated REAL NOT NULL)")

    def secret(self):
        with self.hub.db() as db:
            row = db.execute('SELECT secret FROM apify_config WHERE id=1').fetchone()
        if row:
            try:
                return self.hub.cipher.decrypt(bytes(row['secret'])).decode('utf-8')
            except (InvalidToken, UnicodeError, ValueError):
                raise QueryError('已保存的 Apify 密钥无法解密，请管理员重新保存') from None
        return os.environ.get('APIFY_API_TOKEN', '').strip()

    def available(self):
        return self.pool.available() if hasattr(self,'pool') else bool(self.secret())

    def config_status(self, admin=False):
        with self.hub.db() as db:
            row = db.execute('SELECT updated FROM apify_config WHERE id=1').fetchone()
        try:
            configured, error = self.available(), None
        except QueryError as exc:
            configured, error = False, str(exc)
        result = dict(configured=configured, admin=admin, error=error,
                      automatic_monitoring=True)
        if admin:
            result.update(source='saved' if row else 'environment' if configured else 'none',
                          updated=row['updated'] if row else None)
        return result


def attach(app, hub, user, body):
    service = ApifyConfig(hub)
    app.state.apify_config = service
    from apify_pool import attach as attach_pool
    service.pool=attach_pool(app,hub,user,body,service)
    @app.get('/api/intelligence/apify/status')
    def status(request: Request):
        u = user(request)
        return service.config_status(admin=u['role']=='admin')

    @app.post('/api/intelligence/apify/config')
    async def config(request: Request):
        u = user(request, True)
        data = await body(request)
        secret = data.get('secret_key')
        if not isinstance(secret, str):
            raise HTTPException(400, '请填写新的 API 密钥；当前配置未修改')
        secret = secret.strip()
        if not re.fullmatch(r'[\x21-\x7e]{8,4096}', secret):
            raise HTTPException(400, '密钥应为 8–4096 位可见英文字符，不含空格；当前配置未修改')
        encrypted = hub.cipher.encrypt(secret.encode('utf-8'))
        with hub.db() as db:
            db.execute('INSERT OR REPLACE INTO apify_config(id,secret,updated) VALUES(1,?,?)',
                       (encrypted,time.time()))
            hub.log(db,u['id'],'apify_key_updated','apify_config')
        # Saving never makes a paid request and never returns any part of the key.
        return service.config_status(admin=True)

