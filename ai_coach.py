"""Bounded, deterministic material for the four conversational tools.

No model calls, raw API envelopes, history dumps or paging. Recommendation
ordering is a training heuristic, not a prediction of accuracy or clear rate.
"""

from __future__ import annotations

from datetime import datetime, timezone
from statistics import median

if __package__:
    from . import rating, score_rank, improve_text
else:
    import rating
    import score_rank
    import improve_text


MAX_CHARS = 2500
RECOMMEND_COUNT = 5
GOALS = {"general", "weakness", "accuracy", "full_combo", "score_rank", "explore"}
LIMITATION = "依据为整曲最佳成绩与公共谱面参考；不能定位个人失误小节或预测精度、全连率、过关概率。"


def clean(value, limit=64):
    return " ".join(str(value if value is not None else "未知").split())[:limit]


def pack(header, blocks=(), footer=LIMITATION):
    """Drop whole optional blocks, preserving the provenance and limitations."""
    parts = [header]
    for block in blocks:
        if len("\n".join([*parts, block, footer])) > MAX_CHARS:
            parts.append("次要材料已省略，请根据现有依据回答。")
            break
        parts.append(block)
    parts.append(footer)
    return "\n".join(parts)


def provenance(analysis):
    meta = analysis.get("meta") or {}
    synced = analysis.get("profileSyncedAt")
    if not synced and analysis.get("_ts"):
        synced = datetime.fromtimestamp(analysis["_ts"], timezone.utc).isoformat()
    return (f"来源：{clean(meta.get('provider') or analysis.get('profileSource'))} / "
            f"服务器 {clean(meta.get('server'))}｜同步时间 {clean(synced)}")


def label(row):
    level = row.get("level")
    return f"《{clean(row.get('title') or row.get('titleJa'))}》ID {row.get('id')}·{'鬼' if level == 4 else '里'}"


def constant(row, chart):
    value = row.get("aiConstant")
    if value is None:
        value = (chart.get("feature") or {}).get("aiConstant")
    return float(value) if value is not None else None


def performance(row):
    acc = row.get("accuracy")
    return (f"精度 {float(acc) * 100:.2f}%" if acc is not None else "精度未知") + (
        f"，可 {clean(row.get('okCount'))} / 不可 {clean(row.get('ngCount'))}，"
        f"评价 {score_rank.score_rank_name(int(row.get('bestScoreRank') or 1))}"
    )


def weak_cells(analysis):
    return [c for c in (analysis.get("rhythmAbility") or {}).get("weakest", [])
            if (c.get("charts") or 0) >= 3 and c.get("rarity") != "rare"][:2]


def player_brief(analysis):
    rows = analysis.get("records") or []
    summary = analysis.get("summary") or {}
    weak = weak_cells(analysis)
    detail = "；".join(
        f"{clean(c.get('pattern'))}@{clean(c.get('bpmBand'))}（{c['charts']} 张样本）"
        for c in weak
    ) or "节奏弱项样本不足（每项至少 3 张）"
    return (f"玩家：Rating {summary.get('rating', 0)}，已评级 {len(rows)} 张鬼/里谱面。\n"
            f"主要节奏弱项：{detail}")


def overview(analysis):
    summary = analysis.get("summary") or {}
    rows = analysis.get("records") or []
    blocks = ["能力：" + "；".join(
        f"{rating.AI_DIMENSION_NAMES[key]} {summary[key]}"
        for key in rating.AI_DIMENSIONS[1:] if key in summary
    )]
    for kind, name in (("strengths", "强项"), ("weaknesses", "弱项")):
        items = (analysis.get("featureAbility") or {}).get(kind) or []
        blocks.append(name + "：" + ("；".join(
            f"{rating.AI_DIMENSION_NAMES.get(c['key'], c['key'])} {c.get('score')}"
            for c in items[:2]
        ) or "样本不足"))
    blocks.append(f"全连 {sum(bool(r.get('fullComboCount') or r.get('dondafulComboCount')) for r in rows)} 张；"
                  f"全良 {sum(bool(r.get('dondafulComboCount')) for r in rows)} 张。")
    blocks.extend(f"成绩证据：{label(r)}，{performance(r)}" for r in rows[:2])
    return pack(provenance(analysis) + "\n" + player_brief(analysis), blocks)


def chart_for(charts, row):
    chart = charts.get((row.get("id"), row.get("level"))) or {}
    if row.get("branchProfile") and not any(
        branch.get("key") == row["branchProfile"] for branch in chart.get("branchProfiles", [])
    ):
        return {}
    return rating.chart_for_record(chart, row)


def rhythm_matches(chart, cells):
    matches = []
    for cell in ((chart.get("feature") or {}).get("rhythmProfile") or {}).get("cells", []):
        for target in cells:
            if (cell.get("pattern"), cell.get("bpmBand")) == (target.get("pattern"), target.get("bpmBand")):
                ratio = float(cell.get("noteRatio") or 0)
                if ratio > 0.005:
                    matches.append((ratio, cell))
    return sorted(matches, key=lambda pair: pair[0], reverse=True)


def rhythm_reason(match):
    ratio, cell = match
    return (f"含 {clean(cell.get('pattern'))}@{clean(cell.get('bpmBand'))}，"
            f"配置音符占比 {ratio * 100:.1f}%")


def recommendations(analysis, charts, rank_data, rolls, goal="general", level=None,
                    target_rank=None, scope="", default_rank=5):
    if goal not in GOALS:
        return "目标无效：可用 general、weakness、accuracy、full_combo、score_rank、explore。"
    scope = scope or ("unplayed" if goal == "explore" else "played")
    if scope not in {"played", "unplayed", "all"}:
        return "范围无效：可用 played、unplayed、all。"
    if goal in {"accuracy", "full_combo", "score_rank"} and scope != "played":
        return "精度、全连及评价提升需要已有成绩依据，请使用 played 范围。"
    if goal == "explore" and scope != "unplayed":
        return "探索未玩歌曲请使用 unplayed 范围。"
    if target_rank is not None and goal != "score_rank":
        return "target_rank 仅用于 score_rank 评价提升目标。"
    rows = [r for r in analysis.get("records") or [] if level is None or r.get("level") == level]
    header = provenance(analysis) + "\n" + player_brief(analysis) + f"\n练习目标：{goal}；范围：{scope}。"
    notes = [LIMITATION, "以下按本地训练启发式排序，不代表达成难度或成功率的实测排名。"]
    if not rows:
        return pack(header, ["该难度暂无已评级成绩，无法据此推荐。"])

    if goal == "score_rank":
        rank = target_rank if target_rank is not None else default_rank
        result = score_rank.analyze_rank_improvements(
            rows, charts, rank_data, rank, levels=(level,) if level else (4, 5), rolls_data=rolls,
        )
        by_song = {}
        for row in result["items"]:
            if not row.get("unreachable"):
                by_song.setdefault(row["id"], row)
        candidates = list(by_song.values())[:RECOMMEND_COUNT]
        blocks = [f"目标评价：{score_rank.score_rank_name(rank)}"
                  + ("（按当前难度成绩的常见评价自动取上一档）" if target_rank is None else "")]
        for index, item in enumerate(candidates, 1):
            routes = "；".join(improve_text.gap_route_lines(item, compact=True))
            blocks.append(f"{index}. {label(item)}｜当前 {item['currentScore']} → {item['targetScore']}，"
                          f"差 {item['gap']} 分（{'实测' if item['exact'] else '估算'}门槛）。\n"
                          f"依据与目标：{routes}。")
        if any(r.get("branchProfile") for r in rows):
            notes.append("未核定对应路线评价门槛的分支成绩不参与本次评价推荐。")
        return _finish(header, blocks, len(candidates), notes)

    valid_constants = [value for r in rows if (value := constant(r, chart_for(charts, r))) is not None]
    if not valid_constants:
        return pack(header, ["缺少已玩谱面的定数资料，无法建立练习难度参考范围。"])
    # Use actual played chart constants, never compare chart constants with player Rating.
    top = sorted(rows, key=lambda r: float(r.get("rating") or 0), reverse=True)[:20]
    anchor = median([value for r in top if (value := constant(r, chart_for(charts, r))) is not None]
                    or valid_constants)
    low, high = anchor - 1.5, anchor + 0.5
    notes.append(f"难度筛选：该难度前 20 张成绩的谱面定数中位数 {anchor:.2f}，参考区间 {low:.2f}–{high:.2f}；不等同于能力预测。")
    cells = weak_cells(analysis)
    if goal == "explore" and not cells:
        cells = [c for c in (analysis.get("rhythmAbility") or {}).get("best", [])
                 if (c.get("charts") or 0) >= 3 and c.get("rarity") != "rare"][:2]
    if goal in {"weakness", "explore"} and not cells:
        return pack(header, ["配置样本不足，无法可靠筛选该目标的歌曲。"])
    candidates = []
    if scope in {"played", "all"}:
        for row in rows:
            chart = chart_for(charts, row)
            value = constant(row, chart)
            if value is None or not low <= value <= high or row.get("accuracy") is None:
                continue
            acc = float(row["accuracy"])
            matches = rhythm_matches(chart, cells)
            if goal == "full_combo":
                if row.get("fullComboCount") or row.get("dondafulComboCount") or row.get("ngCount") is None:
                    continue
                reason = f"尚未全连，当前不可 {row['ngCount']}"
                target = "先核对零不可但未记全连的记录，再尝试完整连击" if row["ngCount"] == 0 else "先减少不可，再尝试全连"
                priority = (row["ngCount"], abs(value - anchor))
            else:
                if row.get("dondafulComboCount") or acc >= 1 or row.get("okCount") is None or row.get("ngCount") is None:
                    continue
                if goal == "weakness" and not matches:
                    continue
                reason = rhythm_reason(matches[0]) if matches and goal != "accuracy" else "已有精度成绩，仍有可或不可可改善"
                target = "保持不可不增加，逐步把可转为良"
                if matches and goal != "accuracy":
                    priority = (0, -matches[0][0], abs(value - anchor))
                else:
                    priority = (1, abs(acc - 0.98), abs(value - anchor))
            candidates.append((priority, row, f"{performance(row)}；定数 {value:.2f}", reason, target))
    if scope in {"unplayed", "all"}:
        # Include raw/unrated records: failure to rate a chart does not mean unplayed.
        known = {(r.get("id"), r.get("level")) for r in analysis.get("records") or []}
        known.update((r.get("id"), r.get("level")) for r in analysis.get("unrated") or [])
        known.update((r.get("id"), r.get("level")) for r in analysis.get("profileScoreRows") or [])
        for key, chart in charts.items():
            if key in known or key[1] not in ((level,) if level else (4, 5)) or chart.get("branchProfiles"):
                continue
            value = constant({}, chart)
            matches = rhythm_matches(chart, cells)
            if value is None or not low <= value <= high or not matches:
                continue
            match = matches[0]
            refs = [r for r in rows if rhythm_matches(chart_for(charts, r), [match[1]])]
            if not refs:
                continue
            ref = min(refs, key=lambda r: abs((constant(r, chart_for(charts, r)) or anchor) - value))
            reason = f"{rhythm_reason(match)}；已玩参考 {label(ref)}（{performance(ref)}）"
            candidates.append(((2, -match[0], abs(value - anchor)), chart,
                               f"当前同步数据无游玩记录；定数 {value:.2f}", reason, "先试打熟悉配置，再根据实际成绩调整"))
        notes.append("未玩指当前同步数据无记录；分支路线未经个人成绩确认的谱面不作探索推荐。")
    candidates.sort(key=lambda item: (*item[0], item[1].get("id", 0), item[1].get("level", 0)))
    by_song = {}
    for item in candidates:
        by_song.setdefault(item[1]["id"], item)
    selected = list(by_song.values())[:RECOMMEND_COUNT]
    blocks = [f"{i}. {label(row)}｜{evidence}。\n依据：{reason}；目标：{target}。"
              for i, (_priority, row, evidence, reason, target) in enumerate(selected, 1)]
    return _finish(header, blocks, len(selected), notes)


def _finish(header, blocks, count, notes):
    status = f"本次返回 {count} 首。" + ("符合条件不足 5 首，不补入缺乏依据的歌曲。" if count < RECOMMEND_COUNT else "")
    return pack(header + "\n" + status, blocks, "\n".join(notes))


def song_brief(charts, song_id, level, analysis=None, player_error=""):
    rows = {(r["id"], r["level"]): r for r in (analysis or {}).get("records") or []}
    raw = {(r["id"], r["level"]): r for r in (analysis or {}).get("profileScoreRows") or []}
    unrated = {(r["id"], r["level"]): r for r in (analysis or {}).get("unrated") or []}
    blocks = []
    for key, base in charts.items():
        if key[0] != song_id or key[1] not in ((level,) if level else (4, 5)):
            continue
        row = rows.get(key)
        chart = chart_for(charts, row) if row else base
        value = constant(row or {}, chart)
        lines = [f"{label(chart)}｜定数 {value if value is not None else '未评级'}；音符 {chart.get('totalNotes')}。"]
        if row:
            lines.append("玩家成绩：" + performance(row) + f"；分数 {row.get('highScore')}。")
            if row.get("branchProfile"):
                lines.append(f"成绩匹配路线：{clean(row['branchProfile'])}；不套用其他路线资料。")
        elif key in raw or key in unrated:
            lines.append("已玩但未评级：" + clean((unrated.get(key) or {}).get("reason") or "当前无可用评级", 140))
        else:
            lines.append("当前同步数据无该难度成绩。" if analysis else "玩家成绩不可用，不能判断是否游玩。")
        if base.get("branchProfiles") and not row:
            lines.append("存在分支路线；没有可匹配成绩时不将默认路线视为个人路线。")
        else:
            cells = sorted((((chart.get("feature") or {}).get("rhythmProfile") or {}).get("cells") or []),
                           key=lambda c: c.get("noteRatio") or 0, reverse=True)[:2]
            lines.extend("谱面参考：" + rhythm_reason((float(c.get("noteRatio") or 0), c)) for c in cells)
        blocks.append("\n".join(lines))
    if not blocks:
        blocks = ["当前谱面库无该难度资料。"]
    header = provenance(analysis) if analysis else "来源：插件内置公共谱面库；玩家成绩未获取。"
    if player_error:
        header += "\n成绩状态：" + clean(player_error, 240)
    return pack(header, blocks)
