"""Small valid image bytes shared by offline tests; never production data."""
import io
from PIL import Image


def png():
    stream=io.BytesIO()
    Image.new('RGB',(12,8),(30,120,180)).save(stream,format='PNG')
    return stream.getvalue()
