"""Owner-scoped rotation guard. Unknown refresh outcomes require reauthorization."""
import secrets
import time


def token(service, owner):
    cfg=service.config();lease=secrets.token_hex(16);now=time.time()
    with service.hub.db() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT * FROM feishu_links WHERE owner=?',(owner,)).fetchone()
        if not row:raise ValueError('请先绑定飞书账号')
        tokens=service.unpack(row['secret'])
        if row['expires']>now+120:return tokens['access_token']
        if not tokens.get('refresh_token'):raise ValueError('授权已过期，请重新绑定飞书')
        prior=db.execute('SELECT * FROM feishu_refresh WHERE owner=?',(owner,)).fetchone()
        if prior and prior['state']=='refreshing':
            # Never retry a rotated token after a crash/unknown response.
            raise ValueError('飞书授权正在刷新或上次结果未知，请稍后查询；长时间未恢复请重新绑定，未重复刷新')
        db.execute("INSERT OR REPLACE INTO feishu_refresh VALUES(?,?,?,?)",(owner,lease,'refreshing',now))
        old=row['secret']
    try:
        new=service.call('authen/v2/oauth/token',method='POST',json={'grant_type':'refresh_token','client_id':cfg['app_id'],'client_secret':cfg['app_secret'],'refresh_token':tokens['refresh_token']})
        if not new.get('access_token'):raise ValueError('授权刷新失败，请重新绑定飞书')
        tokens.update(new)
        with service.hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            active=db.execute('SELECT lease FROM feishu_refresh WHERE owner=?',(owner,)).fetchone()
            if not active or active['lease']!=lease:raise ValueError('飞书授权状态已变化，请重新核对')
            changed=db.execute('UPDATE feishu_links SET secret=?,expires=? WHERE owner=? AND secret=?',(service.pack(tokens),time.time()+new.get('expires_in',3600),owner,old)).rowcount
            db.execute('DELETE FROM feishu_refresh WHERE owner=? AND lease=?',(owner,lease))
            if not changed:raise ValueError('飞书绑定已变化，请重新查询')
        return tokens['access_token']
    except Exception:
        # Keep guard on uncertain failure: refreshing with the old single-use
        # refresh token again can revoke valid credentials. Binding clears guard.
        raise
