#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
《红楼梦》地点知识库构建与地点归一化 —— 规则预处理 + 大模型辅助 + 合并为 KB

与「人物姓名↔别称」不同，地点是**层级包含**关系：标准库中「潇湘馆」是大观园下的院落，
JSON 里「黛玉房中」「黛玉闺房」等应归一到「潇湘馆」这类**可点击、可聚合事件**的节点；
纯泛称（园中、厅上、厨房等）不进入标准库，标记为 generic。

流程：
1. 项目根目录运行 extract_locations_to_csv.py → all_locations.csv（含 json_paths）与
   all_locations_by_file.csv（按 JSON 溯源，便于关联章节/视频源）。
2. 本脚本：读取 all_locations.csv + 红楼梦地点表.csv → locations_classified.csv、
   llm_location_normalization_input.json。
3. 运行 normalize_location_mentions_llm.py（DashScope，参数同 deal_txt.py）→
   location_normalization_llm.json。
4. 运行 build_location_kb.py → location_kb.json、location_mention_map.json（供事件侧替换）。

规则优先：泛称直接 generic；大模型在闭表内选 canonical / unknown / generic。
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any


# ========== 路径 ==========
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
ALL_LOCATIONS_CSV = PROJECT_ROOT / "all_locations.csv"
ALL_LOCATIONS_BY_FILE_CSV = PROJECT_ROOT / "all_locations_by_file.csv"
STANDARD_TABLE_CSV = SCRIPT_DIR / "地点知识库" / "红楼梦地点表.csv"
OUTPUT_DIR = SCRIPT_DIR / "location_pipeline_out"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CLASSIFIED_CSV = OUTPUT_DIR / "locations_classified.csv"
STATS_JSON = OUTPUT_DIR / "location_classification_stats.json"
LLM_INPUT_JSON = OUTPUT_DIR / "llm_location_normalization_input.json"
PROMPT_TXT = OUTPUT_DIR / "llm_location_prompt_template.txt"
KB_SAMPLE_JSON = OUTPUT_DIR / "sample_location_kb.json"


# ---------------------------------------------------------------------------
# 规则：可迭代维护（优先级从上到下，先命中先返回）
# ---------------------------------------------------------------------------

# 明确泛称 / 方位 / 功能室（无唯一建筑锚点），不宜强行归一到单一标准点
GENERIC_EXACT: frozenset[str] = frozenset(
    {
        "园中",
        "园内",
        "园外",
        "厅上",
        "外厅",
        "花厅",
        "大厅",
        "后堂",
        "前厅",
        "穿堂",
        "书房",
        "厨房",
        "灶上",
        "门首",
        "门外",
        "院内",
        "院中",
        "路上",
        "街头",
        "巷口",
        "岸边",
        "亭上",
        "台上",
        "席间",
    }
)

# 完全匹配或整词为泛称（补充）
GENERIC_PATTERN = re.compile(
    r"^(厅上|外厅|角门|穿堂|夹道|甬道|回廊|台阶|阶下|阶前|廊下|檐下|屏风后|帘外|帘内)$"
)

# 常见别称 -> 提示目标（仅用于规则标注与 rule_note，最终映射仍由模型在闭表内选择）
ALIAS_HINT_EXACT: dict[str, str] = {
    "荣府": "荣国府",
    "宁府": "宁国府",
    "蘅芜苑": "蘅芜院",
}

# 人物 + 房间类描述 → descriptive（需结合上下文归一，不直接绑死到怡红院等）
DESCRIPTIVE_PERSON = re.compile(
    r"(宝玉|黛玉|宝钗|宝姐姐|林妹妹|凤姐姐|琏二爷|琏二奶奶|凤姐|贾母|老祖宗|王夫人|"
    r"邢夫人|尤氏|探春|迎春|惜春|李纨|珠大嫂子|贾政|贾赦|贾珍|贾琏|贾蓉|贾蔷|贾芸|贾环|贾兰|"
    r"薛姨妈|薛蟠|香菱|秦钟|妙玉|湘云|史大姑娘|巧姐|赵姨娘|鸳鸯|平儿|袭人|晴雯|紫鹃|司棋|"
    r"刘姥姥|周瑞|旺儿|来升|赖大)"
    r".{0,8}(房中|房内|屋内|里间|外间|内室|住处|院里|房中|房内|上房|下处|处)$"
)

# 标准府园名前缀 + 后缀 → 视为大宅/园林下的子空间（非完整标准名）
SUBSPACE_PREFIX = ("荣国府", "宁国府", "大观园", "贾府", "梨香院", "铁槛寺", "清虚观", "馒头庵", "水月庵")
SUBSPACE_SUFFIX = re.compile(
    r"(抱厦|暖阁|东院|西院|内院|外院|夹道|穿堂|角门|垂花门|仪门|大厅|花厅|"
    r"东廊|西廊|后院|前院|内室|外室|上房|下房|门楼|亭子|桥边|岸边|船上|车内)$"
)


def load_standard_locations(path: Path) -> tuple[list[str], set[str], list[dict[str, str]]]:
    """标准地点表：standard_location 列。"""
    names: list[str] = []
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sl = (row.get("standard_location") or "").strip()
            if not sl:
                continue
            names.append(sl)
            rows.append({k: (v or "").strip() for k, v in row.items()})
    return names, set(names), rows


def load_all_locations(path: Path) -> list[dict[str, str]]:
    rows = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(
                {
                    "location": (row.get("location") or "").strip(),
                    "source": (row.get("source") or "").strip(),
                    "occurrence_count": (row.get("occurrence_count") or "0").strip(),
                    "file_count": (row.get("file_count") or "0").strip(),
                    "json_paths": (row.get("json_paths") or "").strip(),
                }
            )
    return [r for r in rows if r["location"]]


def load_all_locations_from_by_file(path: Path) -> list[dict[str, str]]:
    """与 extract_locations_to_csv.py 一致：按 (location, source) 聚合 json_path 与出现次数。"""
    occ: dict[tuple[str, str], int] = defaultdict(int)
    paths: dict[tuple[str, str], set[str]] = defaultdict(set)
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            loc = (row.get("location") or "").strip()
            src = (row.get("source") or "").strip()
            jp = (row.get("json_path") or "").strip()
            if not loc:
                continue
            key = (loc, src)
            try:
                cnt = int((row.get("occurrence_count") or "0").strip() or 0)
            except ValueError:
                cnt = 0
            occ[key] += cnt
            if jp:
                paths[key].add(jp)
    out: list[dict[str, str]] = []
    for (loc, src), count in occ.items():
        plist = sorted(paths[(loc, src)])
        out.append(
            {
                "location": loc,
                "source": src,
                "occurrence_count": str(count),
                "file_count": str(len(plist)),
                "json_paths": "|".join(plist),
            }
        )
    out.sort(key=lambda x: (0 if x["source"] == "txt" else 1, -int(x["occurrence_count"] or 0), x["location"]))
    return out


def classify_location(
    loc: str,
    standard_set: set[str],
) -> tuple[str, str]:
    """
    返回 (location_type, rule_note)。
    location_type ∈ canonical | alias | subspace | generic | descriptive
    """
    if loc in standard_set:
        return "canonical", "与标准地点表 standard_location 完全匹配"

    if loc in GENERIC_EXACT:
        return "generic", "命中泛称/方位白名单"

    if GENERIC_PATTERN.match(loc):
        return "generic", "命中泛称整词模式"

    # 人物+房中类（优先于子空间）
    if DESCRIPTIVE_PERSON.search(loc):
        return "descriptive", "人物+居室/处所类描述，需结合剧情归一"
    if re.search(r"(宝玉|黛玉|宝钗|凤姐|贾母|王夫人|探春|迎春|惜春|李纨|贾政|薛姨妈|赵姨娘|珠大嫂子)", loc) and re.search(
        r"(房中|房内|内室|住处|上房)$", loc
    ):
        return "descriptive", "人物+房中/上房类描述"

    # 子空间：府园名 + 后续成分（非表内完整标准名）
    for prefix in SUBSPACE_PREFIX:
        if loc.startswith(prefix) and len(loc) > len(prefix) and loc not in standard_set:
            return "subspace", f"以「{prefix}」为前缀的复合/局部空间"

    if any(loc.startswith(p) for p in SUBSPACE_PREFIX) and SUBSPACE_SUFFIX.search(loc) and loc not in standard_set:
        return "subspace", "府园区域下的局部空间（后缀匹配）"

    # 别称精确表
    if loc in ALIAS_HINT_EXACT:
        return "alias", f"常见别称，倾向映射至「{ALIAS_HINT_EXACT[loc]}」（须由模型在闭表内确认）"

    # 短称「X府」且非标准名
    if re.fullmatch(r"(荣府|宁府)", loc):
        return "alias", "府邸简称，倾向荣国府/宁国府"

    # 蘅芜苑等变体（未在上面 exact 命中时）
    if "蘅芜" in loc and loc not in standard_set:
        return "alias", "蘅芜相关变体，倾向蘅芜院"

    # 默认：可能为别称或待细分，交模型辅助
    return "alias", "未命中细分规则，默认按别称/待考处理"


def run_pipeline() -> None:
    if not STANDARD_TABLE_CSV.is_file():
        raise FileNotFoundError(f"缺少 {STANDARD_TABLE_CSV}")
    if ALL_LOCATIONS_BY_FILE_CSV.is_file():
        rows = load_all_locations_from_by_file(ALL_LOCATIONS_BY_FILE_CSV)
        print(f"使用聚合自: {ALL_LOCATIONS_BY_FILE_CSV}（{len(rows)} 条 location×source）")
    elif ALL_LOCATIONS_CSV.is_file():
        rows = load_all_locations(ALL_LOCATIONS_CSV)
        print(f"使用: {ALL_LOCATIONS_CSV}")
    else:
        raise FileNotFoundError(f"缺少 {ALL_LOCATIONS_BY_FILE_CSV} 或 {ALL_LOCATIONS_CSV}")

    std_list, std_set, std_rows = load_standard_locations(STANDARD_TABLE_CSV)

    classified: list[dict[str, Any]] = []
    for r in rows:
        loc = r["location"]
        lt, note = classify_location(loc, std_set)
        item = {**r, "location_type": lt, "rule_note": note}
        classified.append(item)

    # 写中间文件
    fieldnames = [
        "location",
        "source",
        "occurrence_count",
        "file_count",
        "json_paths",
        "location_type",
        "rule_note",
    ]
    with CLASSIFIED_CSV.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in classified:
            w.writerow({k: row.get(k, "") for k in fieldnames})

    cnt = Counter(r["location_type"] for r in classified)
    STATS_JSON.write_text(
        json.dumps(dict(cnt), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 任务4：需语义判断的 mention → LLM（canonical 已为标准名；generic 不送模型）
    need_llm = [
        r
        for r in classified
        if r["location_type"] in ("alias", "descriptive", "subspace")
    ]
    payload = {
        "meta": {
            "description": "层级归一：人物居所内间/局部空间 → 归入标准院落或府园节点；泛称 → generic",
            "candidate_count": len(std_list),
            "types_sent": ["alias", "descriptive", "subspace"],
            "note": "标准表含 parent_location：模型应优先映射到「可独立叙事锚点」的 standard_location；"
            "闭集仅允许表内名或 unknown/generic。",
        },
        "candidate_canonical_locations": std_list,
        "standard_table_rows": std_rows,
        "items": [],
    }
    for r in need_llm:
        payload["items"].append(
            {
                "original_location": r["location"],
                "source": r["source"],
                "occurrence_count": int(r["occurrence_count"] or 0),
                "file_count": int(r["file_count"] or 0),
                "json_paths": r.get("json_paths") or "",
                "location_type": r["location_type"],
                "rule_note": r["rule_note"],
            }
        )

    LLM_INPUT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 任务5：示例知识库
    sample_kb = [
        {
            "canonical_location": "怡红院",
            "aliases": ["宝玉房中", "宝玉房内", "宝玉住处", "宝玉卧室"],
            "sources": ["txt", "video"],
            "parent_location": "大观园",
            "location_type_note": "院落级标准节点；人物卧房类描述归并到此",
        },
        {
            "canonical_location": "潇湘馆",
            "aliases": ["黛玉房中", "黛玉闺房", "林黛玉房间"],
            "sources": ["txt", "video"],
            "parent_location": "大观园",
            "location_type_note": "林黛玉住所；其房间/闺房等子空间表述归并到此",
        },
        {
            "canonical_location": "荣国府",
            "aliases": ["荣府"],
            "sources": ["txt", "video"],
            "parent_location": "",
            "location_type_note": "府邸级节点",
        },
    ]
    KB_SAMPLE_JSON.write_text(
        json.dumps(sample_kb, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Prompt 模板（与 normalize_location_mentions_llm.py 的批次字段对齐用 mention）
    prompt_body = """## 角色
你是《红楼梦》地点归一助手。映射目标是「可叙事锚点」的标准地点（院落、府邸、园林节点等），
禁止编造表外名称。

## 核心语义（与人物别称不同）
- **层级包含**：若原文是某标准地点内部的房间、局部（如「黛玉房中」「怡红院外」），应归到**上一级标准节点**
  （如潇湘馆、怡红院、荣国府），只要可依据剧情或人物居所唯一确定。
- **泛称丢弃**：「园中」「厅上」「厨房」「书房」等无法唯一锚定到某一标准建筑时 → canonical_location 填 **generic**
  （或 unknown），不要硬选一个院落。

## 输入字段
- mention / original_location：原始字符串
- location_type：alias | descriptive | subspace 等
- standard_table_rows：含 parent_location，表示大地点—小地点关系（辅助判断）

## 输出
- canonical_location：闭集内一项，或 **unknown**，或 **generic**
- confidence、reason

## 输出格式（仅 JSON）
{"results":[{"mention":"...","canonical_location":"...","confidence":"...","reason":"..."}]}

## 标准地点层级与闭集
{{HIERARCHY_AND_CANDIDATE}}

## 待归一条目
{{ITEMS_JSON}}
"""
    hierarchy_injection_placeholder = (
        "(运行脚本时注入：candidate_canonical_locations + standard_table_rows 的 JSON)"
    )
    # 模板文件用占位符，便于复制到其它工具
    PROMPT_TXT.write_text(
        prompt_body.replace("{{HIERARCHY_AND_CANDIDATE}}", hierarchy_injection_placeholder).replace(
            "{{ITEMS_JSON}}", "(运行脚本时由程序注入 items 批次)"
        ),
        encoding="utf-8",
    )

    hierarchy_blob = json.dumps(
        {
            "candidate_canonical_locations": std_list,
            "standard_table_rows": std_rows,
        },
        ensure_ascii=False,
        indent=2,
    )

    # 带样例的完整 prompt 另存一份，方便直接投喂
    sample_items = need_llm[:12]
    prompt_filled = prompt_body.replace("{{HIERARCHY_AND_CANDIDATE}}", hierarchy_blob).replace(
        "{{ITEMS_JSON}}",
        json.dumps(
            [
                {
                    "mention": x["location"],
                    "source": x["source"],
                    "occurrence_count": int(x["occurrence_count"] or 0),
                    "file_count": int(x["file_count"] or 0),
                    "json_paths": x.get("json_paths") or "",
                    "location_type": x["location_type"],
                    "rule_note": x["rule_note"],
                }
                for x in sample_items
            ],
            ensure_ascii=False,
            indent=2,
        ),
    )
    (OUTPUT_DIR / "llm_location_prompt_filled_sample.txt").write_text(
        prompt_filled, encoding="utf-8"
    )

    print(f"分类统计: {dict(cnt)}")
    print(f"总行数: {len(classified)}")
    print(f"待 LLM 条数 (alias+descriptive+subspace): {len(need_llm)}")
    print(f"中间表: {CLASSIFIED_CSV}")
    print(f"LLM 输入: {LLM_INPUT_JSON}")
    print(f"Prompt 模板: {PROMPT_TXT}")
    print(f"样例填充 Prompt: location_pipeline_out/llm_location_prompt_filled_sample.txt")
    print(f"知识库示例: {KB_SAMPLE_JSON}")


if __name__ == "__main__":
    run_pipeline()
