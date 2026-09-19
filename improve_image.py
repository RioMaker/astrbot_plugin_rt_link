# -*- coding: utf-8 -*-
"""Fixed-size score-rank improvement image for ``/rtlink improve``.

按分区展示「离目标评价最近」的谱面，并给出判定路线（转几个「可」「不可」、是否必须全良）
与连打路线（还差几打、黄条总打数、秒速、是否打得出来）。
版式与 report/profile/weakness 同源：固定 1440 像素宽、随插件携带的中文字体。
"""

from __future__ import annotations

import os
from datetime import datetime

from PIL import Image, ImageDraw

if __package__:
    from . import improve_text as improve_text_mod
    from .report_image import (
        ACCENT, ACCENT_DARK, INK, INK_SOFT, LINE, MINT, MINT_DARK,
        MUTED, PAPER, QUIET, SURFACE, SURFACE_SOFT, _box, _text, _truncate,
    )
    from .score_rank import SCORE_RANK_NAMES, SCORE_RANK_RATIOS
else:
    import improve_text as improve_text_mod
    from report_image import (
        ACCENT, ACCENT_DARK, INK, INK_SOFT, LINE, MINT, MINT_DARK,
        MUTED, PAPER, QUIET, SURFACE, SURFACE_SOFT, _box, _text, _truncate,
    )
    from score_rank import SCORE_RANK_NAMES, SCORE_RANK_RATIOS

WIDTH, HEIGHT = 1440, 2020
DARK, DARK_LINE = "#07101b", "#263547"
GENRE_CARDS = 6
ITEMS_PER_CARD = 3
CARD_W, CARD_H = 640, 410
CARD_GAP_X, CARD_GAP_Y = 20, 28
GRID_LEFT, GRID_TOP = 70, 620
HERO_TOP, HERO_H = 148, 420
FOOTER_LINE_Y = 1926


def build_improve_data(result: dict, generated_at: datetime | None = None) -> dict:
    generated_at = generated_at or datetime.now()
    meta = result.get("meta") or {}
    target = int(result.get("targetRank") or 4)
    genres = list(result.get("genres") or [])[:GENRE_CARDS]
    return {
        "playerId": str(meta.get("playerId") or "未提供编号"),
        "server": str(meta.get("server") or "未知服务器").upper(),
        "generatedAt": generated_at.strftime("%Y.%m.%d"),
        "target": target,
        "targetName": SCORE_RANK_NAMES.get(target, f"评价{target}"),
        "targetRatio": SCORE_RANK_RATIOS.get(target),
        "note": result.get("note") or "",
        "scanned": int(result.get("scanned") or 0),
        "already": int(result.get("alreadyAtTarget") or 0),
        "candidateCount": int(result.get("candidateCount") or 0),
        "exactCount": int(result.get("exactCount") or 0),
        "noRollCount": int(result.get("noRollCount") or 0),
        "allGoodCount": int(result.get("allGoodRequiredCount") or 0),
        "unreachableCount": int(result.get("unreachableCount") or 0),
        "genreCount": len(result.get("genres") or []),
        "genres": [
            {
                "genre": row.get("genre") or "未知",
                "count": int(row.get("count") or 0),
                "gapMedian": int(row.get("gapMedian") or 0),
                "closest": list(row.get("closest") or [])[:ITEMS_PER_CARD],
            }
            for row in genres
        ],
    }


def _level_badge(draw, x, y, level):
    _box(draw, x, y, 42, 26, SURFACE_SOFT, radius=13)
    _text(draw, "里" if level == 5 else "鬼", x + 21, y + 6, 12, MUTED, True, "center")


def _item_row(draw, x, y, width, item):
    title = item.get("titleJa") or item.get("title") or f"谱面 {item.get('id')}"
    _text(draw, _truncate(draw, title, width - 96, 16, True), x, y, 16, INK, True)
    _level_badge(draw, x + width - 46, y - 4, item.get("level"))
    if not item.get("exact"):
        _box(draw, x + width - 96, y - 3, 44, 24, "#eceae4", radius=12)
        _text(draw, "估算", x + width - 74, y + 3, 11, QUIET, True, "center")

    _text(draw, f"{int(item.get('currentScore') or 0)}", x, y + 26, 15, INK_SOFT)
    _text(draw, f"→ {int(item.get('targetScore') or 0)}", x + 118, y + 26, 15, ACCENT_DARK, True)
    _text(draw, f"差 {int(item.get('gap') or 0)}", x + width, y + 26, 15, ACCENT_DARK, True, "right")

    # 判定路线 + 连打路线；没有黄条 / 打不满时用强调色标出来。
    lines = improve_text_mod.gap_route_lines(item, compact=True)
    warning = bool(item.get("mustAllGood") or item.get("unreachable")
                   or (item.get("rollKnown") and not item.get("hasRolls")))
    for index, line in enumerate(lines[:2]):
        _text(
            draw,
            _truncate(draw, line, width, 12),
            x, y + 50 + index * 19, 12,
            ACCENT_DARK if warning else MUTED,
        )


def _genre_card(draw, x, y, row, index):
    _box(draw, x, y, CARD_W, CARD_H, SURFACE, LINE, radius=22)
    _box(draw, x + 22, y + 22, 40, 40, ACCENT_DARK if index == 0 else SURFACE_SOFT, radius=14)
    _text(draw, f"{index + 1:02d}", x + 42, y + 32, 15, "#ffffff" if index == 0 else QUIET, True, "center")
    _text(draw, _truncate(draw, row["genre"], CARD_W - 140, 20, True), x + 76, y + 24, 20, INK, True)
    _text(draw, f"{row['count']} 张待提升 · 中位差距 {row['gapMedian']}", x + 76, y + 54, 13, MUTED)
    draw.line((x + 22, y + 84, x + CARD_W - 22, y + 84), fill=LINE, width=1)
    for item_index, item in enumerate(row["closest"]):
        item_y = y + 100 + item_index * 100
        if item_index:
            draw.line((x + 22, item_y - 14, x + CARD_W - 22, item_y - 14), fill="#efece4", width=1)
        _item_row(draw, x + 22, item_y, CARD_W - 44, item)


def _empty_card(draw, x, y, text):
    _box(draw, x, y, CARD_W, CARD_H, "#eceae4", "#d8d4cb", radius=22)
    _text(draw, text, x + CARD_W // 2, y + CARD_H // 2 - 10, 16, QUIET, False, "center")


def render_improve_image(result: dict, out_path: str, generated_at: datetime | None = None) -> str:
    data = build_improve_data(result, generated_at)
    image = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
    draw = ImageDraw.Draw(image)
    for x in range(0, WIDTH + 1, 40):
        draw.line((x, 0, x, HEIGHT), fill="#ece9e1", width=1)
    for y in range(0, HEIGHT + 1, 40):
        draw.line((0, y, WIDTH, y), fill="#ece9e1", width=1)

    _text(draw, "鼓迹", 70, 54, 34, INK, True)
    _text(draw, "SCORE RANK PLAN", 160, 67, 15, ACCENT, True)
    _text(draw, f"PLAYER {data['playerId']}", 1370, 51, 15, INK, True, "right")
    _text(draw, f"{data['generatedAt']} · {data['server']} SERVER", 1370, 79, 12, MUTED, False, "right")
    draw.line((70, 116, 1370, 116), fill=LINE, width=2)

    # --- 目标评价主卡 -----------------------------------------------------
    _box(draw, 70, HERO_TOP, 1300, HERO_H, DARK, DARK_LINE, radius=28)
    _text(draw, "TARGET / 目标评价", 108, 186, 13, MINT, True)
    _text(draw, f"{data['target']}·{data['targetName']}", 108, 222, 44, "#ffffff", True)
    ratio = data["targetRatio"]
    if ratio is None:
        rule = "门槛 = 该谱極スコア"
    elif ratio >= 1.0:
        rule = "门槛 = 该谱極スコア（约 100 万出头）"
    else:
        rule = f"门槛 = 该谱極スコア × {ratio*100:.0f}%"
    _text(draw, rule, 108, 292, 20, "#b8c4d0", True)
    if data["note"]:
        _text(draw, _truncate(draw, data["note"], 1160, 13), 108, 336, 13, "#93a3b5")

    draw.line((620, 190, 620, HERO_TOP + HERO_H - 22), fill="#263547", width=2)
    _text(draw, "已有成绩谱面", 680, 194, 13, "#93a3b5", True)
    _text(draw, str(data["scanned"]), 680, 220, 56, "#ffffff", True)
    _text(draw, "已达目标", 900, 194, 13, "#93a3b5", True)
    _text(draw, str(data["already"]), 900, 220, 56, MINT, True)
    _text(draw, "可提升", 1120, 194, 13, "#93a3b5", True)
    _text(draw, str(data["candidateCount"]), 1120, 220, 56, "#ff8a6b", True)

    metrics = [
        ("涉及分区", str(data["genreCount"]), ACCENT),
        ("无黄条", f"{data['noRollCount']} 张", MINT_DARK),
        ("必须全良", f"{data['allGoodCount']} 张", "#ff8a6b"),
    ]
    for index, (label, value, color) in enumerate(metrics):
        x = 680 + index * 218
        _box(draw, x, 336, 198, 104, "#101b28", "#2a394b", radius=18)
        draw.ellipse((x + 18, 356, x + 29, 367), fill=color)
        _text(draw, label, x + 40, 350, 12, "#93a3b5", True)
        _text(draw, value, x + 18, 380, 26, "#ffffff", True)

    # --- 分区卡片 ---------------------------------------------------------
    # 分区小标题必须落在深色主卡下沿（HERO_TOP + HERO_H）之外。
    _text(draw, "01 / BY GENRE", 78, 580, 15, ACCENT_DARK, True)
    _text(draw, "按分区列出最接近的谱面", 1370, 582, 14, MUTED, False, "right")

    if not data["genres"]:
        _box(draw, GRID_LEFT, GRID_TOP, 1300, 200, SURFACE, LINE, radius=22)
        _text(draw, "全部谱面都已达到目标评价，暂时没有可提升的曲目。", 720, GRID_TOP + 90, 18, MUTED, False, "center")
    else:
        for index in range(GENRE_CARDS):
            col, row = index % 2, index // 2
            x = GRID_LEFT + col * (CARD_W + CARD_GAP_X)
            y = GRID_TOP + row * (CARD_H + CARD_GAP_Y)
            if index < len(data["genres"]):
                _genre_card(draw, x, y, data["genres"][index], index)
            elif index == len(data["genres"]):
                _empty_card(draw, x, y, "其余分区暂无待提升谱面")
            else:
                _empty_card(draw, x, y, "—")

    # --- 页脚 -------------------------------------------------------------
    draw.line((70, FOOTER_LINE_Y, 1370, FOOTER_LINE_Y), fill=LINE, width=2)
    _text(
        draw,
        "算法：スコア = 良×基本点 + 可×⌊基本点/2⌋ + 黄色連打×100；基本点 = 天井スコア ÷ 总音符数；"
        "评价门槛 = 该谱極スコア × 50/60/70/80/90/95/100%（约 50/60/70/80/90/95/100 万）",
        70, FOOTER_LINE_Y + 18, 12, MUTED,
    )
    _text(
        draw,
        "连打：連打秒数 = 60 ÷ BPM起点 × (拍数 − 1/12)，秒速 = 黄色連打打数 ÷ 合计秒数（风船不计入），"
        "上限 = Σ⌈(秒数+0.001)×60⌉",
        70, FOOTER_LINE_Y + 42, 12, MUTED,
    )
    _text(draw, "天井スコア / 極スコア / 連打秒数 数据来源：太鼓の達人 譜面とか Wiki + ESE 谱面", 70, FOOTER_LINE_Y + 66, 12, MUTED)
    _text(draw, f"{data['generatedAt']} · SCORE RANK", 1370, FOOTER_LINE_Y + 42, 12, ACCENT_DARK, True, "right")

    output = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(output), exist_ok=True)
    image.save(output, "PNG", compress_level=6)
    return output
