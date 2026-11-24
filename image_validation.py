"""Decode validation before persisting or forwarding an untrusted image."""
import io
import warnings
from PIL import Image, UnidentifiedImageError

MAX_PIXELS = 25_000_000
FORMATS = {'image/png': 'PNG', 'image/jpeg': 'JPEG', 'image/webp': 'WEBP'}


def validate(content, mime):
    return _validate(lambda: io.BytesIO(content), mime)


def validate_file(path, mime):
    return _validate(lambda: open(path, 'rb'), mime)


def _validate(open_source, mime):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with open_source() as source, Image.open(source) as image:
                if image.format != FORMATS[mime] or image.width * image.height > MAX_PIXELS:
                    raise ValueError('图片格式或像素超出范围')
                if getattr(image, 'n_frames', 1) != 1:
                    raise ValueError('参考图片不支持多帧动画，请先转为静态图片')
                image.verify()
            # Verify alone does not decode pixel data on every codec.
            with open_source() as source, Image.open(source) as image:
                image.load()
    except (OSError, ValueError, KeyError, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValueError('图片损坏、格式不匹配或超过2500万像素，请缩小后重新选择') from None
