# -*- coding: utf-8 -*-
"""构建曲名别名资源：把同一首歌的各种写法收进一张表。

用法（在插件根目录）：
    python scripts/build_aliases.py
    python scripts/build_aliases.py --ese-root "<ESE 根目录>" --mapping "<mapping-report.v1.json>"

产物：
    resource/aliases.v1.json.gz     按 (song_no, level) 索引的曲名与别名
    resource/aliases.manifest.json  版本、来源、覆盖率与冲突统计

名字来源：
    1. 谱面库 `resource/charts.v1.json.gz`：国服曲名（title）与日文曲名（titleJa）
    2. ESE TJA 的 `TITLE:`：罗马字/英文曲名（需要 --ese-root 与 --mapping）
    3. 段位资料 `resource/dan_courses.v1.json.gz`：段位页面上的写法（多为日文）
    4. `scripts/data/song_aliases.json`：人工整理的简称/黑话/常见错写

派生写法（自动生成，便于「少打几个字」也能查到）：
    - 去掉【限定】、（…）、（裏譜面）等括号内容
    - 只取 ～ / ~ 之前的主标题
    - 去掉空格与标点后的紧凑写法

注意：本脚本只在构建期运行；插件运行期只读 resource/ 下的压缩资源。
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from song_alias import normalize  # noqa: E402

SCHEMA_VERSION = 1
DATA_VERSION = "2026-09-19.1"

BRACKET_RE = re.compile(r"[（(【\[［][^）)】\]］]*[）)】\]］]")
SPLIT_RE = re.compile(r"[～〜~]| - |－")
NOISE = ("【限定】", "（裏譜面）", "(裏譜面)", "【双打】", "（双打）")


def load_charts(path: Path) -> list[dict]:
    raw = path.read_bytes()
    if path.suffix == ".gz":
        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def load_gz_json(path: Path) -> dict:
    raw = path.read_bytes()
    if str(path).endswith(".gz"):
        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def read_tja_title(path: Path) -> tuple[str, str]:
    """只读 TJA 头部的 TITLE / TITLEJA（不打全谱）。"""
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")[:4000]
    except OSError:
        return "", ""
    title = re.search(r"(?mi)^TITLE:(.*)$", text)
    title_ja = re.search(r"(?mi)^TITLEJA:(.*)$", text)
    return (title.group(1).strip() if title else "", title_ja.group(1).strip() if title_ja else "")


def variants(value: str) -> list:
    """派生写法：去括号内容、取主标题、去掉「2000」尾缀、去符号紧凑写法。"""
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not text:
        return []
    out = []
    stripped = BRACKET_RE.sub("", text).strip()
    if stripped and stripped != text:
        out.append(stripped)
    for junk in NOISE:
        stripped = stripped.replace(junk, "").strip()
    head = SPLIT_RE.split(stripped or text)[0].strip()
    if head and head != text and len(normalize(head)) >= 2:
        out.append(head)
    # 「○○2000」系列常被简称为「○○」（北埼玉2000 → 北埼玉）
    no_series = re.sub(r"\s*(?:200|2000)$", "", stripped or text).strip()
    if no_series and no_series != text and len(normalize(no_series)) >= 2:
        out.append(no_series)
    compact = re.sub(r"[\s\-_・、,，。!！?？'\"’”]+", "", text)
    if compact and compact != text:
        out.append(compact)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--charts", default=None, help="谱面库路径（默认 resource/charts.v1.json.gz）")
    parser.add_argument("--dan", default=None, help="段位资料路径（默认 resource/dan_courses.v1.json.gz）")
    parser.add_argument("--curated", default=None, help="人工别名表（默认 scripts/data/song_aliases.json）")
    parser.add_argument("--ese-root", default=None, help="ESE 的 TJA 根目录（取罗马字曲名）")
    parser.add_argument("--mapping", default=None, help="rating 工程的 mapping-report.v1.json")
    parser.add_argument("--out-dir", default=None, help="输出目录（默认插件 resource/）")
    args = parser.parse_args()

    plugin_dir = Path(__file__).resolve().parent.parent
    out_dir = Path(args.out_dir) if args.out_dir else plugin_dir / "resource"
    charts_path = Path(args.charts) if args.charts else out_dir / "charts.v1.json.gz"
    dan_path = Path(args.dan) if args.dan else out_dir / "dan_courses.v1.json.gz"
    curated_path = Path(args.curated) if args.curated else plugin_dir / "scripts" / "data" / "song_aliases.json"

    charts = load_charts(charts_path)
    catalog = {(chart["id"], chart["level"]): chart for chart in charts}
    stats = {"charts": len(catalog), "romaji": 0, "danTitles": 0, "curated": 0, "missingCurated": []}

    songs: dict[str, dict] = {}
    for (song_no, level), chart in catalog.items():
        key = f"{song_no}|{level}"
        names: list[str] = []
        aliases: list[str] = []
        for field in ("title", "titleJa"):
            value = chart.get(field)
            if value and value not in names:
                names.append(value)
        songs[key] = {"names": names, "aliases": aliases}

    # 1) ESE TJA 的罗马字 / 英文曲名
    if args.ese_root and args.mapping:
        ese_root = Path(args.ese_root)
        mapping = json.loads(Path(args.mapping).read_text(encoding="utf-8"))["mappings"]
        for entry in mapping:
            if entry.get("status") != "matched" or not entry.get("selected"):
                continue
            key = f"{entry.get('songNo')}|{entry.get('level')}"
            item = songs.get(key)
            if item is None:
                continue
            title, _title_ja = read_tja_title(ese_root / entry["selected"]["relativePath"])
            if title and title not in item["names"] and title not in item["aliases"]:
                item["aliases"].append(title)
                stats["romaji"] += 1
    elif args.ese_root or args.mapping:
        print("提示：--ese-root 与 --mapping 需要同时提供，已跳过罗马字曲名。")

    # 2) 段位资料里的写法
    if dan_path.exists():
        dan = load_gz_json(dan_path)
        for course in dan.get("courses", []):
            for song in course.get("songs", []):
                title = str(song.get("title") or "").strip()
                if not title:
                    continue
                for song_no in song.get("song_no_candidates") or []:
                    item = songs.get(f"{song_no}|{song.get('level')}")
                    if item is None:
                        continue
                    if title not in item["names"] and title not in item["aliases"]:
                        item["aliases"].append(title)
                        stats["danTitles"] += 1

    # 3) 人工整理的别名
    if curated_path.exists():
        curated = json.loads(curated_path.read_text(encoding="utf-8")).get("aliases") or {}
        for song_no_text, values in curated.items():
            try:
                song_no = int(song_no_text)
            except (TypeError, ValueError):
                continue
            levels = [level for (sid, level) in catalog if sid == song_no]
            if not levels:
                stats["missingCurated"].append(song_no_text)
                continue
            for level in levels:
                item = songs[f"{song_no}|{level}"]
                for value in values:
                    value = str(value or "").strip()
                    if value and value not in item["names"] and value not in item["aliases"]:
                        item["aliases"].append(value)
                        stats["curated"] += 1

    # 4) 派生写法
    for item in songs.values():
        for value in list(item["names"]) + list(item["aliases"]):
            for variant in variants(value):
                if variant not in item["names"] and variant not in item["aliases"]:
                    item["aliases"].append(variant)

    # 统计冲突：同一归一化写法指向多首歌
    index: dict[str, set] = {}
    for key, item in songs.items():
        for value in item["names"] + item["aliases"]:
            norm = normalize(value)
            if norm:
                index.setdefault(norm, set()).add(key.partition("|")[0])
    ambiguous = {norm: sorted(keys) for norm, keys in index.items() if len(keys) > 1}

    payload = {
        "schema_version": SCHEMA_VERSION,
        "data_version": DATA_VERSION,
        "sources": {
            "catalog": "resource/charts.v1.json.gz（国服曲名 + 日文曲名）",
            "ese": str(args.mapping or ""),
            "dan": "resource/dan_courses.v1.json.gz（段位资料里的写法）",
            "curated": str(curated_path),
        },
        "note": "names=规范曲名（国服/日文/罗马字），aliases=额外别名；匹配时统一 normalize 后比较",
        "songs": songs,
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    out_dir.mkdir(parents=True, exist_ok=True)
    gz_path = out_dir / "aliases.v1.json.gz"
    gz_path.write_bytes(gzip.compress(raw, 9))

    total_names = sum(len(item["names"]) + len(item["aliases"]) for item in songs.values())
    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "dataVersion": DATA_VERSION,
        "catalogCharts": len(catalog),
        "aliasEntries": total_names,
        "averageNamesPerChart": round(total_names / len(catalog), 2) if catalog else 0,
        "ambiguousKeys": len(ambiguous),
        "ambiguousSamples": dict(list(ambiguous.items())[:10]),
        "sources": stats,
        "compressedBytes": gz_path.stat().st_size,
        "rawBytes": len(raw),
    }
    (out_dir / "aliases.manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"谱面 {len(catalog)} 张 → 写法 {total_names} 条（平均 {manifest['averageNamesPerChart']}/张）；"
        f"罗马字 {stats['romaji']}、段位写法 {stats['danTitles']}、人工别名 {stats['curated']}；"
        f"冲突写法 {len(ambiguous)}"
    )
    if stats["missingCurated"]:
        print(f"人工别名表里有谱面库不存在的 ID（已忽略）：{stats['missingCurated']}")
    print(f"已写出 {gz_path.name}（{manifest['compressedBytes']} bytes）与 manifest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
