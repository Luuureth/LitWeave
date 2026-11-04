#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将 mention_normalization_llm.json 整理为与 sample_character_kb.json 相同结构的
人物知识库 JSON：每个标准人物一条，aliases 为映射到该人的 mention（不含与标准名完全相同的重复）。

可选：从 alias_for_llm.json 汇总各 mention 出现的 source（txt / video），写入每条 sources。
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PIPELINE_OUT = SCRIPT_DIR / "character_pipeline_out"
NORM_JSON = PIPELINE_OUT / "mention_normalization_llm.json"
ALIAS_JSON = PIPELINE_OUT / "alias_for_llm.json"
OUTPUT_JSON = PIPELINE_OUT / "character_kb.json"


def load_mention_sources(path: Path) -> dict[str, set[str]]:
    """character -> {txt, video}"""
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, set[str]] = defaultdict(set)
    for row in data:
        if not isinstance(row, dict):
            continue
        ch = (row.get("character") or "").strip()
        src = (row.get("source") or "").strip().lower()
        if ch and src in ("txt", "video"):
            out[ch].add(src)
    return dict(out)


def build_kb(
    norm_path: Path,
    mention_sources: dict[str, set[str]],
) -> list[dict]:
    data = json.loads(norm_path.read_text(encoding="utf-8"))
    results = data.get("results") or []

    # 所有出现过映射的标准名（含仅「mention == 标准名」自映射）
    all_canon: set[str] = set()
    # canonical_name -> set of alias mentions（mention 与标准名不同才记入别称）
    aliases_by_canon: dict[str, set[str]] = defaultdict(set)
    reasons_by_canon: dict[str, set[str]] = defaultdict(set)

    for r in results:
        if not isinstance(r, dict):
            continue
        canon = (r.get("canonical_name") or "").strip()
        if not canon or canon == "unknown":
            continue
        mention = (r.get("mention") or "").strip()
        if not mention:
            continue
        all_canon.add(canon)
        if mention != canon:
            aliases_by_canon[canon].add(mention)
        reason = (r.get("reason") or "").strip()
        if reason:
            reasons_by_canon[canon].add(reason)

    entries: list[dict] = []
    for canon in sorted(all_canon):
        aliases = sorted(aliases_by_canon.get(canon, set()))
        sources: set[str] = set()
        for a in aliases:
            sources |= mention_sources.get(a, set())
        if canon in mention_sources:
            sources |= mention_sources[canon]
        src_list = [s for s in ("txt", "video") if s in sources]
        reason_bits = sorted(reasons_by_canon.get(canon, []))[:8]
        notes = (
            "由 mention_normalization_llm 聚合；映射理由摘要："
            + "；".join(reason_bits)
            if reason_bits
            else "由 mention_normalization_llm 聚合"
        )
        if len(notes) > 500:
            notes = notes[:497] + "…"

        entries.append(
            {
                "canonical_name": canon,
                "aliases": aliases,
                "sources": src_list,
                "notes": notes,
            }
        )

    return entries


def main() -> None:
    if not NORM_JSON.is_file():
        raise FileNotFoundError(f"缺少: {NORM_JSON}")

    mention_sources = load_mention_sources(ALIAS_JSON)
    kb = build_kb(NORM_JSON, mention_sources)

    OUTPUT_JSON.write_text(
        json.dumps(kb, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"已写入: {OUTPUT_JSON}")
    print(f"标准人物条目数: {len(kb)}")
    alias_total = sum(len(e["aliases"]) for e in kb)
    print(f"别称条数（去重后合计）: {alias_total}")


if __name__ == "__main__":
    main()
