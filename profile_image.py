# -*- coding: utf-8 -*-
"""Fixed-size player profile image for ``/rtlink profile``."""

from __future__ import annotations

import math
import os
from datetime import datetime

from PIL import Image, ImageDraw, ImageFilter

if __package__:
    from .report_image import (
        ACCENT, ACCENT_DARK, FAMILY_META, FAMILY_ORDER, FAMILY_PRACTICE,
        INK, INK_SOFT, LINE, MAX_RATING, MINT, MINT_DARK, MUTED, PAPER,
        QUIET, SURFACE, SURFACE_SOFT, _box, _fixed, _stage, _text,
        _truncate, _wrapped,
    )
else:
    from report_image import (
        ACCENT, ACCENT_DARK, FAMILY_META, FAMILY_ORDER, FAMILY_PRACTICE,
        INK, INK_SOFT, LINE, MAX_RATING, MINT, MINT_DARK, MUTED, PAPER,
        QUIET, SURFACE, SURFACE_SOFT, _box, _fixed, _stage, _text,
        _truncate, _wrapped,
    )

WIDTH, HEIGHT = 1440, 1800
DARK, DARK_LINE = "#07101b", "#263547"


def build_profile_data(analysis: dict, generated_at: datetime | None = None) -> dict:
    generated_at = generated_at or datetime.now()
    summary = analysis.get("summary") or {}
    meta = analysis.get("meta") or {}
    records = analysis.get("records") or []
    raw_families = (analysis.get("featureAbility") or {}).get("families") or []
    family_map = {item.get("key"): item for item in raw_families if item.get("key") in FAMILY_META}
    families = []
    for key in FAMILY_ORDER:
        raw = family_map.get(key) or {}
        families.append({"key": key, "score": float(raw.get("score") or 0), "charts": int(raw.get("charts") or 0)})
    ranked = sorted([item for item in families if item["charts"] >= 3], key=lambda item: item["score"], reverse=True)
    strongest = ranked[0] if ranked else {"key": "chartPower", "score": 0.0, "charts": 0}
    weakest = ranked[-1] if ranked else strongest
    top_records = sorted(records, key=lambda row: float(row.get("rating") or 0), reverse=True)[:3]
    return {
        "playerId": str(meta.get("playerId") or "未提供编号"),
        "server": str(meta.get("server") or "未知服务器").upper(),
        "generatedAt": generated_at.strftime("%Y.%m.%d"),
        "rating": float(summary.get("rating") or 0),
        "stage": _stage(float(summary.get("rating") or 0)),
        "charts": len(records),
        "fullCombo": sum(1 for row in records if (row.get("fullComboCount") or 0) > 0),
        "dondaful": sum(1 for row in records if (row.get("dondafulComboCount") or 0) > 0),
        "families": families,
        "ranked": ranked,
        "strongest": strongest,
        "weakest": weakest,
        "topRecords": top_records,
    }


def _glow(image, x, y, radius, color):
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    brush = ImageDraw.Draw(layer)
    brush.ellipse((x - radius * 2, y - radius * 2, x + radius * 2, y + radius * 2), fill=color + "68")
    image.alpha_composite(layer.filter(ImageFilter.GaussianBlur(radius)))


def _rating_ring(draw, x, y, radius, rating):
    bounds = (x - radius, y - radius, x + radius, y + radius)
    draw.ellipse(bounds, outline="#314052", width=20)
    end = -90 + 360 * min(max(rating / MAX_RATING, 0), 1)
    draw.arc(bounds, -90, end, fill=ACCENT, width=20)
    angle = math.radians(end)
    dot_x, dot_y = x + math.cos(angle) * radius, y + math.sin(angle) * radius
    draw.ellipse((dot_x - 8, dot_y - 8, dot_x + 8, dot_y + 8), fill="#ffffff")


def _radar(draw, cx, cy, radius, family_map):
    angles = [-math.pi / 2 + i * math.tau / len(FAMILY_ORDER) for i in range(len(FAMILY_ORDER))]
    for step in range(1, 6):
        grid_radius = radius * step / 5
        points = [(cx + math.cos(angle) * grid_radius, cy + math.sin(angle) * grid_radius) for angle in angles]
        draw.polygon(points, outline="#2a394b")
    for angle in angles:
        draw.line((cx, cy, cx + math.cos(angle) * radius, cy + math.sin(angle) * radius), fill="#223144", width=2)
    points = []
    for key, angle in zip(FAMILY_ORDER, angles):
        score = family_map[key]["score"]
        point_radius = radius * min(max(score / MAX_RATING, 0), 1)
        points.append((cx + math.cos(angle) * point_radius, cy + math.sin(angle) * point_radius))
    draw.polygon(points, fill="#ee654744", outline=ACCENT)
    draw.line(points + [points[0]], fill=ACCENT, width=5, joint="curve")
    for key, angle, (x, y) in zip(FAMILY_ORDER, angles, points):
        color = FAMILY_META[key]["color"]
        draw.ellipse((x - 8, y - 8, x + 8, y + 8), fill=color, outline="#ffffff", width=2)
        label_radius = radius + 55
        lx, ly = cx + math.cos(angle) * label_radius, cy + math.sin(angle) * label_radius
        align = "center" if abs(math.cos(angle)) < .3 else ("left" if math.cos(angle) > 0 else "right")
        _text(draw, FAMILY_META[key]["label"], lx, ly - 12, 14, "#dce4ec", True, align)
        _text(draw, _fixed(family_map[key]["score"]), lx, ly + 10, 13, color, True, align)


def _metric(draw, x, y, width, label, value, note, color):
    _box(draw, x, y, width, 82, "#101b28", "#2a394b", radius=16)
    draw.ellipse((x + 20, y + 19, x + 30, y + 29), fill=color)
    _text(draw, label, x + 42, y + 14, 12, "#93a3b5", True)
    _text(draw, value, x + 20, y + 38, 24, "#ffffff", True)
    _text(draw, note, x + width - 18, y + 45, 11, "#8795a5", False, "right")


def _ranked_row(draw, x, y, width, rank, item):
    meta = FAMILY_META[item["key"]]
    _text(draw, f"{rank:02d}", x, y - 3, 12, QUIET, True)
    _text(draw, meta["label"], x + 42, y - 7, 16, INK_SOFT, True)
    bar_x, bar_width = x + 188, width - 280
    _box(draw, bar_x, y, bar_width, 11, SURFACE_SOFT, radius=6)
    _box(draw, bar_x, y, max(8, bar_width * item["score"] / MAX_RATING), 11, meta["color"], radius=6)
    _text(draw, _fixed(item["score"]), x + width, y - 11, 20, meta["color"], True, "right")


def _insight_card(draw, x, y, width, title, value, body, fill, border, accent):
    _box(draw, x, y, width, 213, fill, border, radius=22)
    _text(draw, title, x + 28, y + 25, 12, accent, True)
    _text(draw, value, x + 28, y + 58, 30, INK, True)
    _wrapped(draw, body, x + 28, y + 108, width - 56, 16, 27, INK_SOFT, False, 3)


def render_profile_image(analysis: dict, out_path: str, generated_at: datetime | None = None) -> str:
    data = build_profile_data(analysis, generated_at)
    strongest, weakest = data["strongest"], data["weakest"]
    strong_meta, weak_meta = FAMILY_META[strongest["key"]], FAMILY_META[weakest["key"]]
    family_map = {item["key"]: item for item in data["families"]}
    image = Image.new("RGBA", (WIDTH, HEIGHT), PAPER)
    draw = ImageDraw.Draw(image)
    for x in range(0, WIDTH + 1, 40): draw.line((x, 0, x, HEIGHT), fill="#ece9e1", width=1)
    for y in range(0, HEIGHT + 1, 40): draw.line((0, y, WIDTH, y), fill="#ece9e1", width=1)

    _text(draw, "鼓迹", 70, 54, 34, INK, True)
    _text(draw, "TAIKO PROFILE", 160, 67, 15, ACCENT, True)
    _text(draw, f"PLAYER {data['playerId']}", 1370, 51, 15, INK, True, "right")
    _text(draw, f"{data['generatedAt']} · {data['server']} SERVER", 1370, 79, 12, MUTED, False, "right")
    draw.line((70, 116, 1370, 116), fill=LINE, width=2)

    _box(draw, 70, 148, 1300, 650, DARK, DARK_LINE, radius=28)
    _text(draw, "PLAYER ARCHETYPE / 玩家画像", 108, 184, 13, MINT, True)
    _text(draw, f"{strong_meta['label']}型", 108, 218, 40, "#ffffff", True)
    _text(draw, f"{data['stage']['label']} · {data['server']} SERVER", 108, 274, 14, data["stage"]["color"], True)
    _wrapped(draw, f"以{strong_meta['label']}为核心优势，当前最值得投入的突破口是{weak_meta['label']}。", 108, 318, 390, 17, 29, "#b8c4d0", False, 3)
    _glow(image, 300, 525, 100, data["stage"]["color"])
    draw = ImageDraw.Draw(image)
    _rating_ring(draw, 300, 525, 116, data["rating"])
    _text(draw, _fixed(data["rating"]), 300, 480, 58, "#ffffff", True, "center")
    _text(draw, "AI RATING", 300, 552, 14, MINT, True, "center")
    _text(draw, "/ 15.50", 300, 579, 13, "#7f8d9d", False, "center")
    draw.line((550, 188, 550, 662), fill="#263547", width=2)
    _text(draw, "SEVEN-DIMENSION PROFILE", 594, 184, 13, "#93a3b5", True)
    _text(draw, "七维能力轮廓", 594, 214, 24, "#ffffff", True)
    _radar(draw, 970, 455, 188, family_map)
    charts = max(data["charts"], 1)
    _metric(draw, 108, 698, 286, "有效谱面", str(data["charts"]), "仅鬼 / 里", ACCENT)
    _metric(draw, 410, 698, 286, "全连", str(data["fullCombo"]), "有 FC 记录", MINT_DARK)
    _metric(draw, 712, 698, 286, "全良", str(data["dondaful"]), "咚大福", "#c89b31")
    _metric(draw, 1014, 698, 286, "全连率", f"{data['fullCombo'] / charts * 100:.1f}%", "FC / 有效", "#8565b3")

    _text(draw, "01 / PROFILE READOUT", 78, 848, 16, ACCENT_DARK, True)
    _text(draw, "从轮廓到下一步", 78, 878, 34, INK, True)
    _box(draw, 70, 948, 802, 440, SURFACE, LINE, radius=22)
    _text(draw, "七维精确排名", 102, 978, 18, INK, True)
    _text(draw, "排名 / 维度 / 同标尺分值", 838, 981, 12, MUTED, False, "right")
    for index, item in enumerate(data["ranked"][:7]):
        y = 1032 + index * 46
        if index: draw.line((102, y - 16, 840, y - 16), fill="#e5e1d8", width=1)
        _ranked_row(draw, 102, y, 730, index + 1, item)
    _insight_card(draw, 900, 948, 470, "SIGNATURE / 最强标签", strong_meta["label"], f"{strongest['score']:.2f} 位列第一。{strong_meta['description']}是当前最稳定的能力名片。", "#dcefe9", "#b7d8cf", MINT_DARK)
    practice = FAMILY_PRACTICE.get(weakest["key"], "选择低压谱面稳定练习，再逐步回到当前攻关区间。")
    _insight_card(draw, 900, 1175, 470, "NEXT STEP / 优先补强", weak_meta["label"], f"{weakest['score']:.2f} 位列末位。{practice}", "#f8ddd6", "#e9bbb0", ACCENT_DARK)

    _text(draw, "02 / PERSONAL BEST", 78, 1433, 16, ACCENT_DARK, True)
    _text(draw, "代表当前上限的谱面", 78, 1463, 34, INK, True)
    _box(draw, 70, 1533, 1300, 164, SURFACE, LINE, radius=22)
    for index, row in enumerate(data["topRecords"]):
        x, card_width = 104 + index * 420, 400
        if index: draw.line((x - 20, 1563, x - 20, 1667), fill=LINE, width=2)
        _text(draw, f"TOP {index + 1:02d}", x, 1560, 12, QUIET, True)
        _text(draw, _truncate(draw, row.get("title") or f"谱面 {row.get('id')}", card_width - 20, 18, True), x, 1592, 18, INK, True)
        level = "里" if row.get("level") == 5 else "鬼"
        _box(draw, x, 1634, 44, 26, SURFACE_SOFT, radius=13)
        _text(draw, level, x + 22, 1640, 12, MUTED, True, "center")
        _text(draw, _fixed(row.get("rating")), x + card_width - 20, 1626, 26, ACCENT_DARK, True, "right")
    draw.line((70, 1736, 1370, 1736), fill=LINE, width=2)
    _text(draw, "AI 主结果 · Taiko Signal Rhythm v2 · 玩家成绩只用于本次画像", 70, 1754, 12, MUTED)
    _text(draw, f"{data['generatedAt']} · PROFILE", 1370, 1754, 12, ACCENT_DARK, True, "right")
    output = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(output), exist_ok=True)
    image.convert("RGB").save(output, "PNG", compress_level=6)
    return output
