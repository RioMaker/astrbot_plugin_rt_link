# -*- coding: utf-8 -*-
"""Fixed-size rhythm weakness image for ``/rtlink weakness``."""

from __future__ import annotations

import os
from datetime import datetime

from PIL import Image, ImageDraw

if __package__:
    from .report_image import (
        ACCENT, ACCENT_DARK, INK, INK_SOFT, LINE, MINT, MINT_DARK,
        MUTED, PAPER, QUIET, SURFACE, SURFACE_SOFT, _box, _bpm_label,
        _fixed, _rhythm_label, _rhythm_practice, _text, _truncate, _wrapped,
    )
else:
    from report_image import (
        ACCENT, ACCENT_DARK, INK, INK_SOFT, LINE, MINT, MINT_DARK,
        MUTED, PAPER, QUIET, SURFACE, SURFACE_SOFT, _box, _bpm_label,
        _fixed, _rhythm_label, _rhythm_practice, _text, _truncate, _wrapped,
    )

WIDTH, HEIGHT = 1440, 2200
DARK, DARK_LINE = "#07101b", "#263547"


def build_weakness_data(analysis: dict, generated_at: datetime | None = None) -> dict:
    generated_at = generated_at or datetime.now()
    meta = analysis.get("meta") or {}
    rhythm = analysis.get("rhythmAbility") or {}
    common = sorted(rhythm.get("weakest") or [], key=lambda item: float(item.get("score") or 0))
    rare = sorted(rhythm.get("rareWeakest") or [], key=lambda item: float(item.get("score") or 0))
    focus = common[0] if common else (rare[0] if rare else None)
    return {
        "playerId": str(meta.get("playerId") or "未提供编号"),
        "server": str(meta.get("server") or "未知服务器").upper(),
        "generatedAt": generated_at.strftime("%Y.%m.%d"),
        "common": common[:4],
        "rare": rare[:3],
        "focus": focus,
        "focusIsRare": bool(focus and not common),
        "catalogCharts": int(rhythm.get("catalogCharts") or 0),
        "threshold": float(rhythm.get("rareCatalogCoverageThreshold") or .03),
    }


def _priority_row(draw, x, y, width, index, item, score_min, score_max):
    active = index == 0
    _box(draw, x, y, width, 94, "#f8ddd6" if active else SURFACE, "#e9b2a5" if active else LINE, radius=18)
    _box(draw, x + 20, y + 21, 52, 52, ACCENT_DARK if active else SURFACE_SOFT, radius=16)
    _text(draw, f"{index + 1:02d}", x + 46, y + 34, 16, "#ffffff" if active else QUIET, True, "center")
    _text(draw, _rhythm_label(item.get("pattern")), x + 94, y + 17, 19, INK, True)
    _text(draw, f"BPM {_bpm_label(item.get('bpmBand'))} · 平均 {float(item.get('averageBpm') or 0):.0f}", x + 94, y + 50, 13, MUTED)
    bar_x, bar_width = x + 420, 410
    _box(draw, bar_x, y + 35, bar_width, 13, SURFACE_SOFT, radius=7)
    span = max(score_max - score_min, .01)
    ratio = (float(item.get("score") or 0) - score_min + .18) / (span + .36)
    _box(draw, bar_x, y + 35, max(12, bar_width * ratio), 13, ACCENT if active else "#87a99f", radius=7)
    _text(draw, "更需优先", bar_x, y + 58, 11, ACCENT_DARK if active else QUIET)
    _text(draw, "相对稳定", bar_x + bar_width, y + 58, 11, QUIET, False, "right")
    _text(draw, _fixed(item.get("score")), x + 930, y + 18, 27, ACCENT_DARK if active else INK, True, "right")
    _text(draw, "处理 Rating", x + 930, y + 54, 11, MUTED, False, "right")
    _text(draw, f"{int(item.get('charts') or 0)} 张", x + 1040, y + 22, 17, INK_SOFT, True, "center")
    _text(draw, "证据谱面", x + 1040, y + 53, 11, MUTED, False, "center")
    coverage = float(item.get("catalogCoverage") or 0) * 100
    _box(draw, x + width - 164, y + 26, 136, 40, SURFACE_SOFT, radius=20)
    _text(draw, f"全库 {coverage:.1f}%", x + width - 96, y + 36, 13, MUTED, True, "center")


def _rare_card(draw, x, y, width, item):
    _box(draw, x, y, width, 166, "#eceae4", "#d2cec5", radius=20)
    _box(draw, x + 22, y + 20, 84, 30, "#d8d5cd", radius=15)
    _text(draw, "冷门观察", x + 64, y + 27, 12, "#667078", True, "center")
    _text(draw, _rhythm_label(item.get("pattern")), x + 22, y + 65, 19, INK_SOFT, True)
    _text(draw, f"BPM {_bpm_label(item.get('bpmBand'))}", x + 22, y + 99, 13, MUTED)
    _text(draw, _fixed(item.get("score")), x + width - 22, y + 58, 27, "#667078", True, "right")
    _text(draw, "处理 Rating", x + width - 22, y + 96, 11, MUTED, False, "right")
    catalog_charts = item.get("catalogCharts")
    coverage = float(item.get("catalogCoverage") or 0) * 100
    _text(draw, f"全库 {catalog_charts if catalog_charts is not None else '--'} 张 / {coverage:.2f}%  ·  个人证据 {int(item.get('charts') or 0)} 张", x + 22, y + 132, 12, MUTED)


def _step_card(draw, x, y, width, index, title, body, accent):
    _box(draw, x, y, width, 112, SURFACE, LINE, radius=18)
    _box(draw, x + 20, y + 20, 50, 50, accent, radius=16)
    _text(draw, str(index), x + 45, y + 31, 16, "#ffffff", True, "center")
    _text(draw, title, x + 88, y + 18, 17, INK, True)
    _wrapped(draw, body, x + 88, y + 48, width - 116, 14, 23, INK_SOFT, False, 2)


def _evidence_row(draw, x, y, width, index, row):
    if index: draw.line((x, y - 14, x + width, y - 14), fill=LINE, width=1)
    _text(draw, f"{index + 1:02d}", x, y, 12, QUIET, True)
    _text(draw, _truncate(draw, row.get("title") or f"谱面 {row.get('id')}", width - 170, 16, True), x + 42, y - 4, 16, INK, True)
    level = "里" if row.get("level") == 5 else "鬼"
    _box(draw, x + width - 150, y - 7, 42, 27, SURFACE_SOFT, radius=14)
    _text(draw, level, x + width - 129, y, 12, MUTED, True, "center")
    _text(draw, _fixed(row.get("rating")), x + width, y - 8, 21, ACCENT_DARK, True, "right")
    accuracy = float(row.get("accuracy") or 0) * 100
    _text(draw, f"精度 {accuracy:.2f}%", x + 42, y + 25, 12, MUTED)


def render_weakness_image(analysis: dict, out_path: str, generated_at: datetime | None = None) -> str:
    data = build_weakness_data(analysis, generated_at)
    focus = data["focus"]
    if not focus:
        raise ValueError("节奏画像样本不足（至少 3 张同节奏型谱面才会形成结论）")
    image = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
    draw = ImageDraw.Draw(image)
    for x in range(0, WIDTH + 1, 40): draw.line((x, 0, x, HEIGHT), fill="#ece9e1", width=1)
    for y in range(0, HEIGHT + 1, 40): draw.line((0, y, WIDTH, y), fill="#ece9e1", width=1)

    _text(draw, "鼓迹", 70, 54, 34, INK, True)
    _text(draw, "RHYTHM DIAGNOSIS", 160, 67, 15, ACCENT, True)
    _text(draw, f"PLAYER {data['playerId']}", 1370, 51, 15, INK, True, "right")
    _text(draw, f"{data['generatedAt']} · {data['server']} SERVER", 1370, 79, 12, MUTED, False, "right")
    draw.line((70, 116, 1370, 116), fill=LINE, width=2)

    _box(draw, 70, 148, 1300, 450, DARK, DARK_LINE, radius=28)
    hero_label = "NICHE WATCH / 冷门配置观察" if data["focusIsRare"] else "PRIMARY WEAKNESS / 首要常见弱项"
    _text(draw, hero_label, 108, 186, 13, MINT, True)
    _text(draw, _rhythm_label(focus.get("pattern")), 108, 226, 43, "#ffffff", True)
    _text(draw, f"BPM {_bpm_label(focus.get('bpmBand'))}", 108, 288, 22, "#b8c4d0", True)
    _box(draw, 108, 344, 460, 164, "#101b28", "#2a394b", radius=20)
    _text(draw, "建议动作", 136, 370, 12, ACCENT, True)
    advice = "此配置覆盖较少，保留观察即可，不建议替代常见节奏型成为主练目标。" if data["focusIsRare"] else _rhythm_practice(focus)
    _wrapped(draw, advice, 136, 406, 404, 17, 29, "#eef2f6", False, 3)
    draw.line((620, 190, 620, 544), fill="#263547", width=2)
    _text(draw, "处理 RATING", 680, 198, 13, "#93a3b5", True)
    _text(draw, _fixed(focus.get("score")), 680, 229, 72, "#ffffff", True)
    note = "当前常见配置中数值最低，应最先练习" if not data["focusIsRare"] else "仅有冷门配置形成结论，暂不列入核心优先级"
    _text(draw, note, 680, 322, 14, "#aebac6")
    metrics = [
        ("平均 BPM", f"{float(focus.get('averageBpm') or 0):.0f}", "#8565b3"),
        ("证据谱面", str(int(focus.get("charts") or 0)), MINT_DARK),
        ("复合占比", f"{float(focus.get('compoundRatio') or 0) * 100:.0f}%", ACCENT),
    ]
    for index, (label, value, color) in enumerate(metrics):
        x = 680 + index * 205
        _box(draw, x, 386, 185, 122, "#101b28", "#2a394b", radius=18)
        draw.ellipse((x + 20, 407, x + 31, 418), fill=color)
        _text(draw, label, x + 43, 400, 12, "#93a3b5", True)
        _text(draw, value, x + 20, 438, 31, "#ffffff", True)

    _text(draw, "01 / PRIORITY", 78, 648, 16, ACCENT_DARK, True)
    _text(draw, "常见节奏弱项优先级", 78, 678, 34, INK, True)
    _text(draw, "处理 Rating 越低，越应优先补强", 1370, 690, 14, MUTED, False, "right")
    if data["common"]:
        score_min = min(float(item.get("score") or 0) for item in data["common"])
        score_max = max(float(item.get("score") or 0) for item in data["common"])
        for index, item in enumerate(data["common"]):
            _priority_row(draw, 70, 748 + index * 108, 1300, index, item, score_min, score_max)
    else:
        _box(draw, 70, 748, 1300, 94, SURFACE, LINE, radius=18)
        _text(draw, "暂无达到常见度阈值的节奏弱项，继续积累成绩后再判断。", 720, 779, 17, MUTED, False, "center")

    threshold_pct = data["threshold"] * 100
    _text(draw, "02 / NICHE WATCH", 78, 1210, 16, "#667078", True)
    _text(draw, "冷门配置观察", 78, 1240, 32, INK, True)
    _text(draw, f"全库覆盖低于 {threshold_pct:.0f}%，不计入核心弱项优先级", 1370, 1250, 14, MUTED, False, "right")
    for index, item in enumerate(data["rare"]):
        _rare_card(draw, 70 + index * 438, 1300, 420, item)
    if not data["rare"]:
        _box(draw, 70, 1300, 1300, 166, "#eceae4", "#d2cec5", radius=20)
        _text(draw, "当前没有形成有效结论的冷门配置。", 720, 1365, 17, MUTED, False, "center")

    _text(draw, "03 / PRACTICE", 78, 1520, 16, ACCENT_DARK, True)
    _text(draw, "针对首要常见弱项的练习路径", 78, 1550, 34, INK, True)
    _box(draw, 70, 1620, 650, 480, "#f7f4ed", LINE, radius=22)
    _text(draw, "三步练习", 102, 1650, 18, INK, True)
    _step_card(draw, 102, 1694, 586, 1, "降速拆分", "从目标速度下调一个 BPM 档，只练起手与收手。", ACCENT_DARK)
    _step_card(draw, 102, 1818, 586, 2, "固定动作", "口读配色并固定左右手顺序，避免临场重新分配动作。", "#8565b3")
    _step_card(draw, 102, 1942, 586, 3, "回到实战", "连续稳定后回到目标区间，优先保证动作小且落点均匀。", MINT_DARK)
    _box(draw, 742, 1620, 628, 480, SURFACE, LINE, radius=22)
    _text(draw, "参考谱面", 774, 1650, 18, INK, True)
    _text(draw, "用于验证该节奏型的当前处理上限", 1338, 1654, 12, MUTED, False, "right")
    for index, row in enumerate((focus.get("best") or [])[:3]):
        _evidence_row(draw, 774, 1708 + index * 96, 564, index, row)
    _box(draw, 774, 2010, 564, 26, "#f8ddd6", radius=13)
    _text(draw, "参考谱面用于定位问题，不代表必须从最高难度开始练习。", 1056, 2016, 11, ACCENT_DARK, True, "center")
    draw.line((70, 2140, 1370, 2140), fill=LINE, width=2)
    total_note = str(data["catalogCharts"]) if data["catalogCharts"] else "内置"
    _text(draw, f"AI 主结果 · 常见度按 {total_note} 张谱面的配置覆盖率计算", 70, 2160, 12, MUTED)
    _text(draw, f"{data['generatedAt']} · WEAKNESS", 1370, 2160, 12, ACCENT_DARK, True, "right")
    output = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(output), exist_ok=True)
    image.save(output, "PNG", compress_level=6)
    return output
