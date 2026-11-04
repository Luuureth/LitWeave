#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
红楼梦人物 mention 归一化：读取标准名 + alias 列表，按 deal_txt.py 相同方式调用 DashScope，
分批请求模型，合并为 {"results":[...]} 并校验 canonical_name。

输入默认：character_pipeline_out/llm_normalization_input.json
输出：character_pipeline_out/mention_normalization_llm.json
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

# ========== 与 deal_txt.py 对齐的 API 配置 ==========
dashscope.base_http_api_url = os.getenv(
    "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/api/v1"
)
def _read_api_key_from_deal_txt() -> str:
    """从 deal_txt.py 文本读取 API_KEY，避免 exec_module 触发其 main()。"""
    p = Path(__file__).resolve().parent.parent / "红楼梦文本" / "deal_txt.py"
    if not p.is_file():
        return ""
    txt = p.read_text(encoding="utf-8")
    m = re.search(r'^API_KEY\s*=\s*["\']([^"\']+)["\']', txt, re.MULTILINE)
    return m.group(1).strip() if m else ""


API_KEY = os.getenv("DASHSCOPE_API_KEY", "").strip() or _read_api_key_from_deal_txt()
if not API_KEY:
    raise ValueError("请设置环境变量 DASHSCOPE_API_KEY，或配置 红楼梦文本/deal_txt.py 中的 API_KEY。")

MODEL_NAME = os.getenv("DASHSCOPE_MODEL", "qwen3.6-plus")
MAX_RETRIES = int(os.getenv("DASHSCOPE_MAX_RETRIES", "5"))
REQUEST_TIMEOUT = int(os.getenv("DASHSCOPE_TIMEOUT", "600"))
BATCH_SIZE = int(os.getenv("MENTION_NORM_BATCH_SIZE", "45"))

SCRIPT_DIR = Path(__file__).resolve().parent
PIPELINE_OUT = SCRIPT_DIR / "character_pipeline_out"
INPUT_JSON = PIPELINE_OUT / "llm_normalization_input.json"
OUTPUT_JSON = PIPELINE_OUT / "mention_normalization_llm.json"
PARTIAL_JSON = PIPELINE_OUT / "mention_normalization_llm.partial.json"
RAW_LOG = PIPELINE_OUT / "mention_normalization_llm.raw.txt"

SYSTEM_INSTRUCTION = """你是《红楼梦》人物归一助手。你只根据用户给定的标准人物名列表做判断，禁止编造列表外姓名。
输出必须是合法 JSON 对象，且仅包含一个顶层键 "results"，不要 markdown，不要解释性前后文。"""

USER_TEMPLATE = """## 任务
对「待归一列表」中的每一条（按数组顺序），判断最可能对应的标准人物名。

## 规则
1. canonical_name 只能从「标准人物名集合」中选择一个完全相同的字符串；无法确定时填 unknown。
2. 明显泛称、群体称呼、纯视觉描述 → canonical_name 为 unknown。
3. 「二爷」「老太太」「太太」等有歧义称呼：仅在有较高把握时映射，否则 unknown。
4. confidence 只能是 high、medium、low 之一。

## 输出格式（严格遵守）
顶层：{{"results": [...]}}
results 长度必须等于待归一列表长度；results[i] 对应第 i 条输入（从 0 起）。
每条对象字段：
- "mention": 字符串，与输入该条 mention 完全一致
- "canonical_name": 标准姓名或 unknown
- "confidence": "high" | "medium" | "low"
- "reason": 简短中文理由

## 标准人物名集合（JSON 数组，仅此集合内可选）
{names_json}

## 待归一列表（JSON 数组，按顺序处理；字段 mention, source, occurrence_count, file_count）
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


def call_llm(user_text: str) -> str:
    """与 deal_txt 一致仅使用 user 消息，将 system 指令拼入首段，兼容性更好。"""
    blob = SYSTEM_INSTRUCTION + "\n\n" + user_text
    last_err = None
    response = None
    for attempt in range(MAX_RETRIES):
        try:
            response = MultiModalConversation.call(
                api_key=API_KEY,
                model=MODEL_NAME,
                timeout=REQUEST_TIMEOUT,
                messages=[
                    {
                        "role": "user",
                        "content": [{"text": blob}],
                    },
                ],
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
    canonical_set: set[str],
) -> list[dict]:
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
                f"  提示: 第 {i} 条模型回显 mention 与输入略有差异，已以输入为准。"
                f" 模型: {m_model!r} 输入: {mention_truth!r}"
            )
        cn = (r.get("canonical_name") or "").strip()
        cf = (r.get("confidence") or "").strip()
        rs = r.get("reason", "")
        if cf not in conf_ok:
            raise ValueError(f"非法 confidence: {cf!r}")
        if cn != "unknown" and cn not in canonical_set:
            raise ValueError(f"非法 canonical_name（不在表中）: {cn!r}")
        out.append(
            {
                "mention": mention_truth,
                "canonical_name": cn,
                "confidence": cf,
                "reason": rs if isinstance(rs, str) else str(rs),
                "_source": row.get("source"),
                "_occurrence_count": row.get("occurrence_count"),
                "_file_count": row.get("file_count"),
            }
        )
    return out


def chunks(lst: list, n: int):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


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
    parser = argparse.ArgumentParser(description="红楼梦人物 mention 归一化（DashScope）")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="仅处理前 N 条（调试用，0 表示全部）",
    )
    args = parser.parse_args()

    if not INPUT_JSON.is_file():
        raise FileNotFoundError(f"缺少输入: {INPUT_JSON}，请先运行 character_normalization_pipeline.py")

    data = json.loads(INPUT_JSON.read_text(encoding="utf-8"))
    names = data["candidate_canonical_names"]
    items = list(data["alias_mentions"])
    if args.limit and args.limit > 0:
        items = items[: args.limit]
        print(f"已启用 --limit={args.limit}，仅处理前 {len(items)} 条")

    canonical_set = set(names)

    all_results: list[dict] = []
    raw_blocks: list[str] = []

    batches = list(chunks(items, BATCH_SIZE))
    total_batches = len(batches)
    print(f"共 {len(items)} 条 mention，分 {total_batches} 批（每批最多 {BATCH_SIZE} 条）")

    for bi, batch in enumerate(batches, start=1):
        user_text = USER_TEMPLATE.format(
            names_json=json.dumps(names, ensure_ascii=False),
            items_json=json.dumps(batch, ensure_ascii=False),
        )
        print(f"批次 {bi}/{total_batches}，本批 {len(batch)} 条…")
        raw = call_llm(user_text)
        raw_blocks.append(f"===== BATCH {bi} =====\n{raw}\n")
        parsed = try_parse_json(raw)
        validated = validate_batch(parsed, batch, canonical_set)
        for v in validated:
            v.pop("_source", None)
            v.pop("_occurrence_count", None)
            v.pop("_file_count", None)
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
    print(f"原始响应汇总: {RAW_LOG}")


if __name__ == "__main__":
    main()
