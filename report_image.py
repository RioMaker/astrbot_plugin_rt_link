# -*- coding: utf-8 -*-
"""Fixed 1440x2400 PNG export matching the rating-analysis report template."""

from __future__ import annotations

import math
import os
import textwrap

import matplotlib

matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
from matplotlib.patches import Ellipse, FancyBboxPatch, Rectangle, Wedge

_fonts_ready = False
_cjk_font = None
WIDTH, HEIGHT = 1440, 2400
MAX_RATING = 15.5
INK, INK_SOFT = "#17202a", "#26313d"
PAPER, SURFACE = "#f3f0e8", "#fffdf8"
SURFACE_SOFT, LINE = "#ebe7dd", "#d7d2c6"
MUTED, QUIET = "#69727a", "#8c928f"
ACCENT, ACCENT_DARK = "#ee6547", "#b9422e"
MINT, MINT_DARK = "#87c9b8", "#2a7f72"

RADAR_DIMS = [
    ("chartPower", "谱面底力", "#ff6b4a", "攻关星"),
    ("sustainedEndurance", "持续耐力", "#f1ba3e", "耐力星"),
    ("burstSpeed", "爆发手速", "#a879e0", "爆发星"),
    ("hitPrecision", "击打精度", "#55c9a9", "精度星"),
    ("patternControl", "配置处理", "#66a5ef", "复合星"),
    ("timingAdaptation", "节奏适应", "#ee78ad", "节奏星"),
    ("visualReading", "读谱", "#a4b4bd", "目视星"),
]
DIM_NAME = {key: label for key, label, _color, _planet in RADAR_DIMS}
DIM_COLOR = {key: color for key, _label, color, _planet in RADAR_DIMS}


def _setup_fonts():
    global _fonts_ready, _cjk_font
    if _fonts_ready:
        return
    _fonts_ready = True
    plugin_font = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resource", "NotoSansCJKsc-Regular.otf")
    paths = [
        plugin_font,
        r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyhl.ttc",
        r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\simsun.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    ]
    names = []
    for path in paths:
        if os.path.exists(path):
            try:
                fm.fontManager.addfont(path)
                names.append(fm.FontProperties(fname=path).get_name())
                if _cjk_font is None:
                    _cjk_font = fm.FontProperties(fname=path)
            except Exception:
                pass
    if _cjk_font is None:
        raise RuntimeError("未找到可显示中文的 CJK 字体，请安装 Microsoft YaHei、Noto Sans CJK 或文泉驿字体")
    plt.rcParams["font.sans-serif"] = names
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["axes.unicode_minus"] = False


def _number(value, fallback=0.0):
    try:
        value = float(value)
        return value if math.isfinite(value) else fallback
    except (TypeError, ValueError):
        return fallback


def _score(value):
    return max(0.0, min(MAX_RATING, _number(value)))


def _fixed(value, digits=2):
    return f"{_number(value):.{digits}f}"


def _box(ax, x, y, width, height, color, edge=None, radius=24, z=1):
    ax.add_patch(FancyBboxPatch((x, y), width, height,
                                boxstyle=f"round,pad=0,rounding_size={radius}",
                                facecolor=color, edgecolor=edge or "none",
                                linewidth=1.5, zorder=z))


def _text(ax, value, x, y, size, color=INK, weight="normal", align="left", family=None, z=5):
    font_properties = None
    if any(ord(char) > 127 for char in str(value)):
        font_properties = _cjk_font
    if family == "monospace" and font_properties is None:
        family = "monospace"
    elif font_properties is not None:
        family = "sans-serif"
    ax.text(x, y, str(value), fontsize=size, color=color, fontweight=weight,
            ha=align, va="top", family=family if font_properties is None else None,
            fontproperties=font_properties, zorder=z)


def _wrap(value, max_width, size, limit=3):
    """Wrap by estimated rendered width, not character count.

    CJK glyphs are close to one em while Latin text is narrower. Character
    count alone was the source of the long lines escaping the fixed cards.
    """
    lines, current, current_width = [], "", 0.0
    for char in str(value or ""):
        char_width = size * (1.02 if ord(char) > 127 else 0.58)
        if current and current_width + char_width > max_width:
            lines.append(current)
            current, current_width = char, char_width
            if len(lines) == limit:
                break
        else:
            current += char
            current_width += char_width
    if len(lines) < limit and current:
        lines.append(current)
    if not lines:
        lines = [""]
    if len(lines) == limit and sum(1 for _ in str(value or "")) > len("".join(lines)):
        lines[-1] = lines[-1][:-1] + "…"
    return lines


def _wrapped(ax, value, x, y, width, size, line_height, color=MUTED, weight="normal", limit=3):
    for index, line in enumerate(_wrap(value, width, size, limit)):
        _text(ax, line, x, y + index * line_height, size, color, weight)


def _truncate(value, max_width, size):
    text = str(value or "")
    return _wrap(text, max_width, size, 1)[0]


def _level(level):
    return {4: "鬼", 5: "里"}.get(level, f"Lv.{level}")


def _stage(rating):
    if rating < 1: return ("冰冻石核", "你的 Rating 正孕育一颗冰冻星核", "#8bb8cf")
    if rating < 5: return ("逐步解冻", "你的 Rating 正在解冻一颗沉睡星核", "#b7c3bf")
    if rating < 7: return ("岩浆混合体", "你的 Rating 正在唤醒一颗岩浆星", "#ef7044")
    if rating < 9: return ("日冕成长期", "你的 Rating 正在点燃一颗恒星", "#ffb13c")
    if rating < 10: return ("类太阳体", "你的 Rating 正在稳定一颗类太阳体", "#ffd45a")
    if rating < 13: return ("超新星前兆", "你的 Rating 正推动恒星走向爆发", "#fff0a3")
    return ("极亮超新星", "你的 Rating 正照亮一颗极亮超新星", "#f7fbff")


def _families(analysis):
    raw = (analysis.get("featureAbility") or {}).get("families") or []
    return [{**item, "key": item.get("key"), "score": _score(item.get("score")),
             "charts": int(_number(item.get("charts")))} for item in raw if item.get("key")]


def _draw_header(ax, analysis):
    meta = analysis.get("meta") or {}
    _text(ax, "鼓迹", 70, 58, 34, INK, "bold")
    _text(ax, "TAIKO TRACE", 160, 70, 15, ACCENT, "bold", family="monospace")
    _text(ax, f"PLAYER {meta.get('playerId') or '--'}", 1370, 56, 15, INK, "bold", "right", "monospace")
    _text(ax, f"{meta.get('server') or '--'} · AI v2", 1370, 82, 13, MUTED, align="right")
    ax.plot([70, 1370], [120, 120], color=LINE, lw=1)


def _draw_hero(ax, analysis, families):
    rating = _score((analysis.get("summary") or {}).get("rating"))
    ranked = sorted((f for f in families if f["charts"] >= 3), key=lambda item: item["score"], reverse=True)
    strongest, weakest = (ranked[0] if ranked else None), (ranked[-1] if ranked else None)
    stage, _headline, stage_color = _stage(rating)
    _box(ax, 70, 148, 390, 340, INK, radius=24)
    _text(ax, "AI 综合 RATING", 108, 192, 18, MINT, "bold", family="monospace")
    center = (265, 321)
    ax.add_patch(Wedge(center, 96, 0, 360, width=18, facecolor="white", alpha=.12, zorder=3))
    ax.add_patch(Wedge(center, 96, 90, 90 - rating / MAX_RATING * 360, width=18, facecolor=ACCENT, zorder=4))
    _text(ax, _fixed(rating), 265, 290, 54, "white", "bold", "center", "monospace")
    _text(ax, "/ 15.50", 265, 355, 16, "#8f9ca8", align="center", family="monospace")
    _box(ax, 108, 426, 314, 36, "#26313d", radius=18)
    _text(ax, f"恒星阶段 · {stage}", 265, 434, 14, stage_color, "bold", "center")
    _box(ax, 480, 148, 890, 340, SURFACE, LINE, radius=24)
    _text(ax, "本次关键结论", 528, 190, 17, ACCENT_DARK, "bold", family="monospace")
    headline = f"{DIM_NAME.get(strongest['key'], strongest['key'])}最突出，{DIM_NAME.get(weakest['key'], weakest['key'])}是当前突破口" if strongest and weakest else "有效成绩已生成，能力证据仍待补充"
    _wrapped(ax, headline, 528, 228, 790, 41, 52, INK, "bold", 2)
    summary = (f"七类能力最大差距为 {_fixed(strongest['score'] - weakest['score'])}。保持{DIM_NAME.get(strongest['key'], strongest['key'])}优势；下一轮优先处理{DIM_NAME.get(weakest['key'], weakest['key'])}。" if strongest and weakest else "当前数据不足以稳定比较七类能力，请继续积累鬼或里难度成绩。")
    _wrapped(ax, summary, 528, 340, 790, 20, 32, MUTED, limit=2)
    tags = []
    if strongest: tags.append(f"优势 · {DIM_NAME.get(strongest['key'], strongest['key'])} {_fixed(strongest['score'])}")
    if weakest: tags.append(f"补强 · {DIM_NAME.get(weakest['key'], weakest['key'])} {_fixed(weakest['score'])}")
    x = 528
    for tag in tags[:2]:
        tag = _truncate(tag, 220, 15)
        tag_width = min(250, max(150, len(tag) * 11 + 30))
        _box(ax, x, 422, tag_width, 32, SURFACE_SOFT, radius=16)
        _text(ax, tag, x + 15, 429, 15, INK_SOFT, "bold")
        x += tag_width + 12
    return ranked


def _draw_galaxy(ax, analysis, families):
    rating = _score((analysis.get("summary") or {}).get("rating"))
    stage, headline, stage_color = _stage(rating)
    ranked = sorted((f for f in families if f["charts"] >= 3), key=lambda item: item["score"], reverse=True)
    center = sum(item["score"] for item in ranked) / len(ranked) if ranked else 0
    _text(ax, "01 / GALAXY", 78, 530, 17, ACCENT_DARK, "bold", family="monospace")
    _text(ax, "能力星系数据", 78, 560, 34, INK, "bold")
    _box(ax, 70, 620, 1300, 615, "#050911", "#263345", radius=24)
    _text(ax, headline, 106, 655, 25, "white", "bold")
    _wrapped(ax, f"恒星阶段：{stage}。七颗能力行星以同一 15.50 标尺呈现。", 106, 693, 570, 15, 24, "#9caaba", limit=2)
    cx, cy = 382, 945
    for index, item in enumerate(RADAR_DIMS):
        key, _label, color, _planet = item
        score = next((f["score"] for f in families if f["key"] == key), 0)
        rx, ry = 72 + index * 38, 30 + index * 15
        ax.add_patch(Ellipse((cx, cy), rx * 2, ry * 2, angle=-7,
                             fill=False, edgecolor="#97b8e2", alpha=.12 + index * .012))
        angle = -.7 + index * .91
        px, py = cx + math.cos(angle) * rx, cy + math.sin(angle) * ry
        ax.scatter([px], [py], s=50 + score / MAX_RATING * 120, color=color, alpha=.95, zorder=4)
    ax.scatter([cx], [cy], s=350, color=stage_color, alpha=.85, zorder=3)
    _text(ax, _fixed(rating), cx, cy - 15, 22, INK, "bold", "center", "monospace", 6)
    _box(ax, 106, 1142, 570, 58, "#101722", "#36475c", radius=14)
    _text(ax, f"阶段 {stage}", 128, 1158, 14, stage_color, "bold")
    spread = ranked[0]["score"] - ranked[-1]["score"] if len(ranked) > 1 else 0
    _text(ax, f"中位 {_fixed(center)} · 最大差 {_fixed(spread)}", 650, 1158, 14, "#c4ced9", "bold", "right", "monospace")
    ax.plot([735, 735], [650, 1200], color="#263345")
    _text(ax, "七颗能力行星", 778, 654, 18, "white", "bold")
    _text(ax, "分数 / 证据 / 相对中位", 1328, 658, 12, "#93a3b5", align="right", family="monospace")
    for index, (key, label, color, planet) in enumerate(RADAR_DIMS):
        item = next((f for f in families if f["key"] == key), {"score": 0, "charts": 0})
        y = 706 + index * 68
        if index: ax.plot([778, 1328], [y - 10, y - 10], color="#97b8e2", alpha=.12)
        ax.scatter([791], [y + 13], s=50, color=color)
        _text(ax, planet, 812, y, 15, "white", "bold")
        _text(ax, label, 920, y + 1, 14, "#9caaba")
        _text(ax, _fixed(item.get("score")), 1160, y - 3, 23, color, "bold", "right", "monospace")
        _text(ax, f"{item.get('charts', 0)} 张 · {item.get('score', 0) - center:+.2f}", 1183, y + 2, 12, "#c4ced9", family="monospace")
        _box(ax, 812, y + 32, 348, 7, "#263345", radius=4)
        _box(ax, 812, y + 32, max(5, item.get("score", 0) / MAX_RATING * 348), 7, color, radius=4)


def _draw_actions(ax, analysis, families):
    ranked = sorted((f for f in families if f["charts"] >= 3), key=lambda item: item["score"])
    rhythm = (analysis.get("rhythmAbility") or {}).get("weakest") or []
    weakest = ranked[0] if ranked else None
    actions = []
    if weakest:
        actions.append(("01 / 能力突破口", f"{DIM_NAME.get(weakest['key'], weakest['key'])}补强", weakest["score"], f"{weakest['charts']} 张能力证据", f"围绕{DIM_NAME.get(weakest['key'], weakest['key'])}选择低压谱面，稳定后再提高压力。"))
    if rhythm:
        item = rhythm[0]
        actions.append(("02 / 节奏突破口", f"{item.get('pattern', '节奏型')} · BPM {item.get('bpmBand', '--')}", _score(item.get("score")), f"{item.get('charts', 0)} 张节奏证据", "先在同 BPM 的低压谱面中分段练习，确认空拍与落点。"))
    actions.append(("03 / 目视突破口", "目视变化识别", weakest["score"] if weakest else 0, "静态画像建议", "先降低击打压力，单独识别视觉变化，再回到实战谱面。"))
    _text(ax, "02 / DIAGNOSIS", 78, 1270, 17, ACCENT_DARK, "bold", family="monospace")
    _text(ax, "关键弱项与下一步动作", 78, 1300, 34, INK, "bold")
    width, gap = (1300 - 36) / 3, 18
    for index, (category, title, score, evidence, method) in enumerate(actions[:3]):
        x = 70 + index * (width + gap)
        _box(ax, x, 1358, width, 332, "#f8ddd6" if index == 0 else SURFACE, LINE, radius=20)
        _text(ax, category, x + 28, 1386, 14, ACCENT_DARK if index == 0 else MUTED, "bold", family="monospace")
        _wrapped(ax, title, x + 28, 1420, 322, 23, 30, INK, "bold", 2)
        _text(ax, f"{_fixed(score)} · {evidence}", x + 28, 1486, 14, MUTED, "bold", family="monospace")
        ax.plot([x + 28, x + width - 28], [1592, 1592], color=LINE)
        _text(ax, "建议动作", x + 28, 1610, 12, ACCENT_DARK if index == 0 else MINT_DARK, "bold", family="monospace")
        _wrapped(ax, method, x + 28, 1633, 322, 15, 22, INK_SOFT, limit=2)


def _draw_evidence(ax, analysis):
    records = sorted(analysis.get("records") or [], key=lambda item: -_score(item.get("rating")))[:5]
    _text(ax, "03 / EVIDENCE", 78, 1725, 17, ACCENT_DARK, "bold", family="monospace")
    _text(ax, "支撑弱项判断的关键谱面", 78, 1755, 34, INK, "bold")
    _box(ax, 70, 1813, 1300, 352, SURFACE, LINE, radius=20)
    for label, x in (("#", 102), ("对应判断", 150), ("谱面", 340), ("难度", 950), ("AI 定数", 1040), ("准确率", 1162), ("Rating", 1322)):
        _text(ax, label, x, 1836, 12, MUTED, "bold", "right" if label == "Rating" else "left", "monospace")
    for index, row in enumerate(records):
        y = 1878 + index * 53
        if index: ax.plot([96, 1344], [y - 12, y - 12], color=LINE)
        _text(ax, f"{index + 1:02d}", 102, y + 2, 13, QUIET, "bold", family="monospace")
        _box(ax, 148, y - 3, 162, 28, "#ebe7dd", radius=14)
        _text(ax, "综合上限", 229, y + 3, 12, MINT_DARK, "bold", "center")
        title = _truncate(row.get("title") or f"谱面 {row.get('id')}", 570, 16)
        _text(ax, title, 340, y, 16, INK, "bold")
        _text(ax, _level(row.get("level")), 950, y + 2, 14, MUTED, "bold")
        _text(ax, _fixed(row.get("aiConstant") or row.get("constant"), 1), 1040, y + 2, 14, INK_SOFT, "bold", family="monospace")
        _text(ax, f"{_number(row.get('accuracy')) * 100:.2f}%", 1162, y + 2, 14, INK_SOFT, "bold", family="monospace")
        _text(ax, _fixed(row.get("rating")), 1322, y - 1, 18, INK, "bold", "right", "monospace")


def render_report_image(analysis: dict, out_path: str) -> str:
    """Render the same fixed report hierarchy as the source Canvas exporter."""
    _setup_fonts()
    fig = plt.figure(figsize=(WIDTH / 100, HEIGHT / 100), dpi=100)
    fig.patch.set_facecolor(PAPER)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, WIDTH)
    ax.set_ylim(HEIGHT, 0)
    ax.axis("off")
    ax.set_facecolor(PAPER)
    ax.set_xticks(range(0, WIDTH + 1, 40), minor=False)
    ax.set_yticks(range(0, HEIGHT + 1, 40), minor=False)
    ax.grid(True, color=INK, alpha=.025, linewidth=.5)
    ax.tick_params(left=False, bottom=False, labelleft=False, labelbottom=False)
    _draw_header(ax, analysis)
    families = _families(analysis)
    _draw_hero(ax, analysis, families)
    _draw_galaxy(ax, analysis, families)
    _draw_actions(ax, analysis, families)
    _draw_evidence(ax, analysis)
    metrics = [
        ("有效谱面", str((analysis.get("meta") or {}).get("uniqueCharts") or 0), "去重后的最佳成绩"),
        ("特征覆盖", f"{_number((analysis.get('featureAbility') or {}).get('matchedCharts')) / max(_number((analysis.get('meta') or {}).get('uniqueCharts')), 1) * 100:.1f}%", "有完整画像"),
        ("v1 参考差", _fixed(_number((analysis.get("summary") or {}).get("rating")) - _number(((analysis.get("ourTaikoV1") or {}).get("summary") or {}).get("rating"))), "仅用于标尺对照"),
        ("未纳入成绩", str(_number((analysis.get("counts") or {}).get("belowThreshold")) + _number((analysis.get("counts") or {}).get("missing"))), "低准确率或未匹配"),
    ]
    for index, (label, value, note) in enumerate(metrics):
        x = 70 + index * ((1300 + 12) / 4)
        _box(ax, x, 2200, 316, 88, "#fffdf8", LINE, radius=14)
        _text(ax, label, x + 18, 2217, 11, QUIET, "bold", family="monospace")
        _text(ax, value, x + 18, 2238, 22, INK_SOFT, "bold", family="monospace")
        _text(ax, note, x + 300, 2243, 11, MUTED, align="right")
    meta = analysis.get("meta") or {}
    _text(ax, f"AI 主结果 · 玩家成绩只用于本次报告 · {meta.get('server') or '--'}", 70, 2335, 12, MUTED)
    _text(ax, "星系为能力数据的静态表达；不代表历史趋势、通关预测或官方竞技裁定。", 70, 2360, 12, MUTED)
    _text(ax, "报告含玩家 ID 与成绩摘要，请按个人数据妥善分享。", 1370, 2360, 12, ACCENT_DARK, "bold", "right")
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    fig.savefig(out_path, dpi=100, facecolor=PAPER, pil_kwargs={"compress_level": 6})
    plt.close(fig)
    return out_path
