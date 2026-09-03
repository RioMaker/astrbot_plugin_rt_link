# -*- coding: utf-8 -*-
"""Render the RTLink guide as a kkz-web/VitePress styled long PNG."""

from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw

if __package__:
    from .report_image import _box, _text, _wrapped
else:
    from report_image import _box, _text, _wrapped

WIDTH, HEIGHT = 1440, 8200
ASSET_DIR = Path(__file__).resolve().parent / "resource" / "help"

# kkz-web docs/.vitepress/theme/custom.css + VitePress light theme tokens.
BG = "#ffffff"
BG_ALT = "#f6f6f7"
TEXT = "#3c3c43"
TEXT_2 = "#67676c"
TEXT_3 = "#929295"
DIVIDER = "#e2e2e3"
BORDER = "#c2c2c4"
BRAND = "#6f54d5"
BRAND_2 = "#8066e3"
BRAND_3 = "#5f43c7"
BRAND_SOFT = "#f0edf9"
TIP_SOFT = "#f2effa"
WARNING = "#915930"
WARNING_SOFT = "#fff6e5"
DANGER = "#b8272c"
DANGER_SOFT = "#fdecef"
CONTENT_X, CONTENT_W = 160, 1120


def _heading(draw, text, y, level=2):
    size = 34 if level == 2 else 25
    _text(draw, text, CONTENT_X, y, size, TEXT, True)
    if level == 2:
        draw.line((CONTENT_X, y + 62, CONTENT_X + CONTENT_W, y + 62), fill=DIVIDER, width=2)


def _custom_block(draw, y, title, body, kind="tip", height=126):
    styles = {
        "tip": (TIP_SOFT, BRAND, BRAND),
        "warning": (WARNING_SOFT, WARNING, WARNING),
        "danger": (DANGER_SOFT, DANGER, DANGER),
    }
    fill, accent, title_color = styles[kind]
    _box(draw, CONTENT_X, y, CONTENT_W, height, fill, radius=12)
    draw.rounded_rectangle((CONTENT_X, y, CONTENT_X + 6, y + height), radius=3, fill=accent)
    _text(draw, title, CONTENT_X + 28, y + 23, 17, title_color, True)
    _wrapped(draw, body, CONTENT_X + 28, y + 57, CONTENT_W - 56, 16, 27, TEXT, False, 3)


def _code_block(draw, y, code, height=74):
    _box(draw, CONTENT_X, y, CONTENT_W, height, BG_ALT, radius=12)
    _text(draw, "TEXT", CONTENT_X + CONTENT_W - 24, y + 16, 11, TEXT_3, True, "right")
    _text(draw, code, CONTENT_X + 26, y + 24, 18, BRAND_3, True)


def _step(draw, index, title, y):
    _text(draw, f"步骤 {index}/4：{title}", CONTENT_X, y, 25, TEXT, True)
    _box(draw, CONTENT_X - 48, y + 2, 32, 32, BRAND, radius=16)
    _text(draw, str(index), CONTENT_X - 32, y + 8, 13, "#ffffff", True, "center")


def _paste_rounded(image, source, x, y, radius=12):
    mask = Image.new("L", source.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, source.width - 1, source.height - 1), radius=radius, fill=255)
    image.paste(source, (x, y), mask)


def _screenshot(image, draw, filename, y, target_width=None):
    with Image.open(ASSET_DIR / filename) as source:
        shot = source.convert("RGB")
    width = int(target_width or shot.width)
    height = round(shot.height * width / shot.width)
    if shot.size != (width, height):
        shot = shot.resize((width, height), Image.Resampling.LANCZOS)
    x = (WIDTH - width) // 2
    # VitePress content image: subtle divider, 12px radius, no ornamental frame.
    draw.rounded_rectangle((x - 1, y - 1, x + width, y + height), radius=13, fill=DIVIDER)
    _paste_rounded(image, shot, x, y, 12)
    return y + height


def _table(draw, y, rows):
    command_w, row_h = 490, 70
    total_h = row_h * (len(rows) + 1)
    draw.rounded_rectangle(
        (CONTENT_X, y, CONTENT_X + CONTENT_W, y + total_h),
        radius=12,
        fill=BG,
        outline=DIVIDER,
        width=2,
    )
    draw.rounded_rectangle(
        (CONTENT_X + 1, y + 1, CONTENT_X + CONTENT_W - 1, y + row_h),
        radius=11,
        fill=BG_ALT,
    )
    draw.rectangle((CONTENT_X + 1, y + row_h - 12, CONTENT_X + CONTENT_W - 1, y + row_h), fill=BG_ALT)
    _text(draw, "指令", CONTENT_X + 24, y + 22, 16, TEXT, True)
    _text(draw, "用途", CONTENT_X + command_w + 24, y + 22, 16, TEXT, True)
    for index, (command, description) in enumerate(rows):
        row_y = y + row_h * (index + 1)
        draw.line((CONTENT_X, row_y, CONTENT_X + CONTENT_W, row_y), fill=DIVIDER, width=1)
        _box(draw, CONTENT_X + 20, row_y + 17, command_w - 40, 36, BRAND_SOFT, radius=7)
        _text(draw, command, CONTENT_X + 34, row_y + 24, 14, BRAND_3, True)
        _text(draw, description, CONTENT_X + command_w + 24, row_y + 23, 15, TEXT_2)
    return y + total_h


def _nav(image, draw):
    draw.rectangle((0, 0, WIDTH, 96), fill=BG)
    draw.line((0, 95, WIDTH, 95), fill=DIVIDER, width=1)
    with Image.open(ASSET_DIR / "kkz-logo.png") as source:
        logo = source.convert("RGBA").resize((52, 52), Image.Resampling.LANCZOS)
    mask = Image.new("L", (52, 52), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, 51, 51), radius=10, fill=255)
    image.paste(logo, (54, 22), mask)
    _text(draw, "可可子说明", 124, 31, 21, TEXT, True)
    nav = ["首页", "认识可可子", "插件说明", "指令速查", "更新记录"]
    x = 720
    for label in nav:
        color = BRAND if label == "插件说明" else TEXT_2
        _text(draw, label, x, 36, 15, color, label == "插件说明")
        x += 128


def render_help_image(out_path: str) -> str:
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)
    _nav(image, draw)

    _text(draw, "插件说明  /  太鼓成绩评级", CONTENT_X, 142, 14, BRAND, True)
    _text(draw, "太鼓成绩评级（rt_link）", CONTENT_X, 190, 48, TEXT, True)
    _wrapped(
        draw,
        "绑定菌菌控制台 apikey，查询太鼓达人成绩，并用鼓迹 AI v2 评估玩家实力与节奏型弱项。",
        CONTENT_X,
        270,
        CONTENT_W,
        19,
        32,
        TEXT_2,
        False,
        2,
    )
    _custom_block(
        draw,
        360,
        "两种帮助入口",
        "发送 /rtlink help 或 /rtlink 帮助，都会返回这一张完整说明长图。裸 /rtlink 默认生成 Rating 实力画像。",
        "tip",
        132,
    )

    _heading(draw, "从菌菌控制台获取 apikey 并完成绑定", 550)
    _text(draw, "完整绑定共 4 步：进入 API 密钥页面、创建并命名密钥、复制 apikey、在 QQ 私聊中完成绑定。", CONTENT_X, 638, 17, TEXT_2)
    _custom_block(
        draw,
        690,
        "绑定前请注意",
        "apikey 相当于账号访问凭证。不要把完整 apikey 发到群聊、公开页面或交给其他人；绑定指令只能在与可可子的私聊中发送。",
        "warning",
        138,
    )

    _step(draw, 1, "进入个人 API 密钥页面", 886)
    _text(draw, "① 左侧选择「账号信息」　② 进入「第三方访问」　③ 点击「新建密钥」", CONTENT_X, 938, 17, TEXT_2)
    end = _screenshot(image, draw, "apikey-create-entry.png", 990)

    _step(draw, 2, "给密钥命名", end + 72)
    _wrapped(draw, "名称可以自定义，建议使用容易辨认用途的名字，例如「可可子-rtlink」，然后点击「创建」。", CONTENT_X, end + 126, CONTENT_W, 17, 28, TEXT_2, False, 2)
    end = _screenshot(image, draw, "apikey-name.png", end + 190)

    _step(draw, 3, "复制 apikey", end + 72)
    _wrapped(draw, "点击「复制密钥」，或手动复制以 tk_ 开头的全部内容。之后也可以回到密钥列表重新显示并复制。", CONTENT_X, end + 126, CONTENT_W, 17, 28, TEXT_2, False, 2)
    end = _screenshot(image, draw, "apikey-copy.png", end + 190)
    _custom_block(
        draw,
        end + 42,
        "不要公开 apikey",
        "文档截图中的敏感内容已经遮挡。截图求助时也应遮住完整密钥；如果密钥泄露，请立即删除旧密钥并重新创建。",
        "danger",
        132,
    )

    step4_y = end + 232
    _step(draw, 4, "在 QQ 私聊中绑定 RTLink", step4_y)
    _text(draw, "打开与可可子的 QQ 私聊，发送以下指令：", CONTENT_X, step4_y + 56, 17, TEXT_2)
    _code_block(draw, step4_y + 100, "/rtlink bind <apikey> <player_id> [server]")
    _text(draw, "apikey：完整 tk_ 密钥　　player_id：太鼓玩家 ID　　server：可省略，默认 cn", CONTENT_X, step4_y + 198, 16, TEXT_2)
    _code_block(draw, step4_y + 246, "/rtlink bind tk_xxx 30053354 cn")
    end = _screenshot(image, draw, "qq-bind.png", step4_y + 356)
    _custom_block(
        draw,
        end + 40,
        "绑定完成",
        "收到绑定成功提示后，可发送 /rtlink 检查成绩读取。需要解绑时发送 /rtlink unbind。",
        "tip",
        112,
    )

    commands_y = end + 214
    _heading(draw, "常用指令", commands_y)
    rows = [
        ("/rtlink", "生成完整 Rating 实力画像"),
        ("/rtlink score <曲名>", "查询指定曲目成绩"),
        ("/rtlink rating", "Rating、七维、强弱项与冷门配置"),
        ("/rtlink profile", "生成个人强项 / 弱项画像"),
        ("/rtlink weakness", "生成节奏型弱项与练习建议"),
        ("/rtlink update", "重新拉取成绩并记录历史快照"),
        ("/rtlink alias <曲名> <别名>", "申请歌曲别名，等待管理员审核"),
        ("/rtlink help / 帮助", "查看本说明长图"),
        ("/rtlink about", "查看插件版本与简介"),
    ]
    table_end = _table(draw, commands_y + 92, rows)
    _custom_block(
        draw,
        table_end + 34,
        "也可以自然语言询问",
        "例如：“可可子，我的实力怎么样”“可可子，我该练什么”“可可子，我的夏祭成绩是多少”。查分支持「鬼夏祭」「里夏祭」这类难度前缀组合名。",
        "tip",
        126,
    )

    reference_y = table_end + 224
    _heading(draw, "难度别名与评级说明", reference_y)
    card_y = reference_y + 94
    _box(draw, CONTENT_X, card_y, 535, 380, BG_ALT, radius=16)
    _text(draw, "难度别名", CONTENT_X + 26, card_y + 26, 20, TEXT, True)
    difficulties = [
        "鬼 / 魔王 / 4 / oni / mania",
        "里 / 里鬼 / 里魔王 / 5 / ura",
        "松 / 困难 / 3 / hard",
        "竹 / 一般 / 普通 / 2 / normal",
        "梅 / 简单 / 1 / easy",
    ]
    for index, line in enumerate(difficulties):
        _text(draw, line, CONTENT_X + 26, card_y + 78 + index * 48, 16, TEXT_2)
    _text(draw, "仅鬼 / 里（4 / 5）参与 Rating", CONTENT_X + 26, card_y + 330, 15, BRAND, True)

    right_x = CONTENT_X + 563
    _box(draw, right_x, card_y, 557, 380, BG_ALT, radius=16)
    _text(draw, "评级与记录", right_x + 26, card_y + 26, 20, TEXT, True)
    notes = [
        "主 Rating：鼓迹 AI v2",
        "七维：底力、耐力、手速、精度、配置、节奏、读谱",
        "冷门配置独立观察，不混入核心弱项排行",
        "获取 Rating 或 update 时追加历史快照",
        "历史数据位于 AstrBot 持久化目录",
    ]
    for index, line in enumerate(notes):
        draw.ellipse((right_x + 28, card_y + 84 + index * 48, right_x + 38, card_y + 94 + index * 48), fill=BRAND)
        _text(draw, line, right_x + 54, card_y + 75 + index * 48, 15, TEXT_2)
    _text(draw, "apikey 不会发送给 AI 或写入历史快照", right_x + 26, card_y + 330, 15, DANGER, True)

    footer_y = card_y + 444
    draw.line((CONTENT_X, footer_y, CONTENT_X + CONTENT_W, footer_y), fill=DIVIDER, width=1)
    _text(draw, "可可子功能与插件使用说明", CONTENT_X, footer_y + 28, 14, TEXT_3)
    _text(draw, "太鼓成绩评级 · rt_link", CONTENT_X + CONTENT_W, footer_y + 28, 14, BRAND, True, "right")

    output = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(output), exist_ok=True)
    image = image.crop((0, 0, WIDTH, min(HEIGHT, footer_y + 82)))
    image.save(output, "PNG", compress_level=6)
    return output
