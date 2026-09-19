# -*- coding: utf-8 -*-
"""スコアランク（成绩评价）门槛数据与「提升评价」候选曲目分析。

算分公式（AC16 ニジイロ～，来源与推导见 resource/score_rank.manifest.json）：

    スコア = 良 × 基本点 + 可 × ⌊基本点 / 2⌋ + 黄色連打打数 × 100
    基本点 = 天井スコア ÷ 总音符数     （每谱固定、10 的整数倍）
    天井スコア = 全良且连打打满时的分数上限，约 1,000,000（各曲 98.5 万 ~ 100.8 万）
    極スコア  = 天井スコア + 必要連打打数 × 100   （「必要連打打数」是全良前提下的参考值）

評価（スコアランク）共 8 档，门槛是该谱**極スコア**的固定比例，比较值是**总分数**：

    1 无          < 50%  極スコア
    2 白粹        ≥ 50%
    3 铜粹        ≥ 60%
    4 银粹        ≥ 70%
    5 金雅        ≥ 80%
    6 粉雅        ≥ 90%
    7 紫雅        ≥ 95%
    8 极          ≥ 100%（即 極スコア 本身）

锚点是 極スコア（＝天井スコア + 必要連打打数 × 100），**不是**天井スコア。
由于 極スコア ≈ 100 万（各曲约 99.75 ~ 101.1 万），这套门槛在数值上接近
「50/60/…/95 万」，但各曲之间有 ±1% 的浮动；用固定绝对值会造成约 1.6% 的错判，
用「極スコア × 比例」则只剩 0.14%（1390 条实测记录；wiki 子集 1341 条零错判）。

「极」**不要求全良**：極スコア 是分数门槛，黄条每打固定 100 分，
判定上留下的「可」可以用多打连打补回来。

连打（黄色連打）相关规则来自同一份 wiki 的「連打秒数表」：

    連打秒数   = 60 ÷ BPM起点 × (拍数 - 1/12)      （黄色連打比拍数短 1/12 拍）
    連打速度   = 黄色連打打数 ÷ 合计連打秒数        （风船连打不计入）
    連打理論値 = ⌈(連打秒数 + 0.001) × 60⌉          （即每秒最多约 60 打）

也就是说：某张谱面的黄条总长（合計連打秒数）是固定的，想把分数补上去就得在这些
黄条里多打进若干打，平均秒速就是「总打数 ÷ 合计秒数」。风船（風船連打）的打数与
秒数都不参与秒速计算。

本模块为纯计算实现，只依赖标准库；AstrBot 解耦，可独立测试。
"""

from __future__ import annotations

import gzip
import json
import math
import unicodedata
from pathlib import Path

SCORE_RANK_SCHEMA_VERSION = 2
# 兼容早期的 schema 1 资源（缺少 speed 字段时按未知处理）。
SUPPORTED_SCHEMA_VERSIONS = (1, 2)

# 每个黄色連打打数的固定得分（ニジイロ配点）。
ROLL_UNIT = 100

# 連打理論値：单位换算上限，即每打最快 1/60 秒 → 每秒最多约 60 打。
ROLL_THEORY_HIT_RATE = 60

# おに 谱面拿「极」时要求连打速度的常见区间（wiki 实测约 16.6 ~ 18 打/秒）。
KIWAMI_SPEED_RANGE = (16.6, 18.0)

# 风船打数缺失时的估算基准：おに 常规秒速中值。
BALLOON_NOMINAL_SPEED = 17.0

# 评价名称与门槛比例。
#
# 门槛 = **该谱極スコア × 比例**，比较值是**总分数**（含黄色连打）。
# 锚点是 極スコア 而不是天井スコア —— 这一点由 1390 条实测记录确定：
#   基准=極スコア + 比例 + 总分数        → 错判 2 / 1390（wiki 子集 1341 条零错判）
#   基准=天井スコア + 比例 + 总分数      → 错判 24
#   固定绝对值 50/60/…/95 万 + 总分数    → 错判 22
#   任何「扣除连打后再比」的变体         → 错判 156 ~ 245
# 各档的「分数 ÷ 極スコア」分布零重叠，边界精确落在整数百分比上
# （金雅下界 80.007%、粉雅 90.001%、紫雅 95.003%、极 100.000%）。
#
# 八档：无 → 白粹 → 铜粹 → 银粹 → 金雅 → 粉雅 → 紫雅 → 极。
# 注意第 3 档是「铜粹」，不要与第 4 档「银粹」写反。
SCORE_RANK_NAMES = {
    1: "无",
    2: "白粹",
    3: "铜粹",
    4: "银粹",
    5: "金雅",
    6: "粉雅",
    7: "紫雅",
    8: "极",
}
SCORE_RANK_RATIOS = {
    2: 0.50,
    3: 0.60,
    4: 0.70,
    5: 0.80,
    6: 0.90,
    7: 0.95,
    8: 1.00,
}
SCORE_RANK_MIN = 1
SCORE_RANK_MAX = 8

# 名称别名（含日文写法、罗马字与常见简写），用于命令与 LLM 参数解析。
SCORE_RANK_ALIASES = {
    1: {"1", "无", "無", "なし", "none", "未达成"},
    2: {"2", "白粹", "白粋", "shirosui", "しろすい"},
    3: {"3", "铜粹", "銅粹", "铜粋", "銅粋", "dousui", "どうすい"},
    4: {"4", "银粹", "銀粹", "银粋", "銀粋", "ginsui", "ぎんすい"},
    5: {"5", "金雅", "kinga", "きんが"},
    6: {"6", "粉雅", "funga", "ふんが"},
    7: {"7", "紫雅", "shiga", "しが"},
    8: {"8", "极", "極", "kiwami", "きわみ", "極スコア", "极满", "极+连打满"},
}

# 谱面库覆盖不到的曲目（以及 wiki 未收录的曲目）用估算值兜底：
# 基本点取 100 万 ÷ 总音符数 最近的 10 的整数倍，该估算值同时充当極スコア 锚点。
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
    if payload.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS:
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
        speed = value.get("speed")
        speed = float(speed) if isinstance(speed, (int, float)) and speed > 0 else None
        cleaned[key] = {
            "ceiling": ceiling,
            "top": top,
            "topMax": value.get("topMax") if isinstance(value.get("topMax"), int) else None,
            "rolls": rolls,
            "rollsMax": value.get("rollsMax") if isinstance(value.get("rollsMax"), int) else None,
            "kind": value.get("kind") or "",
            "speed": speed,
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
    """给 LLM/用户看的带档位说明的名称，例如「5·金雅（門槛為極スコア的 80%）」。"""
    name = score_rank_name(rank)
    ratio = SCORE_RANK_RATIOS.get(rank)
    if ratio is None:
        return f"{rank}·{name}"
    if ratio >= 1.0:
        return f"{rank}·{name}（門槛為該譜極スコア）"
    return f"{rank}·{name}（門槛為該譜極スコア的 {ratio*100:.0f}%）"


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


def kiwami_anchor(song: dict | None, ceiling: int) -> int:
    """该谱的 極スコア 锚点 —— 八档门槛都是它的固定比例。

    有 wiki 数据时用实测的 極スコア；否则用估算天井（≈100 万）顶替。

    注意这里**不要**再乘「極スコア ÷ 天井スコア」的中位比例（实测 1.00411）：
    估算天井本身已经是按「≈100 万」标的，再乘一次会把门槛整体推高 0.4%，
    实测错判反而从 2 条增加到 6 条。
    """
    if song:
        return int(song["top"])
    return int(ceiling)


def rank_threshold(song: dict | None, total_notes: int, rank: int) -> dict:
    """返回该谱达到指定评价所需的分数、基本点与连打参考值。

    八档统一为「该谱極スコア × 比例」：50 / 60 / 70 / 80 / 90 / 95 / 100%。
    最高档（100%）就是極スコア 本身。

    注意「极」**不要求全良**：極スコア 是一个分数门槛，黄条每打固定 100 分，
    判定上留下的「可」可以用多打连打补回来。`rolls` 只是「全良时所需的连打打数」，
    作为参考值返回。
    """
    ceiling, unit, exact = song_unit(song, total_notes)
    if ceiling <= 0:
        return {"score": None, "ceiling": 0, "unit": 0, "rolls": None, "anchor": 0, "exact": False}

    anchor = kiwami_anchor(song, ceiling)
    rolls = int(song["rolls"]) if song else 0
    ratio = SCORE_RANK_RATIOS.get(rank)
    if ratio is None or anchor <= 0:
        return {"score": None, "ceiling": ceiling, "unit": unit, "rolls": rolls,
                "anchor": anchor, "exact": exact}
    return {
        "score": int(math.ceil(anchor * ratio)),
        "ceiling": ceiling,
        "unit": unit,
        "rolls": rolls,
        "anchor": anchor,
        "exact": exact,
    }


def rank_of_score(song: dict | None, total_notes: int, score: int) -> int:
    """按分数反推评价等级 1-8。"""
    if score is None:
        return 0
    ceiling, _, _ = song_unit(song, total_notes)
    anchor = kiwami_anchor(song, ceiling)
    if anchor <= 0:
        return 0
    for rank in range(SCORE_RANK_MAX, 1, -1):
        if score >= math.ceil(anchor * SCORE_RANK_RATIOS[rank]):
            return rank
    return 1


# ---------------------------------------------------------------------------
# 连打资源（合計連打秒数 / 理論値）与「补连打」路线
# ---------------------------------------------------------------------------

def empty_rolls() -> dict:
    """连打资源不可用时的空表；此时连打路线一律按「资料缺失」处理。"""
    return {
        "schema_version": 1,
        "data_version": "unavailable",
        "source": "",
        "songs": {},
        "catalog_charts": 0,
    }


def load_rolls(path, charts: dict | None = None) -> dict:
    """加载并校验 resource/rolls.v1.json.gz。

    每个谱面条目：
        seconds        黄色連打合计秒数（不含风船）
        rolls          黄色连打条数
        maxHits        連打理論値合计（Σ⌈(秒数+0.001)×60⌉）
        balloonSeconds 风船连打合计秒数（仅作参考，不参与秒速）
        balloons       风船个数
        balloonHits    风船需要打进的总打数（用于从结算连打数里扣除）
        speed          wiki 给出的「极」要求连打速度（打/秒，可选）
        source         seconds 的来源：tja（谱面解析）/ wiki（用要求速度反推）
    """
    raw = Path(path).read_bytes()
    if str(path).endswith(".gz"):
        raw = gzip.decompress(raw)
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ScoreRankDataError("连打资源根节点必须是对象")
    if payload.get("schema_version") != 1:
        raise ScoreRankDataError(f"不支持的连打资源版本：{payload.get('schema_version')}")

    songs = payload.get("songs")
    if not isinstance(songs, dict):
        raise ScoreRankDataError("连打资源缺少 songs")

    cleaned: dict[str, dict] = {}
    for key, value in songs.items():
        if not isinstance(value, dict):
            raise ScoreRankDataError(f"连打条目必须是对象：{key}")
        song_no_text, _, level_text = str(key).partition("|")
        if not song_no_text.isdigit() or not level_text.isdigit():
            raise ScoreRankDataError(f"连打条目的键格式无效：{key}")
        seconds = value.get("seconds")
        seconds = float(seconds) if isinstance(seconds, (int, float)) and seconds > 0 else 0.0
        item = {
            "seconds": seconds,
            "rolls": _to_int(value.get("rolls")),
            "maxHits": _to_int(value.get("maxHits")),
            "balloonSeconds": float(value.get("balloonSeconds") or 0.0),
            "balloons": _to_int(value.get("balloons")),
            "balloonHits": _to_int(value.get("balloonHits")),
            "speed": float(value["speed"]) if isinstance(value.get("speed"), (int, float)) else None,
            "source": str(value.get("source") or ""),
        }
        if item["rolls"] and seconds <= 0:
            # 有黄条却没有秒数：无法算秒速，按未收录处理。
            item["seconds"] = 0.0
        if item["seconds"] and item["maxHits"] <= 0:
            item["maxHits"] = theoretical_hits(item["seconds"])
        cleaned[key] = item

    return {
        "schema_version": payload.get("schema_version"),
        "data_version": payload.get("data_version") or "unknown",
        "source": payload.get("source") or "",
        "songs": cleaned,
        "catalog_charts": len(charts) if charts else 0,
    }


def theoretical_hits(seconds: float) -> int:
    """連打理論値 上限：⌈(秒数 + 0.001) × 60⌉（多本连打要逐本取整后再相加）。"""
    return int(math.ceil((float(seconds or 0) + 0.001) * ROLL_THEORY_HIT_RATE))


def roll_entry(rolls_data: dict | None, song_no, level) -> dict | None:
    """取某谱面的连打资料；没有则返回 None。"""
    if not rolls_data:
        return None
    return (rolls_data.get("songs") or {}).get(f"{song_no}|{level}")


def judgment_plan(gap: int, unit: int, ok_count: int, ng_count: int) -> dict:
    """判定路线：把缺口换算成「可 → 良」与「不可 → 良」，并判断是否必须全良。

    - 一个「可 → 良」补半个基本点，一个「不可 → 良」补一个基本点。
    - `requiresAllGood`：只靠判定达到目标时，现有的「可」和「不可」必须全部打成良，
      也就是这张谱必须全良。
    - `covers`：判定路线的分数上限（全良）是否够补上缺口。
    """
    gap = max(0, int(gap or 0))
    unit = int(unit or 0)
    ok_count = max(0, int(ok_count or 0))
    ng_count = max(0, int(ng_count or 0))
    if gap <= 0:
        return {"okToGood": 0, "ngToGood": 0, "requiresAllGood": False, "covers": True,
                "maxGain": ok_count * unit / 2.0 + ng_count * unit}
    if unit <= 0:
        return {"okToGood": 0, "ngToGood": 0, "requiresAllGood": False, "covers": False,
                "maxGain": 0.0}
    ok_to_good = int(math.ceil(2 * gap / unit))
    ng_to_good = 0
    if ok_to_good > ok_count:
        remainder = gap - ok_count * (unit / 2.0)
        ng_to_good = int(math.ceil(remainder / unit))
    max_gain = ok_count * unit / 2.0 + ng_count * unit
    # 「必须全良」= 现有的「可」和「不可」得一个不留地全打成良（本来就没有可/不可时不算）。
    all_good_needed = bool(ok_count or ng_count) and ok_to_good >= ok_count and ng_to_good >= ng_count
    return {
        "okToGood": ok_to_good,
        "ngToGood": ng_to_good,
        "requiresAllGood": all_good_needed,
        "covers": max_gain + 1e-9 >= gap,
        "maxGain": max_gain,
    }


def roll_plan(
    entry: dict | None,
    gap: int,
    pound_count: int = 0,
    ceiling: int = 0,
) -> dict:
    """连打路线：还差几打、总连打数、要求秒速、是否打得出来。

    - `hitsNeeded`：⌈缺口 ÷ 100⌉，即需要多打进几打黄色连打。
    - `currentHits`：本局已有的黄色连打打数（= 结算连打数 − 风船打数）。
    - `totalHits`：补分后这一局的黄色连打总打数。
    - `speed`：totalHits ÷ 合計連打秒数（按 wiki 规定，风船不计入）。
    - `feasible`：totalHits 是否在該谱的連打理論値以内。
    """
    gap = max(0, int(gap or 0))
    hits_needed = int(math.ceil(gap / ROLL_UNIT)) if gap > 0 else 0
    plan = {
        "known": bool(entry),
        "hasRolls": False,
        "rollCount": 0,
        "seconds": 0.0,
        "maxHits": 0,
        "balloons": 0,
        "balloonSeconds": 0.0,
        "balloonHits": 0,
        "hitsNeeded": hits_needed,
        "currentHits": 0,
        "totalHits": 0,
        "speed": None,
        "speedRaw": None,
        "kiwamiSpeed": None,
        "feasible": False,
        "shortfall": 0,
        "ceiling": int(ceiling or 0),
        "maxScore": int(ceiling or 0),
        "source": "",
    }
    if not entry:
        return plan

    seconds = float(entry.get("seconds") or 0.0)
    max_hits = int(entry.get("maxHits") or 0)
    balloon_hits = balloon_hit_estimate(entry)
    current = max(0, int(pound_count or 0) - balloon_hits)
    total = current + hits_needed
    plan.update({
        "hasRolls": bool(entry.get("rolls")) and seconds > 0,
        "rollCount": int(entry.get("rolls") or 0),
        "seconds": seconds,
        "maxHits": max_hits,
        "balloons": int(entry.get("balloons") or 0),
        "balloonSeconds": float(entry.get("balloonSeconds") or 0.0),
        "balloonHits": balloon_hits,
        "currentHits": current,
        "totalHits": total,
        "kiwamiSpeed": entry.get("speed"),
        "source": str(entry.get("source") or ""),
        "ceiling": int(ceiling or 0),
        # 理论最高分 = 全良天井 + 黄条打满 + 风船打满。
        "maxScore": int(ceiling or 0) + ROLL_UNIT * (max_hits + balloon_hits),
    })
    if plan["hasRolls"]:
        plan["speedRaw"] = total / seconds
        plan["speed"] = round(plan["speedRaw"] + 1e-9, 2)
        plan["feasible"] = total <= max_hits
        plan["shortfall"] = max(0, total - max_hits)
    # 没有黄条（可能只有风船）时，黄条路线直接不成立：`feasible` 保持 False，
    # 由调用方按「只能靠判定 / 风船」来提示。
    return plan


def balloon_hit_estimate(entry: dict | None) -> int:
    """估算结算连打数中属于风船的部分。

    wiki 的秒速规定要求把风船打数从结算连打数里减掉，但国服接口不区分两者，
    所以这里用「谱面数据里的风船要求打数」估：超过常规秒速能打出的量时按常规量封顶
    （部分大風船的要求数远高于实际可打数，例如 Rotter Tarmination 的 999）。
    """
    if not entry:
        return 0
    declared = max(0, int(entry.get("balloonHits") or 0))
    cap = int(math.ceil(float(entry.get("balloonSeconds") or 0.0) * BALLOON_NOMINAL_SPEED))
    if declared and cap:
        return min(declared, cap)
    return declared or cap


# ---------------------------------------------------------------------------
# 「提升评价」候选分析
# ---------------------------------------------------------------------------

def _to_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _roll_fields(plan: dict, judgment: dict) -> dict:
    """把连打路线与判定路线的结论摊平成候选条目的字段。

    - `judgmentRequiresAllGood`：只走判定就必须全良（可/不可全部打成良）。
    - `mustAllGood`：连打路线走不通（无黄条 / 超理論値 / 资料缺失），因此必须全良。
    """
    known = bool(plan["known"])
    feasible = bool(plan["feasible"])
    return {
        "rollKnown": known,
        "hasRolls": bool(plan["hasRolls"]),
        "rollCount": plan["rollCount"],
        "rollSeconds": plan["seconds"],
        "rollMaxHits": plan["maxHits"],
        "rollBalloons": plan["balloons"],
        "balloonSeconds": plan["balloonSeconds"],
        "balloonHits": plan["balloonHits"],
        "rollSource": plan["source"],
        "rollCurrentHits": plan["currentHits"],
        "rollTotalHits": plan["totalHits"],
        "rollSpeed": plan["speed"],
        "rollSpeedRaw": plan["speedRaw"],
        "rollKiwamiSpeed": plan["kiwamiSpeed"],
        "rollFeasible": feasible,
        "rollShortfall": plan["shortfall"],
        "maxScore": plan["maxScore"] if known else None,
        "allGoodScore": plan["ceiling"] or None,
        "judgmentRequiresAllGood": bool(judgment["requiresAllGood"]),
        "mustAllGood": bool(judgment["requiresAllGood"]) and not feasible,
    }


def improvement_plan(
    target_score,
    current_score,
    ceiling,
    unit,
    ok_count,
    ng_count,
    pound_count=0,
    entry: dict | None = None,
    all_good_rolls=0,
) -> dict:
    """把「离目标评价还差多少」一次算成判定路线 + 连打路线。

    分析层（analyze_rank_improvements）与检索层（score_query.annotate_target）共用本函数，
    避免两边各写一套换算。
    """
    target_score = _to_int(target_score)
    current_score = _to_int(current_score)
    gap = max(0, target_score - current_score)
    judgment = judgment_plan(gap, unit, ok_count, ng_count)
    plan = roll_plan(entry, gap, pound_count, ceiling)
    fields = {
        "gap": gap,
        "okToGood": judgment["okToGood"],
        "ngToGood": judgment["ngToGood"],
        "requiresAllGood": bool(judgment["requiresAllGood"]),
        "judgmentCovers": bool(judgment["covers"]),
        "rollsNeeded": plan["hitsNeeded"],
        "allGoodRolls": _to_int(all_good_rolls),
    }
    fields.update(_roll_fields(plan, judgment))
    # 判定路线的上限与缺口：全良也补不满时，文案里要说清楚还差多少。
    fields["judgmentGain"] = int(math.floor(judgment["maxGain"] + 1e-9))
    fields["judgmentShortfall"] = max(0, gap - fields["judgmentGain"])
    # 连理论最高分（全良 + 黄条打满 + 风船打满）都够不到门槛时，这一档就真的不可达。
    fields["unreachable"] = bool(
        plan["known"] and plan["maxScore"] and plan["maxScore"] < target_score
    )
    return fields


def analyze_rank_improvements(
    records: list,
    charts: dict,
    rank_data: dict,
    target_rank: int,
    levels: tuple = (4, 5),
    per_genre: int = 5,
    gap_limit_ratio: float = 0.0,
    rolls_data: dict | None = None,
) -> dict:
    """找出「离目标评价最近」的谱面，并按分区聚合。

    charts: {(song_no, level): chart}，提供 totalNotes 与 genre。
    records: analyze() 的 records（含 highScore / bestScoreRank / 良可不可 / 连打）。
    gap_limit_ratio: 只保留分数缺口不超过天井该比例的谱面（0 表示不限）。
    rolls_data: 连打资源；缺失时连打路线按「资料未知」处理。

    每首候选曲目给出：
      - 目标分数 targetScore 与还需提升的 gap
      - okToGood：把这么多个「可」打成「良」即可（等效换算，按基本点计）
      - ngToGood：若「可」不够用，还需把这么多个「不可」打成「良」
      - requiresAllGood：只靠判定达成就**必须全良**（可/不可要全部打成良）
      - rollsNeeded：或者改为补这么多打黄色连打（每打固定 100 分）
      - allGoodRolls：该谱「全良时所需连打打数」，仅供参考值
      - hasRolls / rollCount / rollSeconds：该谱有没有黄条、几条、合计多少秒
      - rollTotalHits / rollSpeed：补分后这一局的黄色连打总打数与要求秒速（不含风船）
      - rollFeasible / rollShortfall：这么多打在不在该谱的連打理論値以内

    判定提升与连打补足是两条**并行**的路，对最高档「极」也一样 ——
    極スコア 只是分数门槛，并不会强制要求全良。
    """
    songs = rank_data.get("songs") or {}
    candidates = []
    scanned = already = unknown = 0
    exact_count = 0
    no_roll_count = roll_unknown = 0

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
        entry = roll_entry(rolls_data, record.get("id"), level)
        plan = improvement_plan(
            target_score,
            current_score,
            ceiling,
            unit,
            ok_count,
            ng_count,
            pound_count=_to_int(record.get("poundCount")),
            entry=entry,
            all_good_rolls=threshold.get("rolls") or 0,
        )
        if entry is None:
            roll_unknown += 1
        elif not plan["hasRolls"]:
            no_roll_count += 1

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
            "gapRatio": round(gap / ceiling, 4) if ceiling else 0.0,
            "okCount": ok_count,
            "ngCount": ng_count,
            "goodCount": _to_int(record.get("goodCount")),
            "poundCount": _to_int(record.get("poundCount")),
            "exact": bool(threshold["exact"]),
            **plan,
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
        "targetRatio": SCORE_RANK_RATIOS.get(target_rank),
        "scanned": scanned,
        "alreadyAtTarget": already,
        "unavailable": unknown,
        "candidateCount": len(candidates),
        "exactCount": exact_count,
        "noRollCount": no_roll_count,
        "rollUnknownCount": roll_unknown,
        "allGoodRequiredCount": sum(1 for item in candidates if item["mustAllGood"]),
        "unreachableCount": sum(1 for item in candidates if item["unreachable"]),
        "genres": genre_rows,
        "items": candidates,
    }
