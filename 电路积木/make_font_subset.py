"""make_font_subset.py — 生成内置中文字体子集（改了源码里的新字符后重新跑一次）。

用法：
    python -m pip install fonttools
    python make_font_subset.py                 # 用已有的 NotoSansSC.ttf
    python make_font_subset.py path/to/NotoSansSC.ttf

原理：扫描所有 .py / .md 里出现过的字符 + ASCII + 常用符号，把 Noto Sans SC 子集化成
fonts/NotoSansSC-Subset.ttf（约 280KB）。这样游戏在任何没有中文字体的机器 / 手机上都能显示。
"""

from __future__ import annotations

import glob
import io
import os
import sys

EXTRA_SYMBOLS = "Ωμ°·×≈→←↑↓⚠✖✔％…—–‘’“”℃²³√∑∞"

DEFAULT_SOURCE = os.path.join("fonts", "NotoSansSC.ttf")
OUTPUT = os.path.join("fonts", "NotoSansSC-Subset.ttf")


def collect_characters() -> str:
    chars = {chr(code) for code in range(32, 127)}
    chars.update(EXTRA_SYMBOLS)
    patterns = ("*.py", "*.md", os.path.join("android", "*.md"))
    for pattern in patterns:
        for path in glob.glob(pattern):
            with io.open(path, encoding="utf-8") as handle:
                chars.update(handle.read())
    return "".join(sorted(chars))


def main() -> None:
    try:
        from fontTools import subset  # noqa: F401
    except ImportError:
        print("需要 fonttools：python -m pip install fonttools")
        raise SystemExit(1)

    source = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SOURCE
    if not os.path.exists(source):
        print(f"找不到源字体 {source}")
        print("可从 https://fonts.google.com/noto/specimen/Noto+Sans+SC 下载 Noto Sans SC（.ttf）")
        print("或直接 curl：")
        print(
            "  curl -L -o fonts/NotoSansSC.ttf "
            "https://fonts.gstatic.com/s/notosanssc/v36/"
            "k3kCo84MPvpLmixcA63oeAL7Iqp5IZJF9bmaG9_FnYxNbPzS5HE.ttf"
        )
        raise SystemExit(1)

    text = collect_characters()
    chars_file = "_subset_chars.txt"
    with io.open(chars_file, "w", encoding="utf-8") as handle:
        handle.write(text)
    try:
        args = [
            "pyftsubset",
            source,
            f"--text-file={chars_file}",
            f"--output-file={OUTPUT}",
            "--layout-features=*",
            "--glyph-names",
            "--symbol-cmap",
            "--legacy-cmap",
            "--notdef-glyph",
            "--notdef-outline",
            "--recommended-glyphs",
            "--name-IDs=*",
            "--name-legacy",
            "--name-languages=*",
        ]
        from fontTools import subset as _subset

        _subset.main(args[1:])
    finally:
        if os.path.exists(chars_file):
            os.remove(chars_file)
    size = os.path.getsize(OUTPUT)
    print(f"已生成 {OUTPUT}：{len(text)} 个字符，{size // 1024} KB")


if __name__ == "__main__":
    main()
