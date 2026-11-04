"""
《红楼梦》统一事件表示 — 入口脚本。

流程：
1. ueo_core：批量读取 JSON → 结构统一 + 规则 semantic_core + keywords
2. ueo_export：写出 unified_events.json / unified_events.csv

子模块：
- ueo_config.py   路径配置
- ueo_core.py     规则层与单条组装
- ueo_export.py   导出
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ueo_config import (
    OUTPUT_CSV,
    OUTPUT_JSON,
    TEXT_DIR,
    VIDEO_DIR,
)
from ueo_core import build_unified_event as _build_unified_event_core
from ueo_core import load_text_events, load_video_events
from ueo_export import export_results

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None  # type: ignore[misc, assignment]


def build_unified_event(
    item: dict,
    use_llm_semantic_core: bool | None = None,  # 兼容旧签名，参数不再生效
) -> dict:
    _ = use_llm_semantic_core
    return _build_unified_event_core(item)


def build_unified_events(
    video_dir: Path = VIDEO_DIR,
    text_dir: Path = TEXT_DIR,
    output_json: Path = OUTPUT_JSON,
    output_csv: Path = OUTPUT_CSV,
    use_llm_semantic_core: bool | None = None,  # 兼容旧签名，参数不再生效
    llm_batch_size: int | None = None,  # 兼容旧签名，参数不再生效
) -> list[dict]:
    """纯规则批量处理：结构统一并导出 JSON / CSV。"""
    video_items = load_video_events(video_dir)
    text_items = load_text_events(text_dir)
    all_items = video_items + text_items

    _ = use_llm_semantic_core
    _ = llm_batch_size

    iterator: Any = all_items
    if tqdm is not None:
        iterator = tqdm(all_items, desc="结构统一（规则层）", unit="条")

    unified_events: list[dict] = []
    for item in iterator:
        unified_events.append(_build_unified_event_core(item))

    export_results(unified_events, output_json, output_csv)
    return unified_events


def main() -> None:
    unified_events = build_unified_events()
    video_count = sum(1 for x in unified_events if x["modality"] == "video")
    text_count = sum(1 for x in unified_events if x["modality"] == "text")
    print(f"完成统一表示构建：总事件 {len(unified_events)} 条")
    print(f"- 视频事件: {video_count}")
    print(f"- 文本事件: {text_count}")
    print("- semantic_core：仅规则生成（已移除 LLM 压缩层）")
    print(f"- JSON 输出: {OUTPUT_JSON}")
    print(f"- CSV  输出: {OUTPUT_CSV}")
    if tqdm is None:
        print(
            "提示：安装 tqdm 可获得更顺滑的条级进度条：pip install tqdm",
            flush=True,
        )


if __name__ == "__main__":
    main()
