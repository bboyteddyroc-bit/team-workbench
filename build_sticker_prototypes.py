"""Generate the built-in animated arrow stickers served from static/stickers.

Each sticker is a 96x96 transparent GIF, 12 frames at 12 fps (1 s loop) with a
pulse + drift animation so the motion is visible at any preview size.
"""
import math
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'static' / 'stickers'
SIZE = 96
FPS = 12
FRAMES = 12
SS = 3  # supersampling factor for smooth edges
STYLES = ('solid', 'outline', 'curved', 'double', 'dashed', 'chevron')


def _seg(x, y, ax, ay, bx, by, w):
    dx, dy = bx - ax, by - ay
    d = dx * dx + dy * dy
    t = 0.0 if d == 0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / d))
    return (x - ax - t * dx) ** 2 + (y - ay - t * dy) ** 2 <= w * w


def _tri(x, y, a, b, c):
    def side(p, q):
        return (x - q[0]) * (p[1] - q[1]) - (p[0] - q[0]) * (y - q[1])
    d1, d2, d3 = side(a, b), side(b, c), side(c, a)
    neg = d1 < 0 or d2 < 0 or d3 < 0
    pos = d1 > 0 or d2 > 0 or d3 > 0
    return not (neg and pos)


def _shapes(style):
    """Return (segments, triangles) in a 96x96 box, arrow pointing right."""
    if style == 'curved':
        segs = [(20, 74, 20, 58), (20, 58, 26, 44), (26, 44, 40, 36), (40, 36, 62, 36)]
        tris = [((62, 22), (62, 50), (86, 36))]
        return segs, tris
    if style == 'double':
        segs = [(20, 48, 76, 48)]
        tris = [((20, 30), (20, 66), (4, 48)), ((76, 30), (76, 66), (92, 48))]
        return segs, tris
    if style == 'chevron':
        segs = [(26, 26, 48, 48), (26, 70, 48, 48), (50, 26, 72, 48), (50, 70, 72, 48)]
        return segs, []
    segs = [(14, 48, 64, 48)]
    tris = [((64, 28), (64, 68), (88, 48))]
    return segs, tris


def _hit(style, x, y):
    segs, tris = _shapes(style)
    if style == 'outline':
        outer = any(_seg(x, y, *s, 5.0) for s in segs) or any(_tri(x, y, *t) for t in tris)
        inner = any(_seg(x, y, *s, 2.4) for s in segs)
        if not outer:
            return False
        if inner:
            return False
        # Hollow the triangle interior, keep a 2.6px rim.
        for t in tris:
            cx = sum(p[0] for p in t) / 3.0
            cy = sum(p[1] for p in t) / 3.0
            if _tri(x, y, *t) and _tri(x, y, *[(cx + (p[0] - cx) * .62, cy + (p[1] - cy) * .62) for p in t]):
                return False
        return True
    if style == 'dashed':
        # Dashed shaft with a solid head, so the direction stays readable at small sizes.
        if any(_tri(x, y, *t) for t in tris):
            return True
        return any(_seg(x, y, *s, 5.0) for s in segs) and (int(x / 9) % 2 == 0)
    return any(_seg(x, y, *s, 5.0) for s in segs) or any(_tri(x, y, *t) for t in tris)


def _frame(style, scale, dx):
    """Render one RGBA frame with supersampled coverage."""
    buf = bytearray()
    cx = cy = SIZE / 2.0
    for py in range(SIZE):
        for px in range(SIZE):
            cover = 0
            for sy in range(SS):
                for sx in range(SS):
                    ux = px + (sx + .5) / SS
                    uy = py + (sy + .5) / SS
                    # Inverse-transform into the sticker's own coordinate space.
                    x = (ux - cx - dx) / scale + cx
                    y = (uy - cy) / scale + cy
                    if 0 <= x < SIZE and 0 <= y < SIZE and _hit(style, x, y):
                        cover += 1
            alpha = round(255 * cover / (SS * SS))
            buf.extend((255, 255, 255, alpha))
    return bytes(buf)


def main():
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise SystemExit('ffmpeg unavailable')
    OUT.mkdir(parents=True, exist_ok=True)
    for style in STYLES:
        path = OUT / ('arrow-' + style + '.gif')
        args = [ffmpeg, '-v', 'error', '-y', '-f', 'rawvideo', '-pixel_format', 'rgba',
                '-video_size', f'{SIZE}x{SIZE}', '-framerate', str(FPS), '-i', 'pipe:0',
                '-filter_complex',
                '[0:v]split[a][b];[a]palettegen=reserve_transparent=1:stats_mode=single[p];'
                '[b][p]paletteuse=alpha_threshold=128',
                '-loop', '0', str(path)]
        frames = bytearray()
        for f in range(FRAMES):
            phase = 2 * math.pi * f / FRAMES
            frames.extend(_frame(style, .90 + .10 * math.cos(phase), 3.0 * math.cos(phase)))
        p = subprocess.run(args, input=bytes(frames), stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=120)
        if p.returncode:
            raise RuntimeError(f'{style}: {p.stderr.decode(errors="replace")}')
        print(path.name, path.stat().st_size)


if __name__ == '__main__':
    main()
