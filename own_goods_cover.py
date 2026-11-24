"""Small, authenticated product portraits displayed in the evidence workspace."""
from hashlib import sha256
from io import BytesIO

from fastapi import HTTPException, Request, Response
from PIL import Image, ImageOps, UnidentifiedImageError
from starlette.concurrency import run_in_threadpool

from own_goods import PREFIX, get_goods, require_editor


def displayed_cover(db, goods, lookup=None):
    from own_goods_cover_tasks import image_record
    gid = goods['id']
    manual = db.execute('SELECT version FROM own_goods_covers WHERE goods=?', (gid,)).fetchone()
    if manual:
        return {'cover_url': f'{PREFIX}/{gid}/cover?v={manual[0]}', 'cover_source': 'manual',
                'cover_observed': None, 'cover_basis':'manual'}
    image = image_record(db, goods, lookup)
    return {'cover_url': f"{PREFIX}/{gid}/cover?v={image['version']}" if image else '',
            'cover_source': 'listing' if image else '', 'cover_observed': image['observed'] if image else None,
            'cover_basis': image['source'] if image else ''}


def listing_thumbnail(url):
    from safe_cover import fetch
    return thumbnail(fetch(url, product=True))


def thumbnail(data):
    try:
        with Image.open(BytesIO(data), formats=('JPEG', 'PNG', 'WEBP')) as image:
            if image.width * image.height > 16_000_000:
                raise HTTPException(413, '请使用 1600 万像素以内的商品图片')
            image.thumbnail((560, 560), Image.Resampling.LANCZOS)
            frame = ImageOps.exif_transpose(image).convert('RGBA')
            buffer = BytesIO()
            frame.save(buffer, 'WEBP', quality=85)
            return buffer.getvalue()
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        raise HTTPException(400, '请上传可读取的 JPG、PNG 或 WebP 图片') from None


def attach(app, hub, user):
    with hub.db() as db:
        db.execute('CREATE TABLE IF NOT EXISTS own_goods_covers(goods TEXT PRIMARY KEY, version TEXT NOT NULL, picture BLOB NOT NULL)')

    @app.get(PREFIX+'/{gid}/cover')
    def read_cover(gid: str, request: Request):
        from own_goods_cover_tasks import image_record
        user(request)
        with hub.db() as db:
            db.execute('BEGIN')
            goods = get_goods(db, gid)
            row = db.execute('SELECT picture FROM own_goods_covers WHERE goods=?', (gid,)).fetchone()
            if not row:
                row = image_record(db, goods, picture=True)
        if not row:
            raise HTTPException(404, '暂无可用的商品主图')
        return Response(row['picture'], media_type='image/webp')

    @app.post(PREFIX+'/{gid}/cover')
    async def upload_cover(gid: str, request: Request):
        actor = user(request)
        with hub.db() as db:
            require_editor(get_goods(db, gid), actor)
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > 8 * 1024 * 1024:
                raise HTTPException(413, '商品图片最大 8 MB')
            data.extend(chunk)
        picture = await run_in_threadpool(thumbnail, data)
        version = sha256(picture).hexdigest()[:16]
        with hub.db() as db:
            db.execute('BEGIN IMMEDIATE')
            goods = get_goods(db, gid)
            require_editor(goods, actor)
            db.execute('INSERT OR REPLACE INTO own_goods_covers VALUES(?, ?, ?)', (gid, version, picture))
            return displayed_cover(db, goods)
