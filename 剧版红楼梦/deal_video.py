import os
import json
import re
import time
from pathlib import Path

import dashscope
from dashscope import MultiModalConversation


# ========== 1. 基础配置 ==========
# 中国内地（可用环境变量覆盖）：
dashscope.base_http_api_url = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/api/v1")
# 国际站可改成：
# dashscope.base_http_api_url = "https://dashscope-intl.aliyuncs.com/api/v1"

API_KEY = "sk-1dd5967eb1034316947e3ac887a5552a"
if not API_KEY:
    raise ValueError("未检测到 DASHSCOPE_API_KEY 环境变量，请先配置。")

BASE_DIR = Path(r"D:\大三下\礼物计划\剧版红楼梦")
SEGMENTS_ROOT = BASE_DIR / "hongloumeng_segments"
JSON_ROOT = BASE_DIR / "hongloumeng_json"

MODEL_NAME = os.getenv("DASHSCOPE_MODEL", "qwen3.6-plus")  # 你现在在用的模型

# 定向重跑清单（直接指定视频片段，避免歧义）
# 这些路径相对于 SEGMENTS_ROOT
REPROCESS_VIDEO_PATHS = [
    "hongloumeng1_segments/2.mp4",
    "hongloumeng22_segments/7.mp4",
    "hongloumeng4_segments/11.mp4",
    "hongloumeng4_segments/5.mp4",
    "hongloumeng5_segments/23.mp4",
    "hongloumeng5_segments/3.mp4",
    "hongloumeng6_segments/1.mp4",
    "hongloumeng6_segments/4.mp4",
    "hongloumeng6_segments/9.mp4",
    "hongloumeng7_segments/18.mp4",
    "hongloumeng8_segments/11.mp4",
    "hongloumeng8_segments/17.mp4",
]


# ========== 2. 你的最小 JSON 提示词 ==========
PROMPT_TEMPLATE = """
请分析我上传的这一段《红楼梦》视频，并以“后续构建事件知识图谱、时间线和人物网”为目标，
抽取当前视频段中的主要叙事事件。

请严格遵守以下要求：
1. 只分析当前视频段，不要推断整集外的信息。
2. 按“叙事事件”切分，不要按镜头切分。
3. 一个事件应是相对完整的动作或情节单元。
4. 不要为了凑数量强行拆事件。
5. 如果某段只是片头、片尾、字幕、过场风景，且没有明确叙事功能，则不要作为事件输出。
6. 人物、地点尽量标准化；若不能确定，就用当前视频段内最稳妥的称呼，不要编造。
7. 地点字段只输出一个“最主要地点”：
   - 若画面中出现多个层级地点，请优先输出更稳定、便于后续归并的主地点；
   - 不要使用“地点1/地点2”这样的写法；
   - 若无法确定，则写 null。
8. 时间信息不要编造精确时间，只保留简洁的时间线索。
9. time_hint 只能从以下枚举中选择：
   - null
   - "background"
   - "same_time"
   - "after"
   - "flashback"
10. explicit_time 仅记录视频、字幕、对白中明确出现的时间表达，如果没有明确时间信息，写 null；不要根据常识或剧情自行推断。
11. relation_to_previous 只能从以下枚举中选择：
   - "start"
   - "sequential"
   - "flashback"
   - "parallel"
   - "unclear"
12. 只输出合法 JSON，不要输出任何解释、说明或代码块标记。
13. 请优先保证：事件边界清晰、JSON 合法、字段稳定。
14. characters 只保留对后续图谱有意义的人物或角色称呼；
15. 如果同一事件中的人物角色存在不确定，不要混淆带入其他事件的信息；
16. event_summary 必须与当前 event 的 characters 和 location 保持一致。
17. 语言要求（非常重要）：
   - action / characters / location / event_summary 必须使用简体中文；
   - 禁止输出英文人名、英文地点、英文句子；
   - 若不确定可写 null，不要改用英文。

当前分段信息如下：
- episode_id: "{episode_id}"
- episode_title: "{episode_title}"
- segment_id: "{segment_id}"

请输出以下 JSON 格式：

{{
  "episode_id": "{episode_id}",
  "episode_title": "{episode_title}",
  "segment_id": "{segment_id}",
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
      "event_summary": "一句话概括该事件，概括事件的核心动作、主要人物和关键结果，不要写成长篇描述。"
    }}
  ]
}}

字段要求：
- event_id：当前视频段内连续编号，如 E01, E02, E03
- narrative_order：该事件在当前视频段中的叙事顺序
- action：简洁概括事件核心动作，尽量使用短语，不要写成长段
- characters：该事件中明确出现或被明确提及的人物列表；尽量使用稳定称呼
- location：事件发生的最主要地点；只能输出一个地点；若不明确可写 null
- time_hint：只能从以下枚举中选择：
  - null
  - "background"
  - "same_time"
  - "after"
  - "flashback"
- 只有以下情况才填 explicit_time
  - 对白中明确提到时间
  - 旁白中明确提到时间
  - 屏幕字幕中明确出现时间
  - 画面中可直接读取的日期/时间信息
  - 否则一律填 null
- relation_to_previous：只能从以下枚举中选择：
  - "start"
  - "sequential"
  - "flashback"
  - "parallel"
  - "unclear"
- event_summary：一句话概括事件内容，简洁客观，不要写成长篇描述，概括事件的核心动作、主要人物和关键结果

输出约束：
1. event_count 必须等于 events 数组长度
2. 所有字段名必须使用英文
3. 所有字符串必须使用英文双引号
4. 若不确定，不要编造，直接写 null
5. 不要输出 schema 之外的字段
6. 不要使用中文引号、中文逗号、中文布尔值
7. 输出前请自行检查 JSON 是否合法
"""


# ========== 3. 工具函数 ==========
def segment_id_from_filename(file_path: Path) -> str:
    """
    从文件名生成 segment_id
    例如：segment_01.mp4 -> S01
    """
    stem = file_path.stem
    m = re.search(r"(\d+)", stem)
    if m:
        return f"S{int(m.group(1)):02d}"
    return stem


def extract_text_from_response(response) -> str:
    """
    从 DashScope 返回中尽量稳妥地取出文本
    """
    try:
        content = response.output.choices[0].message.content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    if "text" in item:
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
    """
    尝试解析 JSON；如果模型返回 ```json ... ```，先剥掉代码块
    """
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()
    return json.loads(text)


def call_qwen_on_video(video_path: Path, segment_id: str, episode_id: str, episode_title: str) -> dict:
    """
    调用 Qwen 处理单个本地视频文件
    """
    prompt = PROMPT_TEMPLATE.format(
        episode_id=episode_id,
        episode_title=episode_title,
        segment_id=segment_id,
    )

    # DashScope 本地路径格式：file://D:/...（Windows 下用正斜杠，避免 file:///D:/ 被解析成 /D:/）
    video_uri = "file://" + video_path.resolve().as_posix()

    last_err = None
    response = None
    for attempt in range(3):
        try:
            response = MultiModalConversation.call(
                api_key=API_KEY,
                model=MODEL_NAME,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"video": video_uri},
                            {"text": prompt},
                        ],
                    }
                ],
            )
            break
        except Exception as e:
            last_err = e
            if attempt < 2:
                time.sleep(1.5 * (2**attempt))
            else:
                raise

    if response is None and last_err is not None:
        raise last_err

    if getattr(response, "status_code", None) not in (None, 200):
        raise RuntimeError(
            f"DashScope 调用失败: status_code={response.status_code}, message={getattr(response, 'message', None)}"
        )

    text = extract_text_from_response(response)
    return {"raw_text": text}


def parse_episode_no_from_json_dir(json_dir_name: str) -> int | None:
    m = re.search(r"hongloumeng(\d+)_json", json_dir_name)
    if m:
        return int(m.group(1))
    return None


def read_episode_meta_from_existing_json(json_path: Path) -> tuple[str, str]:
    """
    优先从现有 json 里读 episode_id / episode_title，避免丢失原始集名。
    """
    default_episode_id = ""
    default_episode_title = "红楼梦分段"

    ep_no = parse_episode_no_from_json_dir(json_path.parent.name)
    if ep_no is not None:
        default_episode_id = f"{ep_no:02d}"
        default_episode_title = f"红楼梦第{ep_no}集"

    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return default_episode_id, default_episode_title

    episode_id = data.get("episode_id")
    episode_title = data.get("episode_title")
    if isinstance(episode_id, str) and episode_id.strip():
        default_episode_id = episode_id.strip()
    if isinstance(episode_title, str) and episode_title.strip():
        default_episode_title = episode_title.strip()
    return default_episode_id, default_episode_title


def find_video_by_json_path(json_path: Path) -> Path | None:
    """
    根据 json 路径反查对应分段视频：
    hongloumengX_json/N.json -> hongloumeng_segments/hongloumengX_segments/N.(mp4|mov|avi|mkv)
    """
    episode_no = parse_episode_no_from_json_dir(json_path.parent.name)
    if episode_no is None:
        return None

    segment_stem = json_path.stem
    segment_dir = SEGMENTS_ROOT / f"hongloumeng{episode_no}_segments"
    if not segment_dir.is_dir():
        return None

    for ext in (".mp4", ".mov", ".avi", ".mkv"):
        video_path = segment_dir / f"{segment_stem}{ext}"
        if video_path.is_file():
            return video_path
    return None


def output_json_from_video(video_path: Path) -> Path | None:
    """
    根据视频路径反查输出 JSON：
    hongloumeng_segments/hongloumengX_segments/N.mp4 -> hongloumeng_json/hongloumengX_json/N.json
    """
    episode_no = parse_episode_no_from_json_dir(video_path.parent.name.replace("_segments", "_json"))
    if episode_no is None:
        m = re.search(r"hongloumeng(\d+)_segments", video_path.parent.name)
        if not m:
            return None
        episode_no = int(m.group(1))
    return JSON_ROOT / f"hongloumeng{episode_no}_json" / f"{video_path.stem}.json"


# ========== 4. 主流程 ==========
def main():
    video_targets = [SEGMENTS_ROOT / rel for rel in REPROCESS_VIDEO_PATHS]
    print(f"本次定向重跑视频数: {len(video_targets)}")

    success = 0
    fail = 0
    for video_file in video_targets:
        if not video_file.is_file():
            print(f"✗ 视频不存在，跳过: {video_file}")
            fail += 1
            continue

        output_json = output_json_from_video(video_file)
        if output_json is None:
            print(f"✗ 无法从视频路径推导 JSON 输出路径，跳过: {video_file}")
            fail += 1
            continue

        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_raw = output_json.with_suffix(".raw.txt")
        segment_id = segment_id_from_filename(video_file)
        if output_json.is_file():
            episode_id, episode_title = read_episode_meta_from_existing_json(output_json)
        else:
            m = re.search(r"hongloumeng(\d+)_segments", video_file.parent.name)
            ep = int(m.group(1)) if m else 0
            episode_id = f"{ep:02d}" if ep else ""
            episode_title = f"红楼梦第{ep}集" if ep else "红楼梦分段"

        print(f"正在重跑视频: {video_file} -> {output_json}")
        try:
            result = call_qwen_on_video(
                video_path=video_file,
                segment_id=segment_id,
                episode_id=episode_id,
                episode_title=episode_title,
            )
            raw_text = result["raw_text"]
            output_raw.write_text(raw_text, encoding="utf-8")

            data = try_parse_json(raw_text)
            if "events" in data and "event_count" in data and isinstance(data["events"], list):
                data["event_count"] = len(data["events"])

            output_json.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"✓ 重跑成功并覆盖: {output_json}")
            success += 1
        except Exception as e:
            print(f"✗ 重跑失败: {output_json}")
            print(f"  原因: {e}")
            err_payload = {
                "episode_id": episode_id,
                "episode_title": episode_title,
                "segment_id": segment_id,
                "video_file": str(video_file),
                "model": MODEL_NAME,
                "error": str(e),
            }
            output_json.write_text(
                json.dumps(err_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"  已覆盖为错误信息: {output_json}")
            fail += 1

    print(f"全部处理完成。成功: {success}，失败: {fail}")


if __name__ == "__main__":
    main()

