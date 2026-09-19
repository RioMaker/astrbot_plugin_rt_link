# -*- coding: utf-8 -*-
"""「还差多少 / 怎么补」的文案渲染（成绩检索、提升评价与图片共用一套说法）。

判定路线：把「可」/「不可」打成「良」能补多少分；必要时说明「必须全良」。
连打路线：还要补几打、补完这局一共几打、对应秒速多少 —— 按 wiki「連打秒数表」的规定：
    秒速 = 黄色連打打数 ÷ 合計黄色連打秒数（風船連打不计入）
没有黄条、或者连打理论值不够时，直接说明这条路走不通，免得给出做不到的建议。
"""

from __future__ import annotations

# 只做文案，不依赖 score_rank；常量在此重述以免引入循环依赖。
NORMAL_SPEED_RANGE = (16.6, 18.0)
HIGH_SPEED_HINT = 30.0


def judgment_route_text(item: dict, compact: bool = False) -> str:
    """判定路线说明：转几个可/不可，是否必须全良，全良够不够。"""
    ok_avail = int(item.get("okCount") or 0)
    ng_avail = int(item.get("ngCount") or 0)
    ok_to_good = int(item.get("okToGood") or 0)
    ng_to_good = int(item.get("ngToGood") or 0)
    short = int(item.get("judgmentShortfall") or 0)
    if not (ok_avail or ng_avail):
        return "判定：本局没有「可」「不可」可补，只能靠连打"

    if ok_to_good < ok_avail:
        text = f"判定：把 {ok_to_good} 个「可」打成「良」"
    else:
        text = f"判定：把 {ok_avail} 个「可」全打成「良」"
        use_ng = min(ng_to_good, ng_avail)
        if use_ng:
            text += f"＋{use_ng} 个「不可」打成「良」"
    if item.get("judgmentRequiresAllGood"):
        text += "（全良）" if compact else "（必须全良）"
    if short:
        gain = int(item.get("judgmentGain") or 0)
        text += (
            f"，仍差 {short} 分"
            if compact
            else f"；判定满打满算只能补 {gain} 分，还差 {short} 分"
        )
    return text


def roll_route_text(item: dict, compact: bool = False) -> str:
    """连打路线说明：还差几打、总打数、秒速，以及这条路是否走得通。"""
    need = int(item.get("rollsNeeded") or 0)
    if not item.get("rollKnown"):
        return "连打：缺少该谱连打秒数资料，算不出秒速"
    if not item.get("hasRolls"):
        # 没有黄条：连打这条路直接不成立；判定也不够时要说清楚这一档暂时达不到。
        tail = "" if item.get("judgmentCovers") else "；判定也补不满缺口，本曲这一档暂时达不到"
        if item.get("rollBalloons"):
            return "连打：本曲没有黄条（只有风船），补分只能靠判定" + tail
        return "连打：本曲没有黄条，补分只能靠判定" + tail

    seconds = float(item.get("rollSeconds") or 0)
    count = int(item.get("rollCount") or 0)
    theory = int(item.get("rollMaxHits") or 0)
    if not item.get("rollFeasible"):
        short = int(item.get("rollShortfall") or 0)
        return (
            f"连打：补 {need} 打已超上限（黄条 {count} 条 / {seconds:.2f} 秒，"
            f"理論値共 {theory} 打，还差 {short} 打）"
        )

    total = int(item.get("rollTotalHits") or 0)
    current = int(item.get("rollCurrentHits") or 0)
    speed = item.get("rollSpeed")
    text = f"连打：补 {need} 打 → 黄条共约 {total} 打"
    if current and not compact:
        text += f"（现有约 {current} 打）"
    text += f" ÷ {seconds:.2f} 秒 = 秒速约 {float(speed):.2f} 打/秒"
    if speed and float(speed) > HIGH_SPEED_HINT:
        reference = item.get("rollKiwamiSpeed")
        if reference:
            text += f"（该谱拿「极」约需 {float(reference):.2f} 打/秒，这个要求偏高）"
        else:
            text += f"（常规拿「极」约 {NORMAL_SPEED_RANGE[0]}~{NORMAL_SPEED_RANGE[1]} 打/秒，偏高）"
    elif item.get("balloonSeconds") and not compact:
        text += f"；另有风船 {float(item['balloonSeconds']):.2f} 秒，不计入秒速"
    return text


def gap_route_lines(item: dict, compact: bool = False) -> list:
    """把判定路线与连打路线渲染成若干行。"""
    if item.get("unreachable"):
        cap = int(item.get("maxScore") or 0)
        target = item.get("targetName") or "该评价"
        return [f"本曲上限约 {cap}（全良＋黄条打满），达不到「{target}」门槛"]
    return [
        line for line in (
            judgment_route_text(item, compact),
            roll_route_text(item, compact),
        )
        if line
    ]
