"""Approved V7 Profile and configuration detail renderer. No network or player globals."""
from __future__ import annotations
import copy, math, os
from collections import Counter
from datetime import datetime, timedelta, timezone
from PIL import Image,ImageDraw,ImageFilter,ImageColor,ImageChops
if __package__:
    from . import profile_theme as theme
    from .profile_theme import txt,box,PAPER,WHITE,INK,MUTED,LINE,TEAL,RED
    from .report_image import _font,_draw_galaxy,build_report_data,RHYTHM_META,_stage
    from .score_rank import SCORE_RANK_RATIOS
    from .profile_data import build_profile_data
else:
    import profile_theme as theme
    from profile_theme import txt,box,PAPER,WHITE,INK,MUTED,LINE,TEAL,RED
    from report_image import _font,_draw_galaxy,build_report_data,RHYTHM_META,_stage
    from score_rank import SCORE_RANK_RATIOS
    from profile_data import build_profile_data
ASSETS=theme.ASSETS
def title(row):
    return str(row.get('title') or row.get('titleJa') or row.get('id') or '未知曲目')

TEXT_RAINBOW = ['#ca3861', '#b96813', '#948211', '#328759', '#237f9e', '#546cc2', '#9b51b0']
RANK_COLORS = {1: '#69747d', 2: '#fffefa', 3: '#a36534', 4: '#7687a4', 5: '#aa7c15', 6: '#cf5892', 7: '#8660bc'}
TEXT_RANK_COLORS = {**RANK_COLORS, 2: RANK_COLORS[1]}
STAGE_STARTS = (0, 1, 5, 7, 9, 10, 13)
STAGES = [{**_stage(float(value)), 'startsAt': value} for value in STAGE_STARTS]
PLANET_COLORS = ['#ef967e', '#e7c565', '#b69bdd', '#80cfba', '#81b8dc', '#df96b8', '#aabcc9']
TAG_COLOR = '#416b73'

def asset(im, name, x, y, w, h):
    a = Image.open(ASSETS / (name + '.png')).convert('RGBA')
    a = a.crop(a.getchannel('A').getbbox())
    a.thumbnail((round(w), round(h)), Image.Resampling.LANCZOS)
    im.alpha_composite(a, (round(x + (w - a.width) / 2), round(y + (h - a.height) / 2)))

def grade_ratio(current, full):
    if current is None or full is None or not math.isfinite(current) or not math.isfinite(full) or full <= 0:
        return None
    ratio = current / full
    return max((rank for (rank, bound) in SCORE_RANK_RATIOS.items() if ratio >= bound), default=1)

def colored_text(im, text, x, y, size, rank, align='left'):
    font = _font(size)
    width = font.getlength(text)
    if align == 'right':
        x -= width
    elif align == 'center':
        x -= width / 2
    if rank == 8:
        bounds = font.getbbox(text)
        ww = math.ceil(width) + 4
        hh = bounds[3] - bounds[1] + 6
        mask = Image.new('L', (ww, hh))
        ImageDraw.Draw(mask).text((1, 1), text, font=font, anchor='lt', fill=255)
        im.paste(theme.gradient((ww, hh), TEXT_RAINBOW), (round(x) - 1, round(y) - 1), mask)
    else:
        txt(ImageDraw.Draw(im), text, x, y, size, TEXT_RANK_COLORS.get(rank, MUTED))

def score_pair(im, current, full, cx, y, size=20, full_digits=2, align='center'):
    rank = grade_ratio(current, full)
    left = f'{current:.2f}' if current is not None else '—'
    right = f'{full:.{full_digits}f}' if full is not None else '—'
    text = f'{left} / {right}'
    font = _font(size)
    x = cx - font.getlength(text) / 2 if align == 'center' else cx
    colored_text(im, left, x, y, size, rank)
    txt(ImageDraw.Draw(im), ' / ', x + font.getlength(left), y, size, MUTED)
    colored_text(im, right, x + font.getlength(left + ' / '), y, size, 8 if rank == 8 else None)

def rainbow_border(im, x, y, w, h):
    pad = 16
    size = (w + 2 * pad, h + 2 * pad)
    outline = Image.new('L', size)
    d = ImageDraw.Draw(outline)
    d.rounded_rectangle((pad, pad, pad + w - 1, pad + h - 1), radius=16, outline=255, width=2)
    glow = outline.filter(ImageFilter.GaussianBlur(4)).point(lambda q: round(q * 0.52))
    layer = theme.gradient(size, theme.RAINBOW)
    layer.putalpha(glow)
    im.alpha_composite(layer, (x - pad, y - pad))
    layer = theme.gradient(size, theme.RAINBOW)
    layer.putalpha(outline.point(lambda q: round(q * 0.78)))
    im.alpha_composite(layer, (x - pad, y - pad))

def corner_tag(im, index, x, y, w, h):
    mask = Image.new('L', (w, h))
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((0, 0, w - 1, h - 1), radius=16, fill=255)
    triangle = Image.new('RGBA', (w, h))
    td = ImageDraw.Draw(triangle)
    td.polygon(((0, 0), (54, 0), (0, 54)), fill=TAG_COLOR)
    triangle.putalpha(ImageChops.multiply(triangle.getchannel('A'), mask))
    im.alpha_composite(triangle, (x, y))
    txt(ImageDraw.Draw(im), str(index), x + 8, y + 6, 18, '#fffef7')

def judgment_icon(im, name, x, y, height=32):
    a = Image.open(ASSETS / (name + '.png')).convert('RGBA')
    a = a.crop(a.getchannel('A').getbbox())
    width = round(a.width * height / a.height)
    a = a.resize((width, height), Image.Resampling.LANCZOS)
    im.alpha_composite(a, (round(x), round(y)))
    return (width, height)

def card_score_rank(row):
    try:
        value = int(row.get('bestScoreRank'))
    except (ValueError, TypeError):
        return None
    return value if 2 <= value <= 8 else None

def card(im, row, index, x, y, w=420, h=204):
    d = ImageDraw.Draw(im)
    ura = row['level'] == 5
    state = theme.crown_state(row)
    box(d, x, y, w, h, '#f7f5fe' if ura else WHITE, '#d9d3e4' if ura else LINE, 16)
    if ura:
        theme.asset(im, 'ura', x + w - 158, y + 6, 156, 119, 0.08)
    if index is not None:
        corner_tag(im, index, x, y, w, h)
    if state == 'ap':
        rainbow_border(im, x, y, w, h)
    if state != 'none':
        theme.asset(im, 'crown-' + state, x + 15, y + 34, 60, 56)
    rank = card_score_rank(row)
    if rank is not None:
        asset(im, f'rank-{rank}', x + 81, y + 37, 48, 50)
    d = ImageDraw.Draw(im)
    name = title(row)
    size = 23
    title_x = x + 142
    title_width = w - 162
    while len(theme.title_lines(d, name, title_width, size)) > 2 and size > 17:
        size -= 1
    lines = theme.title_lines(d, name, title_width, size)
    if len(lines) > 2:
        lines = [lines[0], theme.ellipsize(lines[1] + '…', title_width, size, force=True)]
    text_y = y + (34 if len(lines) == 2 else 49)
    for (i, line) in enumerate(lines):
        txt(d, line, title_x, text_y + i * (size + 6), size, INK, True)
    for (j, (key, icon)) in enumerate((('goodCount', 'good'), ('okCount', 'ok'), ('ngCount', 'ng'))):
        xx = x + (24, 157, 282)[j]
        judgment_icon(im, icon, xx, y + 105, 32)
        txt(ImageDraw.Draw(im), f'{int(row.get(key) or 0):,}', x + (128, 259, 400)[j], y + 109, 23, INK, align='right')
    d = ImageDraw.Draw(im)
    d.line((x + 20, y + 146, x + w - 20, y + 146), fill='#ddd9e1', width=1)
    txt(d, 'Rating / AI 定数', x + 24, y + 155, 15, MUTED)
    score_pair(im, row['rating'], row['aiConstant'], x + 24, y + 176, 23, full_digits=1, align='left')
    txt(d, '精度', x + w - 24, y + 155, 15, MUTED, align='right')
    accuracy = f"{row['accuracy'] * 100:.2f}%"
    if row['accuracy'] >= 1:
        colored_text(im, accuracy, x + w - 24, y + 176, 23, 8, 'right')
    else:
        txt(d, accuracy, x + w - 24, y + 176, 23, TEAL, True, 'right')

def sphere(im, cx, cy, radius, color, locked=False):
    r = math.ceil(radius)
    side = 2 * r + 4
    rgb = ImageColor.getrgb(color)
    bg = ImageColor.getrgb('#101c29')
    if locked:
        rgb = tuple((round(b + (c - b) * 0.22) for (b, c) in zip(bg, rgb)))
    sprite = Image.new('RGBA', (side, side))
    pixels = sprite.load()
    for y in range(side):
        for x in range(side):
            nx = (x - r - 2) / radius
            ny = (y - r - 2) / radius
            distance = nx * nx + ny * ny
            if distance > 1:
                continue
            nz = math.sqrt(1 - distance)
            light = max(0, -0.42 * nx - 0.56 * ny + 0.71 * nz)
            gain = 0.71 + 0.22 * nz + 0.1 * light
            shine = light ** 8 * 0.1 if not locked else 0
            color = tuple((round(min(255, c * gain + (255 - c) * shine)) for c in rgb))
            pixels[x, y] = (*color, 255)
    im.alpha_composite(sprite, (round(cx - r - 2), round(cy - r - 2)))

def center_label(im, text, cx, cy, size, color):
    font = _font(size)
    w = math.ceil(font.getlength(text)) + 8
    h = size * 2
    layer = Image.new('RGBA', (w, h))
    ImageDraw.Draw(layer).text((4, 4), text, font=font, anchor='lt', fill=color)
    layer = layer.crop(layer.getchannel('A').getbbox())
    x = round(cx - layer.width / 2)
    y = round(cy - layer.height / 2)
    im.alpha_composite(layer, (x, y))
    return (x, y, x + layer.width, y + layer.height)

def stage_frame(im, data, x=106, y=1105, w=570):
    d = ImageDraw.Draw(im)
    box(d, x, y, w, 104, '#101a27', '#35465a', 14)
    current = next((i for (i, s) in enumerate(STAGES) if s['key'] == data['stage']['key']))
    txt(d, f"阶段 · {STAGES[current]['label']}", x + 21, y + 15, 16, STAGES[current]['color'])
    txt(d, f"中位 {data['center']:.2f}  ·  最大差 {data['spread']:.2f}", x + w - 21, y + 17, 13, '#aebdcc', align='right')
    start = x + 34
    step = (w - 72) / 6
    cy = y + 57
    d.line((start, cy, start + step * 6, cy), fill='#293849', width=2)
    for (i, stage) in enumerate(STAGES):
        cx = start + i * step
        locked = i > current
        if i == current:
            d.ellipse((cx - 15, cy - 15, cx + 15, cy + 15), outline=stage['color'], width=1)
        sphere(im, cx, cy, 10 if i == current else 8, stage['color'], locked)
        txt(ImageDraw.Draw(im), stage['label'], cx, y + 78, 12, '#536374' if locked else stage['color'] if i == current else '#99aabd', align='center')
    return [{'key': s['key'], 'startsAt': s['startsAt'], 'locked': i > current, 'current': i == current, 'color': s['color']} for (i, s) in enumerate(STAGES)]

def galaxy(im, data):
    data = copy.deepcopy(data)
    for (planet, color) in zip(data['planets'], PLANET_COLORS):
        planet['color'] = color
    _draw_galaxy(im, ImageDraw.Draw(im), data)
    (cx, cy) = (382, 945)
    for (index, planet) in enumerate(data['planets']):
        (rx, ry) = (72 + index * 38, 30 + index * 15)
        angle = -0.7 + index * 0.91
        (px, py) = (cx + math.cos(angle) * rx, cy + math.sin(angle) * ry)
        sphere(im, px, py, 7 + planet['normalized'] * 8, planet['color'])
    sphere(im, cx, cy, 40, data['stage']['color'])
    center_label(im, f"{data['rating']:.2f}", cx, cy, 22, '#43381f' if data['stage']['key'] in ('magma', 'corona', 'solar', 'nova') else '#233745')
    stage_frame(im, data)

class ProfileRenderer:

    def __init__(self, data):
        self.data = data
        self.analysis = data['analysis']
        self.normalized = {'rows': data['scoreRows']}
        self.improvement = data['improvement']
        self.sync_label = data['syncLabel']

    def overview(self, im):
        d = ImageDraw.Draw(im)
        rows = [r for r in self.normalized['rows'] if r['level'] in (4, 5)]
        ranks = Counter((int(r.get('bestScoreRank') or 1) for r in rows))
        states = Counter((theme.crown_state(r) for r in rows))
        box(d, 480, 148, 890, 340, '#fff8fb', '#e5d5e1', 24)
        txt(d, '成绩概况', 512, 178, 26, INK, True)
        columns = [510, 789, 1068]
        for (rank, col, y) in [(8, 2, 158), (5, 0, 229), (6, 1, 229), (7, 2, 229), (2, 0, 300), (3, 1, 300), (4, 2, 300)]:
            x = columns[col]
            asset(im, f'rank-{rank}', x, y, 66, 62)
            txt(ImageDraw.Draw(im), ranks[rank], x + 237, y + 16, 37, INK, True, 'right')
        for (col, state) in enumerate(('clear', 'fc', 'ap')):
            x = columns[col]
            theme.asset(im, 'crown-' + state, x + 3, 382, 60, 60)
            txt(ImageDraw.Draw(im), states[state], x + 237, 397, 37, INK, True, 'right')
        d = ImageDraw.Draw(im)
        txt(d, f'已玩 {len(rows):,}', 512, 451, 17, MUTED)
        txt(d, f"未通过 {states['none']} · 无评价 {ranks[1]}", 1336, 451, 17, MUTED, align='right')
        x = 501.0
        total = max(1, len(rows))
        for rank in range(1, 9):
            width = 848 * ranks[rank] / total
            if width <= 0:
                continue
            if rank == 8:
                im.alpha_composite(theme.gradient((max(1, round(width)), 9), theme.RAINBOW), (round(x), 474))
            else:
                d.rectangle((x, 474, x + width, 483), fill=RANK_COLORS[rank])
            x += width

    def config_frame(self, im, y, data):
        d = ImageDraw.Draw(im)
        box(d, 70, y, 1300, 502)
        txt(d, '当前评分 / 理论满分', 95, y + 22, 23, INK, True)
        txt(d, '按评价比例着色 · 更多配置与历史见 /rtlink progress', 1345, y + 26, 18, MUTED, align='right')
        x0 = 269
        cw = 180
        for (j, label) in enumerate(theme.COMPACT_LABELS):
            txt(d, label, x0 + j * cw + cw / 2, y + 69, 21, INK, align='center')
        cells = {c['key']: c for c in data['cells']}
        for (i, (band, label, interval)) in enumerate(data['bands']):
            yy = y + 107 + i * 48
            if i % 2 == 0:
                box(d, 85, yy - 5, 1270, 47, '#f1f3ed', '#f1f3ed', 6)
            txt(d, label, 99, yy - 1, 20, TEAL if i < 6 else '#8560ac')
            txt(d, interval + ' BPM', 99, yy + 24, 14, MUTED)
            for (j, pat) in enumerate(theme.COMPACT_PATTERNS):
                c = cells.get(pat + '|' + band)
                score_pair(im, c.get('score') if c else None, c.get('ceiling') if c else None, x0 + j * cw + cw / 2, yy + 10)
        note = '分母：相关谱面全良后按同一配置算法计算。— 表示数据或样本不足。'
        if not data.get('available'):
            note = '配置资源不可用或与谱面库不匹配，请更新完整插件资源后重新同步。'
        txt(d, note, 96, y + 464, 18, MUTED)

    def best20(self, im, y):
        rows = sorted(self.analysis['records'], key=lambda r: (-r['rating'], -r.get('accuracy', 0), r['id'], r['level']))[:20]
        if not rows:
            box(ImageDraw.Draw(im), 70, y, 1300, 110)
            txt(ImageDraw.Draw(im), '暂无可评级谱面，游玩后同步成绩即可生成 BEST 20。', 98, y + 40, 23, MUTED)
        for (i, row) in enumerate(rows):
            card(im, row, i + 1, 70 + i % 3 * 440, y + i // 3 * 220)

    def next_plays(self, im, y, count=8):
        items = self.improvement['items'][:count]
        if not items:
            box(ImageDraw.Draw(im), 70, y, 1300, 110, '#edf2e9', '#ccd8ca', 14)
            txt(ImageDraw.Draw(im), '当前没有符合条件的推荐，可用 /rtlink improve 指定其他目标评价。', 98, y + 40, 23, MUTED)
        for (i, item) in enumerate(items):
            x = 70 + i % 2 * 665
            yy = y + i // 2 * 144
            box(ImageDraw.Draw(im), x, yy, 635, 130, '#edf2e9', '#ccd8ca', 14)
            if item['level'] == 5:
                theme.asset(im, 'ura', x + 554, yy + 6, 62, 51, 0.1)
            d = ImageDraw.Draw(im)
            txt(d, f'{i + 1:02d}', x + 21, yy + 23, 19, TEAL)
            name = title(item)
            size = 23
            while _font(size).getlength(name) > 475 and size > 16:
                size -= 1
            txt(d, theme.ellipsize(name, 475, size), x + 65, yy + 18, size, INK, True)
            asset(im, f"rank-{self.improvement.get('targetRank', 8)}", x + 551, yy + 49, 40, 39)
            txt(ImageDraw.Draw(im), f"还差 {item['gap']:,} 分", x + 329, yy + 67, 19, RED)
            routes = [('ng', item.get('ngToGood', 0)), ('ok', item.get('okToGood', 0))]
            routes = [(kind, int(n)) for (kind, n) in routes if n]
            xx = x + 22
            if item.get('judgmentCovers') and routes:
                for (kind, n) in routes:
                    asset(im, kind, xx, yy + 62, 31, 27)
                    txt(ImageDraw.Draw(im), f'×{n}', xx + 34, yy + 64, 20, TEAL)
                    xx += 85
                txt(ImageDraw.Draw(im), '→', xx, yy + 63, 24, TEAL)
                asset(im, 'good', xx + 35, yy + 61, 31, 28)
            else:
                txt(ImageDraw.Draw(im), '组合判定 / 连打路线', xx, yy + 65, 19, TEAL)
            if item.get('rollFeasible') and item.get('rollsNeeded') is not None:
                txt(ImageDraw.Draw(im), f"或黄条再加 {item['rollsNeeded']} 打", x + 24, yy + 102, 17, MUTED)

    def profile(self, data):
        best_rows = max(1, math.ceil(min(20, len(self.analysis['records'])) / 3))
        recommendation_count = min(8, len(self.improvement['items']))
        next_heading = 2038 + best_rows * 220 + 42
        next_y = next_heading + 98
        height = next_y + max(1, math.ceil(recommendation_count / 2)) * 144 + 56
        im = Image.new('RGBA', (1440, height), PAPER)
        d = ImageDraw.Draw(im)
        rating = self.analysis['summary']['rating']
        txt(d, '鼓迹', 70, 52, 35, INK, True)
        txt(d, 'RTLINK / PROFILE', 170, 65, 19, RED)
        txt(d, f"PLAYER {self.data['playerId']} · {self.data['serverLabel']}", 1370, 54, 22, INK, align='right')
        txt(d, self.sync_label, 1370, 86, 18, MUTED, align='right')
        d.line((70, 120, 1370, 120), fill=LINE, width=1)
        box(d, 70, 148, 390, 340, '#17202a', '#17202a', 24)
        txt(d, 'AI 综合 RATING', 108, 185, 22, '#b9deda')
        theme.ring(im, 265, 321, 98, rating)
        d = ImageDraw.Draw(im)
        txt(d, f'{rating:.2f}', 265, 284, 59, '#ffffff', True, 'center')
        txt(d, '/ 15.50', 265, 355, 19, '#bac7ce', align='center')
        txt(d, f"已评级 {len(self.analysis['records']):,} 张", 265, 444, 18, '#c9d2d8', align='center')
        self.overview(im)
        galaxy(im, build_report_data(self.analysis))
        d = ImageDraw.Draw(im)
        txt(d, '右侧正负值为相对七维中位数，不代表历史涨跌。', 70, 1250, 19, MUTED)
        theme.section(d, '02 / CONFIGURATIONS', '配置评分概览', 1296, '7 个速度档 · 6 种常用配置')
        self.config_frame(im, 1390, data)
        theme.section(ImageDraw.Draw(im), '03 / BEST 20', '综合评分最佳 20 谱面', 1937, '按单谱 Rating 排序')
        self.best20(im, 2038)
        theme.section(ImageDraw.Draw(im), '04 / NEXT PLAY', '下一步可以尝试', next_heading, f'推荐 {recommendation_count} 首 · 更多路线见 /rtlink improve')
        self.next_plays(im, next_y)
        txt(ImageDraw.Draw(im), self.data['footer'], 70, height - 40, 18, MUTED)
        return im.convert('RGB')

    def config_details(self, data):
        has_history = len(self.data['history']) >= 2
        height = 5430 if has_history else 3630
        im = Image.new('RGBA', (1440, height), PAPER)
        d = ImageDraw.Draw(im)
        txt(d, '配置评分 · 完整详情', 70, 48, 37, INK, True)
        txt(d, f"PLAYER {self.data['playerId']} · {self.data['serverLabel']}", 1370, 57, 20, MUTED, align='right')
        note = '当前评分 / 理论满分；颜色按评价比例划分。样本为计分样本 / 库内谱面。' if data.get('available') else '配置资源不可用或与谱面库不匹配，请更新完整插件资源后重新同步。'
        txt(d, note, 70, 110, 22, MUTED)
        cells = {c['key']: c for c in data['cells']}
        for (i, (band, label, interval)) in enumerate(data['bands']):
            y = 166 + i * 459
            box(d, 70, y, 1300, 437)
            txt(d, label, 96, y + 20, 28, TEAL if i < 6 else '#8560ac', True)
            txt(d, interval + ' BPM', 256, y + 25, 21, MUTED)
            for col in range(2):
                x = 95 + col * 650
                txt(d, '配置', x, y + 72, 18, MUTED)
                txt(d, '当前 / 理论满分', x + 408, y + 72, 18, MUTED, align='right')
                txt(d, '样本', x + 594, y + 72, 18, MUTED, align='right')
                for (j, (pat, name)) in enumerate(list(RHYTHM_META.items())[col * 9:col * 9 + 9]):
                    yy = y + 113 + j * 33
                    if j % 2 == 0:
                        box(d, x - 9, yy - 4, 620, 32, '#f3f4ef', '#f3f4ef', 4)
                    c = cells.get(pat + '|' + band)
                    current = c.get('score') if c else None
                    full = c.get('ceiling') if c else None
                    txt(d, name, x, yy, 20, INK)
                    score_pair(im, current, full, x + 326, yy, 20)
                    sample = str(c['playerSamples']) if c and current is not None else '—'
                    txt(d, f"{sample} / {(c['catalogSamples'] if c else 0)}", x + 594, yy, 18, MUTED, align='right')
            txt(d, '—：该档无配置或未达到评分所需样本数。', 97, y + 411, 15, MUTED)
        y = 3405
        if has_history:
            self.history_panels(im, y)
        else:
            box(d, 70, y, 1300, 132, '#e7eee6', '#ccd8ca', 14)
            txt(d, '历史曲线 · 等待更多同步记录', 97, y + 22, 25, INK, True)
            txt(d, '至少两次有成绩变化的同版本同步后显示走势；旧 BPM 分档不会混入。', 97, y + 66, 21, MUTED)
        txt(d, self.data['footer'], 70, height - 52, 18, MUTED)
        return im.convert('RGB')

    def history_panels(self, im, y):
        """All configurations on a shared time axis; missing samples break lines."""
        history = self.data['history']
        times = [datetime.fromisoformat(row['captured_at']).timestamp() for row in history]
        span = max(1e-6, times[-1] - times[0])
        snapshots = [{c['key']: c.get('score') for c in row['payload']['configurations']['cells']} for row in history]
        d = ImageDraw.Draw(im)
        txt(d, f'配置走势 · 最近 {len(history)} 次有效同步', 70, y, 28, INK, True)
        txt(d, '同一玩家 / 服务器 / 数据源 / 算法版本 · 缺失样本不连线', 70, y + 43, 18, MUTED)
        for i, (_, label, _) in enumerate(self.data['configurations']['bands']):
            x = 80 + i * 184
            d.line((x, y + 89, x + 27, y + 89), fill=PLANET_COLORS[i], width=4)
            txt(d, label, x + 36, y + 79, 18, INK)
        scores = [v for snap in snapshots for v in snap.values() if v is not None]
        low = max(0, math.floor(min(scores, default=0)) - 1)
        high = max(low + 2, math.ceil(max(scores, default=1)) + 1)
        for i, (pattern, name) in enumerate(RHYTHM_META.items()):
            x = 70 + i % 3 * 440
            yy = y + 121 + i // 3 * 298
            box(d, x, yy, 420, 282)
            txt(d, name, x + 18, yy + 16, 23, INK, True)
            left, right, top, bottom = x + 44, x + 402, yy + 61, yy + 240
            for value in (low, (low + high) / 2, high):
                py = bottom - (value - low) / (high - low) * (bottom - top)
                d.line((left, py, right, py), fill=LINE, width=1)
                txt(d, f'{value:g}', left - 8, py - 7, 13, MUTED, align='right')
            has_points = False
            for j, (band, _, _) in enumerate(self.data['configurations']['bands']):
                previous = None
                for timestamp, snap in zip(times, snapshots):
                    value = snap.get(pattern + '|' + band)
                    if value is None:
                        previous = None
                        continue
                    has_points = True
                    px = left + (timestamp - times[0]) / span * (right - left)
                    py = bottom - (value - low) / (high - low) * (bottom - top)
                    if previous is not None:
                        d.line((*previous, px, py), fill=PLANET_COLORS[j], width=2)
                    d.ellipse((px - 2, py - 2, px + 2, py + 2), fill=PLANET_COLORS[j])
                    previous = (px, py)
            if not has_points:
                txt(d, '暂无足够样本', (left + right) / 2, yy + 142, 18, MUTED, align='center')
            for timestamp, xx, align in ((times[0], left, 'left'), (times[-1], right, 'right')):
                label = datetime.fromtimestamp(timestamp, timezone(timedelta(hours=8))).strftime('%m/%d %H:%M')
                txt(d, label, xx, yy + 255, 13, MUTED, align=align)

def _save_image(image,out_path):
    output=os.path.abspath(out_path)
    os.makedirs(os.path.dirname(output),exist_ok=True)
    image.save(output,'PNG',compress_level=6)
    return output

def render_profile_image(analysis,out_path,generated_at=None):
    data=build_profile_data(analysis,generated_at)
    return _save_image(ProfileRenderer(data).profile(data['configurations']),out_path)

def render_configuration_image(analysis,out_path,generated_at=None):
    data=build_profile_data(analysis,generated_at)
    return _save_image(ProfileRenderer(data).config_details(data['configurations']),out_path)
