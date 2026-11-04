#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
《红楼梦》地点知识库 — 二轮流程：补表候选筛选 + 标准地点表 v2 草案 + 二轮归一输入 + Prompt。

不覆盖原始 红楼梦地点表.csv；所有产物写入 location_pipeline_out/。

依赖：pandas、标准库 json/re/pathlib。
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import pandas as pd

# ========== 路径 ==========
SCRIPT_DIR = Path(__file__).resolve().parent
TABLE_CSV = SCRIPT_DIR / "红楼梦地点表.csv"
PIPELINE_OUT = SCRIPT_DIR / "location_pipeline_out"
ROUND1_JSON = PIPELINE_OUT / "llm_location_normalization_input.json"

OUT_CANDIDATES = PIPELINE_OUT / "location_table_enrichment_candidates.csv"
OUT_V2 = PIPELINE_OUT / "standard_locations_v2_candidates.csv"
OUT_ROUND2_JSON = PIPELINE_OUT / "llm_location_normalization_round2_input.json"
OUT_PROMPT = PIPELINE_OUT / "llm_location_round2_prompt.txt"

# ========== 可维护规则配置 ==========

# 硬排除：绝不作为「新标准地点」补表（仍可在二轮作为 mention 归一）
EXCLUDE_ENRICHMENT_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(途中|路上|去.+途中|往.+途中|送殡|回.+途中)"), "路径/过程描述"),
    (re.compile(r"(园中|园内)(小径|道路|水路|角落)"), "园内过细场景描述"),
    (re.compile(r"(廊檐|檐下|窗外|树下|桥边|门前|门首|阶下)(?!.*[亭台楼])"), "依附性方位片段"),
    (re.compile(r".+房中$|.+房内$|.+内室$|.+住处$|.+上房$"), "人物依附型居室（优先别称归一）"),
    (re.compile(
        r"(宝玉|黛玉|宝钗|凤姐|贾母|王夫人|探春|迎春|惜春|李纨|贾政|薛姨妈|赵姨娘|"
        r"鸳鸯|平儿|袭人|晴雯|紫鹃|贾琏|贾珍|贾蓉|邢夫人|尤氏).{0,6}(房中|房内|住处|上房)$"
    ), "人物+房中类"),
]

# 泛称空间：不宜作为新节点补表
GENERIC_SPACE_EXACT = frozenset(
    {
        "室内", "庭院", "卧室", "花园", "厅上", "外厅", "花厅", "大厅", "书房",
        "厨房", "园中", "园内", "院中", "院内", "穿堂", "夹道", "甬道",
    }
)

# 建筑/场所类后缀加分（稳定节点倾向）
SUFFIX_BONUS: list[tuple[str, int, str]] = [
    ("府", 18, "府邸类后缀"),
    ("园", 14, "园林类后缀"),
    ("院", 12, "院落类后缀"),
    ("馆", 14, "馆阁类后缀"),
    ("楼", 14, "楼类后缀"),
    ("亭", 14, "亭类后缀"),
    ("台", 12, "台类后缀"),
    ("庵", 14, "庵类后缀"),
    ("寺", 14, "寺类后缀"),
    ("庙", 12, "庙类后缀"),
    ("观", 14, "观类后缀"),
    ("桥", 12, "桥类后缀"),
    ("闸", 10, "水闸/闸桥"),
    ("榭", 12, "榭类后缀"),
    ("轩", 10, "轩类后缀"),
    ("斋", 12, "斋类后缀"),
    ("坞", 10, "坞类后缀"),
    ("阁", 12, "阁类后缀"),
    ("堂", 10, "堂类后缀"),
    ("书房", 16, "书房复合"),
    ("衙门", 12, "衙署类"),
    ("街", 8, "街巷"),
    ("巷", 8, "街巷"),
]

# 降分/排除关键词
WEAK_SUBSTRINGS: list[tuple[str, int, str]] = [
    ("东屋", -25, "过细局部"),
    ("西屋", -25, "过细局部"),
    ("东院", -15, "复合院内方位"),
    ("西院", -15, "复合院内方位"),
    ("大门外", -10, "门外复合"),
    ("及东院", -20, "复合路径描述"),
]

# 补表候选最低分（可调）
ENRICHMENT_SCORE_THRESHOLD = 35

# 根据名称猜测 location_type（用于 v2 草案）
def guess_location_type(name: str) -> str:
    n = name
    if re.search(r"府$|国公府", n):
        return "府邸"
    if "大观园" in n or "会芳园" in n or "园" in n and len(n) <= 8:
        if n.endswith("园"):
            return "园林"
    if re.search(r"庵$|寺$|庙$", n):
        return "寺庙"
    if re.search(r"观$", n):
        return "道观"
    if re.search(r"亭$|榭$|桥$|闸$", n):
        return "景观"
    if re.search(r"书房$", n):
        return "书房"
    if re.search(r"楼$|阁$", n):
        return "楼阁"
    if re.search(r"斋$|坞$|轩$", n):
        return "院落"
    if re.search(r"馆$|院$", n):
        return "院落"
    if re.search(r"街|巷", n):
        return "街巷"
    if "太虚幻境" in n or "幻境" in n:
        return "神话场景"
    return "其他"


# ---------------------------------------------------------------------------
# 打分：是否应进入「补表候选」列表（不等同于自动写入标准表）
# ---------------------------------------------------------------------------
def score_enrichment_candidate(
    loc: str,
    location_type: str,
    occurrence_count: int,
    file_count: int,
    existing_names: set[str],
) -> tuple[float, str, bool]:
    """
    返回 (score, reason_text, eligible)。
    eligible=False 表示硬排除，不应出现在补表候选中。
    """
    loc = (loc or "").strip()
    reasons: list[str] = []

    if not loc:
        return 0.0, "空字符串", False

    if loc in existing_names:
        return 0.0, "已在标准地点表中", False

    for pat, desc in EXCLUDE_ENRICHMENT_PATTERNS:
        if pat.search(loc):
            return -100.0, f"硬排除：{desc}", False

    if loc in GENERIC_SPACE_EXACT:
        return -80.0, "泛称空间白名单", False

    # 泛称前缀 + 具体后缀的混合串，一般不单独作为新节点（如「室内书房」）
    if re.match(r"^(室内|室外|园中|院内|厅上)", loc):
        return -60.0, "以泛称空间为前缀的复合串，不自动补表", False

    score = 0.0

    if location_type == "alias":
        score += 28
        reasons.append("规则类型为 alias（+28）")
    elif location_type == "descriptive":
        score += 8
        reasons.append("规则类型为 descriptive（+8）")
    else:
        reasons.append(f"规则类型 {location_type}（不加分）")

    # 频次（对数缩放避免极端值）
    score += min(22, 4.0 * math.log1p(occurrence_count))
    score += min(12, 2.5 * math.log1p(file_count))
    reasons.append(f"频次 occ={occurrence_count} file={file_count}")

    # 后缀从长到短匹配，避免「院」误套在过长串中间
    for suf, pts, desc in sorted(SUFFIX_BONUS, key=lambda x: -len(x[0])):
        if loc.endswith(suf):
            score += pts
            reasons.append(f"后缀「{suf}」+{pts}（{desc}）")
            break

    for sub, delta, desc in WEAK_SUBSTRINGS:
        if sub in loc:
            score += delta
            reasons.append(f"含「{sub}」{delta}（{desc}）")

    # 过短或纯双字泛称略降
    if len(loc) <= 2 and loc not in existing_names:
        score -= 15
        reasons.append("名称过短（-15）")

    eligible = score >= ENRICHMENT_SCORE_THRESHOLD
    reason_str = "；".join(reasons) + f" → 总分 {score:.1f}，阈值 {ENRICHMENT_SCORE_THRESHOLD}"
    return score, reason_str, eligible


# ---------------------------------------------------------------------------
# 二轮策略：每条 mention 如何处理
# ---------------------------------------------------------------------------
PERSON_ROOM = re.compile(
    r"(宝玉|黛玉|宝钗|凤姐|琏二奶奶|贾母|老祖宗|王夫人|邢夫人|尤氏|探春|迎春|惜春|李纨|"
    r"贾政|薛姨妈|赵姨娘|珠大嫂子|贾琏|贾珍|贾蓉|薛蟠|香菱|秦钟|妙玉|湘云|巧姐).{0,8}(房中|房内|内室|住处|上房|院里)$"
)

GENERIC_OR_UNKNOWN_HINT = re.compile(
    r"^(室内|庭院|卧室|花园|厅上|外厅|花厅|大厅|书房|厨房|园中|园内|院中|院内|穿堂|夹道|甬道|廊下|檐下)$"
)
PATH_LIKE = re.compile(r"(途中|路上|去.*途中|往.*途中|送殡|回.*路)")


def classify_round2_strategy(loc: str, location_type: str) -> str:
    loc = (loc or "").strip()
    if not loc:
        return "generic_or_unknown"
    if PERSON_ROOM.search(loc) or re.search(
        r"(房中|房内|内室|住处|上房)$", loc
    ) and re.search(
        r"(宝玉|黛玉|宝钗|凤姐|贾母|王夫人|探春|迎春|惜春|李纨|贾政|薛姨妈|赵姨娘)",
        loc,
    ):
        return "keep_as_alias"
    if loc in GENERIC_SPACE_EXACT or GENERIC_OR_UNKNOWN_HINT.match(loc):
        return "generic_or_unknown"
    if PATH_LIKE.search(loc):
        return "generic_or_unknown"
    if re.search(r"(小径|道路|水路|廊檐下|窗外|树下)", loc):
        return "generic_or_unknown"
    if re.search(r"(东屋|西屋|及东院|大门外及)", loc):
        return "generic_or_unknown"

    # 有建筑后缀或像专名 → 二轮优先映射标准点
    for suf, _, _ in SUFFIX_BONUS:
        if loc.endswith(suf) and len(loc) >= 2:
            return "map_to_canonical"
    if re.search(r"[·\u4e00-\u9fff]{2,}(书房|府|园|院|楼|亭|庵|寺|观|桥|馆|斋|榭|轩|阁|堂)$", loc):
        return "map_to_canonical"

    if location_type == "alias":
        return "map_to_canonical"
    return "generic_or_unknown"


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def load_round1(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_existing_table(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig")


def main() -> None:
    PIPELINE_OUT.mkdir(parents=True, exist_ok=True)
    if not TABLE_CSV.is_file():
        raise FileNotFoundError(TABLE_CSV)
    if not ROUND1_JSON.is_file():
        raise FileNotFoundError(ROUND1_JSON)

    df_table = load_existing_table(TABLE_CSV)
    required = {"standard_location", "parent_location", "location_type", "note"}
    if not required.issubset(df_table.columns):
        raise ValueError(f"地点表缺少列: {required - set(df_table.columns)}")

    existing_names = set(df_table["standard_location"].astype(str).str.strip())

    data = load_round1(ROUND1_JSON)
    items = data.get("items") or []
    candidate_locations = list(data.get("candidate_canonical_locations") or [])
    standard_rows = list(data.get("standard_table_rows") or [])

    # ---------- 任务2：补表候选打分 ----------
    cand_rows: list[dict] = []
    for it in items:
        loc = (it.get("original_location") or "").strip()
        lt = (it.get("location_type") or "").strip()
        occ = int(it.get("occurrence_count") or 0)
        fc = int(it.get("file_count") or 0)
        rn = (it.get("rule_note") or "").strip()
        src = (it.get("source") or "").strip()

        score, reason, eligible = score_enrichment_candidate(
            loc, lt, occ, fc, existing_names
        )
        cand_rows.append(
            {
                "original_location": loc,
                "source": src,
                "occurrence_count": occ,
                "file_count": fc,
                "location_type": lt,
                "rule_note": rn,
                "candidate_score": round(score, 2),
                "candidate_reason": reason,
                "eligible_for_enrichment": eligible,
            }
        )

    df_cand = pd.DataFrame(cand_rows)
    df_cand.sort_values(
        by=["eligible_for_enrichment", "candidate_score"],
        ascending=[False, False],
        inplace=True,
    )
    df_cand.to_csv(OUT_CANDIDATES, index=False, encoding="utf-8-sig")
    print(f"已写入: {OUT_CANDIDATES}")

    # 仅 eligible 且不在表中者进入 v2 新增行（草案）
    to_add = df_cand[
        (df_cand["eligible_for_enrichment"] == True)
        & (~df_cand["original_location"].isin(existing_names))
    ].copy()

    # 去重：同一 original_location 保留最高分一条
    to_add = to_add.sort_values("candidate_score", ascending=False).drop_duplicates(
        subset=["original_location"], keep="first"
    )

    # ---------- 任务3：v2 草案 CSV ----------
    df_existing = df_table.copy()
    df_existing["source_of_addition"] = "existing"
    df_existing["confidence"] = "high"
    df_existing["review_needed"] = False

    new_blocks: list[pd.DataFrame] = []
    for _, row in to_add.iterrows():
        name = row["original_location"]
        lt = guess_location_type(name)
        new_blocks.append(
            pd.DataFrame(
                [
                    {
                        "standard_location": name,
                        "parent_location": "",
                        "location_type": lt,
                        "note": f"【二轮草案】由规则打分候选；{row['candidate_reason'][:200]}",
                        "source_of_addition": "candidate_from_llm_input",
                        "confidence": "medium",
                        "review_needed": True,
                    }
                ]
            )
        )

    if new_blocks:
        df_new = pd.concat(new_blocks, ignore_index=True)
        df_v2 = pd.concat([df_existing, df_new], ignore_index=True)
    else:
        df_v2 = df_existing

    df_v2.to_csv(OUT_V2, index=False, encoding="utf-8-sig")
    print(f"已写入: {OUT_V2}（原有 {len(df_existing)} 行，新增草案 {len(to_add)} 行）")

    # ---------- 任务4：二轮 JSON ----------
    v2_names = (
        df_v2["standard_location"].astype(str).str.strip().unique().tolist()
    )
    v2_names = sorted(set(v2_names), key=lambda x: (len(x), x))

    standard_table_rows_v2: list[dict] = []
    for _, r in df_v2.iterrows():
        standard_table_rows_v2.append(
            {
                "standard_location": str(r["standard_location"]).strip(),
                "parent_location": ""
                if pd.isna(r["parent_location"])
                else str(r["parent_location"]).strip(),
                "location_type": str(r["location_type"]).strip(),
                "note": "" if pd.isna(r["note"]) else str(r["note"]).strip(),
                "source_of_addition": str(r.get("source_of_addition", "")),
                "confidence": str(r.get("confidence", "")),
                "review_needed": bool(r.get("review_needed", False)),
            }
        )

    items_r2: list[dict] = []
    for it in items:
        loc = (it.get("original_location") or "").strip()
        lt = (it.get("location_type") or "").strip()
        strategy = classify_round2_strategy(loc, lt)
        row = dict(it)
        row["round2_strategy"] = strategy
        items_r2.append(row)

    round2_payload = {
        "meta": {
            "description": "二轮地点归一：闭集为 v2 草案标准地点；items 含 round2_strategy",
            "round": 2,
            "candidate_count": len(v2_names),
            "enrichment_threshold": ENRICHMENT_SCORE_THRESHOLD,
            "source_table": str(TABLE_CSV),
            "source_round1": str(ROUND1_JSON),
        },
        "candidate_canonical_locations": v2_names,
        "standard_table_rows": standard_table_rows_v2,
        "items": items_r2,
    }

    with OUT_ROUND2_JSON.open("w", encoding="utf-8") as f:
        json.dump(round2_payload, f, ensure_ascii=False, indent=2)
    print(f"已写入: {OUT_ROUND2_JSON}")

    # ---------- 任务5：Prompt ----------
    prompt = """你是《红楼梦》地点归一助手（二轮）。你只允许使用用户提供的「标准地点集合」中的名称作为映射目标，禁止编造新地点名。

## 规则
1. canonical_location 只能是：标准地点集合中的某一项、generic、unknown 三者之一（字符串完全一致）。
2. 人物依附型地点（如「宝玉房中」「贾母房中」「黛玉房中」）：若剧情上可唯一对应某人居所，可映射到该居所对应的标准地点（如怡红院、贾母正房）；若把握不足则 unknown。
3. 泛称空间（如「室内」「园中」「厅上」「外厅」等）：canonical_location 填 generic。
4. 无法从闭集中确定唯一标准地点：填 unknown。
5. confidence 只能是 high、medium、low。
6. 只输出合法 JSON，不要 markdown，不要解释性前后文。

## 输出格式
顶层对象唯一键为 "results"，值为数组。results 长度与输入条数一致且顺序对应。
每条：
{
  "mention": "<与输入完全一致>",
  "canonical_location": "<标准名或 generic 或 unknown>",
  "confidence": "high|medium|low",
  "reason": "简短中文"
}

## 标准地点集合（JSON 数组，闭集）
{{LOCATIONS_JSON}}

## 待归一列表（JSON 数组；含 original_location / source / round2_strategy 等）
{{ITEMS_JSON}}

说明：round2_strategy 含义供你参考——
- map_to_canonical：优先映射到某一标准地点；
- keep_as_alias：多为人物居所类，请结合人物与原著映射；
- generic_or_unknown：泛称或不宜强行归一者，倾向 generic 或 unknown。
"""
    # 模板中占位符保留，另存一份可直接复制的说明
    OUT_PROMPT.write_text(prompt, encoding="utf-8")
    print(f"已写入: {OUT_PROMPT}")

    # 附：一份已填充样例（前 8 条）便于试跑
    sample_items = items_r2[:8]
    filled = prompt.replace(
        "{{LOCATIONS_JSON}}",
        json.dumps(v2_names[:40], ensure_ascii=False, indent=2)
        + "\n...（完整列表见 llm_location_normalization_round2_input.json）",
    ).replace(
        "{{ITEMS_JSON}}",
        json.dumps(sample_items, ensure_ascii=False, indent=2),
    )
    (PIPELINE_OUT / "llm_location_round2_prompt_filled_sample.txt").write_text(
        filled, encoding="utf-8"
    )
    print(f"样例填充 Prompt: {PIPELINE_OUT / 'llm_location_round2_prompt_filled_sample.txt'}")

    print("完成。")


if __name__ == "__main__":
    main()
