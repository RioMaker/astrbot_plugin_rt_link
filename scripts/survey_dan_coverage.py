# -*- coding: utf-8 -*-
"""统计段位课题曲写法与曲库曲名的吻合度（用于文档与别名覆盖率复盘）。

用法（插件根目录）：
    python scripts/survey_dan_coverage.py
    python scripts/survey_dan_coverage.py --json test/tmp/dan_coverage.json

分类口径（每条课题曲记录算一条）：
    cn  : 段位资料的写法 == 曲库国服曲名（charts.title）
    ja  : 段位资料的写法 == 曲库日文曲名（charts.titleJa）
    id  : 两者都不同，但已映射到曲库 ID（靠归一化或别名表命中）
    miss: 曲库中找不到（含尚未进入评级曲库的新曲）

大字输出只用 ASCII，避免 GBK 控制台乱码；中文细节写进 --json 文件。
"""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path


def load_json(path: Path):
    raw = path.read_bytes()
    if str(path).endswith(".gz"):
        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def survey(dan_path: Path, charts_path: Path) -> dict:
    dan = load_json(dan_path)
    charts = load_json(charts_path)
    titles = {str(row.get("title") or "") for row in charts}
    titles_ja = {str(row.get("titleJa") or "") for row in charts}

    stats = {
        "dataVersion": dan.get("data_version"),
        "courses": len(dan.get("courses") or []),
        "songs": 0,
        "cn": 0,
        "ja": 0,
        "id": 0,
        "miss": 0,
        "missTitles": [],
    }
    for course in dan.get("courses") or []:
        for song in course.get("songs") or []:
            stats["songs"] += 1
            raw = str(song.get("title") or "")
            if raw in titles:
                stats["cn"] += 1
            elif raw in titles_ja:
                stats["ja"] += 1
            elif song.get("song_no"):
                stats["id"] += 1
            else:
                stats["miss"] += 1
                stats["missTitles"].append(f"{course.get('year')} {course.get('rank')} {raw}")
    stats["missTitles"] = sorted(set(stats["missTitles"]))
    return stats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dan", default="resource/dan_courses.v1.json.gz")
    parser.add_argument("--charts", default="resource/charts.v1.json.gz")
    parser.add_argument("--json", default=None, help="把完整结果写到指定 JSON 文件")
    args = parser.parse_args()

    stats = survey(Path(args.dan), Path(args.charts))
    print(
        "dan {version}: {courses} courses / {songs} songs | "
        "cn {cn} | ja {ja} | id-only {id} | missing {miss}".format(
            version=stats["dataVersion"], **stats
        )
    )
    if args.json:
        Path(args.json).write_text(
            json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"written {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
