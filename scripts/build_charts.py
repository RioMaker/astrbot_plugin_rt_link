# -*- coding: utf-8 -*-
"""从 taiko-star-rating-system-cal-by-ai 的 charts.v1.json 裁剪并压缩谱面元数据。

用法（在插件根目录）：
    python scripts/build_charts.py --src ../taiko-star-rating-system-cal-by-ai/public/data/charts.v1.json

产物：
    resource/charts.v1.json.gz    裁剪后的 gzip 谱面数据
    resource/charts.manifest.json 版本/字段清单
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
from pathlib import Path

KEEP_PUBLIC = ("constant", "composite", "avgDensity", "instDensity", "separation", "bpmChange", "hsChange")


def _get(obj, key):
    return obj.get(key) if isinstance(obj, dict) else None


def trim_chart(chart: dict) -> dict:
    out = {
        "id": chart.get("id"),
        "level": chart.get("level"),
        "title": chart.get("title"),
        "titleJa": chart.get("titleJa"),
        "genre": chart.get("genre"),
        "totalNotes": chart.get("totalNotes"),
    }
    public = chart.get("public")
    out["public"] = {k: _get(public, k) for k in KEEP_PUBLIC} if isinstance(public, dict) else None
    feature = chart.get("feature")
    out["feature"] = {
        "aiConstant": _get(feature, "aiConstant"),
        "specializations": _get(feature, "specializations"),
        "proportions": _get(feature, "proportions"),
        "rhythmProfile": _get(feature, "rhythmProfile"),
    } if isinstance(feature, dict) else None
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", required=True, help="charts.v1.json 源文件路径")
    args = parser.parse_args()

    src = Path(args.src)
    charts = json.loads(src.read_text(encoding="utf-8"))
    trimmed = [trim_chart(c) for c in charts if isinstance(c, dict)]
    raw = json.dumps(trimmed, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    out_dir = Path(__file__).resolve().parent.parent / "resource"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "charts.v1.json.gz").write_bytes(gzip.compress(raw, 9))

    manifest = {
        "schemaVersion": 2,
        "modelId": "taiko-signal-rhythm-v2-2026-08-05",
        "chartCount": len(trimmed),
        "source": str(src),
        "trimmedFields": list(KEEP_PUBLIC)
        + ["feature.aiConstant", "feature.specializations", "feature.proportions", "feature.rhythmProfile"],
        "compressedBytes": os.path.getsize(out_dir / "charts.v1.json.gz"),
        "rawBytes": len(raw),
    }
    (out_dir / "charts.manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"charts {len(trimmed)}，raw {len(raw)} bytes，gz {manifest['compressedBytes']} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
