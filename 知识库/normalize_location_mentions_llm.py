#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
《红楼梦》地点 mention 归一化：读取 location_pipeline_out/llm_location_normalization_input.json，
按 deal_txt.py 相同方式调用 DashScope（MultiModalConversation），分批输出
{"results":[{"mention","canonical_location","confidence","reason"}, ...]}。

语义为「大地点包含小地点」：人物房中/卧房等应归入潇湘馆、怡红院等标准节点；泛称 → generic。
canonical_location 只能是：标准地点集合中的某一项、unknown、generic。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path

import dashscope
from dashscope import MultiModalConversation

dashscope.base_http_api_url = os.getenv(
    "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/api/v1"
)


def _read_api_key_from_deal_txt() -> str:
    p = Path(__file__).resolve().parent.parent / "红楼梦文本" / "deal_txt.py"
    if not p.is_file():
        return ""
    txt = p.read_text(encoding="utf-8")
    m = re.search(r'^API_KEY\s*=\s*["\']([^"\']+)["\']', txt, re.MULTILINE)
    return m.group(1).strip() if m else ""


API_KEY = os.getenv("DASHSCOPE_API_KEY", "").strip() or _read_api_key_from_deal_txt()
MODEL_NAME = os.getenv("DASHSCOPE_MODEL", "qwen3.6-plus")
MAX_RETRIES = int(os.getenv("DASHSCOPE_MAX_RETRIES", "5"))
REQUEST_TIMEOUT = int(os.getenv("DASHSCOPE_TIMEOUT", "600"))
BATCH_SIZE = int(os.getenv("LOCATION_NORM_BATCH_SIZE", "40"))

SCRIPT_DIR = Path(__file__).resolve().parent
PIPELINE_OUT = SCRIPT_DIR / "location_pipeline_out"
INPUT_JSON = PIPELINE_OUT / "llm_location_normalization_input.json"
OUTPUT_JSON = PIPELINE_OUT / "location_normalization_llm.json"
PARTIAL_JSON = PIPELINE_OUT / "location_normalization_llm.partial.json"
RAW_LOG = PIPELINE_OUT / "location_normalization_llm.raw.txt"

SYSTEM_INSTRUCTION = """你是《红楼梦》地点归一助手。你只根据用户给定的「标准地点闭集」与层级表做判断，禁止编造集合外的地点名。
输出必须是合法 JSON 对象，且仅包含一个顶层键 "results"，不要 markdown，不要解释性前后文。"""

USER_TEMPLATE = """## 任务
对「待归一列表」按顺序逐条判断：该表述应对应哪一个**标准地点**（可作为叙事与点击聚合锚点的节点）。

## 语义：层级包含（不同于「姓名—别称」）
标准地点表中的节点往往是**院落 / 府邸 / 园林**等；原文里更细的「房间、卧房、内室、某人物房中」等，若能依据《红楼梦》常识唯一落到某一标准节点，应归到**上一级标准地点**。
示例（表中有对应项时）：「黛玉房中」「黛玉闺房」「林黛玉房间」→ 潇湘馆；「宝玉房中」「宝玉卧室」→ 怡红院；「荣府」→ 荣国府。
「宁国府抱厦」等府园局部若表无更细项，可归 **宁国府**。

## 规则（严格遵守）
1. canonical_location 只能是：
   - 下方「闭集」中的某一项，字符串必须完全一致；
   - **unknown**：无法较可靠地映射；
   - **generic**：泛称、方位、功能室通称、无法唯一锚定到某一标准节点（如园中、厅上、厨房、书房、院内、路上、外厅等）——这类不进入可点击地点库。
2. 高歧义时不要勉强映射，优先 unknown 或 generic。
3. confidence 只能是 high、medium、low。

## 输出格式
顶层为 JSON 对象，只含键 "results"；results 为数组，长度等于待归一列表长度，results[i] 对应第 i 条输入。
每条对象字段：
- "mention": 与输入该条的 mention 字段完全一致
- "canonical_location": 闭集内标准名，或 unknown，或 generic
- "confidence": "high" | "medium" | "low"
- "reason": 简短中文理由

## 标准地点层级（standard_table_rows：parent_location 表示隶属的大地点）
{hierarchy_json}

## 标准地点闭集（仅此列表中的字符串可作为具体映射目标）
{locations_json}

## 待归一列表（JSON 数组；字段 mention, source, occurrence_count, file_count, json_paths, location_type, rule_note）
{items_json}
"""


def extract_text_from_response(response) -> str:
    try:
        content = response.output.choices[0].message.content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and "text" in item:
                    parts.append(item["text"])
                elif isinstance(item, str):
                    parts.append(item)
            return "\n".join(parts).strip()
        if isinstance(content, str):
            return content.strip()
    except Exception:
        pass
    return str(response)


def try_parse_json(text: str):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()
    return json.loads(text)


def call_llm(user_blob: str) -> str:
    blob = SYSTEM_INSTRUCTION + "\n\n" + user_blob
    last_err = None
    response = None
    for attempt in range(MAX_RETRIES):
        try:
            response = MultiModalConversation.call(
                api_key=API_KEY,
                model=MODEL_NAME,
                timeout=REQUEST_TIMEOUT,
                messages=[{"role": "user", "content": [{"text": blob}]}],
            )
            break
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES - 1:
                wait_s = min(30, 2.0 * (2**attempt))
                print(f"  调用失败，{wait_s:.1f}s 后重试: {e}")
                time.sleep(wait_s)
            else:
                raise
    if response is None and last_err is not None:
        raise last_err
    if getattr(response, "status_code", None) not in (None, 200):
        raise RuntimeError(
            f"DashScope 失败: status_code={response.status_code}, "
            f"message={getattr(response, 'message', None)}"
        )
    return extract_text_from_response(response)


def validate_batch(
    parsed: dict,
    batch: list[dict],
    allowed: set[str],
) -> list[dict]:
    """
    按数组下标对齐：results[i] 对应 batch[i]。
    mention 以输入为准写入最终 JSON，避免模型改写、多空格、全角空格等导致与输入逐字不一致而中断。
    """
    if not isinstance(parsed, dict) or "results" not in parsed:
        raise ValueError("返回 JSON 缺少 results")
    results = parsed["results"]
    if not isinstance(results, list) or len(results) != len(batch):
        raise ValueError(
            f"results 长度 {len(results) if isinstance(results, list) else '?'} != 批次 {len(batch)}"
        )
    conf_ok = {"high", "medium", "low"}
    out = []
    for i, (row, r) in enumerate(zip(batch, results)):
        if not isinstance(r, dict):
            raise ValueError(f"results[{i}] 不是对象")
        m_model = (r.get("mention") or "").strip()
        mention_truth = row["mention"]
        if m_model and m_model != mention_truth:
            print(
                f"  提示: 批次内第 {i} 条模型回显 mention 与输入略有差异，已以输入为准。"
                f" 模型: {m_model!r} 输入: {mention_truth!r}"
            )
        loc = (r.get("canonical_location") or "").strip()
        cf = (r.get("confidence") or "").strip()
        rs = r.get("reason", "")
        if cf not in conf_ok:
            raise ValueError(f"非法 confidence: {cf!r}")
        if loc not in allowed:
            raise ValueError(f"非法 canonical_location: {loc!r}")
        out.append(
            {
                "mention": mention_truth,
                "canonical_location": loc,
                "confidence": cf,
                "reason": rs if isinstance(rs, str) else str(rs),
            }
        )
    return out


def chunks(lst: list, n: int):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def items_to_batch_rows(items: list[dict]) -> list[dict]:
    """将 llm_location_normalization_input 的 items 转为带 mention 的批次行。"""
    rows = []
    for it in items:
        rows.append(
            {
                "mention": (it.get("original_location") or "").strip(),
                "source": (it.get("source") or "").strip(),
                "occurrence_count": int(it.get("occurrence_count") or 0),
                "file_count": int(it.get("file_count") or 0),
                "json_paths": (it.get("json_paths") or "").strip(),
                "location_type": (it.get("location_type") or "").strip(),
                "rule_note": (it.get("rule_note") or "").strip(),
            }
        )
    return [r for r in rows if r["mention"]]


def save_partial(all_results: list[dict], raw_blocks: list[str], done_batches: int) -> None:
    PARTIAL_JSON.write_text(
        json.dumps(
            {"results": all_results, "_meta": {"batches_completed": done_batches}},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    RAW_LOG.write_text("\n".join(raw_blocks), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="红楼梦地点 mention 归一化（DashScope）")
    parser.add_argument("--limit", type=int, default=0, help="仅处理前 N 条（0=全部）")
    args = parser.parse_args()

    if not API_KEY:
        raise ValueError("请设置环境变量 DASHSCOPE_API_KEY，或配置 红楼梦文本/deal_txt.py 中的 API_KEY。")

    if not INPUT_JSON.is_file():
        raise FileNotFoundError(
            f"缺少 {INPUT_JSON}，请先运行 location_normalization_pipeline.py"
        )

    data = json.loads(INPUT_JSON.read_text(encoding="utf-8"))
    locations = data["candidate_canonical_locations"]
    std_rows = data.get("standard_table_rows") or []
    hierarchy_json = json.dumps(std_rows, ensure_ascii=False, indent=2)
    items = data.get("items") or []
    batch_rows = items_to_batch_rows(items)
    if args.limit and args.limit > 0:
        batch_rows = batch_rows[: args.limit]
        print(f"--limit={args.limit}，处理 {len(batch_rows)} 条")

    allowed = set(locations) | {"unknown", "generic"}

    all_results: list[dict] = []
    raw_blocks: list[str] = []

    batches = list(chunks(batch_rows, BATCH_SIZE))
    total = len(batches)
    print(f"共 {len(batch_rows)} 条，分 {total} 批（每批最多 {BATCH_SIZE} 条）")

    for bi, batch in enumerate(batches, start=1):
        user_text = USER_TEMPLATE.format(
            hierarchy_json=hierarchy_json,
            locations_json=json.dumps(locations, ensure_ascii=False),
            items_json=json.dumps(batch, ensure_ascii=False),
        )
        print(f"批次 {bi}/{total}，本批 {len(batch)} 条…")
        raw = call_llm(user_text)
        raw_blocks.append(f"===== BATCH {bi} =====\n{raw}\n")
        parsed = try_parse_json(raw)
        validated = validate_batch(parsed, batch, allowed)
        all_results.extend(validated)
        save_partial(all_results, raw_blocks, bi)

    out_obj = {"results": all_results}
    OUTPUT_JSON.write_text(
        json.dumps(out_obj, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    RAW_LOG.write_text("\n".join(raw_blocks), encoding="utf-8")
    if PARTIAL_JSON.is_file():
        try:
            PARTIAL_JSON.unlink()
        except OSError:
            pass
    print(f"已写入: {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
