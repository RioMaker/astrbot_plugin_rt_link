# -*- coding: utf-8 -*-
"""Deterministic 1440x2720 report renderer shared with the Taiko Trace design.

The browser report uses a fixed Canvas layout.  This module mirrors that data
summary and those pixel coordinates with Pillow so AstrBot can generate the
same report without a browser, Node.js, Matplotlib, or a remote backend.
"""

from __future__ import annotations

import math
import os
from datetime import datetime
from functools import lru_cache
from statistics import median

from PIL import Image, ImageDraw, ImageFilter, ImageFont

WIDTH, HEIGHT = 1440, 2720
MAX_RATING = 15.5
INK, INK_SOFT = "#17202a", "#26313d"
PAPER, SURFACE = "#f3f0e8", "#fffdf8"
SURFACE_SOFT, LINE = "#ebe7dd", "#d7d2c6"
MUTED, QUIET = "#69727a", "#8c928f"
ACCENT, ACCENT_DARK = "#ee6547", "#b9422e"
MINT, MINT_DARK = "#87c9b8", "#2a7f72"

FAMILY_META = {
    "chartPower": {"label": "基础攻关", "color": "#e85e47", "planet": "攻关星", "planetColor": "#ff6b4a", "description": "AI 定数与成绩准确率共同体现的基础难度处理"},
    "sustainedEndurance": {"label": "持续耐力", "color": "#c89b31", "planet": "耐力星", "planetColor": "#f1ba3e", "description": "相对同难度谱面的持续密度、长串和体力负荷"},
    "burstSpeed": {"label": "爆发速度", "color": "#8565b3", "planet": "爆发星", "planetColor": "#a879e0", "description": "相对同难度谱面的瞬时密度、24/32 分与短串峰值"},
    "hitPrecision": {"label": "精度兑现", "color": "#2f9584", "planet": "精度星", "planetColor": "#55c9a9", "description": "当前难度上的良率和全良兑现表现"},
    "patternControl": {"label": "复合控制", "color": "#4e80bd", "planet": "复合星", "planetColor": "#66a5ef", "description": "相对同难度谱面的配色、换手和复合句型要求"},
    "timingAdaptation": {"label": "节奏适应", "color": "#bd6088", "planet": "节奏星", "planetColor": "#ee78ad", "description": "相对同难度谱面的叩击区分、细分与 BPM 变化要求"},
    "visualReading": {"label": "目视读谱", "color": "#66727c", "planet": "目视星", "planetColor": "#a4b4bd", "description": "相对同难度谱面的 HS、超车、逆向和滚动模式要求"},
}
FAMILY_ORDER = tuple(FAMILY_META)
FAMILY_PRACTICE = {
    "chartPower": "选择 AI 定数略低一档的谱面稳定精度，再逐步回到当前攻关区间。",
    "sustainedEndurance": "选择密度相近但更短的长串，分段练习放松与续力，避免全程紧绷。",
    "burstSpeed": "从目标速度下调一个 BPM 档，保持动作小而均匀；稳定后再逐步回到目标速度。",
    "hitPrecision": "选择已能稳定通过的同类谱面，把目标改为减少“可”，保持落点一致。",
    "patternControl": "先口读并固定换手，再用低速重复同类配色；定位具体换色点。",
    "timingAdaptation": "先脱离谱面确认拍点和细分，再回到低压谱面，优先保证落点稳定。",
    "visualReading": "降低击打压力，主动观察视线落点、HS 和超车，先练看懂再练跟上。",
}
RHYTHM_META = {
    "quarter_scatter": "4 分散音", "quarter_stream": "4 分连续",
    "8-scatter": "8 分散音", "8-stream": "8 分连续",
    "12-triplet": "12 分跳音", "12-fish": "12 分鱼蛋",
    "sixteenth_2": "16 分二连", "16-3": "16 分三连", "16-4": "16 分四连",
    "16-5": "16 分五连", "16-6": "16 分六连", "16-7": "16 分七连", "16-fish": "16 分鱼蛋",
    "twentyfourth_burst": "24 分短串", "twentyfourth_compound": "24 分复合", "24-fish": "24 分鱼蛋",
    "thirtysecond_burst": "32 分爆发", "32-fish": "32 分鱼蛋",
}
BPM_META = {"lt120": "< 120", "120_149": "120-149", "150_179": "150-179", "180_209": "180-209", "210_239": "210-239", "gte240": ">= 240"}
VISUAL_META = {
    "overtake": ("超车", "不同视觉速度的音符在击打前交换前后关系"),
    "scrollChange": ("滚速变化", "HS 变化时重新判断视觉速度"),
    "reverse": ("逆向", "负 HS 音符从相反方向接近判定点"),
    "verticalReverse": ("纵向逆向", "复数 HS 的负虚部让音符沿相反纵向移动"),
    "complexScroll": ("复数滚动", "复数 HS 让音符沿二维斜向轨迹接近判定点"),
    "stopped": ("停止", "HS 为零时失去正常移动提示"),
    "compressed": ("视觉压缩", "低 HS 让视觉间距比实际节奏更密"),
    "expanded": ("视觉拉伸", "高 HS 让视觉间距比实际节奏更疏"),
    "bmScroll": ("BM 滚动", "忽略 HS 与 BPM 绝对值、按有符号拍位显示"),
    "hbScroll": ("HB 滚动", "保留 HS、按有符号拍位而非时间距离显示"),
}


def _number(value, fallback=0.0):
    try:
        value = float(value)
        return value if math.isfinite(value) else fallback
    except (TypeError, ValueError):
        return fallback


def _fixed(value, digits=2):
    return f"{_number(value):.{digits}f}"


def _stage(rating):
    if rating < 1: return {"key": "frozen", "label": "冰冻石核", "detail": "核心尚未点燃，表面被冰层与岩石覆盖。", "headline": "你的 Rating 正孕育一颗冰冻星核", "color": "#8bb8cf"}
    if rating < 5: return {"key": "thawing", "label": "逐步解冻", "detail": "内部热量上升，冰层裂开并出现微弱熔光。", "headline": "你的 Rating 正在解冻一颗沉睡星核", "color": "#b7c3bf"}
    if rating < 7: return {"key": "magma", "label": "岩浆混合体", "detail": "岩石地壳与岩浆共存，裂隙开始持续喷发。", "headline": "你的 Rating 正在唤醒一颗岩浆星", "color": "#ef7044"}
    if rating < 9: return {"key": "corona", "label": "日冕成长期", "detail": "恒星点燃，日冕和表面喷流随 Rating 增强。", "headline": "你的 Rating 正在点燃一颗恒星", "color": "#ffb13c"}
    if rating < 10: return {"key": "solar", "label": "类太阳体", "detail": "稳定恒星状态，表面对流和耀斑活动明显。", "headline": "你的 Rating 正在稳定一颗类太阳体", "color": "#ffd45a"}
    if rating < 13: return {"key": "nova", "label": "超新星前兆", "detail": "能量持续积聚，冲击波和高温喷流环绕核心。", "headline": "你的 Rating 正推动恒星走向爆发", "color": "#fff0a3"}
    return {"key": "supernova", "label": "极亮超新星", "detail": "能力核心进入极亮阶段，强烈日冕与冲击波持续爆发。", "headline": "你的 Rating 正照亮一颗极亮超新星", "color": "#f7fbff"}


def _orbit_period(score):
    normalized = max(0.0, min(1.0, score / 14.0))
    return 10 + 590 * (1 - normalized) ** 3


def _format_period(period):
    if period >= 60:
        minutes = period / 60
        return f"{minutes:.0f}m" if minutes >= 10 else f"{minutes:.1f}m"
    return f"{period:.1f}s"


def _rhythm_label(pattern):
    return RHYTHM_META.get(pattern, str(pattern or "").replace("_", " "))


def _bpm_label(band):
    return BPM_META.get(band, str(band or "--"))


def _rhythm_practice(item):
    cue = "先降低一个 BPM 档" if item.get("bpmBand") in ("gte240", "210_239") else "先在同 BPM 的低压谱面中"
    pattern = str(item.get("pattern") or "")
    if "fish" in pattern: return f"{cue}分段练连续放松与换手，稳定后再延长。"
    if any(token in pattern for token in ("24", "32", "twentyfourth", "thirtysecond")): return f"{cue}练短串爆发，动作保持小而均匀。"
    if any(token in pattern for token in ("16-3", "16-4", "16-5", "16-6", "16-7", "sixteenth")): return f"{cue}固定起手与配色，连续稳定后再提高压力。"
    if "12" in pattern: return f"{cue}口读三等分拍点，再回谱面确认落点。"
    return f"{cue}跟随节拍口读并击打，确认空拍与落点。"


def _append_evidence(target, seen, rows, focus, color, limit):
    for row in (rows or [])[:limit]:
        key = f"{row.get('id')}-{row.get('level')}"
        if key in seen or len(target) >= 5:
            continue
        seen.add(key)
        target.append({
            "focus": focus, "color": color, "title": row.get("title") or f"谱面 {row.get('id')}",
            "level": "里" if row.get("level") == 5 else "鬼" if row.get("level") == 4 else f"Lv.{row.get('level')}",
            "rating": _number(row.get("rating")), "accuracy": _number(row.get("accuracy")),
            "constant": _number(row.get("aiConstant") if row.get("aiConstant") is not None else row.get("constant")),
        })


def build_report_data(analysis: dict, generated_at: datetime | None = None) -> dict:
    """Build the same compact summary consumed by the website Canvas renderer."""
    generated_at = generated_at or datetime.now()
    rating = _number((analysis.get("summary") or {}).get("rating"))
    raw_families = (analysis.get("featureAbility") or {}).get("families") or []
    families = []
    for raw in raw_families:
        if _number(raw.get("charts")) < 3:
            continue
        key = raw.get("key")
        meta = FAMILY_META.get(key, {})
        families.append({**raw, "key": key, "label": meta.get("label", key), "color": meta.get("color", ACCENT),
                         "description": meta.get("description", ""), "score": _number(raw.get("score")), "charts": int(_number(raw.get("charts")))})
    families.sort(key=lambda item: item["score"], reverse=True)
    center = median([item["score"] for item in families]) if families else 0.0
    strongest = families[0] if families else None
    weakest = families[-1] if families else None
    rhythm = analysis.get("rhythmAbility") or {}
    best_rhythm = (rhythm.get("best") or [None])[0]
    weak_rhythm = (rhythm.get("weakest") or [None])[0]
    visuals = [item for item in (rhythm.get("visual") or {}).values() if _number(item.get("charts")) >= 3]
    weakest_visual = min(visuals, key=lambda item: _number(item.get("score")), default=None)
    rare_rhythms = []
    for item in (rhythm.get("rareWeakest") or [])[:3]:
        rare_rhythms.append({
            "pattern": item.get("pattern"),
            "label": _rhythm_label(item.get("pattern")),
            "bpm": _bpm_label(item.get("bpmBand")),
            "score": _number(item.get("score")),
            "charts": int(_number(item.get("charts"))),
            "catalogCharts": int(_number(item.get("catalogCharts"))),
            "catalogCoverage": _number(item.get("catalogCoverage")),
        })
    unique = int(_number((analysis.get("meta") or {}).get("uniqueCharts")))
    matched = int(_number((analysis.get("featureAbility") or {}).get("matchedCharts")))
    public_rating = _number(((analysis.get("ourTaikoV1") or {}).get("summary") or {}).get("rating"), math.nan)
    stage = _stage(rating)

    planets = []
    family_map = {item["key"]: item for item in families}
    ranked_keys = [item["key"] for item in families]
    for index, key in enumerate(FAMILY_ORDER):
        meta = FAMILY_META[key]
        item = family_map.get(key, {"score": 0.0, "charts": 0})
        score = _number(item.get("score"))
        planets.append({**item, "key": key, "name": meta["planet"], "label": meta["label"],
                        "color": meta["planetColor"], "score": score, "charts": int(_number(item.get("charts"))),
                        "normalized": max(0.0, min(1.0, score / 14.0)), "period": _orbit_period(score),
                        "delta": score - center, "rank": ranked_keys.index(key) + 1 if key in ranked_keys else 0,
                        "index": index})

    actions = []
    if weakest:
        actions.append({"index": "01", "category": "能力突破口", "title": f"{weakest['label']}补强", "score": weakest["score"],
                        "evidence": f"{weakest['charts']} 张能力证据", "signal": f"{weakest['description']}低于个人七项能力中位 {_fixed(abs(weakest['score'] - center))}。",
                        "method": FAMILY_PRACTICE.get(weakest["key"], f"围绕{weakest['description']}选择低压谱面稳定练习。")})
    if weak_rhythm:
        actions.append({"index": "02", "category": "节奏突破口", "title": f"{_rhythm_label(weak_rhythm.get('pattern'))} · BPM {_bpm_label(weak_rhythm.get('bpmBand'))}",
                        "score": _number(weak_rhythm.get("score")), "evidence": f"{int(_number(weak_rhythm.get('charts')))} 张节奏证据",
                        "signal": f"平均 BPM {_fixed(weak_rhythm.get('averageBpm'), 0)}，是当前合格节奏单元中的优先补强项。", "method": _rhythm_practice(weak_rhythm)})
    if weakest_visual:
        visual_key = weakest_visual.get("key")
        visual_label, visual_desc = VISUAL_META.get(visual_key, (visual_key or "目视变化", "视觉变化"))
        actions.append({"index": "03", "category": "目视突破口", "title": f"{visual_label}识别", "score": _number(weakest_visual.get("score")),
                        "evidence": f"{int(_number(weakest_visual.get('charts')))} 张目视证据", "signal": f"{visual_desc}，暴露权重 {_fixed(weakest_visual.get('exposure'))}。",
                        "method": f"先降低击打压力，单独识别{visual_desc}，再回到实战谱面。"})

    evidence, seen = [], set()
    _append_evidence(evidence, seen, weakest.get("best") if weakest else [], weakest.get("label") if weakest else "能力补强", weakest.get("color") if weakest else ACCENT, 2)
    _append_evidence(evidence, seen, weak_rhythm.get("best") if weak_rhythm else [], _rhythm_label(weak_rhythm.get("pattern")) if weak_rhythm else "节奏补强", ACCENT_DARK, 2)
    if weakest_visual:
        visual_label = VISUAL_META.get(weakest_visual.get("key"), (weakest_visual.get("key"), ""))[0]
        _append_evidence(evidence, seen, weakest_visual.get("best"), visual_label, "#66727c", 1)
    records = sorted(analysis.get("records") or [], key=lambda row: _number(row.get("rating")), reverse=True)
    _append_evidence(evidence, seen, records, "综合上限", MINT_DARK, 5)
    for index, row in enumerate(evidence): row["rank"] = index + 1

    tags = []
    if strongest: tags.append(f"优势 · {strongest['label']} {_fixed(strongest['score'])}")
    if weakest: tags.append(f"补强 · {weakest['label']} {_fixed(weakest['score'])}")
    if best_rhythm: tags.append(f"节奏强项 · {_rhythm_label(best_rhythm.get('pattern'))}")
    if weak_rhythm: tags.append(f"节奏短板 · {_rhythm_label(weak_rhythm.get('pattern'))}")
    counts = analysis.get("counts") or {}
    meta = analysis.get("meta") or {}
    return {
        "playerId": str(meta.get("playerId") or "未提供编号"), "server": str(meta.get("server") or "未知服务器"),
        "generatedAt": f"{generated_at.year}年{generated_at.month}月{generated_at.day}日", "model": "Taiko Signal Rhythm v2 2026-08-05",
        "rating": rating, "stage": stage, "planets": planets, "center": center,
        "spread": strongest["score"] - weakest["score"] if strongest and weakest else 0,
        "galaxyHeadline": stage["headline"],
        "headline": f"{strongest['label']}最突出，{weakest['label']}是当前突破口" if strongest and weakest else "有效成绩已生成，能力证据仍待补充",
        "summary": f"七类能力最大差距为 {_fixed(strongest['score'] - weakest['score'])}。保持{strongest['label']}优势，下一轮优先处理{weakest['description']}。" if strongest and weakest else "当前数据不足以稳定比较七类能力，请继续积累鬼或里难度成绩。",
        "tags": tags, "actions": actions[:3], "evidence": evidence,
        "rareRhythms": rare_rhythms,
        "rhythmCatalogCharts": int(_number(rhythm.get("catalogCharts"))),
        "rareCatalogCoverageThreshold": _number(rhythm.get("rareCatalogCoverageThreshold"), .03),
        "metrics": [
            {"label": "有效谱面", "value": str(unique), "note": "去重后的最佳成绩"},
            {"label": "特征覆盖", "value": f"{matched / max(unique, 1) * 100:.1f}%", "note": f"{matched} 张有完整画像"},
            {"label": "v1 参考差", "value": f"{rating - public_rating:+.2f}" if math.isfinite(public_rating) else "--", "note": "仅用于标尺对照"},
            {"label": "未纳入成绩", "value": str(int(_number(counts.get("belowThreshold")) + _number(counts.get("missing")))), "note": f"{int(_number(counts.get('belowThreshold')))} 条低准确率 · {int(_number(counts.get('missing')))} 条未匹配"},
        ],
        "sourceNote": "AI 主结果 · v2 · 玩家成绩只用于本次报告",
    }


def _font_path():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resource", "NotoSansCJKsc-Regular.otf")
    if not os.path.isfile(path):
        raise RuntimeError("插件缺少 resource/NotoSansCJKsc-Regular.otf，无法稳定渲染中文")
    return path


@lru_cache(maxsize=64)
def _font(size, bold=False):
    return ImageFont.truetype(_font_path(), size=size)


def _text(draw, value, x, y, size, color=INK, bold=False, align="left"):
    font = _font(size, bold)
    anchor = {"left": "lt", "center": "mt", "right": "rt"}[align]
    draw.text((x, y), str(value), font=font, fill=color, anchor=anchor,
              # The bundled font is Regular. A 1 px stroke is useful for large
              # display headings, but on labels/table rows it makes Chinese
              # glyphs merge and look much heavier than the website.
              stroke_width=1 if bold and size >= 28 else 0, stroke_fill=color)


def _measure(draw, value, size, bold=False):
    return draw.textlength(str(value), font=_font(size, bold))


def _lines(draw, value, max_width, size, bold=False):
    result = []
    closing_punctuation = "，。；：！？、）」》】〕〉”’…"
    for paragraph in str(value or "").split("\n"):
        current = ""
        for char in paragraph:
            candidate = current + char
            if current and _measure(draw, candidate, size, bold) > max_width:
                # Chinese closing punctuation must not start a new line. Keep
                # it with the preceding glyph even if that line grows by one
                # punctuation width; this matches browser line breaking and
                # avoids visually dangling commas in action cards.
                if char in closing_punctuation:
                    result.append(candidate.rstrip())
                    current = ""
                else:
                    result.append(current.rstrip())
                    current = char.lstrip()
            else:
                current = candidate
        if current or not paragraph:
            result.append(current)
    return result


def _wrapped(draw, value, x, y, max_width, size, line_height, color=MUTED, bold=False, limit=3):
    lines = _lines(draw, value, max_width, size, bold)
    visible = lines[:limit]
    if len(lines) > limit and visible:
        last = visible[-1]
        while last and _measure(draw, last + "…", size, bold) > max_width:
            last = last[:-1]
        visible[-1] = last + "…"
    for index, line in enumerate(visible):
        _text(draw, line, x, y + index * line_height, size, color, bold)
    return len(visible) * line_height


def _truncate(draw, value, max_width, size, bold=False):
    value = str(value or "")
    if _measure(draw, value, size, bold) <= max_width:
        return value
    while value and _measure(draw, value + "…", size, bold) > max_width:
        value = value[:-1]
    return value + "…"


def _box(draw, x, y, width, height, fill, outline=None, radius=24, line_width=2):
    draw.rounded_rectangle((x, y, x + width, y + height), radius=radius, fill=fill, outline=outline, width=line_width)


def _section(draw, index, title, y):
    _text(draw, index, 78, y, 17, ACCENT_DARK, True)
    _text(draw, title, 78, y + 30, 34, INK, True)


def _draw_ring(draw, rating):
    bounds = (169, 225, 361, 417)
    draw.ellipse(bounds, outline="#36414d", width=18)
    start = -90
    end = start + 360 * min(rating / MAX_RATING, 1)
    draw.arc(bounds, start=start, end=end, fill=ACCENT, width=18)
    radius, cx, cy = 96, 265, 321
    for angle in (start, end):
        radians = math.radians(angle)
        px, py = cx + radius * math.cos(radians), cy + radius * math.sin(radians)
        draw.ellipse((px - 9, py - 9, px + 9, py + 9), fill=ACCENT)


def _planet_glow(image, x, y, radius, color):
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.ellipse((x - radius * 2, y - radius * 2, x + radius * 2, y + radius * 2), fill=color + "88")
    layer = layer.filter(ImageFilter.GaussianBlur(radius))
    image.alpha_composite(layer)


def _draw_header_footer(draw, data):
    _text(draw, "鼓迹", 70, 58, 33, INK, True)
    _text(draw, "TAIKO TRACE", 160, 70, 15, ACCENT, True)
    _text(draw, f"PLAYER {data['playerId']}", 1370, 56, 15, INK, True, "right")
    _text(draw, f"{data['generatedAt']} · {data['server']} · {data['model']}", 1370, 82, 13, MUTED, False, "right")
    draw.line((70, 120, 1370, 120), fill=LINE, width=2)
    _text(draw, data["sourceNote"], 70, 2655, 12, MUTED)
    _text(draw, "星系为能力数据的静态表达；不代表历史趋势、通关预测或官方竞技裁定。", 70, 2680, 12, MUTED)
    _text(draw, "报告含玩家 ID 与成绩摘要，请按个人数据妥善分享。", 1370, 2680, 12, ACCENT_DARK, True, "right")


def _draw_hero(draw, data):
    _box(draw, 70, 148, 390, 340, INK)
    _text(draw, "AI 综合 RATING", 108, 192, 18, MINT, True)
    _draw_ring(draw, data["rating"])
    _text(draw, _fixed(data["rating"]), 265, 290, 54, "#ffffff", True, "center")
    _text(draw, "/ 15.50", 265, 355, 16, "#8f9ca8", False, "center")
    _box(draw, 108, 426, 314, 36, "#26313d", radius=18)
    _text(draw, f"恒星阶段 · {data['stage']['label']}", 265, 434, 14, data["stage"]["color"], True, "center")
    _box(draw, 480, 148, 890, 340, SURFACE, LINE)
    _text(draw, "本次关键结论", 528, 190, 17, ACCENT_DARK, True)
    _wrapped(draw, data["headline"], 528, 228, 790, 41, 52, INK, True, 2)
    _wrapped(draw, data["summary"], 528, 340, 790, 20, 32, MUTED, False, 2)
    x, y = 528, 422
    for value in data["tags"][:4]:
        width = min(_measure(draw, value, 15, True) + 30, 360)
        if x + width > 1320:
            x, y = 528, y + 42
        _box(draw, x, y, width, 32, SURFACE_SOFT, radius=16)
        _text(draw, value, x + 15, y + 7, 15, INK_SOFT, True)
        x += width + 10


def _draw_galaxy(image, draw, data):
    _section(draw, "01 / GALAXY", "能力星系数据", 530)
    _box(draw, 70, 620, 1300, 615, "#050911", "#263345")
    _text(draw, data["galaxyHeadline"], 106, 655, 25, "#ffffff", True)
    _wrapped(draw, data["stage"]["detail"], 106, 693, 570, 15, 24, "#9caaba", False, 2)
    cx, cy = 382, 945
    orbit_layer = Image.new("RGBA", (620, 420), (0, 0, 0, 0))
    od = ImageDraw.Draw(orbit_layer)
    local_cx, local_cy = 310, 210
    for index, planet in enumerate(data["planets"]):
        rx, ry = 72 + index * 38, 30 + index * 15
        od.ellipse((local_cx - rx, local_cy - ry, local_cx + rx, local_cy + ry), outline=(151, 184, 226, 38 + index * 3), width=2)
    rotated = orbit_layer.rotate(7, resample=Image.Resampling.BICUBIC, expand=False)
    image.alpha_composite(rotated, (cx - local_cx, cy - local_cy))
    for index, planet in enumerate(data["planets"]):
        rx, ry = 72 + index * 38, 30 + index * 15
        angle = -.7 + index * .91
        x, y = cx + math.cos(angle) * rx, cy + math.sin(angle) * ry
        radius = 7 + planet["normalized"] * 8
        _planet_glow(image, x, y, radius, planet["color"])
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=planet["color"])
    _planet_glow(image, cx, cy, 38, data["stage"]["color"])
    draw.ellipse((cx - 39, cy - 39, cx + 39, cy + 39), fill=data["stage"]["color"])
    _text(draw, _fixed(data["rating"]), cx, cy - 15, 22, INK, True, "center")
    _box(draw, 106, 1142, 570, 58, "#101722", "#36475c", radius=14)
    _text(draw, f"阶段 {data['stage']['label']}", 128, 1158, 14, data["stage"]["color"], True)
    _text(draw, f"中位 {_fixed(data['center'])}  ·  最大差 {_fixed(data['spread'])}", 650, 1158, 14, "#c4ced9", True, "right")
    draw.line((735, 650, 735, 1200), fill="#263345", width=2)
    _text(draw, "七颗能力行星", 778, 654, 18, "#ffffff", True)
    _text(draw, "分数 / 证据 / 相对中位 / 公转周期", 1328, 658, 12, "#93a3b5", False, "right")
    for index, planet in enumerate(data["planets"]):
        y = 706 + index * 68
        if index:
            draw.line((778, y - 10, 1328, y - 10), fill="#1c2a3a", width=1)
        draw.ellipse((784, y + 6, 798, y + 20), fill=planet["color"])
        _text(draw, planet["name"], 812, y, 15, "#ffffff", True)
        _text(draw, planet["label"], 920, y + 1, 14, "#9caaba")
        _text(draw, f"#{planet['rank']}" if planet["rank"] else "--", 1062, y + 2, 12, "#75869a", True)
        _text(draw, _fixed(planet["score"]), 1160, y - 3, 23, planet["color"], True, "right")
        _text(draw, f"{planet['charts']} 张 · {planet['delta']:+.2f}", 1183, y + 2, 12, "#c4ced9")
        _text(draw, _format_period(planet["period"]), 1328, y + 2, 13, "#93a3b5", True, "right")
        _box(draw, 812, y + 32, 348, 7, "#1b2430", radius=4)
        _box(draw, 812, y + 32, max(5, min(348, planet["score"] / MAX_RATING * 348)), 7, planet["color"], radius=4)


def _draw_actions(draw, data):
    _section(draw, "02 / DIAGNOSIS", "关键弱项与下一步动作", 1270)
    gap, width = 18, (1300 - 36) / 3
    for index, item in enumerate(data["actions"]):
        x = 70 + index * (width + gap)
        _box(draw, x, 1358, width, 332, "#f8ddd6" if index == 0 else SURFACE, LINE, radius=20)
        color = ACCENT_DARK if index == 0 else MUTED
        _text(draw, f"{item['index']} / {item['category']}", x + 28, 1386, 14, color, True)
        _wrapped(draw, item["title"], x + 28, 1420, width - 56, 23, 30, INK, True, 2)
        _text(draw, f"{_fixed(item['score'])} · {item['evidence']}", x + 28, 1486, 14, MUTED, True)
        _wrapped(draw, item["signal"], x + 28, 1520, width - 56, 15, 23, MUTED, False, 3)
        draw.line((x + 28, 1592, x + width - 28, 1592), fill=LINE, width=2)
        _text(draw, "建议动作", x + 28, 1610, 12, ACCENT_DARK if index == 0 else MINT_DARK, True)
        _wrapped(draw, item["method"], x + 28, 1633, width - 56, 15, 22, INK_SOFT, False, 2)


def _draw_evidence(draw, data):
    _section(draw, "03 / EVIDENCE", "支撑弱项判断的关键谱面", 1725)
    _box(draw, 70, 1813, 1300, 352, SURFACE, LINE, radius=20)
    headers = (("#", 102), ("对应判断", 150), ("谱面", 340), ("难度", 950), ("AI 定数", 1040), ("准确率", 1162), ("Rating", 1322))
    for label, x in headers:
        _text(draw, label, x, 1836, 12, MUTED, True, "right" if label == "Rating" else "left")
    for index, row in enumerate(data["evidence"]):
        y = 1878 + index * 53
        if index:
            draw.line((96, y - 12, 1344, y - 12), fill=LINE, width=2)
        _text(draw, f"{row['rank']:02d}", 102, y + 2, 13, QUIET, True)
        _box(draw, 148, y - 3, 162, 28, SURFACE_SOFT, radius=14)
        _text(draw, _truncate(draw, row["focus"], 142, 12, True), 229, y + 3, 12, row["color"], True, "center")
        _text(draw, _truncate(draw, row["title"], 570, 16, True), 340, y, 16, INK, True)
        _text(draw, row["level"], 950, y + 2, 14, MUTED, True)
        _text(draw, _fixed(row["constant"], 1), 1040, y + 2, 14, INK_SOFT, True)
        _text(draw, f"{row['accuracy'] * 100:.2f}%", 1162, y + 2, 14, INK_SOFT, True)
        _text(draw, _fixed(row["rating"]), 1322, y - 1, 18, INK, True, "right")


def _draw_niche_watch(draw, data):
    _section(draw, "04 / NICHE WATCH", "冷门节奏配置观察", 2200)
    threshold = data["rareCatalogCoverageThreshold"] * 100
    _text(draw, f"全库覆盖低于 {threshold:.0f}%，不计入核心弱项排行", 1370, 2240, 14, MUTED, False, "right")
    rare = data["rareRhythms"]
    if not rare:
        _box(draw, 70, 2290, 1300, 178, "#eceae4", "#d2cec5", radius=20)
        _text(draw, "当前没有形成有效结论的冷门节奏配置。", 720, 2355, 17, MUTED, False, "center")
    else:
        total = data["rhythmCatalogCharts"] or "--"
        for index, item in enumerate(rare):
            x, width = 70 + index * 438, 420
            _box(draw, x, 2290, width, 178, "#eceae4", "#d2cec5", radius=20)
            _box(draw, x + 22, 2308, 84, 30, "#d8d5cd", radius=15)
            _text(draw, "冷门观察", x + 64, 2315, 12, "#667078", True, "center")
            _text(draw, item["label"], x + 22, 2352, 19, INK_SOFT, True)
            _text(draw, f"BPM {item['bpm']}", x + 22, 2386, 13, MUTED)
            _text(draw, _fixed(item["score"]), x + width - 22, 2345, 27, "#667078", True, "right")
            _text(draw, "处理 Rating", x + width - 22, 2383, 11, MUTED, False, "right")
            _text(draw, f"全库 {item['catalogCharts']}/{total} 张 · {item['catalogCoverage'] * 100:.2f}%", x + 22, 2420, 12, MUTED)
            _text(draw, f"个人证据 {item['charts']} 张", x + width - 22, 2420, 12, MUTED, True, "right")
    _text(draw, "冷门配置保留数据观察价值，但不建议取代常见节奏型成为主练目标。", 70, 2480, 12, QUIET)


def _draw_metrics(draw, data):
    gap, width = 12, (1300 - 36) / 4
    for index, item in enumerate(data["metrics"]):
        x = 70 + index * (width + gap)
        _box(draw, x, 2510, width, 88, SURFACE, LINE, radius=14)
        _text(draw, item["label"], x + 18, 2527, 11, QUIET, True)
        _text(draw, item["value"], x + 18, 2548, 22, INK_SOFT, True)
        _text(draw, _truncate(draw, item["note"], width - 130, 11), x + width - 16, 2553, 11, MUTED, False, "right")


def render_report_image(analysis: dict, out_path: str, generated_at: datetime | None = None) -> str:
    """Render a fixed-size PNG and return its absolute output path."""
    data = build_report_data(analysis, generated_at)
    image = Image.new("RGBA", (WIDTH, HEIGHT), PAPER)
    draw = ImageDraw.Draw(image)
    for x in range(0, WIDTH + 1, 40):
        draw.line((x, 0, x, HEIGHT), fill="#ece9e1", width=1)
    for y in range(0, HEIGHT + 1, 40):
        draw.line((0, y, WIDTH, y), fill="#ece9e1", width=1)
    _draw_header_footer(draw, data)
    _draw_hero(draw, data)
    _draw_galaxy(image, draw, data)
    _draw_actions(draw, data)
    _draw_evidence(draw, data)
    _draw_niche_watch(draw, data)
    _draw_metrics(draw, data)
    output = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(output), exist_ok=True)
    image.convert("RGB").save(output, format="PNG", compress_level=6)
    return output
