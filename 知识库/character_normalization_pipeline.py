#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
红楼梦人物知识库构建与人物归一 —— 半自动流水线（规则预处理 + 大模型辅助 + 人工审核）

本脚本不负责“一次性全自动映射”，仅完成：
1. 读取标准人物表与 mention 汇总表
2. 对每条 mention 做可解释的初步分类（canonical / alias / generic / visual_noise）
3. 导出 alias 供大模型归一、生成大模型输入 JSON、提供 prompt 模板与最终知识库数据结构示例

后续步骤：将 alias 批次送入大模型 → 人工审核合并 → 写入最终 character_kb.json
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# 路径配置（可按需修改）
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

PATH_CANONICAL_TABLE = SCRIPT_DIR / "红楼梦人物表.csv"
PATH_MENTIONS = PROJECT_ROOT / "all_characters.csv"
OUTPUT_DIR = SCRIPT_DIR / "character_pipeline_out"


# ---------------------------------------------------------------------------
# 任务5：最终人物知识库条目结构（Python 侧定义，便于序列化与校验）
# ---------------------------------------------------------------------------
@dataclass
class CharacterKnowledgeEntry:
    """单条标准人物在知识库中的结构。"""

    canonical_name: str
    """与标准人物表「姓名」一致的标准名。"""

    aliases: list[str] = field(default_factory=list)
    """已确认可归一到该标准名的别称、简称等（不含 generic / visual_noise）。"""

    sources: list[str] = field(default_factory=list)
    """aliases 分别来自 txt / video 时可按需填充，例如 ["txt", "video"]。"""

    notes: str | None = None
    """人工或模型备注。"""


def character_kb_to_json_list(entries: list[CharacterKnowledgeEntry]) -> list[dict[str, Any]]:
    """转为可 json.dump 的列表。"""
    return [asdict(e) for e in entries]


# ---------------------------------------------------------------------------
# 读取 CSV
# ---------------------------------------------------------------------------
def load_canonical_names(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """
    读取标准人物表。
    返回：(姓名列表用于候选集合, 完整行列表便于后续扩展)
    """
    rows: list[dict[str, str]] = []
    names: list[str] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("姓名") or "").strip()
            if not name:
                continue
            rows.append({k: (v or "").strip() for k, v in row.items()})
            names.append(name)
    return names, rows


def load_mentions(path: Path) -> list[dict[str, str]]:
    """读取 all_characters.csv：character, source, occurrence_count, file_count"""
    out: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            out.append(
                {
                    "character": (row.get("character") or "").strip(),
                    "source": (row.get("source") or "").strip(),
                    "occurrence_count": (row.get("occurrence_count") or "0").strip(),
                    "file_count": (row.get("file_count") or "0").strip(),
                }
            )
    return out


# ---------------------------------------------------------------------------
# 任务2：规则分类（可解释、可扩展）
# ---------------------------------------------------------------------------

# 视觉噪声：偏画面/衣着/外貌描述，不宜直接当人物 ID
_VISUAL_NOISE_PATTERNS: list[tuple[str, str]] = [
    (r"路人", "含「路人」"),
    (r"(粉|红|蓝|绿|紫|青|白|黑|灰|黄).{0,4}(衣|衫|裙|袍).{0,6}(女|男)子?", "衣着+人物类描述"),
    (r"(年轻|年老|中年)?(女子|妇人|男子)", "泛视觉人物（年轻女子等）"),
    (r".*陌生.*", "陌生…"),
    (r"(一|两|三|几|数).{0,2}(个|名|位)?(粉|红|蓝|绿|紫|青|白|黑)?.*(女|男)子", "数量+外观人物"),
    (r"^(粉|红|蓝|绿|紫|青|白|黑).{0,3}(衣|衫)", "以颜色衣着开头"),
]

# 泛称/群体：不适合与单一标准人物一一对应
# 注意：职业词必须用「整串完全等于」或明确群体前缀，避免「张道士」「李嬷嬷」等具体人物被误判
_GENERIC_PATTERNS: list[tuple[str, str]] = [
    (r"^众人$", "众人"),
    (r"^大伙儿$", "大伙儿"),
    (r"^大家$", "大家"),
    (r"^众(人|姑娘|婆子|小厮|丫鬟|家人|太监|尼姑|和尚|道士|奴仆)", "众…开头群体"),
    (r"^(若干|几个|一群|一众)", "数量群体开头"),
    # 整词匹配：无姓氏前缀的泛称
    (
        r"^(小厮|丫头|婆子|丫鬟|仆人|家人|老妈子|奶娘|僧人|尼姑|和尚|衙役|官兵|"
        r"嬷嬷|道士|大夫|太医|小丫头|老婆子|丫鬟们|小厮们|丫头们)$",
        "整词职业/身份泛称",
    ),
    (r".*们$", "…们（群体，含「姐姐们」等）"),
    (r"(奴仆|下人|侍女|侍妾|众丫头婆子)", "仆役群体词"),
]


def _first_matching_pattern(
    text: str, patterns: list[tuple[str, str]]
) -> str | None:
    for pat, reason in patterns:
        if re.search(pat, text):
            return reason
    return None


def classify_mention(
    mention: str,
    canonical_set: set[str],
) -> tuple[str, str]:
    """
    返回 (mention_type, rule_note)。
    mention_type ∈ canonical | alias | generic | visual_noise
    """
    m = mention.strip()
    if not m:
        return "generic", "空字符串"

    # 与标准表「姓名」完全一致
    if m in canonical_set:
        return "canonical", "与标准人物表「姓名」完全匹配"

    # 先判视觉噪声（通常比 generic 更“画面化”）
    vr = _first_matching_pattern(m, _VISUAL_NOISE_PATTERNS)
    if vr:
        return "visual_noise", vr

    gr = _first_matching_pattern(m, _GENERIC_PATTERNS)
    if gr:
        return "generic", gr

    # 其余：可能为简称、别称、关系称呼，交给大模型 + 人工
    return "alias", "未命中规则，待模型/人工判断"


def enrich_mentions(
    rows: list[dict[str, str]], canonical_set: set[str]
) -> list[dict[str, Any]]:
    """为每条 mention 增加 mention_type 与 rule_note。"""
    enriched: list[dict[str, Any]] = []
    for row in rows:
        ch = row["character"]
        mt, note = classify_mention(ch, canonical_set)
        item = dict(row)
        item["mention_type"] = mt
        item["rule_note"] = note
        enriched.append(item)
    return enriched


# ---------------------------------------------------------------------------
# 任务3 & 4：导出 alias + 大模型输入
# ---------------------------------------------------------------------------
def filter_alias(enriched: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in enriched if r.get("mention_type") == "alias"]


def build_llm_payload(
    alias_rows: list[dict[str, Any]],
    canonical_names: list[str],
) -> dict[str, Any]:
    """
    大模型归一化输入：包含每条 alias 的统计字段 + 标准姓名全集（候选）。
    """
    items = []
    for r in alias_rows:
        items.append(
            {
                "mention": r["character"],
                "source": r["source"],
                "occurrence_count": int(r["occurrence_count"] or 0),
                "file_count": int(r["file_count"] or 0),
                "rule_note": r.get("rule_note", ""),
            }
        )
    return {
        "meta": {
            "description": "将每条 mention 映射到标准「姓名」之一，或标记为无法映射（保留为别名录入但需人工确认）",
            "candidate_canonical_names_count": len(canonical_names),
        },
        "candidate_canonical_names": canonical_names,
        "alias_mentions": items,
    }


# ---------------------------------------------------------------------------
# Prompt 模板（任务6 额外要求）
# ---------------------------------------------------------------------------
LLM_PROMPT_TEMPLATE = """你是一个《红楼梦》人物归一助手。下面提供两类信息：

1）从文本与视频事件 JSON 中统计得到的「原始人物 mention」列表（可能为简称、别称、关系称呼等）。
2）标准人物名全集（来自《红楼梦人物表》的「姓名」列），你必须**只从该列表中选择**作为映射目标；若无法合理对应到唯一标准人物，请输出 null，并简短说明原因。

每条输入包含：mention, source (txt/video), occurrence_count, file_count。

请对每条 mention 输出一行 JSON 对象（或输出一个 JSON 数组），字段建议为：
- "mention": 原始字符串
- "canonical_name": 标准姓名字符串，或 null
- "confidence": 0~1
- "reason": 简短中文理由

注意：
- 不要将群体称呼、纯视觉描述映射到具体人物。
- 若 mention 可能对应多人（歧义），canonical_name 置 null，并在 reason 说明歧义。

标准人物名列表（仅允许从中选择）：
{{CANDIDATE_NAMES_JSON_ARRAY}}

待归一的 mention 列表：
{{ALIAS_MENTIONS_JSON_ARRAY}}
"""


def write_prompt_template(path: Path, canonical_names: list[str], sample_aliases: list[dict]) -> None:
    """生成可替换占位符的 prompt 文件；大块列表用 JSON 嵌入。"""
    text = LLM_PROMPT_TEMPLATE.replace(
        "{{CANDIDATE_NAMES_JSON_ARRAY}}",
        json.dumps(canonical_names, ensure_ascii=False, indent=2),
    )
    text = text.replace(
        "{{ALIAS_MENTIONS_JSON_ARRAY}}",
        json.dumps(sample_aliases, ensure_ascii=False, indent=2),
    )
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if not PATH_CANONICAL_TABLE.is_file():
        raise FileNotFoundError(f"未找到标准人物表: {PATH_CANONICAL_TABLE}")
    if not PATH_MENTIONS.is_file():
        raise FileNotFoundError(f"未找到 mention 表: {PATH_MENTIONS}")

    canonical_names, canonical_rows = load_canonical_names(PATH_CANONICAL_TABLE)
    canonical_set = set(canonical_names)

    mention_rows = load_mentions(PATH_MENTIONS)
    enriched = enrich_mentions(mention_rows, canonical_set)

    # 任务2 中间结果：全部分类
    classified_path = OUTPUT_DIR / "mentions_classified.csv"
    fieldnames = [
        "character",
        "source",
        "occurrence_count",
        "file_count",
        "mention_type",
        "rule_note",
    ]
    with classified_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in enriched:
            w.writerow({k: r.get(k, "") for k in fieldnames})

    cnt = Counter(r["mention_type"] for r in enriched)
    stats_path = OUTPUT_DIR / "classification_stats.json"
    stats_path.write_text(
        json.dumps(dict(cnt), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 任务3：仅 alias
    alias_only = filter_alias(enriched)
    alias_csv = OUTPUT_DIR / "alias_for_llm.csv"
    with alias_csv.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in alias_only:
            w.writerow({k: r.get(k, "") for k in fieldnames})

    alias_json = OUTPUT_DIR / "alias_for_llm.json"
    alias_json.write_text(
        json.dumps(alias_only, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 任务4：大模型输入
    llm_input = build_llm_payload(alias_only, canonical_names)
    llm_path = OUTPUT_DIR / "llm_normalization_input.json"
    llm_path.write_text(json.dumps(llm_input, ensure_ascii=False, indent=2), encoding="utf-8")

    # Prompt 模板（嵌入完整候选名；alias 可截断预览避免文件过大）
    sample_aliases = [
        {
            "mention": r["character"],
            "source": r["source"],
            "occurrence_count": int(r["occurrence_count"] or 0),
            "file_count": int(r["file_count"] or 0),
        }
        for r in alias_only[:50]
    ]
    prompt_path = OUTPUT_DIR / "llm_prompt_template.txt"
    write_prompt_template(prompt_path, canonical_names, sample_aliases)

    # 任务5：示例知识库 JSON（空 aliases，仅展示结构；你可人工合并后填充）
    example_entries = [
        CharacterKnowledgeEntry(
            canonical_name="贾宝玉",
            aliases=["宝玉", "宝二爷"],
            sources=["txt", "video"],
            notes="示例",
        ),
        CharacterKnowledgeEntry(
            canonical_name="林黛玉",
            aliases=["黛玉", "林妹妹"],
            sources=["txt", "video"],
            notes="示例",
        ),
    ]
    sample_kb_path = OUTPUT_DIR / "sample_character_kb.json"
    sample_kb_path.write_text(
        json.dumps(character_kb_to_json_list(example_entries), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 打印摘要
    print("分类统计:", dict(cnt))
    print(f"总 mention 行数: {len(enriched)}")
    print(f"alias 待模型处理: {len(alias_only)}")
    print(f"输出目录: {OUTPUT_DIR}")
    print("生成文件:")
    for p in sorted(OUTPUT_DIR.iterdir()):
        print(f"  - {p.name}")


if __name__ == "__main__":
    main()
