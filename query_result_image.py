"""Temporary paper_v1 template: only final conclusions and useful data."""

from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageDraw

if __package__:
    from .report_image import _font, _lines, _text
else:
    from report_image import _font, _lines, _text

WIDTH = 1440
PAPER, WHITE, INK = "#f3f0e8", "#fffdf9", "#202f36"
TEAL, MUTED, LINE = "#236f63", "#64716f", "#d8d9cf"


def prune_query_results(folder, owner, keep_path, retain=5):
    """Rotate only our generated PNGs for this hashed user, after delivery."""
    if not re.fullmatch(r"[0-9a-f]{16}", owner):
        raise ValueError("无效结果文件标识。")
    folder = Path(folder).resolve()
    keep_path = Path(keep_path).resolve()
    candidates = [
        p
        for p in folder.glob(f"query-{owner}-*.png")
        if re.fullmatch(rf"query-{owner}-[0-9a-f]{{32}}\.png", p.name)
        and p.resolve().parent == folder
    ]
    for path in sorted(
        candidates, key=lambda p: (p == keep_path, p.stat().st_mtime_ns), reverse=True
    )[retain:]:
        if path != keep_path:
            path.unlink(missing_ok=True)


def render_query_result(report, output_path, template="paper_v1"):
    if template != "paper_v1":
        raise ValueError("未知查询结果图片模板。")
    result = report["result"]
    scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    blocks = []

    def add(text, size, color=INK, bold=False, gap=20, label=None):
        for line in _lines(scratch, text, 1160, size, bold):
            blocks.append((line, size, color, bold, round(size * 1.55), label))
        blocks.append(("", 0, color, False, gap, None))

    add(result["title"], 50, bold=True, gap=24)
    add(result["conclusion"], 32, gap=35)
    for row in result["rows"]:
        add(row["label"], 26, TEAL, True, gap=4, label="row")
        add(row["value"], 31, gap=24)
    if result["limitations"]:
        add("补充说明", 25, MUTED, True, gap=10)
        for limitation in result["limitations"]:
            add(limitation, 24, MUTED, gap=12)
    height = max(880, 330 + sum(block[4] for block in blocks))
    image = Image.new("RGB", (WIDTH, height), PAPER)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((72, 140, WIDTH - 72, height - 80), radius=28, fill=WHITE)
    draw.rounded_rectangle((72, 140, 82, height - 80), radius=5, fill=TEAL)
    _text(draw, "RTLINK  /  查询结果", 112, 64, 24, TEAL, True)
    source = report.get("source") or "RTLink"
    snapshot = report.get("snapshot") or {}
    stamp = snapshot.get("synced_at")
    provenance = f"来源：{source}" + (
        f"  ·  数据同步：{str(stamp)[:32]}" if stamp else ""
    )
    _text(draw, provenance, 112, 108, 18, MUTED)
    y = 180
    for text, size, color, bold, spacing, label in blocks:
        if label == "row":
            draw.line((116, y - 8, WIDTH - 116, y - 8), fill=LINE, width=1)
        if text:
            draw.text((132, y), text, font=_font(size, bold), fill=color)
        y += spacing
    image.save(output_path, "PNG")
    return str(output_path)
