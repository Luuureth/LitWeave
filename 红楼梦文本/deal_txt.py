import json
import os
import re
import time
from pathlib import Path

import dashscope
from dashscope import MultiModalConversation


PROMPT_TEMPLATE_TEXT = """
请分析我提供的《红楼梦》原著章节文本，并以“后续构建事件知识图谱、时间线和人物网”为目标，
对当前章节文本进行叙事事件划分，并输出统一 JSON。

请严格遵守以下要求：
1. 只分析当前输入的这一回文本，不要推断其他回目的内容。
2. 按“叙事事件”切分，不要按自然段机械切分。
3. 一个事件应是相对完整的动作或情节单元，通常具有明确的动作、人物、地点，必要时带有时间线索。
4. 不要为了凑数量强行拆事件；若连续段落表达的是同一件事，不要拆开。
5. 如果一段文字中明显发生了两件不同的事，可以拆成两个事件。
6. 人物、地点尽量标准化；若不能确定，就使用当前文本中最稳妥的称呼，不要编造。
7. 地点字段只输出一个“最主要地点”：
   - 若文本中出现多个层级地点，请优先输出更稳定、便于后续归并的主地点；
   - 不要使用“地点1/地点2”这样的写法；
   - 若无法确定，则写 null。
8. 时间信息不要编造精确日期，只保留简洁、明确、可直接从文本中支持的时间线索。
9. time_hint 只能从以下枚举中选择：
   - null
   - "background"
   - "same_time"
   - "after"
   - "flashback"
10. explicit_time 仅记录文本中明确出现的时间表达：
   - 例如“次日”“一日”“当晚”“彼时”“少时”“忽一日”等；
   - 若没有明确时间表达，则写 null；
   - 不要根据常识或剧情自行推断。
11. relation_to_previous 只能从以下枚举中选择：
   - "start"
   - "sequential"
   - "flashback"
   - "parallel"
   - "unclear"
12. action 应简洁概括事件核心动作，尽量使用短语，不要写成长句。
13. event_summary 只用一句话概括事件内容，简洁客观，不要写成长篇分析，不要加入评价性语言。
14. 每个事件必须提供 source_text 字段，内容为该事件对应的原文连续片段（可多句），必须直接摘自输入文本，不可改写、不可总结、不可翻译。
15. source_text 要尽量完整覆盖该事件的关键信息，避免只截取几个词。
16. 只输出合法 JSON，不要输出任何解释、说明、前言、后记、注释或代码块标记。
17. 如果信息不确定，请写 null，不要编造。
18. 请优先保证：事件边界清晰、JSON 合法、字段稳定、便于后续程序处理。

当前文本信息如下：
- chapter_id: "{chapter_id}"
- chapter_title: "{chapter_title}"
- source_type: "hongloumeng_text"

请输出以下 JSON 格式：

{{
  "chapter_id": "{chapter_id}",
  "chapter_title": "{chapter_title}",
  "source_type": "hongloumeng_text",
  "event_count": 0,
  "events": [
    {{
      "event_id": "E01",
      "narrative_order": 1,
      "action": "事件核心动作",
      "characters": ["人物1", "人物2"],
      "location": "地点",
      "time_hint": null,
      "explicit_time": null,
      "relation_to_previous": "start",
      "event_summary": "一句话概括该事件",
      "source_text": "该事件在原文中的连续片段"
    }}
  ]
}}

字段要求：
- event_id：当前章节内连续编号，如 E01, E02, E03
- narrative_order：该事件在当前章节文本中的叙事顺序
- action：简洁概括事件核心动作，尽量使用短语
- characters：该事件中明确出现或被明确提及的人物列表；尽量使用稳定称呼
- location：事件发生的最主要地点；只能输出一个地点；若不明确可写 null
- time_hint：只能从以下枚举中选择：
  - null
  - "background"
  - "same_time"
  - "after"
  - "flashback"
- explicit_time：仅记录文本中明确出现的时间表达；若没有则写 null
- relation_to_previous：只能从以下枚举中选择：
  - "start"
  - "sequential"
  - "flashback"
  - "parallel"
  - "unclear"
- event_summary：一句话概括事件内容，简洁客观，不要写成长篇描述
- source_text：该事件对应的原文连续片段，必须直接摘自输入文本，不可改写或总结；若无法定位可写 null

补充规则：
1. 若当前文本主要是背景设定、神话引入、人物介绍，可将事件标记为 "background"。
2. 若当前事件是回忆、插叙、倒叙内容，则：
   - time_hint 设为 "flashback"
   - relation_to_previous 优先设为 "flashback"
3. 若当前事件与前一事件明显属于同一时段但视角切换，则：
   - time_hint 可设为 "same_time"
   - relation_to_previous 可设为 "parallel"
4. 若只是普通叙事推进，则：
   - time_hint 优先设为 "after" 或 null
   - relation_to_previous 优先设为 "sequential"
5. 不要输出 schema 之外的字段。
6. 不要使用中文引号、中文逗号、中文布尔值。
7. 输出前请自行检查 JSON 是否合法。
"""


# ========== 1. 基础配置（与 deal_video.py 对齐）==========
dashscope.base_http_api_url = os.getenv(
    "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/api/v1"
)

API_KEY = "sk-1dd5967eb1034316947e3ac887a5552a"
if not API_KEY:
    raise ValueError("未检测到 DASHSCOPE_API_KEY 环境变量，请先配置。")

SCRIPT_DIR = Path(__file__).resolve().parent
TEXT_DIR = SCRIPT_DIR / "hongloumeng_txt"  # 各回 txt 所在目录
SPLIT_DIR = TEXT_DIR / "split_parts"  # 分段 txt 所在目录
OUTPUT_DIR = SCRIPT_DIR / "hongloumeng_txt_json"  # JSON / raw 输出目录
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MODEL_NAME = os.getenv("DASHSCOPE_MODEL", "qwen3.6-plus")
CHAPTER_START = 71
CHAPTER_END = 72
MAX_RETRIES = int(os.getenv("DASHSCOPE_MAX_RETRIES", "5"))
REQUEST_TIMEOUT = int(os.getenv("DASHSCOPE_TIMEOUT", "600"))
FORCE_REPROCESS = os.getenv("FORCE_REPROCESS", "0") == "1"
PREFER_SPLIT_PARTS = os.getenv("PREFER_SPLIT_PARTS", "1") == "1"
TARGET_FROM_FAILED_JSON = os.getenv("TARGET_FROM_FAILED_JSON", "1") == "1"


def chapter_id_from_filename(path: Path) -> str:
    m = re.search(r"第(\d+)(?:_\d+)?回", path.stem)
    if m:
        return m.group(1)
    return path.stem


def read_chapter_meta(path: Path) -> tuple[str, str, str]:
    """返回 (chapter_id, chapter_title, full_text)。"""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    title_line = lines[0].strip() if lines else ""
    cid = chapter_id_from_filename(path)
    return cid, title_line, text


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


def should_skip_existing_success(path: Path) -> bool:
    """已存在且为成功 JSON（含 events）时可跳过，避免重复调用模型。"""
    if not path.is_file() or FORCE_REPROCESS:
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return isinstance(data, dict) and isinstance(data.get("events"), list)


def is_error_payload(path: Path) -> bool:
    """判断是否是失败产物（记录了 error 字段）。"""
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return isinstance(data, dict) and isinstance(data.get("error"), str)


def normalize_events(data: dict) -> list[dict]:
    """提取并标准化事件列表。"""
    events = data.get("events")
    if not isinstance(events, list):
        return []
    normalized = []
    for ev in events:
        if isinstance(ev, dict):
            if "source_text" not in ev:
                ev["source_text"] = None
            normalized.append(ev)
    return normalized


def finalize_chapter_json(chapter_id: str, chapter_title: str, events: list[dict]) -> dict:
    """重建章节 JSON，统一 event_id / narrative_order。"""
    fixed_events: list[dict] = []
    for i, ev in enumerate(events, start=1):
        new_ev = dict(ev)
        new_ev["event_id"] = f"E{i:02d}"
        new_ev["narrative_order"] = i
        if i > 1 and new_ev.get("relation_to_previous") == "start":
            new_ev["relation_to_previous"] = "sequential"
        fixed_events.append(new_ev)

    return {
        "chapter_id": chapter_id,
        "chapter_title": chapter_title,
        "source_type": "hongloumeng_text",
        "event_count": len(fixed_events),
        "events": fixed_events,
    }


def get_failed_chapters_from_output() -> list[int]:
    """从现有输出中找出 error JSON 对应的章节编号。"""
    numbers = set()
    for p in OUTPUT_DIR.glob("第*回.json"):
        if not is_error_payload(p):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue

        source_file = data.get("source_file")
        if isinstance(source_file, str):
            m = re.search(r"第(\d+)回\.txt$", source_file)
            if m:
                numbers.add(int(m.group(1)))
                continue

        m2 = re.search(r"第(\d+)回", p.stem)
        if m2:
            numbers.add(int(m2.group(1)))

    return sorted(numbers)


def detect_split_parts(chapter_no: int) -> tuple[Path, Path] | None:
    p1 = SPLIT_DIR / f"第{chapter_no:03d}_1回.txt"
    p2 = SPLIT_DIR / f"第{chapter_no:03d}_2回.txt"
    if p1.is_file() and p2.is_file():
        return p1, p2
    return None


def get_split_pending_chapters() -> list[int]:
    """从 split_parts 中找出尚未成功生成章节 JSON 的回目。"""
    if not SPLIT_DIR.is_dir():
        return []

    numbers = set()
    for p in SPLIT_DIR.glob("第*_1回.txt"):
        m = re.search(r"第(\d+)_1回", p.stem)
        if not m:
            continue
        n = int(m.group(1))
        p2 = SPLIT_DIR / f"第{n:03d}_2回.txt"
        if not p2.is_file():
            continue

        output_json = OUTPUT_DIR / f"第{n:03d}回.json"
        if should_skip_existing_success(output_json):
            continue
        numbers.add(n)

    return sorted(numbers)


def call_qwen_on_chapter(chapter_id: str, chapter_title: str, body: str) -> dict:
    instruction = PROMPT_TEMPLATE_TEXT.format(
        chapter_id=chapter_id,
        chapter_title=chapter_title,
    )
    user_blob = f"{instruction}\n\n【本回正文】\n{body}"

    response = None
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            response = MultiModalConversation.call(
                api_key=API_KEY,
                model=MODEL_NAME,
                timeout=REQUEST_TIMEOUT,
                messages=[
                    {
                        "role": "user",
                        "content": [{"text": user_blob}],
                    }
                ],
            )
            break
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES - 1:
                wait_s = min(30, 2.0 * (2**attempt))
                print(
                    f"  调用失败，{wait_s:.1f}s 后重试 "
                    f"({attempt + 1}/{MAX_RETRIES - 1})：{e}"
                )
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

    return {"raw_text": extract_text_from_response(response)}


def run_single_text(chapter_id: str, chapter_title: str, body: str) -> tuple[dict, str]:
    result = call_qwen_on_chapter(chapter_id, chapter_title, body)
    raw_text = result["raw_text"]
    data = try_parse_json(raw_text)
    events = normalize_events(data)
    final = finalize_chapter_json(chapter_id, chapter_title, events)
    return final, raw_text


def process_chapter(chapter_no: int) -> tuple[bool, str]:
    target_txt = TEXT_DIR / f"第{chapter_no:03d}回.txt"
    if not target_txt.is_file():
        return False, f"缺少源文件: {target_txt.name}"

    chapter_id, chapter_title, body = read_chapter_meta(target_txt)
    output_json = OUTPUT_DIR / f"第{chapter_no:03d}回.json"
    output_raw = OUTPUT_DIR / f"第{chapter_no:03d}回.raw.txt"

    if should_skip_existing_success(output_json):
        return True, f"已跳过（已有成功结果）: {target_txt.name}"

    split_parts = detect_split_parts(chapter_no) if PREFER_SPLIT_PARTS else None

    try:
        if split_parts:
            part1, part2 = split_parts
            print(f"正在分析: 第{chapter_no:03d}回（分段模式）")
            cid1, _, body1 = read_chapter_meta(part1)
            cid2, _, body2 = read_chapter_meta(part2)
            cid = cid1 if cid1 == cid2 else chapter_id

            data1, raw1 = run_single_text(cid, chapter_title, body1)
            data2, raw2 = run_single_text(cid, chapter_title, body2)
            merged_events = normalize_events(data1) + normalize_events(data2)
            merged = finalize_chapter_json(cid, chapter_title, merged_events)

            output_raw.write_text(
                "===== PART 1 =====\n"
                + raw1
                + "\n\n===== PART 2 =====\n"
                + raw2
                + "\n",
                encoding="utf-8",
            )
            output_json.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
            return True, f"✓ 成功保存（分段合并）: {output_json.name}"

        print(f"正在分析: {target_txt.name} (chapter_id={chapter_id})")
        final_data, raw_text = run_single_text(chapter_id, chapter_title, body)
        output_raw.write_text(raw_text, encoding="utf-8")
        output_json.write_text(json.dumps(final_data, ensure_ascii=False, indent=2), encoding="utf-8")
        return True, f"✓ 成功保存: {output_json.name}"

    except Exception as e:
        err_payload = {
            "chapter_id": chapter_id,
            "chapter_title": chapter_title,
            "source_file": str(target_txt),
            "model": MODEL_NAME,
            "error": str(e),
        }
        output_json.write_text(json.dumps(err_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return False, f"✗ 处理失败: {target_txt.name}，原因: {e}"


def main():
    failed_targets = get_failed_chapters_from_output() if TARGET_FROM_FAILED_JSON else []
    split_pending = get_split_pending_chapters() if PREFER_SPLIT_PARTS else []

    if failed_targets or split_pending:
        target_chapters = sorted(set(failed_targets) | set(split_pending))
        if failed_targets:
            print(f"检测到失败章节（来自 error JSON）：{failed_targets}")
        if split_pending:
            print(f"检测到待补章节（来自 split_parts）：{split_pending}")
        print(f"本次目标章节：{target_chapters}")
    else:
        target_chapters = list(range(CHAPTER_START, CHAPTER_END + 1))
        print(f"按区间处理章节：{CHAPTER_START}-{CHAPTER_END}")

    success = 0
    fail = 0
    for n in target_chapters:
        ok, msg = process_chapter(n)
        print(msg)
        if ok:
            success += 1
        else:
            fail += 1

    print(f"\n处理完成：成功 {success}，失败 {fail}")


if __name__ == "__main__":
    main()
