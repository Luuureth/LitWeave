"""
统一事件表示：路径配置（纯规则版，无 LLM 调用）。
"""
from pathlib import Path


# scripts/ 的上一级为项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASE_DIR = PROJECT_ROOT
VIDEO_DIR = BASE_DIR / "剧版红楼梦" / "hongloumeng_json"
TEXT_DIR = BASE_DIR / "红楼梦文本" / "hongloumeng_txt_json"

OUTPUT_DIR = BASE_DIR / "unified_events"
OUTPUT_JSON = OUTPUT_DIR / "unified_events.json"
OUTPUT_CSV = OUTPUT_DIR / "unified_events.csv"
