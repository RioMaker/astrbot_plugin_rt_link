# -*- coding: utf-8 -*-
"""从谱面 wiki 的「極スコア」页抓取每曲天井スコア / 極スコア / 必要連打数，构建スコアランク资源。

用法（在插件根目录）：
    python scripts/build_score_rank.py

产物：
    resource/score_rank.v1.json.gz    按 (song_no, level) 索引的评分门槛数据
    resource/score_rank.manifest.json 版本、来源、覆盖率与字段清单

数据用途：
    - 天井スコア 是「全良（且连打打满可获得完整加成）时的分数上限」，
      也就是该谱面的评价分母：スコアランク = 达成分 / 天井スコア。
    - 極スコア 是「极」之上的最高档门槛（= 天井 + 必要連打数 × 100）。
    - 每个音符的基本点 = 天井スコア / 总音符数，用于把分数缺口换算成「良数」。

注意：本脚本只在构建期联网；插件运行期只读 resource/ 下的压缩资源。
"""

from __future__ import annotations

import argparse
import gzip
import html
import json
import re
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

SCHEMA_VERSION = 2
DATA_VERSION = "2026-09-19.1"

WIKI_BASE = "https://wikiwiki.jp/taiko-fumen/"
WIKI_PAGES = [
    "作品/新AC/極スコア/おに",
    "作品/新AC/極スコア/おに/ナムコオリジナル",
    "作品/新AC/極スコア/おに/サヨナラ曲",
]
SOURCE = WIKI_BASE + urllib.parse.quote("作品/新AC/極スコア/おに")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124 Safari/537.36"
)

# 「裏譜面」标记 → 难度 5；其余为难度 4（おに）。
URA_MARKERS = ("裏譜面", "(裏)", "（裏）")
# 曲名前缀装饰，匹配谱面库时剔除。
TITLE_NOISE = ("【限定】",)


# ---------------------------------------------------------------------------
# 抓取与解析
# ---------------------------------------------------------------------------

def fetch(url: str, timeout: int = 45) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "ja,en;q=0.8"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def _cell_text(raw: str) -> str:
    return html.unescape(re.sub(r"(?s)<[^>]+>", "", raw)).strip()


def _int_first(value: str) -> int | None:
    match = re.search(r"(\d+)", value or "")
    return int(match.group(1)) if match else None


def _int_last(value: str) -> int | None:
    matches = re.findall(r"(\d+)", value or "")
    return int(matches[-1]) if matches else None


def _speed(value: str) -> float | None:
    """从「約17.23打/秒」里取出要求连打速度；非速度单元格返回 None。"""
    match = re.search(r"(\d+(?:\.\d+)?)\s*打\s*/\s*秒", value or "")
    return float(match.group(1)) if match else None


def parse_page(page_html: str) -> list[dict]:
    """解析一页中所有 5 列表格，返回条目列表。"""
    entries: list[dict] = []
    for table in re.findall(r"(?is)<table.*?</table>", page_html):
        genre = None
        for row in re.findall(r"(?is)<tr.*?</tr>", table):
            cells_html = re.findall(r"(?is)<td([^>]*)>(.*?)(?=<td|</tr>)", row)
            if not cells_html:
                continue
            attrs = [item[0] for item in cells_html]
            cells = [_cell_text(item[1]) for item in cells_html]

            # 分区标题行：整行一个单元格。
            if len(cells_html) == 1:
                if cells[0]:
                    genre = cells[0]
                continue
            if len(cells) < 4:
                continue

            title = cells[0]
            if not title or title == "曲名":
                continue
            # 说明/导航类表格的行没有数字，直接跳过。
            ceiling = _int_first(cells[1])
            if ceiling is None or ceiling < 100000:
                continue

            entry = {
                "genre": genre or "",
                "raw_title": title,
                "ceiling": ceiling,
                "level": 5 if any(m in title for m in URA_MARKERS) else 4,
            }
            # 要求連打速度：wiki 表里由「必要連打数 ÷ 合计黄色連打秒数」算出，
            # 用来和 ESE 谱面解析出的秒数交叉校验（見 scripts/build_rolls.py）。
            speed = None
            for cell in cells[3:]:
                speed = speed or _speed(cell)
            if 'colspan="2"' in attrs[1]:
                # 精度曲 / 完全精度曲：极スコア与天井スコア相同，且不需要连打。
                entry.update(top_lo=ceiling, top_hi=ceiling, rolls_lo=0, rolls_hi=0,
                             kind=cells[3] if len(cells) > 3 else "")
            else:
                entry.update(
                    top_lo=_int_first(cells[2]) if len(cells) > 2 else None,
                    top_hi=_int_last(cells[2]) if len(cells) > 2 else None,
                    rolls_lo=_int_first(cells[3]) if len(cells) > 3 else None,
                    rolls_hi=_int_last(cells[3]) if len(cells) > 3 else None,
                    kind="",
                )
            entry["speed"] = speed
            if entry["top_lo"] in (0, None):
                # 极スコア缺失或标 0：退化为天井スコア。
                entry["top_lo"] = entry["top_hi"] = ceiling
            entries.append(entry)
    return entries


def scrape(verbose: bool = True) -> list[dict]:
    entries: list[dict] = []
    for page in WIKI_PAGES:
        url = WIKI_BASE + urllib.parse.quote(page)
        try:
            page_html = fetch(url)
        except Exception as error:  # noqa: BLE001 - 构建期直接报告并跳过
            if verbose:
                print(f"  跳过 {page}：{error}")
            continue
        found = parse_page(page_html)
        if verbose:
            print(f"  {page}: {len(found)} 条")
        entries.extend(found)
    if not entries:
        raise SystemExit("没有从任何页面解析到数据，可能页面结构已变化。")
    return entries


# ---------------------------------------------------------------------------
# 与谱面库匹配
# ---------------------------------------------------------------------------

def norm_title(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").casefold()
    for junk in URA_MARKERS:
        text = text.replace(unicodedata.normalize("NFKC", junk).casefold(), "")
    for junk in TITLE_NOISE:
        text = text.replace(unicodedata.normalize("NFKC", junk).casefold(), "")
    return re.sub(r"[^0-9a-z一-龥ぁ-んァ-ヶ]+", "", text)


def load_charts(path: Path) -> list[dict]:
    raw = path.read_bytes()
    if path.suffix == ".gz":
        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def build_index(charts: list[dict]) -> dict[str, set[tuple[int, int]]]:
    index: dict[str, set[tuple[int, int]]] = {}
    for chart in charts:
        for key in ("titleJa", "title"):
            value = chart.get(key)
            if value:
                index.setdefault(norm_title(value), set()).add((chart["id"], chart["level"]))
    return index


def match(entries: list[dict], index: dict[str, set[tuple[int, int]]]) -> tuple[dict, dict]:
    songs: dict[str, dict] = {}
    stats = {"matched": 0, "ambiguous": 0, "missing": 0, "dropped_songs": 0}
    for entry in entries:
        candidates = index.get(norm_title(entry["raw_title"]), set())
        exact = [item for item in candidates if item[1] == entry["level"]]
        if len(exact) != 1:
            if candidates:
                stats["ambiguous"] += 1
            else:
                stats["missing"] += 1
                stats["dropped_songs"] += 1
            continue
        song_no, level = exact[0]
        record = {
            "ceiling": entry["ceiling"],
            "top": entry["top_lo"],
            "rolls": entry["rolls_lo"],
        }
        if entry.get("speed"):
            record["speed"] = entry["speed"]
        if entry["top_hi"] is not None and entry["top_hi"] != entry["top_lo"]:
            record["topMax"] = entry["top_hi"]
        if entry["rolls_hi"] is not None and entry["rolls_hi"] != entry["rolls_lo"]:
            record["rollsMax"] = entry["rolls_hi"]
        if entry["kind"]:
            record["kind"] = entry["kind"]
        prefix = f"{song_no}|{level}"
        if prefix in songs:
            stats["ambiguous"] += 1
            continue
        songs[prefix] = record
        stats["matched"] += 1
    return songs, stats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--charts", default=None, help="谱面库路径（默认 resource/charts.v1.json.gz）")
    parser.add_argument("--out-dir", default=None, help="输出目录（默认插件 resource/）")
    parser.add_argument("--offline", default=None, help="改用本地已保存的 wiki HTML 目录，不联网")
    args = parser.parse_args()

    plugin_dir = Path(__file__).resolve().parent.parent
    out_dir = Path(args.out_dir) if args.out_dir else plugin_dir / "resource"
    charts_path = Path(args.charts) if args.charts else out_dir / "charts.v1.json.gz"
    charts = load_charts(charts_path)

    print(f"谱面库：{len(charts)} 条（{charts_path}）")
    if args.offline:
        offline_dir = Path(args.offline)
        entries = []
        for page in WIKI_PAGES:
            path = offline_dir / (page.replace("/", "_") + ".html")
            if path.exists():
                found = parse_page(path.read_text(encoding="utf-8"))
                print(f"  {page}: {len(found)} 条")
                entries.extend(found)
    else:
        print("抓取 wiki：")
        entries = scrape()
    print(f"wiki 条目：{len(entries)}")

    songs, stats = match(entries, build_index(charts))
    coverage = len(songs) / len(charts) if charts else 0.0
    print(
        f"匹配：{stats['matched']} 条 → {len(songs)} 个谱面；"
        f"歧义/难度不符 {stats['ambiguous']}；wiki 未收录于谱面库 {stats['missing']}"
    )
    print(f"谱面库覆盖率：{len(songs)}/{len(charts)} = {coverage*100:.1f}%")

    payload = {
        "schema_version": SCHEMA_VERSION,
        "data_version": DATA_VERSION,
        "source": SOURCE,
        "note": (
            "ceiling=天井スコア，top=極スコア，rolls=达到极所需的黄色連打打数，"
            "speed=wiki 给出的极要求連打速度（打/秒，必要連打数 ÷ 合计黄色連打秒数）"
        ),
        "songs": songs,
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    out_dir.mkdir(parents=True, exist_ok=True)
    gz_path = out_dir / "score_rank.v1.json.gz"
    gz_path.write_bytes(gzip.compress(raw, 9))

    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "dataVersion": DATA_VERSION,
        "source": SOURCE,
        "catalogCharts": len(charts),
        "matchedSongs": len(songs),
        "coverageRatio": round(coverage, 4),
        "wikiEntries": len(entries),
        "unmatchedWikiEntries": stats["missing"],
        "ambiguousEntries": stats["ambiguous"],
        "songsWithSpeed": sum(1 for record in songs.values() if record.get("speed")),
        "fields": ["ceiling", "top", "topMax", "rolls", "rollsMax", "kind", "speed"],
        "compressedBytes": gz_path.stat().st_size,
        "rawBytes": len(raw),
    }
    (out_dir / "score_rank.manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"已写出 {gz_path.name}（{manifest['compressedBytes']} bytes）与 manifest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
