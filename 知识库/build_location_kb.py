#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
合并 locations_classified.csv 与 location_normalization_llm.json，生成：
- location_pipeline_out/location_kb.json：标准节点 + 归并后的别名 + 父级 + 来源统计
- location_pipeline_out/location_mention_map.json：每条 (地点, source) 的归一结果（供事件替换与溯源）

须先运行：location_normalization_pipeline.py；再运行 normalize_location_mentions_llm.py（可选，未运行则 LLM 类行记为 unknown）。
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
PIPELINE_OUT = SCRIPT_DIR / "location_pipeline_out"
CLASSIFIED_CSV = PIPELINE_OUT / "locations_classified.csv"
STANDARD_CSV = SCRIPT_DIR / "地点知识库" / "红楼梦地点表.csv"
LLM_INPUT = PIPELINE_OUT / "llm_location_normalization_input.json"
LLM_OUTPUT = PIPELINE_OUT / "location_normalization_llm.json"
KB_JSON = PIPELINE_OUT / "location_kb.json"
MENTION_MAP_JSON = PIPELINE_OUT / "location_mention_map.json"


def load_parent_map(path: Path) -> dict[str, str]:
    m: dict[str, str] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            sl = (row.get("standard_location") or "").strip()
            if not sl:
                continue
            m[sl] = (row.get("parent_location") or "").strip()
    return m


def load_llm_zip() -> dict[tuple[str, str], dict[str, Any]]:
    """(original_location, source) -> LLM 结果行。"""
    if not LLM_INPUT.is_file() or not LLM_OUTPUT.is_file():
        return {}
    inp = json.loads(LLM_INPUT.read_text(encoding="utf-8"))
    out = json.loads(LLM_OUTPUT.read_text(encoding="utf-8"))
    items = inp.get("items") or []
    results = out.get("results") or []
    if len(items) != len(results):
        print(
            f"警告: LLM 输入 items({len(items)}) 与现有输出 results({len(results)}) 条数不一致，"
            "已忽略旧 LLM 结果；请重新运行 normalize_location_mentions_llm.py 生成新结果。"
        )
        return {}
    z: dict[tuple[str, str], dict[str, Any]] = {}
    for it, r in zip(items, results):
        loc = (it.get("original_location") or "").strip()
        src = (it.get("source") or "").strip()
        z[(loc, src)] = r
    return z


def resolve_canonical(
    row: dict[str, str],
    llm_zip: dict[tuple[str, str], dict[str, Any]],
) -> tuple[str, dict[str, Any] | None]:
    """返回 (resolved_canonical_or_flag, llm_row_or_none)。flag 为 generic | unknown 或标准名。"""
    loc = row["location"]
    src = row["source"]
    lt = row.get("location_type") or ""

    if lt == "canonical":
        return loc, None
    if lt == "generic":
        return "generic", None

    r = llm_zip.get((loc, src))
    if not r:
        return "unknown", None
    c = (r.get("canonical_location") or "").strip()
    return c, r


def main() -> None:
    parser = argparse.ArgumentParser(description="合并分类结果与 LLM，生成 location_kb 与 mention 映射")
    parser.parse_args()

    if not CLASSIFIED_CSV.is_file():
        raise FileNotFoundError(f"缺少 {CLASSIFIED_CSV}，请先运行 location_normalization_pipeline.py")

    parent_map = load_parent_map(STANDARD_CSV)
    std_keys = set(parent_map.keys())
    llm_zip = load_llm_zip()

    classified: list[dict[str, str]] = []
    with CLASSIFIED_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            classified.append({k: (v or "").strip() for k, v in row.items()})

    mention_map: list[dict[str, Any]] = []
    # canonical -> 聚合
    agg: dict[str, dict[str, Any]] = {}

    for row in classified:
        loc = row["location"]
        src = row["source"]
        resolved, llm_row = resolve_canonical(row, llm_zip)

        entry: dict[str, Any] = {
            "original_location": loc,
            "source": src,
            "location_type": row.get("location_type"),
            "rule_note": row.get("rule_note"),
            "occurrence_count": int(row.get("occurrence_count") or 0),
            "file_count": int(row.get("file_count") or 0),
            "json_paths": row.get("json_paths") or "",
            "resolved_location": resolved,
        }
        if llm_row:
            entry["llm_confidence"] = llm_row.get("confidence")
            entry["llm_reason"] = llm_row.get("reason")
        if resolved not in ("generic", "unknown") and resolved not in std_keys:
            entry["warning"] = "resolved_not_in_standard_table"
        mention_map.append(entry)

        if resolved in ("generic", "unknown"):
            continue
        if resolved not in std_keys:
            continue

        if resolved not in agg:
            agg[resolved] = {
                "canonical_location": resolved,
                "aliases": set(),
                "sources": set(),
                "occurrence_total": 0,
            }
        a = agg[resolved]
        a["sources"].add(src)
        a["occurrence_total"] += int(row.get("occurrence_count") or 0)
        if loc != resolved:
            a["aliases"].add(loc)

    kb_list: list[dict[str, Any]] = []
    for canon in sorted(agg.keys()):
        a = agg[canon]
        kb_list.append(
            {
                "canonical_location": canon,
                "aliases": sorted(a["aliases"]),
                "sources": sorted(a["sources"]),
                "parent_location": parent_map.get(canon, ""),
                "occurrence_total": a["occurrence_total"],
            }
        )

    meta = {
        "description": "resolved_location 为 generic/unknown 的不进入 location_kb 节点列表；事件侧可按 mention_map 替换或过滤",
        "kb_node_count": len(kb_list),
        "mention_map_rows": len(mention_map),
        "llm_merged": bool(llm_zip),
    }

    KB_JSON.write_text(
        json.dumps({"meta": meta, "locations": kb_list}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    MENTION_MAP_JSON.write_text(
        json.dumps({"meta": meta, "rows": mention_map}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"已写入: {KB_JSON}")
    print(f"已写入: {MENTION_MAP_JSON}")
    print(f"KB 节点数: {len(kb_list)}，mention 行数: {len(mention_map)}，已合并 LLM: {bool(llm_zip)}")


if __name__ == "__main__":
    main()
