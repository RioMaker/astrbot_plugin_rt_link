# -*- coding: utf-8 -*-
"""玩家 Rating 计算（移植自 taiko-star-rating-system-cal-by-ai 的 src/domain/ratingCore.js）。

- 主 Rating：AI v2（Taiko Signal Rhythm v2），使用 feature.aiConstant + feature.specializations。
- 参考 Rating：OurTaiko-v1，使用 public.constant + public 六轴（大豪力/耐力/速度/精度/节奏/复合）。
- 辅助画像：AI 节奏型能力（rhythmProfile → 节奏型 × BPM 档的玩家处理 Rating）。

公式来源（MIT）：
  https://github.com/OurTaiko/taiko-rating-analyzer

本模块为纯数学实现，无第三方依赖，仅依赖标准库 math / datetime。
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime

# ---------------------------------------------------------------------------
# 常量（与 ratingCore.js 保持一致）
# ---------------------------------------------------------------------------

# 定数 → 难度系数 x（key 为浮点定数，保留 JS 原始数值）
CONSTANT_TO_X = [
    (1, 0.05), (1.5, 0.1), (2, 0.15), (2.5, 0.2), (3, 0.25), (3.5, 0.3),
    (4, 0.35), (4.5, 0.4), (5, 0.45), (5.5, 0.5), (6, 0.55), (6.2, 0.65),
    (6.4, 0.75), (6.6, 0.85), (6.8, 0.95), (6.9, 1), (7, 1.14), (7.1, 1.29),
    (7.2, 1.43), (7.3, 1.57), (7.4, 1.71), (7.5, 1.86), (7.6, 2), (7.7, 2.25),
    (7.8, 2.5), (7.9, 2.75), (8, 3), (8.1, 3.25), (8.2, 3.5), (8.3, 3.75),
    (8.4, 4), (8.5, 4.25), (8.6, 4.5), (8.7, 4.75), (8.8, 5), (8.9, 5.333),
    (9, 5.666), (9.1, 6), (9.2, 6.333), (9.3, 6.666), (9.4, 7), (9.5, 7.5),
    (9.6, 8), (9.7, 8.5), (9.8, 9), (9.9, 9.25), (10, 9.5), (10.1, 9.75),
    (10.2, 10), (10.3, 10.5), (10.4, 11), (10.5, 11.333), (10.6, 11.666),
    (10.7, 12), (10.8, 12.5), (10.9, 13), (11, 13.333), (11.1, 13.666),
    (11.2, 14), (11.3, 14.5), (11.4, 15), (11.5, 15.25), (11.6, 15.5),
]
CONSTANT_TO_X_DICT = dict(CONSTANT_TO_X)

# OurTaiko-v1 参考维度
REFERENCE_DIMENSIONS = [
    "rating", "daigouryoku", "stamina", "speed", "accuracy_power", "rhythm", "complex",
]
# AI v2 维度（首个 rating 为综合，其余为七维能力轴）
AI_DIMENSIONS = [
    "rating", "chartPower", "sustainedEndurance", "burstSpeed", "hitPrecision",
    "patternControl", "timingAdaptation", "visualReading",
]
FAMILIES = AI_DIMENSIONS[1:]

# 七维能力 → 谱面 feature.proportions 家族
ABILITY_FEATURE_MAP = {
    "chartPower": "accuracy",
    "sustainedEndurance": "stamina",
    "burstSpeed": "speed",
    "hitPrecision": "accuracy",
    "patternControl": "technique",
    "timingAdaptation": "rhythm",
    "visualReading": "reading",
}

# 复制谱面去重组（同组只保留维度最高的一张）
DUPLICATE_GROUPS = [
    [(399, 4), (400, 4)], [(399, 5), (400, 5)], [(450, 4), (1257, 4)],
    [(141, 4), (1258, 4)], [(137, 4), (1259, 4)], [(750, 4), (1260, 4)],
    [(527, 4), (1261, 4)], [(323, 4), (1262, 4)], [(939, 4), (1263, 4)],
    [(1146, 4), (1264, 4)], [(1146, 5), (1264, 5)], [(433, 5), (1265, 5)],
    [(433, 4), (1265, 4)], [(191, 4), (1266, 4)],
]

# 中位数补偿（仅 OurTaiko-v1 参考维度有；AI v2 轴无补偿，直接返回加权均值）
COMPENSATION = {
    "rating": [15.27045948521676, 15.29963809348486, 14.58],
    "daigouryoku": [15.260226313838062, 15.290645757225318, 14.54],
    "stamina": [14.680215140150393, 14.915699776343342, 13.36],
    "speed": [14.245030515698776, 14.585896650692296, 13.99],
    "accuracy_power": [15.384801656857972, 15.399022586450302, 15.03],
    "rhythm": [14.521553509242171, 14.831288974113518, 14.02],
    "complex": [13.744459013898052, 14.255545767147531, 13.45],
}

WEIGHTS = [
    0.08, 0.08, 0.08, 0.08, 0.08, 0.06, 0.06, 0.06, 0.06, 0.06,
    1 / 30, 1 / 30, 1 / 30, 1 / 30, 1 / 30, 1 / 30,
    0.025, 0.025, 0.025, 0.025,
]

# 节奏型辅助用到的视觉画像字段（rhythmProfile.visual）
VISUAL_DEFINITIONS = {
    "overtake": "overtakeNoteRatio",
    "scrollChange": "scrollChangeRatio",
    "reverse": "reverseNoteRatio",
    "verticalReverse": "verticalReverseNoteRatio",
    "complexScroll": "complexNoteRatio",
    "stopped": "stoppedNoteRatio",
    "compressed": "compressedNoteRatio",
    "expanded": "expandedNoteRatio",
    "bmScroll": "bmscrollNoteRatio",
    "hbScroll": "hbscrollNoteRatio",
}

# 维度中文名（面向 LLM / 用户输出）
AI_DIMENSION_NAMES = {
    "rating": "综合Rating",
    "chartPower": "谱面底力",
    "sustainedEndurance": "持续耐力",
    "burstSpeed": "爆发手速",
    "hitPrecision": "击打精度",
    "patternControl": "配置处理",
    "timingAdaptation": "节奏适应",
    "visualReading": "读谱",
}
REFERENCE_DIMENSION_NAMES = {
    "rating": "综合Rating",
    "daigouryoku": "大豪力",
    "stamina": "耐力",
    "speed": "速度",
    "accuracy_power": "精度安定",
    "rhythm": "节奏",
    "complex": "复合处理",
}


class RatingError(ValueError):
    """Rating 计算错误（定数缺失 / 准确率越界等）。"""


# ---------------------------------------------------------------------------
# 基础函数
# ---------------------------------------------------------------------------

def nearest_legal_constant(value: float) -> float:
    """把 AI 预测的连续定数吸附到 CONSTANT_TO_X 最近的合法定数。"""
    selected = None
    distance = float("inf")
    for candidate, _ in CONSTANT_TO_X:
        current = abs(candidate - value)
        if current < distance:
            distance = current
            selected = candidate
    return selected


def calc_y(accuracy: float) -> float:
    """精度 → 价值系数 y。"""
    if accuracy <= 0.75:
        return 0.0
    if accuracy <= 0.8278:
        return 16730 * (accuracy - 0.75) ** 3.805
    if accuracy <= 0.9793:
        return 56.4468 * accuracy - 45.7187

    def y3(v: float) -> float:
        return 0.2246 * math.exp(120 * (v - 0.972)) + 9.02

    base = y3(0.9793)
    return base + (y3(accuracy) - base) / (y3(1.0) - base) * (15.5 - base)


def calc_rating(constant: float, accuracy: float) -> float:
    """定数 + 精度 → 单谱 Rating（幂平均）。"""
    x = CONSTANT_TO_X_DICT.get(constant)
    if x is None:
        raise RatingError(f"未知定数 {constant}")
    y = calc_y(accuracy)
    term = 150 ** 2 - (x - y) ** 2 / 2
    p = 150.0 if term < 0 else 150.0 - math.sqrt(term)
    term_w = 25 - (x - 15.5) ** 2 / 25 - (y - 23) ** 2 / 69
    w = 0.5 if term_w < 0 else max(math.sqrt(term_w) - 4, 0.5)
    if p == 0:
        return x ** w * y ** (1 - w)
    return (w * x ** p + (1 - w) * y ** p) ** (1 / p)


def calc_accuracy(good: int, ok: int, bad: int, total_notes: int, dondaful: int = 0) -> float:
    """良=1、可=0.5、不可=0；全良(dondaful>0) 视为满精度 1.0。"""
    if dondaful:
        return 1.0
    if good + ok + bad > total_notes:
        raise RatingError("良、可、不可合计超过总音符数")
    accuracy = (good + ok * 0.5) / total_notes
    if not math.isfinite(accuracy) or accuracy < 0.75 or accuracy > 1:
        raise RatingError("准确率低于 Rating 阈值")
    return accuracy


def _clamp(value: float, lower: float = 0.0, upper: float = 15.5) -> float:
    return max(lower, min(upper, float(value)))


# ---------------------------------------------------------------------------
# 单谱价值计算
# ---------------------------------------------------------------------------

def _score_accuracy(score: dict, total_notes: int) -> float:
    good = _to_int(score.get("goodCount", score.get("good_cnt")), "goodCount")
    ok = _to_int(score.get("okCount", score.get("ok_cnt")), "okCount")
    bad = _to_int(score.get("ngCount", score.get("ng_cnt")), "ngCount")
    dondaful = _to_int(score.get("dondafulComboCount", score.get("dondaful_combo_cnt")) or 0, "dondafulComboCount")
    return calc_accuracy(good, ok, bad, total_notes, dondaful)


def calculate_values(chart: dict, score: dict, constant_override=None) -> dict:
    """OurTaiko-v1 参考：基于 public.constant + public 六轴。"""
    public = chart.get("public")
    if not public:
        raise RatingError("缺少公开公式参数")
    total_notes = _to_int(chart.get("totalNotes", public.get("totalNotes")), "totalNotes")
    accuracy = _score_accuracy(score, total_notes)
    constant = constant_override if constant_override is not None else public.get("constant")
    x = CONSTANT_TO_X_DICT.get(constant)
    if x is None:
        raise RatingError(f"未知定数 {constant}")
    y = calc_y(accuracy)
    rating = calc_rating(constant, accuracy)
    average = float(public.get("avgDensity") or 0)
    instant = float(public.get("instDensity") or 0)
    if average <= 0 or instant <= 0:
        raise RatingError("谱面密度无效")
    if average > instant:
        stamina_raw = average + average / 100 * (1 - instant / average) * (100 - average)
    else:
        stamina_raw = average - (1 - average / instant) * average
    if instant > average:
        speed_raw = instant - (1 - average / instant) * (instant - average)
    else:
        speed_raw = instant + (1 - instant / average) * (average - instant)
    separation = float(public.get("separation") or 0)
    bpm_change = float(public.get("bpmChange") or 0)
    rhythm_raw = separation + separation / 100 * bpm_change / 100 * (100 - separation)
    return {
        "rating": rating,
        "daigouryoku": math.sqrt(rating * x),
        "stamina": math.sqrt(rating * stamina_raw * 15.5 / 100),
        "speed": math.sqrt(rating * speed_raw * 15.5 / 100),
        "accuracy_power": math.sqrt(rating * y),
        "rhythm": math.sqrt(rating * rhythm_raw * 15.5 / 100),
        "complex": math.sqrt(rating * float(public.get("composite") or 0) * 15.5 / 100),
        "accuracy": accuracy,
        "constant": constant,
    }


def calculate_ai_values(chart: dict, score: dict) -> dict:
    """AI v2 主 Rating：基于 feature.aiConstant + feature.specializations。"""
    feature = chart.get("feature")
    if not feature or not _is_finite(feature.get("aiConstant")):
        raise RatingError("缺少 AI v2 谱面预测")
    total_notes = _to_int(chart.get("totalNotes"), "totalNotes")
    accuracy = _score_accuracy(score, total_notes)
    constant_raw = float(feature.get("aiConstant"))
    constant = nearest_legal_constant(constant_raw)
    x = CONSTANT_TO_X_DICT.get(constant)
    y = calc_y(accuracy)
    rating = calc_rating(constant, accuracy)
    specializations = feature.get("specializations") or {}

    def demand(value) -> float:
        return _clamp(x + 1.35 * float(value or 0))

    def axis(value) -> float:
        return math.sqrt(max(0.0, rating * demand(value)))

    timing = (
        0.72 * float(specializations.get("separation") or 0)
        + 0.20 * float(specializations.get("bpmChange") or 0)
        + 0.08 * float(specializations.get("hsChange") or 0)
    )
    reading = (
        0.30 * float(specializations.get("bpmChange") or 0)
        + 0.70 * float(specializations.get("hsChange") or 0)
    )
    return {
        "rating": rating,
        "chartPower": math.sqrt(max(0.0, rating * x)),
        "sustainedEndurance": axis(specializations.get("avgDensity")),
        "burstSpeed": axis(specializations.get("instDensity")),
        "hitPrecision": math.sqrt(max(0.0, rating * y)),
        "patternControl": axis(specializations.get("composite")),
        "timingAdaptation": axis(timing),
        "visualReading": axis(reading),
        "accuracy": accuracy,
        "constant": constant,
        "constantRaw": constant_raw,
    }


# ---------------------------------------------------------------------------
# 成绩归一化（kinoko 全历史 / hiroba 最新）
# ---------------------------------------------------------------------------

def normalize_scores(payload: dict) -> dict:
    """把菌菌 kinoko/hiroba 响应归一到 rows 列表。

    返回 rows（每条含 id/level/title/goodCount/okCount/ngCount/dondafulComboCount/
    highScore/updatedAt/observedTotalNotes），以及 diagnostics / meta。
    """
    outer = (((payload or {}).get("data") or {}).get("playedRecords") or {}).get("scoreInfo")
    if not isinstance(outer, list):
        raise RatingError("未找到 data.playedRecords.scoreInfo")
    rows = []
    diagnostics = []
    for record in outer:
        try:
            id_ = _to_int(record.get("song_no"), "song_no")
            level = _to_int(record.get("level"), "level")
            if level not in (4, 5):
                continue
            inner = record.get("scoreInfo")
            scores = inner if isinstance(inner, list) else [record]
            for source_index, score in enumerate(scores):
                try:
                    if _to_int(score.get("song_no", id_), "song_no") != id_ or \
                            _to_int(score.get("level", level), "level") != level:
                        raise RatingError("内外谱面身份不一致")
                    good = score.get("good_cnt")
                    ok = score.get("ok_cnt")
                    ng = score.get("ng_cnt")
                    observed = int(good or 0) + int(ok or 0) + int(ng or 0)
                    rows.append({
                        "id": id_,
                        "level": level,
                        "sourceIndex": source_index,
                        "title": (record.get("title_cn") or record.get("title")
                                  or (record.get("song_detail") or {}).get("song_name")
                                  or (record.get("song_detail") or {}).get("song_name_jp")
                                  or f"Song {id_}"),
                        "goodCount": good,
                        "okCount": ok,
                        "ngCount": ng,
                        "observedTotalNotes": observed,
                        "dondafulComboCount": score.get("dondaful_combo_cnt") or 0,
                        "highScore": score.get("high_score") or 0,
                        "updatedAt": score.get("update_datetime") or score.get("highscore_datetime") or "",
                        # 透传字段（不参与 Rating 数学，供画像/筛选使用）
                        "bestScoreRank": score.get("best_score_rank"),
                        "fullComboCount": score.get("full_combo_cnt"),
                        "poundCount": score.get("pound_cnt"),
                        "comboCount": score.get("combo_cnt"),
                        "clearCount": score.get("clear_cnt"),
                        "songDetail": record.get("song_detail"),
                        "raw": score,
                    })
                except RatingError as e:
                    diagnostics.append({"code": "invalid-score", "id": id_, "level": level, "message": str(e)})
        except RatingError as e:
            diagnostics.append({"code": "invalid-chart-record", "message": str(e)})
    played = ((payload or {}).get("data") or {}).get("playedRecords") or {}
    return {
        "rows": rows,
        "diagnostics": diagnostics,
        "meta": {
            "playerId": str(played.get("player_id") or played.get("userid") or ""),
            "server": str(played.get("server") or ""),
            "outerRecords": len(outer),
        },
    }


# ---------------------------------------------------------------------------
# 聚合
# ---------------------------------------------------------------------------

def _timestamp(value) -> float:
    text = str(value or "").replace(" ", "T")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(text, fmt).timestamp()
        except ValueError:
            continue
    return 0.0


def best_row(rows: list, rating_key: str = "rating") -> dict | None:
    best = None
    for row in rows:
        if best is None:
            best = row
            continue
        left = [row[rating_key], row.get("accuracy", 0.0), float(row.get("highScore") or 0),
                _timestamp(row.get("updatedAt")), -row.get("sourceIndex", 0)]
        right = [best[rating_key], best.get("accuracy", 0.0), float(best.get("highScore") or 0),
                 _timestamp(best.get("updatedAt")), -best.get("sourceIndex", 0)]
        for i in range(len(left)):
            if left[i] != right[i]:
                if left[i] > right[i]:
                    best = row
                break
    return best


def _duplicate_groups_map() -> dict:
    result = {}
    for index, group in enumerate(DUPLICATE_GROUPS):
        for key in group:
            result[f"{key[0]}-{key[1]}"] = index
    return result


_DUP_GROUP_MAP = _duplicate_groups_map()


def dedupe_for_dimension(rows: list, dimension: str) -> list:
    plain = []
    grouped = {}
    for row in rows:
        group = _DUP_GROUP_MAP.get(f"{row['id']}-{row['level']}")
        if group is None:
            plain.append(row)
        elif group not in grouped or row[dimension] > grouped[group][dimension]:
            grouped[group] = row
    return plain + list(grouped.values())


def aggregate_dimension(rows: list, dimension: str) -> float:
    values = sorted(
        (row[dimension] for row in dedupe_for_dimension(rows, dimension)),
        reverse=True,
    )[:20]
    if not values:
        return 0.0
    middle = len(values) // 2
    if len(values) % 2:
        median = values[middle]
    else:
        median = (values[middle - 1] + values[middle]) / 2
    weight_total = sum(WEIGHTS[: len(values)])
    average = sum(v * WEIGHTS[i] for i, v in enumerate(values)) / weight_total
    if dimension not in COMPENSATION:
        return average
    full_mid, full_average, threshold = COMPENSATION[dimension]
    if round(average * 100) / 100 < threshold:
        return median
    ratio = min(1.0, max(0.0, (average - threshold) / (full_average - threshold)))
    return median + ratio * (15.5 - full_mid)


def aggregate(rows: list, dimensions=REFERENCE_DIMENSIONS) -> dict:
    return {dimension: aggregate_dimension(rows, dimension) for dimension in dimensions}


# ---------------------------------------------------------------------------
# 主分析入口
# ---------------------------------------------------------------------------

def analyze(payload: dict, charts: dict) -> dict:
    """charts: {(song_no, level) -> chart} 的内存字典。"""
    normalized = normalize_scores(payload)
    candidates = defaultdict(list)
    diagnostics = list(normalized["diagnostics"])
    counts = {
        "normalized": len(normalized["rows"]), "matched": 0, "missing": 0,
        "publicMatched": 0, "publicMissing": 0, "belowThreshold": 0,
        "invalid": len(diagnostics), "featureMatched": 0,
    }
    for score in normalized["rows"]:
        key = (score["id"], score["level"])
        chart = charts.get(key)
        if not chart:
            counts["missing"] += 1
            diagnostics.append({"code": "chart-not-found", "id": score["id"], "level": score["level"], "message": score["title"]})
            continue
        counts["matched"] += 1
        try:
            good = _to_int(score["goodCount"], "goodCount")
            ok = _to_int(score["okCount"], "okCount")
            bad = _to_int(score["ngCount"], "ngCount")
            dondaful = _to_int(score["dondafulComboCount"] or 0, "dondafulComboCount")
            observed = _to_int(score["observedTotalNotes"], "observedTotalNotes")
            stored = _to_int(chart.get("totalNotes", (chart.get("public") or {}).get("totalNotes")), "totalNotes")
            total_notes = observed or stored
            if not dondaful and good + ok + bad > total_notes:
                raise RatingError("良、可、不可合计超过总音符数")
            accuracy = calc_accuracy(good, ok, bad, total_notes, dondaful)
            has_public = bool(chart.get("public")) and stored == total_notes
            has_feature = bool(chart.get("feature")) and stored == total_notes
            if has_public:
                counts["publicMatched"] += 1
            else:
                counts["publicMissing"] += 1
                diagnostics.append({
                    "code": "public-profile-version-mismatch" if chart.get("public") else "public-profile-missing",
                    "id": score["id"], "level": score["level"],
                    "message": f"{score['title']} 的 OurTaiko-v1 参考画像不可用",
                })
            reference = calculate_values({**chart, "totalNotes": total_notes}, score) if has_public else None
            if chart.get("feature") and not has_feature:
                diagnostics.append({
                    "code": "feature-profile-version-mismatch",
                    "id": score["id"], "level": score["level"],
                    "message": f"{score['title']} 的 AI v2 谱面版本不一致",
                })
            ai = calculate_ai_values({**chart, "totalNotes": total_notes}, score) if has_feature else None
            row = {**score, **(ai or {}), "chart": chart, "feature": chart.get("feature"),
                   "hasPublicProfile": has_public, "aiV2": ai, "ourTaikoV1": reference}
            if has_feature:
                counts["featureMatched"] += 1
                row["aiConstantRaw"] = ai["constantRaw"]
                row["aiConstant"] = ai["constant"]
                row["aiRating"] = ai["rating"]
            if not _is_finite(row.get("rating")):
                raise RatingError("缺少 AI v2 谱面预测")
            candidates[key].append(row)
        except RatingError as e:
            if "阈值" in str(e):
                counts["belowThreshold"] += 1
                code = "below-threshold"
            else:
                counts["invalid"] += 1
                code = "calculation-error"
            diagnostics.append({"code": code, "id": score["id"], "level": score["level"], "message": str(e)})

    records = [best_row(rows) for rows in candidates.values()]
    records = sorted([r for r in records if r], key=lambda r: r["rating"], reverse=True)
    public_rows = [r for r in records if r.get("hasPublicProfile")]
    public_rows = [{**r, **r["ourTaikoV1"]} for r in public_rows]
    top = {dim: sorted(dedupe_for_dimension(records, dim), key=lambda r: r[dim], reverse=True)[:20]
           for dim in AI_DIMENSIONS}
    reference_top = {dim: sorted(dedupe_for_dimension(public_rows, dim), key=lambda r: r[dim], reverse=True)[:20]
                     for dim in REFERENCE_DIMENSIONS}
    ai_summary = aggregate(records, AI_DIMENSIONS)
    reference_summary = aggregate(public_rows, REFERENCE_DIMENSIONS)
    return {
        "meta": {**normalized["meta"], "uniqueCharts": len(records), "publicCharts": len(public_rows)},
        "counts": counts,
        "diagnostics": diagnostics,
        "summary": ai_summary,
        "aiSummary": {**ai_summary, "chartCount": len(records)},
        "ourTaikoV1": {"summary": reference_summary, "top": reference_top, "chartCount": len(public_rows)},
        "records": records,
        "top": top,
        "referenceTop": reference_top,
        "featureAbility": calculate_feature_ability(records),
        "rhythmAbility": calculate_rhythm_ability(records),
    }


# ---------------------------------------------------------------------------
# 七维能力强弱项
# ---------------------------------------------------------------------------

def calculate_feature_ability(records: list) -> dict:
    families = []
    for key in FAMILIES:
        selected = sorted(dedupe_for_dimension(records, key), key=lambda r: r[key], reverse=True)[:20]
        exposure = sum(float((r.get("feature") or {}).get("proportions", {}).get(ABILITY_FEATURE_MAP[key]) or 0)
                       for r in selected)
        families.append({
            "key": key,
            "score": aggregate_dimension(records, key),
            "charts": len(selected),
            "exposure": exposure,
            "best": selected[:5],
        })
    ranked = sorted([f for f in families if f["charts"] >= 3], key=lambda f: f["score"], reverse=True)
    return {
        "families": families,
        "strengths": ranked[:3],
        "weaknesses": list(reversed(ranked[-3:])),
        "matchedCharts": len(records),
        "method": "ai-v2-specialization-axis-top20",
    }


def _aggregate_arrangement_lengths(arrangement_cells: list) -> list:
    groups = defaultdict(list)
    for cell in arrangement_cells:
        groups[f"{cell['length']}|{cell['bpmBand']}"].append(cell)
    result = []
    for key, items in groups.items():
        length, bpm_band = key.split("|")
        score = sum(float(i["score"]) for i in items) / len(items)
        best_by_chart = {}
        for row in [b for i in items for b in i.get("best", [])]:
            ck = f"{row['id']}-{row['level']}"
            if ck not in best_by_chart or row["rating"] > best_by_chart[ck]["rating"]:
                best_by_chart[ck] = row
        result.append({
            "key": f"16-{length}|{bpm_band}", "pattern": f"16-{length}",
            "length": int(length), "bpmBand": bpm_band, "score": score,
            "arrangementCount": len(items),
            "patterns": sorted(i.get("pattern") for i in items),
            "charts": round(sum(i.get("charts", 0) for i in items) / len(items)),
            "exposure": sum(i.get("exposure", 0) for i in items) / len(items),
            "averageBpm": sum(i.get("averageBpm", 0) for i in items) / len(items),
            "best": sorted(best_by_chart.values(), key=lambda r: r["rating"], reverse=True)[:5],
        })
    result.sort(key=lambda x: (x["length"], x["bpmBand"]))
    return result


def calculate_rhythm_ability(records: list) -> dict:
    cell_samples = defaultdict(list)
    arrangement_samples = defaultdict(list)
    arrangement_cell_samples = defaultdict(list)
    for row in records:
        rhythm = (row.get("feature") or {}).get("rhythmProfile")
        if not rhythm:
            continue
        for cell in rhythm.get("cells") or []:
            weight = float(cell.get("noteRatio") or 0)
            if weight <= 0.005:
                continue
            cell_samples[f"{cell.get('pattern')}|{cell.get('bpmBand')}"].append({"row": row, "weight": weight, "cell": cell})
        for arrangement in rhythm.get("topArrangements") or []:
            weight = float(arrangement.get("count") or 0)
            if weight <= 0:
                continue
            arrangement_samples[arrangement.get("key")].append({"row": row, "weight": weight})
        for cell in rhythm.get("arrangementCells") or []:
            weight = float(cell.get("noteRatio") or 0)
            if weight <= 0.002:
                continue
            arrangement_cell_samples[f"{cell.get('length')}:{cell.get('pattern')}|{cell.get('bpmBand')}"].append(
                {"row": row, "weight": weight, "cell": cell})

    cells = []
    for key, samples in cell_samples.items():
        selected = sorted(samples, key=lambda s: s["row"]["rating"], reverse=True)[:20]
        weight_total = sum(s["weight"] for s in selected)
        pattern, bpm_band = key.split("|")
        cells.append({
            "key": key, "pattern": pattern, "bpmBand": bpm_band,
            "score": sum(s["row"]["rating"] * s["weight"] for s in selected) / weight_total if weight_total else 0.0,
            "charts": len(selected), "exposure": weight_total,
            "averageBpm": sum(s["cell"].get("averageBpm", 0) for s in selected) / len(selected) if selected else 0.0,
            "averageEquivalent16Bpm": sum(s["cell"].get("averageEquivalent16Bpm", 0) for s in selected) / len(selected) if selected else 0.0,
            "compoundRatio": sum(s["cell"].get("compoundRatio", 0) for s in selected) / len(selected) if selected else 0.0,
            "best": [s["row"] for s in selected[:5]],
        })
    cells = sorted([c for c in cells if c["charts"] >= 3], key=lambda c: c["score"], reverse=True)

    arrangements = []
    for key, samples in arrangement_samples.items():
        selected = sorted(samples, key=lambda s: s["row"]["rating"], reverse=True)[:20]
        weight_total = sum(s["weight"] for s in selected)
        arrangements.append({
            "key": key,
            "score": sum(s["row"]["rating"] * s["weight"] for s in selected) / weight_total if weight_total else 0.0,
            "charts": len(selected),
            "best": [s["row"] for s in selected[:3]],
        })
    arrangements = sorted([a for a in arrangements if a["charts"] >= 3], key=lambda a: a["score"], reverse=True)

    arrangement_cells = []
    for key, samples in arrangement_cell_samples.items():
        selected = sorted(samples, key=lambda s: s["row"]["rating"], reverse=True)[:20]
        weight_total = sum(s["weight"] for s in selected)
        example = selected[0]["cell"] if selected else {}
        arrangement_cells.append({
            "key": key, "length": example.get("length"), "pattern": example.get("pattern"),
            "bpmBand": example.get("bpmBand"),
            "score": sum(s["row"]["rating"] * s["weight"] for s in selected) / weight_total if weight_total else 0.0,
            "charts": len(selected), "exposure": weight_total,
            "averageBpm": sum(s["cell"].get("averageBpm", 0) for s in selected) / len(selected) if selected else 0.0,
            "best": [s["row"] for s in selected[:5]],
        })
    arrangement_cells = sorted([c for c in arrangement_cells if c["charts"] >= 3], key=lambda c: c["score"], reverse=True)

    arrangement_length_cells = _aggregate_arrangement_lengths(arrangement_cells)
    arrangement_length_map = {c["key"]: c for c in arrangement_length_cells}
    cells = [arrangement_length_map.get(c["key"], c) for c in cells]
    cells.sort(key=lambda c: c["score"], reverse=True)

    visual = {}
    for key, definition in VISUAL_DEFINITIONS.items():
        samples = []
        for row in records:
            weight = float((((row.get("feature") or {}).get("rhythmProfile") or {}).get("visual") or {}).get(definition) or 0)
            if weight > 0.001:
                samples.append({"row": row, "weight": weight})
        samples.sort(key=lambda s: s["row"]["rating"], reverse=True)
        samples = samples[:20]
        total = sum(s["weight"] for s in samples)
        visual[key] = {
            "key": key,
            "score": sum(s["row"]["rating"] * s["weight"] for s in samples) / total if total else 0.0,
            "charts": len(samples),
            "exposure": total,
            "best": [s["row"] for s in samples[:5]],
        }
    return {
        "cells": cells, "arrangements": arrangements, "arrangementCells": arrangement_cells,
        "arrangementLengthCells": arrangement_length_cells, "visual": visual,
        "best": cells[:10], "weakest": list(reversed(cells[-10:])),
    }


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _is_finite(value) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _to_int(value, field: str) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise RatingError(f"{field} 必须是非负整数")
    if not math.isfinite(number) or number < 0 or number != int(number):
        raise RatingError(f"{field} 必须是非负整数")
    return int(number)
