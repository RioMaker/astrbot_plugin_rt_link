# -*- coding: utf-8 -*-
"""RTLink 完整帮助长图回归测试。"""

import os
import sys
from pathlib import Path

from PIL import Image

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

from help_image import ASSET_DIR, render_help_image  # noqa: E402


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
        assert image.height >= 7000
        assert image.mode == "RGB"


def test_natural_language_examples_include_ai_wake_prefix():
    source = (Path(_PROJECT_ROOT) / "help_image.py").read_text(encoding="utf-8")
    assert "可可子，我的实力怎么样" in source
    assert "可可子，我该练什么" in source
    assert "可可子，我的夏祭成绩是多少" in source
