"""Built-in animated arrow stickers: style whitelist and project-data validation.

Sticker assets ship with the app under ``static/stickers``. A project stores only
the style key plus layout numbers, so a saved project never references a user
file and cannot point outside the bundled asset folder.
"""
import math
from pathlib import Path

FPS = 24
MAX_STICKERS = 50
STICKER_DIR = Path(__file__).resolve().parent / 'static' / 'stickers'

# Ordered for the picker UI; every key maps to ``arrow-<key>.gif``.
ARROW_STYLES = ('solid', 'outline', 'curved', 'double', 'dashed', 'chevron')
STYLE_FILES = {style: f'arrow-{style}.gif' for style in ARROW_STYLES}
STYLE_FILES.update({
    'tk-curve-pink': 'imported/01_curve_pink.gif',
    'tk-bounce-yellow': 'imported/02_bounce_yellow.gif',
    'tk-chevrons-cyan': 'imported/03_chevrons_cyan.gif',
    'tk-glitch-down': 'imported/04_glitch_down.gif',
    'tk-wavy-right': 'imported/05_wavy_right.gif',
    'tk-neon-diag': 'imported/06_neon_diag.gif',
})

EMOJI_FILES = ('01_laugh','02_cool','03_love','04_angry','05_shock','06_cry','07_think','08_hot','09_wink','10_happy','11_mindblown','12_sleep')
STYLE_FILES.update({'emoji-'+name[3:]: 'imported/emoji_'+name+'.gif' for name in EMOJI_FILES})

EMOJI_MORE_FILES = ('01_kiss','02_smirk','03_eyeroll','04_nervous','05_shy','06_dizzy','07_sick','08_freezing','09_moneyeyes','10_starstruck','11_party','12_devil','13_angel','14_pleading','15_yawn','16_speechless')
STYLE_FILES.update({'emoji-more-'+name[3:]: 'imported/emoji_more_'+name+'.gif' for name in EMOJI_MORE_FILES})

POINTING_FILES = ('01_pixel_hand_click','02_finger_point','03_red_scribble_circle','04_circle_with_arrow','05_big_curve_arrow','06_loop_arrow','07_dashed_arrow','08_down_arrow_ripple','09_target_ring_arrow','10_chevrons_yellow','11_burst_lines','12_highlight_box_cursor','13_double_underline','14_location_pin','15_check_circle','16_green_notch_arrow')
STYLE_FILES.update({'pointing-'+name[3:]: 'imported/pointing_'+name+'.gif' for name in POINTING_FILES})


def sticker_path(style):
    """Absolute path of a bundled sticker asset; rejects anything not whitelisted."""
    if style not in STYLE_FILES:
        raise ValueError('贴纸样式无效')
    path = STICKER_DIR / STYLE_FILES[style]
    if not path.is_file():
        raise ValueError('贴纸素材缺失，请重新安装素材包')
    return path


def _number(value, label, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{label}无效')
    value = float(value)
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f'{label}无效')
    return value


def _token(value, label):
    if not isinstance(value, str) or not 1 <= len(value) <= 80:
        raise ValueError(f'{label}无效')
    if not all(c.isascii() and (c.isalnum() or c in '-_') for c in value):
        raise ValueError(f'{label}无效')
    return value


def validate_stickers(value):
    """Return a normalised copy of the sticker list.

    Times are frame-aligned seconds. ``x``/``y`` are the sticker centre as a
    fraction of the output frame, ``width`` is a fraction of frame width, and
    ``rotation`` is clockwise degrees. Unknown fields are rejected so a client
    cannot silently lose data the renderer would ignore.
    """
    if not isinstance(value, list) or len(value) > MAX_STICKERS:
        raise ValueError(f'贴纸列表无效，最多 {MAX_STICKERS} 个')
    fields = {'id', 'style', 'start', 'end', 'x', 'y', 'width', 'rotation', 'track', 'locked'}
    result = []
    for item in value:
        if not isinstance(item, dict) or set(item) - fields or 'style' not in item:
            raise ValueError('贴纸数据无效')
        style = item['style']
        if style not in STYLE_FILES:
            raise ValueError('贴纸样式无效')
        start = _number(item.get('start'), '贴纸开始时间', 0, 86400)
        end = _number(item.get('end'), '贴纸结束时间', 0, 86400)
        start = math.floor(start * FPS + .5) / FPS
        end = math.floor(end * FPS + .5) / FPS
        if end - start < 1 / FPS - 1e-9:
            raise ValueError('贴纸至少保留一帧')
        locked = item.get('locked', False)
        if type(locked) is not bool:
            raise ValueError('贴纸锁定状态无效')
        result.append({
            'id': _token(item.get('id', 'sticker-' + style), '贴纸标识'),
            'style': style,
            'start': start,
            'end': end,
            'x': _number(item.get('x', .5), '贴纸横坐标', 0, 1),
            'y': _number(item.get('y', .5), '贴纸纵坐标', 0, 1),
            'width': _number(item.get('width', .25), '贴纸宽度', .01, 1),
            'rotation': _number(item.get('rotation', 0), '贴纸旋转角度', -360, 360),
            'track': _token(item.get('track', 'sticker-main'), '贴纸轨道标识'),
            'locked': locked,
        })
    return result
