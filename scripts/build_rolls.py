# -*- coding: utf-8 -*-
"""从 TJA 谱面提取每张谱面的黄色連打秒数 / 風船，构建连打资源。

用法（在插件根目录）：
    python scripts/build_rolls.py --ese-root "D:\\taiko\\ESE"
    python scripts/build_rolls.py --ese-root "D:\\taiko\\ESE" --mapping "<mapping-report.v1.json>"

产物：
    resource/rolls.v1.json.gz     按 (song_no, level) 索引的连打资料
    resource/rolls.manifest.json  版本、来源、覆盖率与字段清单

数据用途：
    - `seconds`      黄色連打合计秒数（不含风船），用来把「还需补几打连打」换算成秒速。
    - `maxHits`      該谱黄条的連打理論値合计，即这张谱最多能打进多少打。
    - `balloonHits`  风船要求打数（估算），用于把结算连打数里的风船部分扣掉。

公式（太鼓の達人 譜面とか Wiki「連打秒数表」）：
    連打秒数   = 60 ÷ BPM起点 × (拍数 - 1/12)        # 黄条比拍数短 1/12 拍
    連打理論値 = ⌈(連打秒数 + 0.001) × 60⌉            # 即每秒上限约 60 打
    連打速度   = 黄色連打打数 ÷ 合计連打秒数          # 风船不计入

谱面记号（与 ESE / TJADB 一致）：`5`/`6` = 黄色連打起点，`7`/`9`/`D` = 風船系起点，
`8` = 上述长音的终点；分歧谱固定取达人线（`#M` > `#E` > `#N`）。

注意：本脚本只在构建期读本地 TJA；插件运行期只读 resource/ 下的压缩资源。
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import re
import unicodedata
import urllib.parse
from pathlib import Path

SCHEMA_VERSION = 1
DATA_VERSION = "2026-09-19.1"
WIKI_BASE = "https://wikiwiki.jp/taiko-fumen/"
WIKI_PAGE = "作品/新AC/極スコア/おに"
SOURCE = WIKI_BASE + urllib.parse.quote(WIKI_PAGE)

# TJA 长音记号：起点与终点。
ROLL_STARTS = "56"
BALLOON_STARTS = "79D"
LONG_STARTS = ROLL_STARTS + BALLOON_STARTS
LONG_END = "8"

# wiki 要求速度与 TJA 解析出的秒数允许的相对偏差；超出则以 wiki 为准。
SPEED_TOLERANCE = 0.15

# 「极」要求速度的常见区间（打/秒），用于体检报告。
KIWAMI_SPEED_RANGE = (14.0, 22.0)

URA_MARKERS = ("裏譜面", "(裏)", "（裏）")
TITLE_NOISE = ("【限定】",)


# ---------------------------------------------------------------------------
# TJA 解析
# ---------------------------------------------------------------------------

def strip_comment(line: str) -> str:
    index = line.find("//")
    return line[:index] if index != -1 else line


def select_master_route(lines: list[str]) -> tuple[list[str], str | None]:
    """分歧谱取达人线（M > E > N），返回 (音符行, 选中的线名)。"""
    selected: list[str] = []
    route_chosen: str | None = None
    index = 0
    while index < len(lines):
        line = strip_comment(lines[index])
        if not line.upper().startswith("#BRANCHSTART"):
            selected.append(line)
            index += 1
            continue
        index += 1
        routes: dict[str, list[str]] = {"N": [], "E": [], "M": []}
        prelude: list[str] = []
        route: str | None = None
        while index < len(lines) and not strip_comment(lines[index]).upper().startswith("#BRANCHEND"):
            marker = strip_comment(lines[index]).upper()
            if route is not None and marker.startswith("#BRANCHSTART"):
                break
            if marker in ("#N", "#E", "#M"):
                route = marker[1]
            elif route is None:
                prelude.append(lines[index])
            else:
                routes[route].append(lines[index])
            index += 1
        chosen = "M" if routes["M"] else "E" if routes["E"] else "N"
        route_chosen = chosen
        selected.extend(prelude)
        selected.extend(routes[chosen])
        if index < len(lines) and strip_comment(lines[index]).upper().startswith("#BRANCHEND"):
            index += 1
    return selected, route_chosen


def build_cells(lines: list[str], initial_bpm: float) -> list[tuple[float, str, float]]:
    """把音符行展开成 (该槽拍数, 字符, 生效BPM) 序列。

    - 小节内出现 #BPMCHANGE 时按字符偏移生效（整小节拍数不变）。
    - 空小节同样占用拍数，否则跨小节的连打会被算短。
    """
    cells: list[tuple[float, str, float]] = []
    buffer = ""
    beats = 4.0
    base_bpm = initial_bpm
    events: list[tuple[int, float]] = []

    def resolve_bpm(offset: int) -> float:
        value = base_bpm
        for position, bpm_value in events:
            if position <= offset:
                value = bpm_value
        return value

    def flush() -> None:
        nonlocal buffer, base_bpm, events
        if not buffer:
            cells.append((beats, "0", base_bpm))
        else:
            step = beats / len(buffer)
            for index, char in enumerate(buffer):
                cells.append((step, char, resolve_bpm(index)))
        base_bpm = resolve_bpm(len(buffer))
        buffer = ""
        events = []

    for line in lines:
        upper = line.upper()
        if upper.startswith("#BPMCHANGE"):
            events.append((len(buffer), float(line.split()[-1])))
            continue
        if upper.startswith("#MEASURE"):
            value = line.split()[-1]
            if "/" in value:
                num, den = value.split("/")
                beats = float(num) / float(den) * 4.0
            continue
        if line.startswith("#"):
            continue
        parts = re.sub(r"\s+", "", line).split(",")
        for part in parts[:-1]:
            buffer += part
            flush()
        buffer += parts[-1]
    flush()
    return cells


def marks_of(cells: list[tuple[float, str, float]]) -> dict:
    """从槽序列里取出黄条与风船，按 wiki 公式算出每条秒数与理論値。"""
    rolls: list[dict] = []
    balloons: list[dict] = []
    open_start: tuple[int, str] | None = None
    for index, (step, char, bpm) in enumerate(cells):
        if char in LONG_STARTS:
            if open_start is None:
                open_start = (index, char)
        elif char == LONG_END and open_start is not None:
            start, kind = open_start
            beats = sum(cell[0] for cell in cells[start:index + 1])
            start_bpm = cells[start][2] or 120.0
            seconds = (beats - 1.0 / 12.0) * 60.0 / start_bpm
            item = {
                "beats": beats,
                "seconds": seconds,
                "bpm": start_bpm,
                "maxHits": int(math.ceil((seconds + 0.001) * 60)),
            }
            (rolls if kind in ROLL_STARTS else balloons).append(item)
            open_start = None
    return {"rolls": rolls, "balloons": balloons}


def parse_tja(path: Path) -> list[dict]:
    """解析一个 TJA 文件，返回每个 COURSE 的连打资料。"""
    lines = []
    for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        text = strip_comment(raw).strip()
        if text:
            lines.append(text)

    header_bpm = 120.0
    courses: list[dict] = []
    meta: dict[str, str] = {}
    body: list[str] = []
    course: str | None = None
    collecting = False

    def finish() -> None:
        if course is None:
            return
        route_lines, route = select_master_route(body)
        balloon_key = {"M": "BALLOONMAS", "E": "BALLOONEXP", "N": "BALLOONNOR"}.get(route or "", "")
        balloon_text = meta.get(balloon_key, "") or meta.get("BALLOON", "")
        balloons = [int(value) for value in re.findall(r"\d+", balloon_text)]
        marks = marks_of(build_cells(route_lines, float(meta.get("BPM") or header_bpm)))
        courses.append({
            "course": course,
            "level": meta.get("LEVEL"),
            "route": route,
            "balloonValues": balloons,
            "marks": marks,
        })

    for line in lines:
        upper = line.upper()
        if upper.startswith("COURSE:"):
            finish()
            course = line.split(":", 1)[1].strip()
            meta = {}
            body = []
            collecting = False
            continue
        if upper == "#START":
            collecting = True
            continue
        if upper == "#END":
            collecting = False
            continue
        if ":" in line and not line.startswith("#"):
            key, value = line.split(":", 1)
            key = key.strip().upper()
            if course is not None and key in {
                "LEVEL", "BALLOON", "BALLOONNOR", "BALLOONEXP", "BALLOONMAS", "BPM", "STYLE",
            }:
                meta[key] = value.strip()
            elif key == "BPM":
                header_bpm = float(value)
            continue
        if collecting and course is not None:
            body.append(line)
    finish()
    return courses


def summarize_course(course: dict) -> dict:
    marks = course["marks"]
    rolls = marks["rolls"]
    balloons = marks["balloons"]
    return {
        "seconds": round(sum(item["seconds"] for item in rolls), 6),
        "rolls": len(rolls),
        "maxHits": sum(item["maxHits"] for item in rolls),
        "balloonSeconds": round(sum(item["seconds"] for item in balloons), 6),
        "balloons": len(balloons),
        "balloonHits": sum(course["balloonValues"]) if balloons else 0,
        "route": course["route"],
    }


# ---------------------------------------------------------------------------
# 标题匹配（缺少 mapping 报告时的兜底）
# ---------------------------------------------------------------------------

def norm_title(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").casefold()
    for junk in URA_MARKERS + TITLE_NOISE:
        text = text.replace(unicodedata.normalize("NFKC", junk).casefold(), "")
    return re.sub(r"[^0-9a-z一-龥ぁ-んァ-ヶ]+", "", text)


def build_title_index(charts: list[dict]) -> dict:
    index: dict[str, set[tuple[int, int]]] = {}
    for chart in charts:
        for key in ("titleJa", "title"):
            value = chart.get(key)
            if value:
                index.setdefault(norm_title(value), set()).add((chart["id"], chart["level"]))
    return index


def match_by_title(courses: list[tuple[Path, dict]], charts: list[dict]) -> dict:
    """按「标题 + 难度」把 TJA COURSE 匹配到 (song_no, level)；歧义不猜。"""
    index = build_title_index(charts)
    songs: dict[str, dict] = {}
    for path, course in courses:
        level = 5 if course["course"].lower() in ("edit", "ura") else 4
        title_key = norm_title(path.parent.name) or norm_title(path.stem)
        exact = [item for item in index.get(title_key, set()) if item[1] == level]
        if len(exact) != 1:
            continue
        song_no, _ = exact[0]
        songs.setdefault(f"{song_no}|{level}", summarize_course(course))
    return songs


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

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


def collect_from_mapping(mapping_path: Path, ese_root: Path) -> tuple[dict, list]:
    """按 rating 工程的 mapping 报告取每个谱面对应的 TJA。"""
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))["mappings"]
    songs: dict[str, dict] = {}
    skipped = []
    for entry in mapping:
        selected = entry.get("selected")
        if entry.get("status") != "matched" or not selected:
            skipped.append((f"{entry.get('songNo')}|{entry.get('level')}", "unmatched"))
            continue
        key = f"{entry['songNo']}|{entry['level']}"
        path = ese_root / selected["relativePath"]
        course_name = (selected.get("course") or "oni").lower()
        try:
            courses = parse_tja(path)
        except Exception as error:  # noqa: BLE001 - 构建期跳过并统计
            skipped.append((key, f"parse:{type(error).__name__}"))
            continue
        course = next((item for item in courses if item["course"].lower() == course_name), None)
        if course is None:
            skipped.append((key, "course-not-found"))
            continue
        songs[key] = summarize_course(course)
    return songs, skipped


def collect_from_titles(ese_root: Path, charts: list[dict]) -> tuple[dict, list]:
    """没有 mapping 报告时，遍历 TJA 并按标题匹配。"""
    courses = []
    for path in ese_root.rglob("*.tja"):
        try:
            for course in parse_tja(path):
                courses.append((path, course))
        except Exception:  # noqa: BLE001 - 构建期跳过
            continue
    return match_by_title(courses, charts), []


def merge_wiki(songs: dict, score_rank: dict) -> dict:
    """用 wiki 的「要求連打速度」交叉校验 TJA 解析出的秒数。

    要求速度 = 必要連打数 ÷ 合計連打秒数，因此 T_wiki = 必要連打数 ÷ 要求速度。
    多数谱面的 合計連打秒数 只算黄条，但少数以风船为主的谱面（例如 Rotter Tarmination 裏）
    wiki 把风船的秒数也算进去了，所以两边都对不上时才改用 wiki 的秒数：
        与「黄条秒数」或「黄条+风船秒数」之一在容差内 → 保留 TJA 的结构与秒数；
        都对不上 → 认为 TJA 版本与当前街机谱面不一致，秒数改按 wiki 反推。
    """
    stats = {"tja": 0, "tjaWithBalloon": 0, "wiki": 0, "noWikiSpeed": 0, "noRolls": 0}
    rank_songs = (score_rank or {}).get("songs") or {}
    for key, item in songs.items():
        song = rank_songs.get(key) or {}
        need = int(song.get("rolls") or 0)
        speed = song.get("speed")
        item["speed"] = float(speed) if speed else None
        item["source"] = "tja"
        if item["rolls"] <= 0:
            # TJA 里没有黄条（可能只有风船）：结构以 TJA 为准，不拿 wiki 的必要連打数当黄条。
            item["seconds"] = 0.0
            item["maxHits"] = 0
            stats["noRolls"] += 1
            continue
        if not speed or need <= 0:
            stats["noWikiSpeed"] += 1
            continue
        wiki_seconds = need / float(speed)
        item["wikiSeconds"] = round(wiki_seconds, 6)
        total_seconds = item["seconds"] + item.get("balloonSeconds", 0.0)
        if item["seconds"] > 0 and abs(item["seconds"] / wiki_seconds - 1) <= SPEED_TOLERANCE:
            stats["tja"] += 1
            continue
        if total_seconds > 0 and abs(total_seconds / wiki_seconds - 1) <= SPEED_TOLERANCE:
            # wiki 的要求速度是按「黄条+风船」算的；秒速仍只取黄条。
            stats["tjaWithBalloon"] += 1
            continue
        item.update({
            "seconds": round(wiki_seconds, 6),
            "maxHits": int(math.ceil((wiki_seconds + 0.001) * 60)),
            "source": "wiki",
        })
        stats["wiki"] += 1
    return stats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ese-root", required=True, help="ESE 的 TJA 根目录")
    parser.add_argument("--mapping", default=None, help="rating 工程的 mapping-report.v1.json（推荐）")
    parser.add_argument("--charts", default=None, help="谱面库路径（默认 resource/charts.v1.json.gz）")
    parser.add_argument("--score-rank", default=None, help="评分资源路径（默认 resource/score_rank.v1.json.gz）")
    parser.add_argument("--out-dir", default=None, help="输出目录（默认插件 resource/）")
    args = parser.parse_args()

    plugin_dir = Path(__file__).resolve().parent.parent
    out_dir = Path(args.out_dir) if args.out_dir else plugin_dir / "resource"
    charts_path = Path(args.charts) if args.charts else out_dir / "charts.v1.json.gz"
    rank_path = Path(args.score_rank) if args.score_rank else out_dir / "score_rank.v1.json.gz"
    ese_root = Path(args.ese_root)
    if not ese_root.is_dir():
        raise SystemExit(f"ESE 根目录不存在：{ese_root}")

    charts = load_charts(charts_path)
    score_rank = load_gz_json(rank_path) if rank_path.exists() else {}
    print(f"谱面库：{len(charts)} 条；评分资源：{len((score_rank.get('songs') or {}))} 条")

    if args.mapping:
        songs, skipped = collect_from_mapping(Path(args.mapping), ese_root)
    else:
        songs, skipped = collect_from_titles(ese_root, charts)
    print(f"TJA 解析：{len(songs)} 个谱面；跳过 {len(skipped)}")

    stats = merge_wiki(songs, score_rank)
    with_rolls = sum(1 for item in songs.values() if item["rolls"] > 0)
    balloon_only = sum(1 for item in songs.values() if item["rolls"] <= 0 < item["balloons"])
    no_long = sum(1 for item in songs.values() if item["rolls"] <= 0 and item["balloons"] <= 0)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "data_version": DATA_VERSION,
        "source": SOURCE,
        "note": (
            "seconds=黄色連打合计秒数（不含风船），rolls=黄条条数，maxHits=連打理論値合计，"
            "balloonSeconds/balloons/balloonHits=风船（不参与秒速），speed=wiki 极要求速度，"
            "source=seconds 的来源（tja=谱面解析，wiki=按要求速度反推）"
        ),
        "songs": songs,
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    out_dir.mkdir(parents=True, exist_ok=True)
    gz_path = out_dir / "rolls.v1.json.gz"
    gz_path.write_bytes(gzip.compress(raw, 9))

    coverage = len(songs) / len(charts) if charts else 0.0
    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "dataVersion": DATA_VERSION,
        "source": SOURCE,
        "formula": {
            "seconds": "60 / BPM起点 * (拍数 - 1/12)",
            "maxHits": "ceil((seconds + 0.001) * 60) 逐条求和",
            "speed": "黄色連打打数 / 合计連打秒数（不含风船）",
        },
        "eseRoot": str(ese_root),
        "mappingReport": str(args.mapping) if args.mapping else "",
        "catalogCharts": len(charts),
        "coveredSongs": len(songs),
        "coverageRatio": round(coverage, 4),
        "songsWithRolls": with_rolls,
        "balloonOnlySongs": balloon_only,
        "songsWithoutLongNotes": no_long,
        "skipped": len(skipped),
        "mergeStats": stats,
        "compressedBytes": gz_path.stat().st_size,
        "rawBytes": len(raw),
    }
    (out_dir / "rolls.manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"黄条 {with_rolls} / 只有风船 {balloon_only} / 无长音 {no_long}；"
        f"秒数来源 {stats}；覆盖率 {coverage*100:.1f}%"
    )
    print(f"已写出 {gz_path.name}（{manifest['compressedBytes']} bytes）与 manifest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
