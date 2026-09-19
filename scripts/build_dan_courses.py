# -*- coding: utf-8 -*-
"""Build runtime Dan-i Dojo data from the reviewed Markdown source."""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = 1
DATA_VERSION = "2026-09-19.1"
RANK_ORDER = [
    "五级", "四级", "三级", "二级", "一级",
    "初段", "二段", "三段", "四段", "五段",
    "六段", "七段", "八段", "九段", "十段",
    "玄人", "名人", "超人", "达人",
]
HIGH_RANKS = {"玄人", "名人", "超人", "达人"}
DIFFICULTY_LEVEL = {"简单": 1, "普通": 2, "困难": 3, "鬼": 4, "里": 5}

SOURCES = {
    "official_dan": "https://taiko.namco-ch.net/taiko/special/dani_dojo/",
    "official_jp_2022": "https://taiko-ch.net/blog/?p=7870",
    "official_jp_2023": "https://taiko-ch.net/blog/?p=9459",
    "official_jp_2023_high": "https://taiko-ch.net/blog/?p=9958",
    "official_jp_2024": "https://taiko-ch.net/blog/?p=12313",
    "official_jp_2024_high": "https://taiko-ch.net/blog/?m=202409",
    "official_jp_2025": "https://taiko-ch.net/blog/?p=14433",
    "official_jp_2025_high": "https://taiko-ch.net/blog/?m=202509",
    "official_jp_2026": "https://taiko-ch.net/blog/?p=16229",
    "official_cn_2024": "https://www.weibo.com/ttarticle/p/show?id=2309405133996530204714",
    "official_cn_2025": "https://www.bilibili.com/opus/1119843577790201863",
    "official_cn_2025_high": "https://www.bilibili.com/opus/1158790890953637891",
    "gameplay_cn_2023": "https://www.bilibili.com/video/BV1fE4m1X7ci",
    "reference_2022": "https://wikiwiki.jp/taiko-fumen/段位道場/過去バージョン/ニジイロ2022",
    "reference_2023": "https://wikiwiki.jp/taiko-fumen/段位道場/過去バージョン/ニジイロ2023",
    "reference_2024": "https://wikiwiki.jp/taiko-fumen/段位道場/過去バージョン/ニジイロ2024",
    "reference_2025": "https://wikiwiki.jp/taiko-fumen/段位道場/過去バージョン/ニジイロ2025",
    "reference_2026": "https://wikiwiki.jp/taiko-fumen/段位道場",
}

# 2026 届各段位攻略页：URL 里的段位名用日文写法（級 / 達人），逐段位登记，
# 这样每门课程的「来源」都指向自己那一页，而不是笼统指向十段页。
RANK_PAGE_BASE_2026 = "https://wikiwiki.jp/taiko-fumen/段位道場/ニジイロ2026/"
RANK_PAGE_SLUGS = {
    "五级": "五級", "四级": "四級", "三级": "三級", "二级": "二級", "一级": "一級",
    "初段": "初段", "二段": "二段", "三段": "三段", "四段": "四段", "五段": "五段",
    "六段": "六段", "七段": "七段", "八段": "八段", "九段": "九段", "十段": "十段",
    "玄人": "玄人", "名人": "名人", "超人": "超人", "达人": "達人",
}


def rank_source_id(rank: str) -> str:
    return f"reference_2026_{rank}"


SOURCES.update({rank_source_id(rank): RANK_PAGE_BASE_2026 + slug for rank, slug in RANK_PAGE_SLUGS.items()})

# Only use aliases for typographic or known localized-name differences.
TITLE_ALIASES = {
    "カルメン組曲一番終曲": "カルメン組曲1番終曲",
    "白鳥の湖": "白鳥の湖stilladuckling",
    "トタルエクリプス2035": "トタルエクリプス2035少女の時空皆既日食",
    "テイルズオブジアビス": "thearrowwasshot",
    "soravi火ノ鳥": "soravi火ノ鳥",
    "強風オールバックfeat歌愛ユキ": "強風オールバックfeat歌愛ユキ",
    "チューリングラブfeatsouナナヲアカリ": "チューリングラブfeatsouナナヲアカリ",
}

# These songs are present in the reviewed Dan-i tables but absent from the
# bundled rating chart catalog. Keep them readable instead of guessing an ID.
# They stay `not_in_chart_resource` until the catalog catches up; once the song
# appears in charts.v1, the title lookup maps it automatically again.
KNOWN_MISSING_TITLES = {
    # 2022–2025 tables
    "チュリングラブfeatsouナナヲアカリ",
    "vialactea",
    "brainpower",
    # 2026 tables（2026-09-19 追加；曲库快照只到 song_no 1499，新曲尚未进入评级曲库）
    "鈍響ライクリフド",
    "活声ライクリフド",
    "resumestory",
    "hypernova",
    "vrykolakas",
    "nivalisanima",
    "魔宵月",
    "銀の黎明か黒の晶華か",
}


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").casefold()
    value = value.replace("＆", "&").replace("・", "").replace("：", ":")
    return re.sub(r"[^0-9a-z一-龥ぁ-んァ-ヶ]+", "", value)


def _canonical_title(value: str) -> str:
    normalized = _norm(value)
    return TITLE_ALIASES.get(normalized, normalized)


def _pair(text: str, suffix: str) -> dict:
    match = re.search(r"(\d+)%?\s*/\s*(\d+)%?", text)
    if not match:
        raise ValueError(f"cannot parse normal/gold pair: {text}")
    return {"normal": int(match.group(1)), "gold": int(match.group(2)), "operator": suffix}


def _condition(metric: str, scope: str, pair: dict, unit: str = "count") -> dict:
    return {"metric": metric, "scope": scope, "unit": unit, **pair}


def _parse_conditions(soul: str, primary: str, bad: str, drumroll: str) -> list[dict]:
    result = [_condition("soul_gauge", "course", _pair(soul, ">="), "percent")]
    if primary.startswith("每曲可："):
        pairs = [_pair(part, "<") for part in primary.split("：", 1)[1].split("·")]
        result.append({
            "metric": "ok_count", "scope": "per_song", "unit": "count",
            "normal": [p["normal"] for p in pairs],
            "gold": [p["gold"] for p in pairs], "operator": "<",
        })
    else:
        metric = "hit_count" if primary.startswith("叩击数") else (
            "good_count" if primary.startswith("良") else "ok_count"
        )
        operator = "<" if "未满" in primary else ">="
        result.append(_condition(metric, "course", _pair(primary, operator)))
    if bad != "—":
        result.append(_condition("bad_count", "course", _pair(bad, "<")))
    if drumroll != "—":
        if drumroll.startswith("三曲合计"):
            result.append(_condition("drumroll_count", "course", _pair(drumroll, ">=")))
        else:
            pairs = [_pair(part, ">=") for part in drumroll.replace("以上", "").split("·")]
            result.append({
                "metric": "drumroll_count", "scope": "per_song", "unit": "count",
                "normal": [p["normal"] for p in pairs],
                "gold": [p["gold"] for p in pairs], "operator": ">=",
            })
    return result


def _parse_songs(cell: str) -> list[dict]:
    songs = []
    for order, item in enumerate(cell.split("<br>"), 1):
        match = re.fullmatch(r"(.+?)（(简单|普通|困难|鬼|里)★(\d+)(?:，达人谱面固定)?\s*/\s*(\d+)）", item.strip())
        if not match:
            raise ValueError(f"cannot parse song cell: {item}")
        title, difficulty, stars, notes = match.groups()
        songs.append({
            "order": order,
            "title": title,
            "difficulty": difficulty,
            "level": DIFFICULTY_LEVEL[difficulty],
            "stars": int(stars),
            "total_notes": int(notes),
        })
    if len(songs) != 3:
        raise ValueError(f"course must have exactly three songs: {cell}")
    return songs


def _parse_table(markdown: str, marker: str, end_marker: str | None = None) -> list[dict]:
    start = markdown.index(marker)
    end = markdown.find(end_marker, start + len(marker)) if end_marker else len(markdown)
    block = markdown[start:end if end >= 0 else len(markdown)]
    courses = []
    for line in block.splitlines():
        if not line.startswith("| ") or line.startswith("|---") or "段位 |" in line:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 6 or cells[0] not in RANK_ORDER:
            continue
        rank, songs, soul, primary, bad, drumroll = cells
        courses.append({
            "rank": rank,
            "rank_order": RANK_ORDER.index(rank),
            "songs": _parse_songs(songs),
            "conditions": _parse_conditions(soul, primary, bad, drumroll),
        })
    return courses


def _chart_index(charts: list[dict]) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = {}
    for chart in charts:
        song_no = chart.get("id")
        for title in (chart.get("title"), chart.get("titleJa")):
            key = _canonical_title(str(title or ""))
            if key and isinstance(song_no, int):
                index.setdefault(key, []).append(chart)
    return index


def _candidate_rank(chart: dict, level: int, notes: int) -> tuple:
    """候选谱面可信度排序：难度一致 → 音符数一致 → ID 最小（保证结果稳定）。

    同名曲目（例如「エンジェル ドリーム」同时存在デレマス版与ナムコオリジナル版）
    必须先按难度和音符数收敛，否则会绑到音符数对不上的同名片。
    """
    return (
        0 if chart.get("level") == level else 1,
        0 if chart.get("totalNotes") == notes else 1,
        int(chart.get("id") or 0),
    )


def _map_songs(courses: list[dict], charts: list[dict]) -> dict:
    index = _chart_index(charts)
    chart_keys = {(row.get("id"), row.get("level")) for row in charts}
    mapped = unavailable = unresolved = 0
    evidence_counts: dict[str, int] = {}
    details = []
    for course in courses:
        for song in course["songs"]:
            title_key = _canonical_title(song["title"])
            candidate_rows = sorted(
                index.get(title_key, []),
                key=lambda row: _candidate_rank(row, song["level"], song["total_notes"]),
            )
            candidates = []
            for row in candidate_rows:
                if isinstance(row.get("id"), int) and row["id"] not in candidates:
                    candidates.append(row["id"])
            if candidates:
                best = candidate_rows[0]
                song["song_no"] = candidates[0]
                song["song_no_candidates"] = candidates
                has_rated_chart = any((song_no, song["level"]) in chart_keys for song_no in candidates)
                if len(candidates) > 1:
                    song["mapping_status"] = "verified_aliases"
                else:
                    song["mapping_status"] = "verified" if has_rated_chart else "song_verified_level_unrated"
                if best.get("level") != song["level"]:
                    evidence = "title"
                elif best.get("totalNotes") != song["total_notes"]:
                    evidence = "title+level"
                elif len(candidates) > 1:
                    evidence = "title+level+notes+ambiguous"
                else:
                    evidence = "title+level+notes"
                song["mapping_evidence"] = evidence
                evidence_counts[evidence] = evidence_counts.get(evidence, 0) + 1
                mapped += 1
            elif title_key in KNOWN_MISSING_TITLES:
                song["song_no"] = None
                song["song_no_candidates"] = []
                song["mapping_status"] = "not_in_chart_resource"
                song["mapping_evidence"] = "known_missing"
                unavailable += 1
            else:
                song["song_no"] = None
                song["song_no_candidates"] = []
                song["mapping_status"] = "unmapped"
                song["mapping_evidence"] = "none"
                unresolved += 1
                details.append({
                    "year": course["year"], "region": course["region"], "rank": course["rank"],
                    "order": song["order"], "title": song["title"], "candidates": candidates,
                })
    return {
        "mapped": mapped,
        "unavailable": unavailable,
        "unresolved": unresolved,
        "evidence": evidence_counts,
        "details": details,
    }


def _with_metadata(rows: list[dict], year: int, region: str, opens: str, closes: str | None, sources: list[str]) -> list[dict]:
    result = []
    for row in rows:
        item = copy.deepcopy(row)
        item.update({
            "year": year, "region": region, "opens_at": opens, "closes_at": closes,
            "source_ids": sources, "verification_status": "verified",
        })
        result.append(item)
    return result


def build(markdown_path: Path, charts_path: Path) -> tuple[dict, dict]:
    markdown = markdown_path.read_text(encoding="utf-8")
    charts = json.loads(gzip.decompress(charts_path.read_bytes()).decode("utf-8"))
    years = {
        2022: _parse_table(markdown, "## 3. 段位道场 2022", "## 4. 段位道场 2023"),
        2023: _parse_table(markdown, "## 4. 段位道场 2023", "## 5. 段位道场 2024"),
        2024: _parse_table(markdown, "## 5. 段位道场 2024", "## 6. 段位道场 2025"),
        2025: _parse_table(markdown, "## 6. 段位道场 2025", "## 7. 段位道场 2026"),
        2026: _parse_table(markdown, "## 7. 段位道场 2026", "## 8. RTLink"),
    }
    for year, rows in years.items():
        if len(rows) != len(RANK_ORDER):
            raise ValueError(f"{year}: expected {len(RANK_ORDER)} courses, got {len(rows)}")

    courses = []
    courses += _with_metadata(years[2022], 2022, "jp_worldwide", "2022-06-04", None, ["official_jp_2022", "reference_2022"])
    courses += _with_metadata(years[2023], 2023, "jp_worldwide", "2023-06-10", "2024-05-22", ["official_jp_2023", "official_jp_2023_high", "reference_2023"])
    courses += _with_metadata(years[2024], 2024, "jp_worldwide", "2024-06-01", "2025-05-28", ["official_jp_2024", "official_jp_2024_high", "reference_2024"])
    courses += _with_metadata(years[2025], 2025, "jp_worldwide", "2025-06-07", "2026-05-30", ["official_jp_2025", "official_jp_2025_high", "reference_2025"])
    courses += _with_metadata(years[2026], 2026, "jp_worldwide", "2026-06-06", None, ["official_jp_2026", "reference_2026"])
    for row in courses:
        if row["year"] == 2026:
            row["source_ids"] = [
                "official_jp_2026", "reference_2026", rank_source_id(row["rank"]),
            ]
    jp_high_opens = {
        2022: "2022-09-19",
        2023: "2023-09-23",
        2024: "2024-09-21",
        2025: "2025-09-13",
        2026: "2026-09-12",
    }
    for row in courses:
        if row["region"] == "jp_worldwide" and row["rank"] in HIGH_RANKS:
            row["opens_at"] = jp_high_opens[row["year"]]

    cn_2023 = _with_metadata(years[2023], 2023, "cn", "2024-07-18", "2025-01-28", ["reference_2023"])
    cn_diff = {row["rank"]: row for row in _parse_table(markdown, "### 中国大陆版 2023 差异表", "国服 2023 现场核对入口")}
    for row in cn_2023:
        if row["rank"] in cn_diff:
            replacement = copy.deepcopy(cn_diff[row["rank"]])
            row["songs"] = replacement["songs"]
            row["conditions"] = replacement["conditions"]
            row["source_ids"] = ["reference_2023", "gameplay_cn_2023"]
    courses += cn_2023
    courses += _with_metadata(years[2024], 2024, "cn", "2025-02-19", None, ["official_cn_2024", "reference_2024"])
    cn_2025 = _with_metadata(years[2025], 2025, "cn", "2025-10-09", None, ["official_cn_2025", "official_cn_2025_high", "reference_2025"])
    for row in cn_2025:
        if row["rank"] in HIGH_RANKS:
            row["opens_at"] = "2026-01-21"
    courses += cn_2025

    report = _map_songs(courses, charts)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "data_version": DATA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_markdown_sha256": hashlib.sha256(markdown_path.read_bytes()).hexdigest(),
        "sources": SOURCES,
        "courses": sorted(courses, key=lambda row: (row["year"], row["region"], row["rank_order"])),
    }
    return payload, report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--markdown", default="DAN_I_DOJO_2022_2026.md")
    parser.add_argument("--charts", default="resource/charts.v1.json.gz")
    parser.add_argument("--output", default="resource/dan_courses.v1.json.gz")
    parser.add_argument("--manifest", default="resource/dan_courses.manifest.json")
    parser.add_argument("--report", default="resource/dan_courses.mapping.json")
    args = parser.parse_args()

    payload, report = build(Path(args.markdown), Path(args.charts))
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    Path(args.output).write_bytes(gzip.compress(raw, 9, mtime=0))
    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "dataVersion": DATA_VERSION,
        "courseCount": len(payload["courses"]),
        "songEntryCount": sum(len(row["songs"]) for row in payload["courses"]),
        "mappedSongEntryCount": report["mapped"],
        "unavailableSongEntryCount": report["unavailable"],
        "unresolvedSongEntryCount": report["unresolved"],
        "sourceMarkdownSha256": payload["source_markdown_sha256"],
        "compressedBytes": Path(args.output).stat().st_size,
    }
    Path(args.manifest).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False))
    return 1 if report["unresolved"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
