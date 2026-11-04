# -*- coding: utf-8 -*-
"""
将《红楼梦（原文版）.txt》按「第…回」标题拆成 120 个独立 txt 文件。

标题行格式示例：
  第一回 甄士隐梦幻识通灵 贾雨村风尘怀闺秀
  第一百二零回 甄士隐详说太虚情　贾雨村归结红楼梦

输出目录：项目根目录下的「红楼梦文本」文件夹，文件名为 第001回.txt … 第120回.txt
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# 仅匹配独立成行的回目：「第」+ 中文数字 + 「回」+ 空白 + 回名
CHAPTER_LINE = re.compile(r"^第[一二三四五六七八九十百千万零两]+回\s")

# 默认路径（项目根目录）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = PROJECT_ROOT / "红楼梦（原文版）.txt"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "红楼梦文本"
EXPECTED_CHAPTERS = 120


def split_chapters(source: Path, output_dir: Path) -> None:
    text = source.read_text(encoding="utf-8")
    lines = text.splitlines()

    starts: list[int] = []
    for i, line in enumerate(lines):
        if CHAPTER_LINE.match(line):
            starts.append(i)

    if len(starts) != EXPECTED_CHAPTERS:
        sys.exit(
            f"期望找到 {EXPECTED_CHAPTERS} 个回目标题，实际 {len(starts)} 个。"
            f"请检查源文件或正则是否需要调整。"
        )

    output_dir.mkdir(parents=True, exist_ok=True)

    for n, start in enumerate(starts, start=1):
        end = starts[n] if n < len(starts) else len(lines)
        chunk = "\n".join(lines[start:end])
        if chunk and not chunk.endswith("\n"):
            chunk += "\n"
        out_file = output_dir / f"第{n:03d}回.txt"
        out_file.write_text(chunk, encoding="utf-8")
        print(f"已写入: {out_file.name}")


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(description="按回目拆分红楼梦全文 txt")
    p.add_argument(
        "-i",
        "--input",
        type=Path,
        default=DEFAULT_SOURCE,
        help=f"源 txt 路径（默认: {DEFAULT_SOURCE}）",
    )
    p.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"输出目录（默认: {DEFAULT_OUTPUT_DIR}）",
    )
    args = p.parse_args()

    if not args.input.is_file():
        sys.exit(f"找不到源文件: {args.input}")

    split_chapters(args.input, args.output_dir)
    print(f"完成：共 {EXPECTED_CHAPTERS} 个文件 -> {args.output_dir}")


if __name__ == "__main__":
    main()
