#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
人物表增补：针对 mention_normalization_llm.json 中 canonical_name 为 unknown 的条目，
调用大模型判断是否为《红楼梦》中可单独立条的「真实人物/稳定称谓」。

- append_to_table：写入 红楼梦人物表.csv（姓名、人物简介、首次出场回目、备注）
- reject：泛称、职业无特指、视觉描述等，不写表（如「唱曲儿小子」）

用法：
  python enrich_character_table_from_llm_unknowns.py
  python enrich_character_table_from_llm_unknowns.py --limit 10   # 仅处理前 10 个去重后的 mention
  python enrich_character_table_from_llm_unknowns.py --dry-run  # 不调用 API，只打印待处理列表
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import time
from collections import defaultdict
from pathlib import Path

import dashscope
from dashscope import MultiModalConversation

# ========== API（与 normalize_character_mentions_llm.py 一致）==========
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
BATCH_SIZE = int(os.getenv("ENRICH_TABLE_BATCH_SIZE", "20"))

SCRIPT_DIR = Path(__file__).resolve().parent
PIPELINE_OUT = SCRIPT_DIR / "character_pipeline_out"
NORM_JSON = PIPELINE_OUT / "mention_normalization_llm.json"
TABLE_CSV = SCRIPT_DIR / "红楼梦人物表.csv"
TABLE_BACKUP = SCRIPT_DIR / "红楼梦人物表.csv.bak"
LOG_JSON = PIPELINE_OUT / "character_table_enrichment_log.json"
RAW_LOG = PIPELINE_OUT / "character_table_enrichment.raw.txt"

USER_PROMPT = """你是《红楼梦》人物知识维护助手。下面每条都是「第一次归一」时因不在现有人物表中而被标为 unknown 的 mention（附模型当时给出的简短 reason）。

你的任务：逐条判断该 mention 是否应对应《红楼梦》里**可单独立条、有稳定所指**的人物（含重要仆役、小厮、门子等，如「周瑞」「旺儿」）；还是应视为**泛称、职业无特指、群体、纯视觉描述**等，**不应**写入人物表。

## 判定规则（务必遵守）
1. **append_to_table**：原著/通行本中有明确、稳定身份或称呼的人物实体；简介用一两句客观中文；「首次出场回目」若记不清可填「不详」；「备注」可写「由 mention 增补」或原 mention。
2. **reject**：如「唱曲儿小子」「小厮」「粉衣女子」「路人」「众人」、无法落实为具体一人者。
3. 姓名「姓名」字段：用通行称呼作主名（可与 mention 相同；若 mention 为「周瑞家的」且指仆妇，姓名可写「周瑞家的」）。**不要**编造与《红楼梦》无关的人。
4. 输出 JSON 顶层必须为：{{"decisions": [...]}}
5. decisions 长度必须等于输入条数，且顺序与输入一致。
6. 每条对象字段：
   - "mention": 必须与输入该条 mention **完全一致**
   - "decision": 只能是 "append_to_table" 或 "reject"
   - 若 decision 为 "append_to_table"，还必须包含："姓名", "人物简介", "首次出场回目", "备注"（字符串，可为空串但姓名、人物简介不宜为空）
   - 若 decision 为 "reject"，可省略上述四字段或填 null，但建议带 "reject_reason" 简短说明

## 输入（JSON 数组，按顺序处理）
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
    last_err = None
    response = None
    for attempt in range(MAX_RETRIES):
        try:
            response = MultiModalConversation.call(
                api_key=API_KEY,
                model=MODEL_NAME,
                timeout=REQUEST_TIMEOUT,
                messages=[{"role": "user", "content": [{"text": user_blob}]}],
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


def load_existing_names(path: Path) -> set[str]:
    names: set[str] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            n = (row.get("姓名") or "").strip()
            if n:
                names.add(n)
    return names


def collect_unknown_mentions(norm_path: Path) -> list[dict]:
    """从归一化结果中取 unknown，按 mention 去重，合并 reason。"""
    data = json.loads(norm_path.read_text(encoding="utf-8"))
    results = data.get("results") or []
    by_mention: dict[str, list[str]] = defaultdict(list)
    for r in results:
        if not isinstance(r, dict):
            continue
        if (r.get("canonical_name") or "").strip() != "unknown":
            continue
        m = (r.get("mention") or "").strip()
        if not m:
            continue
        reason = (r.get("reason") or "").strip()
        if reason:
            by_mention[m].append(reason)
    items = []
    for m, reasons in sorted(by_mention.items()):
        uniq_reasons = list(dict.fromkeys(reasons))[:5]
        items.append(
            {
                "mention": m,
                "first_pass_reasons": uniq_reasons,
            }
        )
    return items


def validate_decisions(
    parsed: dict,
    batch: list[dict],
    existing_names: set[str],
) -> list[dict]:
    if not isinstance(parsed, dict) or "decisions" not in parsed:
        raise ValueError("返回 JSON 缺少 decisions")
    decisions = parsed["decisions"]
    if not isinstance(decisions, list) or len(decisions) != len(batch):
        raise ValueError(
            f"decisions 长度 {len(decisions) if isinstance(decisions, list) else '?'} != 批次 {len(batch)}"
        )
    out = []
    for i, (inp, d) in enumerate(zip(batch, decisions)):
        if not isinstance(d, dict):
            raise ValueError(f"decisions[{i}] 不是对象")
        if d.get("mention") != inp["mention"]:
            raise ValueError(
                f"decisions[{i}].mention 不一致: {d.get('mention')!r} vs {inp['mention']!r}"
            )
        dec = (d.get("decision") or "").strip()
        if dec not in ("append_to_table", "reject"):
            raise ValueError(f"非法 decision: {dec!r}")
        if dec == "append_to_table":
            name = (d.get("姓名") or "").strip()
            if not name:
                raise ValueError(f"append 但姓名为空: mention={inp['mention']!r}")
            if name in existing_names:
                # 表中已有则视为本次跳过（可改为 reject）
                d = {
                    **d,
                    "decision": "reject",
                    "reject_reason": f"姓名「{name}」已存在于人物表，跳过写入",
                }
                dec = "reject"
            else:
                existing_names.add(name)  # 同批次内防重复追加
        out.append(d)
    return out


def append_rows_to_csv(path: Path, new_rows: list[dict[str, str]]) -> None:
    fieldnames = ["姓名", "人物简介", "首次出场回目", "备注"]
    with path.open("a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        for row in new_rows:
            w.writerow({k: row.get(k, "") for k in fieldnames})


def chunks(lst: list, n: int):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="仅处理前 N 个去重后的 unknown mention")
    parser.add_argument("--dry-run", action="store_true", help="不调用 API，只列出待处理 mention")
    args = parser.parse_args()

    if not NORM_JSON.is_file():
        raise FileNotFoundError(f"缺少: {NORM_JSON}")
    if not TABLE_CSV.is_file():
        raise FileNotFoundError(f"缺少: {TABLE_CSV}")

    items = collect_unknown_mentions(NORM_JSON)
    if args.limit and args.limit > 0:
        items = items[: args.limit]
        print(f"--limit={args.limit}，本 run 处理 {len(items)} 个去重 mention")

    print(f"去重后 unknown mention 数: {len(items)}")
    if args.dry_run:
        for it in items[:50]:
            print(json.dumps(it, ensure_ascii=False))
        if len(items) > 50:
            print(f"... 共 {len(items)} 条，仅展示前 50")
        return

    if not API_KEY:
        raise ValueError("缺少 API_KEY，请配置 DASHSCOPE_API_KEY 或 deal_txt.py")

    existing = load_existing_names(TABLE_CSV)
    # 预过滤：已在表中的 mention 对应常见全名若已存在可跳过 API（可选）
    to_model: list[dict] = []
    skipped: list[dict] = []
    for it in items:
        # 若 mention 本身已作为姓名在表中（极少数漏映射），直接跳过
        if it["mention"] in existing:
            skipped.append({**it, "note": "mention 已在人物表姓名列"})
            continue
        to_model.append(it)

    print(f"送模型批次数: {(len(to_model) + BATCH_SIZE - 1) // BATCH_SIZE}（每批 {BATCH_SIZE}）")

    shutil.copy2(TABLE_CSV, TABLE_BACKUP)
    print(f"已备份人物表: {TABLE_BACKUP}")

    all_decisions: list[dict] = []
    raw_blocks: list[str] = []
    appended_rows: list[dict[str, str]] = []

    names_snapshot = set(existing)
    for bi, batch in enumerate(chunks(to_model, BATCH_SIZE), start=1):
        user_blob = (
            "你只输出合法 JSON，不要 markdown。\n\n"
            + USER_PROMPT.format(items_json=json.dumps(batch, ensure_ascii=False))
        )
        print(f"批次 {bi}，本批 {len(batch)} 条…")
        raw = call_llm(user_blob)
        raw_blocks.append(f"===== BATCH {bi} =====\n{raw}\n")
        parsed = try_parse_json(raw)
        validated = validate_decisions(parsed, batch, names_snapshot)

        for d in validated:
            all_decisions.append(d)
            if d.get("decision") == "append_to_table":
                row = {
                    "姓名": (d.get("姓名") or "").strip(),
                    "人物简介": (d.get("人物简介") or "").strip(),
                    "首次出场回目": (d.get("首次出场回目") or "").strip() or "不详",
                    "备注": (d.get("备注") or "").strip() or f"mention增补:{d.get('mention')}",
                }
                if row["姓名"]:
                    append_rows_to_csv(TABLE_CSV, [row])
                    appended_rows.append(row)
                    names_snapshot.add(row["姓名"])

    RAW_LOG.write_text("\n".join(raw_blocks), encoding="utf-8")
    log = {
        "appended_count": len(appended_rows),
        "appended_rows": appended_rows,
        "skipped_already_in_table": skipped,
        "all_decisions": all_decisions,
    }
    LOG_JSON.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"本次新增人物表行数: {len(appended_rows)}")
    print(f"日志: {LOG_JSON}")
    print(f"原始模型输出: {RAW_LOG}")
    if appended_rows:
        print("新增姓名预览:", "、".join(r["姓名"] for r in appended_rows[:30]))
        if len(appended_rows) > 30:
            print(f"... 等共 {len(appended_rows)} 人")


if __name__ == "__main__":
    main()
