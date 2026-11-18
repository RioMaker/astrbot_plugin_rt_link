# -*- coding: utf-8 -*-
"""RTLink 完整帮助长图回归测试。"""

import os
import sys
from pathlib import Path

from PIL import Image

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

from command_catalog import (  # noqa: E402
    BIND_SAKURA_USAGE,
    COMMANDS,
    IMPROVE_SHORT_USAGE,
    LIBRARY_RETRY_USAGE,
    user_command_rows,
)
from help_image import ASSET_DIR, HEIGHT, render_help_image  # noqa: E402


def test_all_kkz_rtlink_tutorial_assets_are_packaged():
    expected = {
        "kkz-logo.png": (1024, 1024),
        "apikey-create-entry.png": (721, 961),
        "apikey-name.png": (721, 961),
        "apikey-copy.png": (721, 961),
        "qq-bind.png": (528, 1147),
    }
    for filename, size in expected.items():
        path = ASSET_DIR / filename
        assert path.is_file()
        with Image.open(path) as image:
            assert image.size == size


def test_help_image_renders_as_one_readable_long_png(tmp_path: Path):
    output = render_help_image(str(tmp_path / "rtlink-help.png"))
    with Image.open(output) as image:
        assert image.width == 1440
        assert 7000 <= image.height < HEIGHT
        assert image.mode == "RGB"


def test_natural_language_examples_include_ai_wake_prefix():
    source = (Path(_PROJECT_ROOT) / "help_image.py").read_text(encoding="utf-8")
    assert "可可子，我的实力怎么样" in source
    assert "可可子，我该练什么" in source
    assert "可可子，我的夏祭成绩是多少" in source
    assert "可可子，你的夏祭成绩是多少" in source


def test_help_reference_lists_all_public_commands_and_aliases():
    rows = dict(user_command_rows())
    assert all((command.usage in rows) != command.admin_only for command in COMMANDS)
    assert {"/rtlink", BIND_SAKURA_USAGE, IMPROVE_SHORT_USAGE}.issubset(rows)
    assert LIBRARY_RETRY_USAGE not in rows
    assert all(
        alias in rows[command.usage]
        for command in COMMANDS if not command.admin_only
        for alias in command.aliases
    )
