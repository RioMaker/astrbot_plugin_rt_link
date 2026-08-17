# -*- coding: utf-8 -*-
"""鼓点画像报告图片生成（matplotlib 重实现，参考 taiko-ai-rating 前端报告）。

生成一张 PNG：综合 Rating 环 + 七维能力雷达 + 强弱项 + 表现证据 + 指标条。
"""

from __future__ import annotations

import math
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle, Wedge

plt.rcParams["axes.unicode_minus"] = False

_fonts_ready = False


def _setup_fonts() -> None:
    """显式注册系统中文字体，避免中文显示为方块。"""
    global _fonts_ready
    if _fonts_ready:
        return
    _fonts_ready = True
    font_files = [
        r"C:\Windows\Fonts\msyh.ttc",    # 微软雅黑
        r"C:\Windows\Fonts\msyhbd.ttc",  # 微软雅黑粗体
        r"C:\Windows\Fonts\simhei.ttf",  # 黑体
        r"C:\Windows\Fonts\simsun.ttc",  # 宋体
    ]
    names = []
    for fp in font_files:
        if os.path.exists(fp):
            try:
                fm.fontManager.addfont(fp)
                names.append(fm.FontProperties(fname=fp).get_name())
            except Exception:
                continue
    names += [
        "Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "PingFang SC",
        "WenQuanYi Micro Hei", "DejaVu Sans",
    ]
    plt.rcParams["font.sans-serif"] = names
    plt.rcParams["font.family"] = "sans-serif"

# 与前端一致的配色
INK = "#17202a"
INK_SOFT = "#26313d"
PAPER = "#f3f0e8"
SURFACE = "#fffdf8"
SURFACE_SOFT = "#ebe7dd"
LINE = "#d7d2c6"
MUTED = "#69727a"
QUIET = "#8c928f"
ACCENT = "#ee6547"
ACCENT_DARK = "#b9422e"
MINT = "#87c9b8"
MINT_DARK = "#2a7f72"

MAX_RATING = 15.5

# 七维能力（雷达图 + 强弱项），key 与 rating.AI_DIMENSION_NAMES 一致
RADAR_DIMS = [
    ("chartPower", "谱面底力", "#ee6547"),
    ("sustainedEndurance", "持续耐力", "#2a7f72"),
    ("burstSpeed", "爆发手速", "#e8a13a"),
    ("hitPrecision", "击打精度", "#5b7bd5"),
    ("patternControl", "配置处理", "#9b6bd5"),
    ("timingAdaptation", "节奏适应", "#d56b9b"),
    ("visualReading", "读谱", "#4a9bd5"),
]
_DIM_COLOR = {k: c for k, _n, c in RADAR_DIMS}
_DIM_NAME = {k: n for k, n, _c in RADAR_DIMS}


def _box(ax, x, y, w, h, fc, ec=None, r=0.02, zorder=1):
    """用轴坐标绘制圆角卡片。"""
    ax.add_patch(
        FancyBboxPatch(
            (x, y), w, h,
            boxstyle=f"round,pad=0,rounding_size={r}",
            transform=ax.transAxes, facecolor=fc, edgecolor=ec or "none",
            linewidth=1.2, zorder=zorder,
        )
    )


def _text(ax, x, y, s, size=12, color=INK, weight="normal", ha="left", va="center", zorder=3):
    ax.text(x, y, s, transform=ax.transAxes, fontsize=size, color=color,
            fontweight=weight, ha=ha, va=va, zorder=zorder)


def _level_label(level):
    return {4: "鬼", 5: "里"}.get(level, f"Lv.{level}")


def render_report_image(analysis: dict, out_path: str) -> str:
    """把分析结果渲染为 PNG，写到 out_path 并返回路径。"""
    _setup_fonts()
    summary = analysis.get("summary") or {}
    fa = analysis.get("featureAbility") or {}
    meta = analysis.get("meta") or {}
    counts = analysis.get("counts") or {}
    records = analysis.get("records") or []
    reference = analysis.get("ourTaikoV1") or {}

    rating = float(summary.get("rating") or 0)
    families = fa.get("families") or []
    fam_by_key = {f["key"]: f for f in families}
    scores = {f["key"]: float(f.get("score") or 0) for f in families if f.get("charts", 0) >= 3}
    strongest = fa.get("strengths") or []
    weakest = fa.get("weaknesses") or []

    fig = plt.figure(figsize=(7.2, 12.0), dpi=200)
    fig.patch.set_facecolor(PAPER)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    # ---------- 头部 ----------
    _text(ax, 0.045, 0.965, "鼓迹", 22, INK, "bold")
    _text(ax, 0.115, 0.968, "TAIKO TRACE", 10, ACCENT, "bold")
    _text(ax, 0.955, 0.972, f"PLAYER {meta.get('playerId') or '--'}", 11, INK, "bold", ha="right")
    _text(ax, 0.955, 0.953, f"{meta.get('server') or '--'} · AI v2", 9, MUTED, ha="right")
    ax.plot([0.045, 0.955], [0.945, 0.945], color=LINE, lw=1)

    # ---------- Hero：Rating 环 + 结论 ----------
    _box(ax, 0.045, 0.80, 0.30, 0.13, INK, r=0.02)
    _text(ax, 0.07, 0.915, "AI 综合 RATING", 8, MINT, "bold")
    # 环
    ring_ax = fig.add_axes([0.055, 0.805, 0.12, 0.105])
    ring_ax.set_aspect("equal")
    ring_ax.axis("off")
    ring_ax.add_patch(Wedge((0.5, 0.5), 0.95, 90, 450, width=0.22, facecolor="#3a4653"))
    frac = max(0.0, min(1.0, rating / MAX_RATING))
    ring_ax.add_patch(Wedge((0.5, 0.5), 0.95, 90, 90 + 360 * frac, width=0.22, facecolor=ACCENT))
    ring_ax.text(0.5, 0.55, f"{rating:.2f}", ha="center", va="center", fontsize=17,
                 color="white", fontweight="bold")
    ring_ax.text(0.5, 0.32, "/ 15.50", ha="center", va="center", fontsize=8, color="#8f9ca8")

    # 结论
    _box(ax, 0.365, 0.80, 0.59, 0.13, SURFACE, LINE, r=0.02)
    _text(ax, 0.385, 0.915, "本次关键结论", 9, ACCENT_DARK, "bold")
    if strongest and weakest:
        s_key, w_key = strongest[0]["key"], weakest[0]["key"]
        headline = f"{_DIM_NAME.get(s_key, s_key)}最突出，{_DIM_NAME.get(w_key, w_key)}是当前突破口"
    else:
        headline = "有效成绩已生成，能力证据仍待补充"
    _text(ax, 0.385, 0.885, headline, 13, INK, "bold")
    center = sum(scores.values()) / len(scores) if scores else 0
    if strongest and weakest:
        summary_txt = (f"七类能力最大差距 {float(strongest[0].get('score', 0)) - float(weakest[0].get('score', 0)):.2f}，"
                       f"下一轮优先补强「{_DIM_NAME.get(weakest[0]['key'], weakest[0]['key'])}」。")
    else:
        summary_txt = "当前数据不足以稳定比较七类能力，请继续积累鬼/里难度成绩。"
    _text(ax, 0.385, 0.845, summary_txt, 9, MUTED)
    tags = []
    if strongest:
        tags.append(f"优势·{_DIM_NAME.get(strongest[0]['key'])} {float(strongest[0].get('score', 0)):.2f}")
    if weakest:
        tags.append(f"补强·{_DIM_NAME.get(weakest[0]['key'])} {float(weakest[0].get('score', 0)):.2f}")
    _text(ax, 0.385, 0.815, " ｜ ".join(tags), 8.5, INK_SOFT)

    # ---------- 七维雷达 ----------
    _text(ax, 0.045, 0.775, "01 / 七项能力", 8, ACCENT_DARK, "bold")
    _text(ax, 0.045, 0.755, "看清强项与突破口", 14, INK, "bold")
    radar_ax = fig.add_axes([0.03, 0.42, 0.42, 0.31], polar=True)
    radar_ax.set_facecolor("none")
    angles = [i * 2 * math.pi / len(RADAR_DIMS) for i in range(len(RADAR_DIMS))]
    values = [scores.get(k, 0) for k, _n, _c in RADAR_DIMS]
    values.append(values[0])
    angles.append(angles[0])
    radar_ax.set_theta_offset(math.pi / 2)
    radar_ax.set_theta_direction(-1)
    radar_ax.set_ylim(0, MAX_RATING)
    radar_ax.set_yticks([3.875, 7.75, 11.625, 15.5])
    radar_ax.set_yticklabels([])
    radar_ax.set_xticks(angles[:-1])
    radar_ax.set_xticklabels([f"{n}\n{scores.get(k, 0):.1f}" for k, n, _c in RADAR_DIMS],
                             fontsize=8.5, color=INK)
    radar_ax.grid(True, color=LINE, lw=0.8)
    radar_ax.plot(angles, values, color=ACCENT, lw=2)
    radar_ax.fill(angles, values, color=ACCENT, alpha=0.18)
    for k, n, c in RADAR_DIMS:
        a = RADAR_DIMS.index((k, n, c)) * 2 * math.pi / len(RADAR_DIMS)
        radar_ax.plot([a, a], [0, scores.get(k, 0)], color=c, lw=1, alpha=0.35)

    # ---------- 强弱项 ----------
    _box(ax, 0.50, 0.42, 0.455, 0.31, SURFACE, LINE, r=0.02)
    _text(ax, 0.525, 0.715, "优势区 / 突破区", 9, ACCENT_DARK, "bold")
    y = 0.675
    for label, group in (("优势", strongest[:3]), ("短板", weakest[:3])):
        _text(ax, 0.525, y, label, 8.5, MUTED, "bold")
        for f in group:
            k = f["key"]
            name = _DIM_NAME.get(k, k)
            sc = float(f.get("score") or 0)
            color = _DIM_COLOR.get(k, ACCENT)
            y -= 0.045
            _text(ax, 0.535, y, name, 9.5, INK)
            _text(ax, 0.72, y, f"{sc:.2f}", 9.5, color, "bold")
            ax.add_patch(Rectangle((0.78, y - 0.007), 0.15, 0.012, transform=ax.transAxes,
                                   facecolor=SURFACE_SOFT, edgecolor="none"))
            ax.add_patch(Rectangle((0.78, y - 0.007), min(0.15, sc / MAX_RATING * 0.15), 0.012,
                                   transform=ax.transAxes, facecolor=color, edgecolor="none"))
        y -= 0.025

    # ---------- 表现证据 ----------
    _text(ax, 0.045, 0.385, "02 / 表现证据", 8, ACCENT_DARK, "bold")
    _text(ax, 0.045, 0.365, "最能代表上限的成绩", 14, INK, "bold")
    top = sorted(records, key=lambda r: -(r.get("rating") or 0))[:5]
    ey = 0.33
    for i, r in enumerate(top):
        title = (r.get("title") or f"Song {r.get('id')}")[:18]
        lvl = _level_label(r.get("level"))
        const = r.get("aiConstant") or r.get("constant") or 0
        acc = (r.get("accuracy") or 0) * 100
        rt = r.get("rating") or 0
        _text(ax, 0.055, ey, f"#{i + 1:02d}", 9, QUIET, "bold")
        _text(ax, 0.10, ey, f"《{title}》", 10, INK, "bold")
        _text(ax, 0.53, ey, lvl, 9, MUTED, "bold")
        _text(ax, 0.60, ey, f"定数{const:.1f}", 9, INK_SOFT)
        _text(ax, 0.73, ey, f"{acc:.2f}%", 9, INK_SOFT)
        _text(ax, 0.90, ey, f"{rt:.2f}", 11, INK, "bold", ha="right")
        ey -= 0.048

    # ---------- 指标条 ----------
    metrics = [
        ("有效谱面", str(meta.get("uniqueCharts") or 0), "去重后的最佳成绩"),
        ("v1 参考", f"{float(reference.get('summary', {}).get('rating') or 0):.2f}", "OurTaiko-v1 标尺"),
        ("低于阈值", str(counts.get("belowThreshold") or 0), "准确率 < 75%"),
        ("未匹配", str(counts.get("missing") or 0), "缺谱面特征"),
    ]
    mx = 0.045
    w = 0.215
    for label, value, note in metrics:
        _box(ax, mx, 0.055, w, 0.075, SURFACE, LINE, r=0.02)
        _text(ax, mx + 0.015, 0.108, label, 8, QUIET, "bold")
        _text(ax, mx + 0.015, 0.078, value, 13, INK_SOFT, "bold")
        _text(ax, mx + w - 0.01, 0.078, note, 7.5, MUTED, ha="right")
        mx += w + 0.018

    _text(ax, 0.045, 0.03, "星系为能力数据的静态表达，不代表历史趋势或官方竞技裁定。", 7.5, MUTED)

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    fig.savefig(out_path, facecolor=fig.get_facecolor())
    plt.close(fig)
    return out_path
