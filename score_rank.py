# -*- coding: utf-8 -*-
"""スコアランク（成绩评价）门槛数据与「提升评价」候选曲目分析。

算分公式（AC16 ニジイロ～，来源与推导见 resource/score_rank.manifest.json）：

    スコア = 良 × 基本点 + 可 × ⌊基本点 / 2⌋ + 黄色連打打数 × 100
    基本点 = 天井スコア ÷ 总音符数     （每谱固定、10 的整数倍）
    天井スコア = 全良且连打打满时的分数上限，约 1,000,000（各曲 98.4 万 ~ 100.5 万）
    極スコア  = 天井スコア + 必要連打打数 × 100

評価（スコアランク）门槛按「达成分 ÷ 天井スコア」的比例设定：

    1 无          < 50%
    2 白粹        ≥ 50%
    3 银粹        ≥ 60%
    4 金雅        ≥ 70%
    5 粉雅        ≥ 80%
    6 紫雅        ≥ 90%
    7 极          ≥ 95%
    8 极+连打满    ≥ 極スコア（全良 + 该谱规定打数的黄色连打）

本模块为纯计算实现，只依赖标准库；AstrBot 解耦，可独立测试。
"""

from __future__ import annotations

import gzip
import json
import math
import unicodedata
from pathlib import Path

SCORE_RANK_SCHEMA_VERSION = 1

# 每个黄色連打打数的固定得分（ニジイロ配点）。
ROLL_UNIT = 100

# 评价名称与分数门槛。
#
# 门槛是**绝对分数**，与该谱的天井スコア无关 —— 这一点由实测数据确定：
# 各档之间的分数空隙精确跨过 50/60/70/80/90/95 万（下档最高分 472900 → 上档最低分 512890 等），
# 而若按「天井 × 比例」解释，2 档最低分 512890 将要求该谱天井 ≥ 1025780，
# 远超 wiki 的设定量级（天井スコア 设计为「接近 100 万」，全库最高约 100.8 万），因此比例模型不成立。
# rank 8 没有固定门槛：要求达到该谱自己的極スコア。
SCORE_RANK_NAMES = {
    1: "无",
    2: "白粹",
    3: "银粹",
    4: "金雅",
    5: "粉雅",
    6: "紫雅",
    7: "极",
    8: "极+连打满",
}
SCORE_RANK_BORDERS = {
    2: 500_000,
    3: 600_000,
    4: 700_000,
    5: 800_000,
    6: 900_000,
    7: 950_000,
}
SCORE_RANK_MIN = 1
SCORE_RANK_MAX = 8

# 名称别名（含日文写法、罗马字与常见简写），用于命令与 LLM 参数解析。
SCORE_RANK_ALIASES = {
    1: {"1", "无", "無", "なし", "none", "未达成"},
    2: {"2", "白粹", "白粋", "shirosui", "しろすい"},
    3: {"3", "银粹", "銀粹", "銀粋", "ginsui", "ぎんすい"},
    4: {"4", "金雅", "kinga", "きんが"},
    5: {"5", "粉雅", "funga", "ふんが"},
    6: {"6", "紫雅", "shiga", "しが"},
    7: {"7", "极", "極", "kiwami", "きわみ"},
    8: {"8", "极+连打满", "极满", "極+連打満", "全良", "kiwami_full", "極スコア"},
}

# 谱面库覆盖不到的曲目（以及 wiki 未收录的曲目）用估算值兜底：
# 基本点取 100 万 ÷ 总音符数 最近的 10 的整数倍。
ESTIMATE_TOTAL_SCORE = 1_000_000


class ScoreRankDataError(ValueError):
    """スコアランク静态资源格式错误。"""


# ---------------------------------------------------------------------------
# 资源加载
# ---------------------------------------------------------------------------

def load_score_rank(path, charts: dict | None = None) -> dict:
    """加载并校验 resource/score_rank.v1.json.gz。

    返回 {schema_version, data_version, source, songs, by_genre, catalog_charts}。
    songs 以 "song_no|level" 为键。
    """
    raw = Path(path).read_bytes()
    if str(path).endswith(".gz"):
        raw = gzip.decompress(raw)
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ScoreRankDataError("评分资源根节点必须是对象")
    if payload.get("schema_version") != SCORE_RANK_SCHEMA_VERSION:
        raise ScoreRankDataError(f"不支持的评分资源版本：{payload.get('schema_version')}")

    songs = payload.get("songs")
    if not isinstance(songs, dict):
        raise ScoreRankDataError("评分资源缺少 songs")

    cleaned: dict[str, dict] = {}
    for key, value in songs.items():
        if not isinstance(value, dict):
            raise ScoreRankDataError(f"评分条目必须是对象：{key}")
        song_no_text, _, level_text = str(key).partition("|")
        if not song_no_text.isdigit() or not level_text.isdigit():
            raise ScoreRankDataError(f"评分条目的键格式无效：{key}")
        level = int(level_text)
        if level not in (4, 5):
            raise ScoreRankDataError(f"评分条目难度必须为 4 或 5：{key}")
        ceiling = value.get("ceiling")
        if not isinstance(ceiling, int) or ceiling <= 0:
            raise ScoreRankDataError(f"天井スコア无效：{key}")
        top = value.get("top")
        if top is None:
            top = ceiling
        if not isinstance(top, int) or top < ceiling:
            # 极スコア不可能低于天井スコア；出现时按天井处理，避免算出不可达门槛。
            top = ceiling
        rolls = value.get("rolls")
        rolls = rolls if isinstance(rolls, int) and rolls >= 0 else 0
        cleaned[key] = {
            "ceiling": ceiling,
            "top": top,
            "topMax": value.get("topMax") if isinstance(value.get("topMax"), int) else None,
            "rolls": rolls,
            "rollsMax": value.get("rollsMax") if isinstance(value.get("rollsMax"), int) else None,
            "kind": value.get("kind") or "",
        }

    by_genre: dict[str, list] = {}
    if charts:
        for (song_no, level), chart in charts.items():
            entry = cleaned.get(f"{song_no}|{level}")
            if entry is None:
                continue
            genre = chart.get("genre") or "未知"
            by_genre.setdefault(genre, []).append(song_no)

    return {
        "schema_version": payload.get("schema_version"),
        "data_version": payload.get("data_version") or "unknown",
        "source": payload.get("source") or "",
        "songs": cleaned,
        "by_genre": by_genre,
        "catalog_charts": len(charts) if charts else 0,
    }


def empty_score_rank() -> dict:
    """评分资源不可用时的空表；此时全部曲目走估算门槛。"""
    return {
        "schema_version": SCORE_RANK_SCHEMA_VERSION,
        "data_version": "unavailable",
        "source": "",
        "songs": {},
        "by_genre": {},
        "catalog_charts": 0,
    }


# ---------------------------------------------------------------------------
# 评价解析
# ---------------------------------------------------------------------------

def parse_score_rank(text) -> int | None:
    """把评价名称/数字解析为 1-8；无法识别返回 None。"""
    if text is None:
        return None
    value = unicodedata.normalize("NFKC", str(text)).strip().lower()
    if not value:
        return None
    for rank, names in SCORE_RANK_ALIASES.items():
        if value in {unicodedata.normalize("NFKC", name).lower() for name in names}:
            return rank
    if value.isdigit():
        number = int(value)
        return number if SCORE_RANK_MIN <= number <= SCORE_RANK_MAX else None
    return None


def score_rank_name(rank) -> str:
    return SCORE_RANK_NAMES.get(rank, f"评价{rank}")


def score_rank_label(rank) -> str:
    """给 LLM/用户看的带档位说明的名称，例如「4·金雅（门槛 700000 分）」。"""
    name = score_rank_name(rank)
    border = SCORE_RANK_BORDERS.get(rank)
    if border is None:
        return f"{rank}·{name}（门槛为该谱極スコア）"
    return f"{rank}·{name}（门槛 {border} 分）"


# ---------------------------------------------------------------------------
# 单谱门槛
# ---------------------------------------------------------------------------

def song_unit(song: dict | None, total_notes: int) -> tuple[int, int, bool]:
    """返回 (天井スコア, 基本点, 是否精确)。

    精确值来自 wiki 极スコア表；缺失时按「基本点 = 100 万 ÷ 总音符数」取 10 的整数倍估算。
    """
    notes = int(total_notes or 0)
    if notes <= 0:
        return 0, 0, False
    if song:
        ceiling = int(song["ceiling"])
        # wiki 天井 / 总音符数 才是该谱的真实基本点，吸附到 10 的整数倍。
        unit = int(round(ceiling / notes / 10.0) * 10)
        # 一致性校验：天井スコア 必须与该谱音符数量级吻合（约 100 万）。
        # 若不吻合说明 wiki 条目与谱面库错配（例如分岐谱面），此时宁可退回估算。
        expected = ESTIMATE_TOTAL_SCORE / notes
        if unit > 0 and abs(unit - expected) <= 0.03 * expected:
            return ceiling, unit, True
    unit = max(10, int(round(ESTIMATE_TOTAL_SCORE / notes / 10.0) * 10))
    return unit * notes, unit, False


def rank_threshold(song: dict | None, total_notes: int, rank: int) -> dict:
    """返回该谱达到指定评价所需的分数、基本点与连打要求。

    rank 2-7 是固定的绝对分数门槛，与谱面无关；rank 8 的门槛是该谱的極スコア
    （天井スコア + 规定连打打数 × 100），并要求全良。
    """
    ceiling, unit, exact = song_unit(song, total_notes)
    if ceiling <= 0:
        return {"score": None, "ceiling": 0, "unit": 0, "rolls": None, "exact": False}

    if rank >= SCORE_RANK_MAX:
        score = int(song["top"]) if song else ceiling
        rolls = int(song["rolls"]) if song else 0
        return {
            "score": score,
            "ceiling": ceiling,
            "unit": unit,
            "rolls": rolls,
            "requiresAllGood": True,
            "exact": exact and song is not None,
        }

    border = SCORE_RANK_BORDERS.get(rank)
    if border is None:
        return {"score": None, "ceiling": ceiling, "unit": unit, "rolls": None, "exact": exact}
    return {
        "score": int(border),
        "ceiling": ceiling,
        "unit": unit,
        "rolls": 0,
        "requiresAllGood": False,
        "exact": True,
    }


def rank_of_score(song: dict | None, total_notes: int, score: int) -> int:
    """按分数反推评价等级 1-8。"""
    ceiling, _, _ = song_unit(song, total_notes)
    if score is None:
        return 0
    top = int(song["top"]) if song else ceiling
    if top and score >= top:
        return 8
    for rank in range(7, 1, -1):
        if score >= SCORE_RANK_BORDERS[rank]:
            return rank
    return 1


# ---------------------------------------------------------------------------
# 「提升评价」候选分析
# ---------------------------------------------------------------------------

def _to_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def analyze_rank_improvements(
    records: list,
    charts: dict,
    rank_data: dict,
    target_rank: int,
    levels: tuple = (4, 5),
    per_genre: int = 5,
    gap_limit_ratio: float = 0.0,
) -> dict:
    """找出「离目标评价最近」的谱面，并按分区聚合。

    charts: {(song_no, level): chart}，提供 totalNotes 与 genre。
    records: analyze() 的 records（含 highScore / bestScoreRank / 良可不可 / 连打）。
    gap_limit_ratio: 只保留分数缺口不超过天井该比例的谱面（0 表示不限）。

    每首候选曲目给出：
      - 目标分数 targetScore 与还需提升的 gap
      - okToGood：把这么多个「可」打成「良」即可（等效换算，按基本点计）
      - ngToGood：若「可」不够用，还需把这么多个「不可」打成「良」
      - rollsNeeded：或者改为补这么多打黄色连打
    """
    songs = rank_data.get("songs") or {}
    candidates = []
    scanned = already = unknown = 0
    exact_count = 0

    for record in records:
        level = record.get("level")
        if level not in levels:
            continue
        chart = charts.get((record.get("id"), level))
        if not chart:
            continue
        total_notes = _to_int(chart.get("totalNotes"))
        if total_notes <= 0:
            continue
        scanned += 1
        song = songs.get(f"{record.get('id')}|{level}")
        threshold = rank_threshold(song, total_notes, target_rank)
        target_score = threshold["score"]
        if not target_score:
            unknown += 1
            continue

        current_score = _to_int(record.get("highScore"))
        # 游戏返回的 best_score_rank 才是权威评价；本地门槛只是用来推算还需要多少分。
        # 两者冲突时以游戏为准，否则会出现「游戏里已经是紫雅、这里还说没到」的自相矛盾。
        api_rank = _to_int(record.get("bestScoreRank"))
        if api_rank >= target_rank or current_score >= target_score:
            already += 1
            continue

        gap = target_score - current_score
        ceiling = threshold["ceiling"]
        unit = threshold["unit"] or 1
        if gap_limit_ratio and gap > ceiling * gap_limit_ratio:
            continue

        ok_count = _to_int(record.get("okCount"))
        ng_count = _to_int(record.get("ngCount"))
        requires_all_good = bool(threshold.get("requiresAllGood"))
        target_rolls = threshold.get("rolls") or 0

        if requires_all_good:
            # 最高档（极+连打满）只能全良到达：先把残留的「可」「不可」全部打成「良」，
            # 再补足该谱规定的黄色连打打数。两者是「且」的关系，不是二选一。
            ok_to_good, ng_to_good = ok_count, ng_count
            rolls_needed = target_rolls
            rolls_alternative = False
        else:
            # 一个「可 → 良」增加半个基本点，因此所需良数 = ⌈2 × 分数缺口 ÷ 基本点⌉。
            ok_to_good = int(math.ceil(2 * gap / unit)) if unit else 0
            ng_to_good = 0
            if ok_to_good > ok_count:
                remainder = gap - ok_count * (unit / 2.0)
                ng_to_good = int(math.ceil(remainder / unit)) if unit else 0
            # 另一条路：不动判定，改靠黄色连打（每打固定 100 分）补足缺口。
            rolls_needed = int(math.ceil(gap / ROLL_UNIT))
            rolls_alternative = True

        if threshold["exact"]:
            exact_count += 1

        candidates.append({
            "id": record.get("id"),
            "level": level,
            "title": record.get("title") or f"Song {record.get('id')}",
            "titleJa": record.get("titleJa"),
            "genre": chart.get("genre") or "未知",
            "constant": record.get("constant"),
            "rating": record.get("rating"),
            "totalNotes": total_notes,
            "ceiling": ceiling,
            "currentScore": current_score,
            "currentRank": _to_int(record.get("bestScoreRank")) or rank_of_score(song, total_notes, current_score),
            "targetScore": target_score,
            "gap": gap,
            "gapRatio": round(gap / ceiling, 4) if ceiling else 0.0,
            "okToGood": ok_to_good,
            "ngToGood": ng_to_good,
            "rollsNeeded": rolls_needed,
            "rollsAlternative": rolls_alternative,
            "okCount": ok_count,
            "ngCount": ng_count,
            "goodCount": _to_int(record.get("goodCount")),
            "poundCount": _to_int(record.get("poundCount")),
            "pathRequiresAllGood": requires_all_good,
            "targetRolls": target_rolls,
            "exact": bool(threshold["exact"]),
        })

    for item in candidates:
        item["currentRankName"] = score_rank_name(item["currentRank"])

    candidates.sort(key=lambda item: (item["gap"], -(item["rating"] or 0)))

    genres: dict[str, list] = {}
    for item in candidates:
        genres.setdefault(item["genre"], []).append(item)
    genre_rows = [
        {
            "genre": genre,
            "count": len(items),
            "closest": items[:per_genre],
            "gapMedian": sorted(i["gap"] for i in items)[len(items) // 2],
        }
        for genre, items in genres.items()
    ]
    genre_rows.sort(key=lambda row: (row["gapMedian"], -row["count"]))

    return {
        "targetRank": target_rank,
        "targetName": score_rank_name(target_rank),
        "targetBorder": SCORE_RANK_BORDERS.get(target_rank),
        "scanned": scanned,
        "alreadyAtTarget": already,
        "unavailable": unknown,
        "candidateCount": len(candidates),
        "exactCount": exact_count,
        "genres": genre_rows,
        "items": candidates,
    }
