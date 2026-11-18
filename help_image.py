# -*- coding: utf-8 -*-
"""Render the RTLink guide as a kkz-web/VitePress styled long PNG."""

from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw

if __package__:
    from .command_catalog import BIND_SAKURA_USAGE, COMMAND_BY_NAME, user_command_rows
    from .report_image import _box, _text, _wrapped
else:
    from command_catalog import BIND_SAKURA_USAGE, COMMAND_BY_NAME, user_command_rows
    from report_image import _box, _text, _wrapped

WIDTH, HEIGHT = 1440, 9000
PLUGIN_DIR = Path(__file__).resolve().parent
ASSET_DIR = PLUGIN_DIR / "resource" / "help"

# kkz-web docs/.vitepress/theme/custom.css + VitePress light theme tokens.
BG = "#ffffff"
BG_ALT = "#f6f6f7"
TEXT = "#3c3c43"
TEXT_2 = "#67676c"
TEXT_3 = "#929295"
DIVIDER = "#e2e2e3"
BORDER = "#c2c2c4"
BRAND = "#684bd4"
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
    _text(draw, code, CONTENT_X + 26, y + 24, 18, BRAND_3, True)


def _step(draw, index, title, y):
    _text(draw, title, CONTENT_X, y, 25, TEXT, True)
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
    _text(draw, "指令", CONTENT_X + 24, y + 22, 21, TEXT, True)
    _text(draw, "用途", CONTENT_X + command_w + 24, y + 22, 21, TEXT, True)
    for index, (command, description) in enumerate(rows):
        row_y = y + row_h * (index + 1)
        draw.line((CONTENT_X, row_y, CONTENT_X + CONTENT_W, row_y), fill=DIVIDER, width=1)
        _box(draw, CONTENT_X + 20, row_y + 14, command_w - 40, 42, BRAND_SOFT, radius=7)
        _text(draw, command, CONTENT_X + 34, row_y + 22, 21, BRAND_3, True)
        _text(draw, description, CONTENT_X + command_w + 24, row_y + 22, 20, TEXT_2)
    return y + total_h


def _nav(image, draw):
    draw.rectangle((0, 0, WIDTH, 96), fill=BG)
    draw.line((0, 95, WIDTH, 95), fill=DIVIDER, width=1)
    with Image.open(PLUGIN_DIR / "logo.png") as source:
        logo = source.convert("RGBA").resize((52, 52), Image.Resampling.LANCZOS)
    image.paste(logo, (54, 22), logo)
    _text(draw, "RTLink · 可可子", 124, 31, 21, TEXT, True)


def render_help_image(out_path: str) -> str:
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)
    _nav(image, draw)

    _text(draw, "插件说明", CONTENT_X, 142, 14, BRAND, True)
    _text(draw, "太鼓成绩评级（rt_link）", CONTENT_X, 190, 48, TEXT, True)
    _wrapped(
        draw,
        "绑定菌菌或 Sakura，独立保存各来源成绩，并用鼓迹 AI v2 评估玩家实力与节奏型弱项。",
        CONTENT_X,
        270,
        CONTENT_W,
        19,
        32,
        TEXT_2,
        False,
        2,
    )
    commands_y = 360
    _heading(draw, "指令速查", commands_y)
    table_end = _table(draw, commands_y + 92, user_command_rows())
    _custom_block(
        draw,
        table_end + 34,
        "用自然语言查询",
        "查自己的成绩可以问「可可子，我的实力怎么样」「可可子，我该练什么」「可可子，我的夏祭成绩是多少」。\n"
        "查可可子自有成绩可以问「可可子，你的夏祭成绩是多少」。该账号由管理员在 AstrBot WebUI 设置。",
        "tip",
        146,
    )

    kinoko_y = table_end + 224
    _heading(draw, "绑定菌菌账号", kinoko_y)
    _custom_block(
        draw,
        kinoko_y + 92,
        "绑定前请注意",
        "请在与可可子的 QQ 私聊中发送绑定指令，留存凭据时注意遮挡。菌菌和 Sakura 的绑定、缓存、成绩与历史独立保存。",
        "warning",
        126,
    )

    _step(draw, 1, "进入个人 API 密钥页面", kinoko_y + 264)
    _text(draw, "① 左侧选择「账号信息」　② 进入「第三方访问」　③ 点击「新建密钥」", CONTENT_X, kinoko_y + 316, 17, TEXT_2)
    end = _screenshot(image, draw, "apikey-create-entry.png", kinoko_y + 368)

    _step(draw, 2, "给密钥命名", end + 72)
    _wrapped(draw, "名称可以自定义，建议使用容易辨认用途的名字，例如「可可子-rtlink」，然后点击「创建」。", CONTENT_X, end + 126, CONTENT_W, 17, 28, TEXT_2, False, 2)
    end = _screenshot(image, draw, "apikey-name.png", end + 190)

    _step(draw, 3, "复制 apikey", end + 72)
    _wrapped(draw, "点击「复制密钥」，或手动复制以 tk_ 开头的全部内容。之后也可以回到密钥列表重新显示并复制。", CONTENT_X, end + 126, CONTENT_W, 17, 28, TEXT_2, False, 2)
    end = _screenshot(image, draw, "apikey-copy.png", end + 190)
    _custom_block(
        draw,
        end + 42,
        "保护 API 密钥",
        "截图求助时请完整遮挡密钥。如果密钥泄露，请删除旧密钥并重新创建。",
        "danger",
        132,
    )

    step4_y = end + 232
    _step(draw, 4, "在 QQ 私聊中绑定 RTLink", step4_y)
    _text(draw, "打开与可可子的 QQ 私聊，填写密钥和玩家 ID。", CONTENT_X, step4_y + 56, 17, TEXT_2)
    _code_block(draw, step4_y + 100, COMMAND_BY_NAME["bind"].usage)
    _text(draw, "用完整的 tk_ 密钥和太鼓玩家 ID。省略 server 时读取插件配置，出厂值为 cn。", CONTENT_X, step4_y + 198, 16, TEXT_2)
    _code_block(draw, step4_y + 246, "/rtlink bind tk_xxx 30053354 cn")
    end = _screenshot(image, draw, "qq-bind.png", step4_y + 356)
    _custom_block(
        draw,
        end + 40,
        "绑定完成",
        "绑定成功后自动选择菌菌。发送 /rtlink 立即同步并生成个人画像。",
        "tip",
        112,
    )

    sakura_y = end + 214
    _heading(draw, "绑定 Sakura 账号与切换数据源", sakura_y)
    _wrapped(draw, "登录 viewer.sakura-bot.cn，在个人账户的「多端同步」中生成 48 位 token，再私聊发送给可可子。", CONTENT_X, sakura_y + 86, CONTENT_W, 18, 30, TEXT_2)
    _code_block(draw, sakura_y + 140, BIND_SAKURA_USAGE)
    _wrapped(
        draw,
        "绑定成功后自动选择 Sakura。发送 /rtlink source 查看当前数据源。\n"
        "发送 /rtlink source kinoko 或 /rtlink source sakura 切换到已绑定的来源。\n"
        "发送 /rtlink unbind 解绑当前来源，历史成绩保留。",
        CONTENT_X, sakura_y + 238, CONTENT_W, 18, 30, TEXT_2,
    )

    reference_y = sakura_y + 385
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
        "成功同步且评分输入变化时保存历史",
        "历史数据位于 AstrBot 持久化目录",
    ]
    for index, line in enumerate(notes):
        draw.ellipse((right_x + 28, card_y + 84 + index * 48, right_x + 38, card_y + 94 + index * 48), fill=BRAND)
        _text(draw, line, right_x + 54, card_y + 75 + index * 48, 15, TEXT_2)
    _text(draw, "apikey / token 不会写入评级历史快照", right_x + 26, card_y + 330, 15, DANGER, True)

    footer_y = card_y + 444
    draw.line((CONTENT_X, footer_y, CONTENT_X + CONTENT_W, footer_y), fill=DIVIDER, width=1)
    _text(draw, "可可子功能与插件使用说明", CONTENT_X, footer_y + 28, 14, TEXT_3)
    _text(draw, "太鼓成绩评级 · rt_link", CONTENT_X + CONTENT_W, footer_y + 28, 14, BRAND, True, "right")

    output = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(output), exist_ok=True)
    image = image.crop((0, 0, WIDTH, min(HEIGHT, footer_y + 82)))
    image.save(output, "PNG", compress_level=6)
    return output
