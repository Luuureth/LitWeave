import argparse
import json
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional

import dashscope  # type: ignore[reportMissingImports]
from dashscope import MultiModalConversation  # type: ignore[reportMissingImports]
try:
    from tqdm import tqdm
except Exception:
    tqdm = None


# -----------------------------
# DashScope 基础配置
# -----------------------------
dashscope.base_http_api_url = os.getenv(
    "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/api/v1"
)

# 按你的要求保留这个默认模型名
MODEL_NAME = os.getenv("DASHSCOPE_MODEL", "qwen3.6-plus")
API_KEY = os.getenv("DASHSCOPE_API_KEY", "")

MAX_RETRIES = int(os.getenv("DASHSCOPE_MAX_RETRIES", "5"))
REQUEST_TIMEOUT = int(os.getenv("DASHSCOPE_TIMEOUT", "600"))


# -----------------------------
# 通用工具函数
# -----------------------------
def safe_text(x) -> str:
    if x is None:
        return ""
    s = str(x).strip()
    if s.lower() in {"nan", "none", "null", "na"}:
        return ""
    return s


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


def extract_first_json_object(text: str) -> str:
    """
    从模型输出中提取首个完整 JSON 对象。
    兼容：
    - markdown 代码块
    - 前后多余解释文字
    - 只取第一个合法 JSON 对象
    """
    text = text.strip()

    # 去掉 markdown 代码块包裹
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()

    # 直接就是 JSON
    if text.startswith("{") and text.endswith("}"):
        return text

    start = text.find("{")
    if start == -1:
        raise ValueError("未找到 JSON 起始符号 '{'")

    depth = 0
    in_string = False
    escape = False

    for i in range(start, len(text)):
        ch = text[i]

        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        else:
            if ch == '"':
                in_string = True
                continue
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]

    raise ValueError("未找到完整的 JSON 对象闭合 '}'")


def try_parse_json(text: str):
    json_str = extract_first_json_object(text)
    return json.loads(json_str)


def parse_model_output(raw_text: str) -> Dict:
    data = try_parse_json(raw_text)
    if isinstance(data, list):
        if not data:
            return {}
        if isinstance(data[0], dict):
            return data[0]
        return {}
    if isinstance(data, dict):
        return data
    return {}


# -----------------------------
# Prompt 构造
# -----------------------------
def build_prompt_for_item(item: Dict) -> str:
    """
    为单条事件构造闭集时间锚定提示词
    """
    ueid = safe_text(item.get("ueid"))
    event_repr = safe_text(item.get("event_repr_text"))
    event_summary = safe_text(item.get("event_summary"))
    semantic_core = safe_text(item.get("semantic_core"))
    characters = safe_text(item.get("characters"))
    location = safe_text(item.get("location"))
    candidates = item.get("candidate_nodes", [])

    cand_lines = []
    for c in candidates:
        cand_lines.append(
            (
                f"- timeline_id={safe_text(c.get('timeline_id'))} | "
                f"timeline_order={safe_text(c.get('timeline_order'))} | "
                f"红楼年份={safe_text(c.get('红楼年份'))} | "
                f"季节月份={safe_text(c.get('季节月份'))} | "
                f"事件名称={safe_text(c.get('事件名称'))} | "
                f"retrieval_score={safe_text(c.get('retrieval_score'))}"
            )
        )
    cand_block = "\n".join(cand_lines) if cand_lines else "- 无候选"

    prompt = f"""
你是《红楼梦》事件时间锚定器。你的任务不是开放生成，而是做“闭集选择”。

请根据输入事件的语义内容，从给定候选时间线节点中选择唯一一个最合适的 timeline_id。
如果候选都不合适，必须输出 "unknown"。

【严格约束】
1. 你只能输出候选列表中的 timeline_id，或者输出 "unknown"。
2. 不允许编造候选外的 timeline_id。
3. 不允许输出多个候选。
4. 不要输出 markdown、代码块、解释段落、前后缀，只能输出一个 JSON 对象。
5. grounding_confidence 必须是 0~1 之间的小数。
6. 当事件过于泛化、候选都不匹配、或你把握不足时，优先输出 "unknown"。
7. 优先依据 action、event_summary、semantic_core 判断事件语义，而不是只看人物或地点是否重合。
8. 若只是人物重合，但事件内容明显不一致，不应选择该候选。
9. 红楼年份、季节月份、timeline_order 是辅助信息；核心仍是事件语义匹配。
10. 若多个候选相近，请选择语义最具体、最直接对应当前事件的那个。

【输入事件】
- ueid: {ueid}
- event_repr_text: {event_repr}
- event_summary: {event_summary}
- semantic_core: {semantic_core}
- characters: {characters}
- location: {location if location else "无"}

【候选时间线（闭集）】
{cand_block}

【输出格式】
{{
  "ueid": "{ueid}",
  "timeline_id": "Txxx 或 unknown",
  "grounding_confidence": 0.0,
  "grounding_reason": "中文简短说明"
}}
""".strip()

    return prompt


# -----------------------------
# LLM 调用
# -----------------------------
def call_qwen(prompt: str, request_timeout: int) -> str:
    response = None
    last_err: Optional[Exception] = None

    for attempt in range(MAX_RETRIES):
        try:
            response = MultiModalConversation.call(
                api_key=API_KEY,
                model=MODEL_NAME,
                timeout=request_timeout,
                messages=[
                    {
                        "role": "system",
                        "content": [
                            {
                                "text": (
                                    "你是一个严格执行闭集选择任务的 JSON 输出器。"
                                    "你只能输出一个合法 JSON 对象，"
                                    "不得输出候选集之外的 ID，"
                                    "不得输出任何额外解释。"
                                )
                            }
                        ],
                    },
                    {
                        "role": "user",
                        "content": [{"text": prompt}],
                    },
                ],
            )
            break
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES - 1:
                wait_s = min(30, 2.0 * (2 ** attempt))
                print(f"调用失败，{wait_s:.1f}s 后重试 ({attempt + 1}/{MAX_RETRIES - 1})：{e}")
                time.sleep(wait_s)
            else:
                raise

    if response is None and last_err is not None:
        raise last_err

    if getattr(response, "status_code", None) not in (None, 200):
        raise RuntimeError(
            f"DashScope 调用失败: status_code={response.status_code}, "
            f"message={getattr(response, 'message', None)}"
        )

    return extract_text_from_response(response)


# -----------------------------
# 闭集结果校验
# -----------------------------
def validate_item(raw_obj: Dict, candidate_ids: List[str], fallback_ueid: str) -> Dict:
    ueid = safe_text(raw_obj.get("ueid")) or fallback_ueid
    timeline_id = safe_text(raw_obj.get("timeline_id")) or "unknown"
    reason = safe_text(raw_obj.get("grounding_reason")) or "模型未给出理由"

    try:
        conf = float(raw_obj.get("grounding_confidence", 0.0))
    except Exception:
        conf = 0.0

    conf = max(0.0, min(1.0, conf))

    if timeline_id != "unknown" and timeline_id not in set(candidate_ids):
        timeline_id = "unknown"
        conf = min(conf, 0.3)
        reason = f"闭集校验失败：模型返回了候选外 timeline_id。原始理由：{reason}"

    return {
        "ueid": ueid,
        "timeline_id": timeline_id if timeline_id else "unknown",
        "grounding_confidence": conf,
        "grounding_reason": reason,
    }


# -----------------------------
# 主批处理逻辑
# -----------------------------
def run_batch_grounding(
    input_path: Path,
    output_path: Path,
    progress_path: Path,
    error_path: Path,
    raw_log_path: Path,
    batch_size: int = 20,
    sleep_s: float = 0.2,
    start_index: int = 0,
    end_index: int = -1,
    resume: bool = True,
    request_timeout: int = REQUEST_TIMEOUT,
):
    if not API_KEY:
        raise ValueError("未检测到 DASHSCOPE_API_KEY 环境变量，请先设置后再运行。")

    packets = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(packets, list):
        raise ValueError("输入文件不是 JSON 数组。")

    total = len(packets)
    l = max(0, start_index)
    r = total if end_index < 0 else min(total, end_index)
    packets = packets[l:r]
    print(f"待处理样本区间: [{l}, {r})，共 {len(packets)} 条")

    done_map: Dict[str, Dict] = {}
    errors: List[Dict] = []
    raw_records: List[Dict] = []

    # 断点恢复：加载已有结果
    if resume and output_path.is_file():
        try:
            old = json.loads(output_path.read_text(encoding="utf-8"))
            if isinstance(old, list):
                for x in old:
                    if isinstance(x, dict) and safe_text(x.get("ueid")):
                        done_map[safe_text(x["ueid"])] = x
            print(f"已加载历史结果 {len(done_map)} 条，将自动跳过。")
        except Exception:
            pass

    # 断点恢复：加载已有 raw log
    if resume and raw_log_path.is_file():
        try:
            old_raw = json.loads(raw_log_path.read_text(encoding="utf-8"))
            if isinstance(old_raw, list):
                raw_records.extend(old_raw)
        except Exception:
            pass

    if tqdm is not None:
        pbar = tqdm(total=len(packets), desc="LLM闭集锚定", unit="条")
    else:
        pbar = None

    for i, item in enumerate(packets, start=1):
        ueid = safe_text(item.get("ueid"))
        if not ueid:
            if pbar is not None:
                pbar.update(1)
            continue

        if resume and ueid in done_map:
            if pbar is not None:
                pbar.update(1)
            continue

        cands = item.get("candidate_nodes", [])
        candidate_ids = [
            safe_text(c.get("timeline_id"))
            for c in cands
            if safe_text(c.get("timeline_id"))
        ]

        # 无候选，直接 unknown
        if not candidate_ids:
            done_map[ueid] = {
                "ueid": ueid,
                "timeline_id": "unknown",
                "grounding_confidence": 0.0,
                "grounding_reason": "无候选时间节点",
            }
            raw_records.append({
                "ueid": ueid,
                "prompt": "",
                "raw_response": "",
                "note": "无候选，直接unknown"
            })
            if pbar is not None:
                pbar.update(1)
                pbar.set_postfix_str(f"当前={ueid} | 无候选")
            continue

        prompt = build_prompt_for_item(item)

        try:
            raw_text = call_qwen(prompt, request_timeout=request_timeout)
            raw_records.append({
                "ueid": ueid,
                "prompt": prompt,
                "raw_response": raw_text,
            })

            raw_obj = parse_model_output(raw_text)
            fixed = validate_item(raw_obj, candidate_ids, fallback_ueid=ueid)
            done_map[ueid] = fixed

        except Exception as e:
            done_map[ueid] = {
                "ueid": ueid,
                "timeline_id": "unknown",
                "grounding_confidence": 0.0,
                "grounding_reason": f"LLM调用失败，保底unknown: {e}",
            }
            errors.append({"ueid": ueid, "error": str(e)})
            raw_records.append({
                "ueid": ueid,
                "prompt": prompt,
                "raw_response": "",
                "note": f"调用失败: {e}"
            })
        finally:
            if pbar is not None:
                pbar.update(1)
                pbar.set_postfix_str(f"当前={ueid} | done={len(done_map)} | err={len(errors)}")

        # 定期落盘
        if i % batch_size == 0:
            merged = list(done_map.values())
            output_path.write_text(
                json.dumps(merged, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            raw_log_path.write_text(
                json.dumps(raw_records, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            progress_path.write_text(
                json.dumps(
                    {
                        "processed_in_range": i,
                        "total_in_range": len(packets),
                        "current_ueid": ueid,
                        "done_count": len(done_map),
                        "timestamp": int(time.time()),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            print(f"进度: {i}/{len(packets)}，已累计结果 {len(done_map)}")

        if sleep_s > 0:
            time.sleep(sleep_s)

    # 最终落盘
    merged = list(done_map.values())
    output_path.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    raw_log_path.write_text(
        json.dumps(raw_records, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    error_path.write_text(
        json.dumps(errors, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"完成：输出 {output_path}，共 {len(merged)} 条；错误 {len(errors)} 条")
    if pbar is not None:
        pbar.close()


# -----------------------------
# CLI
# -----------------------------
def main():
    parser = argparse.ArgumentParser(
        description="批量闭集LLM时间锚定：timeline_grounding_input.json -> LLM结果JSON"
    )
    parser.add_argument(
        "--input",
        type=str,
        default="timeline_grounding_input.json",
        help="输入：闭集锚定包（JSON数组）",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="timeline_grounding_llm_output.json",
        help="输出：LLM回填结果（JSON数组）",
    )
    parser.add_argument(
        "--progress",
        type=str,
        default="timeline_grounding_llm_progress.json",
        help="进度文件",
    )
    parser.add_argument(
        "--error-log",
        type=str,
        default="timeline_grounding_llm_errors.json",
        help="错误日志",
    )
    parser.add_argument(
        "--raw-log",
        type=str,
        default="timeline_grounding_llm_raw.json",
        help="原始响应日志",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=20,
        help="每处理 N 条就落盘一次"
    )
    parser.add_argument(
        "--sleep-s",
        type=float,
        default=0.2,
        help="每次请求后休眠秒数"
    )
    parser.add_argument(
        "--start-index",
        type=int,
        default=0,
        help="起始索引（含）"
    )
    parser.add_argument(
        "--end-index",
        type=int,
        default=-1,
        help="结束索引（不含，-1表示到末尾）"
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="禁用断点续跑（默认启用）"
    )
    parser.add_argument(
        "--request-timeout",
        type=int,
        default=REQUEST_TIMEOUT,
        help="单次API请求超时（秒），建议先用60~120排查卡顿",
    )
    args = parser.parse_args()

    run_batch_grounding(
        input_path=Path(args.input),
        output_path=Path(args.output),
        progress_path=Path(args.progress),
        error_path=Path(args.error_log),
        raw_log_path=Path(args.raw_log),
        batch_size=args.batch_size,
        sleep_s=args.sleep_s,
        start_index=args.start_index,
        end_index=args.end_index,
        resume=not args.no_resume,
        request_timeout=args.request_timeout,
    )


if __name__ == "__main__":
    main()