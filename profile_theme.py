"""Shared drawing primitives for the approved RTLink Profile."""
from __future__ import annotations
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageColor
if __package__:
    from .report_image import _font, _lines, _text, _box
else:
    from report_image import _font, _lines, _text, _box
ASSETS=Path(__file__).resolve().parent/'resource'/'profile'
PAPER='#f3f0e8'; WHITE='#fffdf9'; INK='#202f36'; MUTED='#5e6a6c'; LINE='#d8d9cf'; TEAL='#236f63'; RED='#b94330'
def txt(d,value,x,y,size=24,color=INK,bold=False,align='left'):
    _text(d,value,x,y,size,color,bold,align)
def box(d,x,y,w,h,fill=WHITE,outline=LINE,r=18):
    _box(d,x,y,w,h,fill,outline,radius=r,line_width=1)

RAINBOW = ['#ef4e6d', '#f29943', '#ebd85a', '#67c16f', '#4cbdc7', '#7698e8', '#b886db']
SILVER = ['#7b899b', '#dce6ef', '#ffffff', '#a8b5c8', '#eef4fa', '#8d9eb4']
GOLD = ['#af7424', '#f4cf6a', '#fff4bc', '#ce963a', '#ffe892', '#b58229']

def color_at(colors, t):
    u = max(0, min(0.999999, t)) * (len(colors) - 1)
    i = int(u)
    f = u - i
    a = ImageColor.getrgb(colors[i])
    b = ImageColor.getrgb(colors[min(i + 1, len(colors) - 1)])
    return tuple((round(x + (y - x) * f) for (x, y) in zip(a, b)))

def gradient(size, colors):
    im = Image.new('RGBA', size)
    d = ImageDraw.Draw(im)
    for x in range(size[0]):
        d.line((x, 0, x, size[1]), fill=(*color_at(colors, x / max(1, size[0] - 1)), 255))
    return im

def ring(im, cx, cy, r, rating):
    width = 20
    pad = width + 4
    side = 2 * (r + pad)
    mask = Image.new('L', (side, side))
    d = ImageDraw.Draw(mask)
    end = -90 + 360 * min(max(rating / 15.5, 0), 1)
    bounds = (pad, pad, pad + 2 * r, pad + 2 * r)
    d.arc(bounds, -90, end, fill=255, width=width)
    for a in (-90, end):
        xx = r + pad + math.cos(math.radians(a)) * (r - width / 2)
        yy = r + pad + math.sin(math.radians(a)) * (r - width / 2)
        d.ellipse((xx - width / 2, yy - width / 2, xx + width / 2, yy + width / 2), fill=255)
    colors = ['#9cd9fa'] * 2 if rating < 6 else ['#ee6547'] * 2 if rating < 10 else SILVER if rating < 15 else GOLD
    draw = ImageDraw.Draw(im)
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline='#34424f', width=width)
    if rating > 0:
        im.paste(gradient((side, side), colors), (int(cx - r - pad), int(cy - r - pad)), mask)

def asset(im, name, x, y, w, h, opacity=1):
    a = Image.open(ASSETS / (name + '.png')).convert('RGBA')
    bounds = a.getchannel('A').getbbox()
    a = a.crop(bounds)
    a.thumbnail((w, h), Image.Resampling.LANCZOS)
    if opacity < 1:
        a.putalpha(a.getchannel('A').point(lambda q: round(q * opacity)))
    im.alpha_composite(a, (int(x + (w - a.width) / 2), int(y + (h - a.height) / 2)))

def crown_state(row):
    if row.get('dondafulComboCount'):
        return 'ap'
    if row.get('fullComboCount'):
        return 'fc'
    if row.get('clearCount'):
        return 'clear'
    return 'none'

def title_lines(d, name, width, size):
    if name.isascii() and ' ' in name:
        lines = []
        line = ''
        for word in name.split():
            candidate = (line + ' ' + word).strip()
            if _font(size).getlength(candidate) <= width:
                line = candidate
            else:
                if line:
                    lines.append(line)
                line = word
        if line:
            lines.append(line)
        if all((_font(size).getlength(s) <= width for s in lines)):
            return lines
    return _lines(d, name, width, size)

def ellipsize(text, width, size, force=False):
    if not force and _font(size).getlength(text) <= width:
        return text
    text = text.rstrip('…')
    while text and _font(size).getlength(text + '…') > width:
        text = text[:-1]
    return text + '…'

def section(d, num, text, y, note=''):
    txt(d, num, 70, y, 20, RED)
    txt(d, text, 70, y + 34, 34, INK, True)
    if note:
        txt(d, note, 1370, y + 45, 19, MUTED, align='right')
COMPACT_PATTERNS = ['sixteenth_2', '16-3', '16-5', '16-7', '16-fish', 'twentyfourth_burst']
COMPACT_LABELS = ['16 分二连', '16 分三连', '16 分五连', '16 分七连', '16 分鱼蛋', '24 分短串']
