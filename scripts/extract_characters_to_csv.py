import csv
import json
from collections import defaultdict
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
TXT_JSON_ROOT = BASE_DIR / "红楼梦文本" / "hongloumeng_txt_json"
VIDEO_JSON_ROOT = BASE_DIR / "剧版红楼梦" / "hongloumeng_json"
OUTPUT_CSV = BASE_DIR / "all_characters.csv"


def iter_json_files(root: Path):
    if not root.is_dir():
        return
    for p in root.rglob("*.json"):
        if p.is_file():
            yield p


def extract_characters_from_json(data):
    characters = []
    events = data.get("events")
    if isinstance(events, list):
        for event in events:
            if not isinstance(event, dict):
                continue
            chars = event.get("characters")
            if isinstance(chars, list):
                for c in chars:
                    if isinstance(c, str):
                        name = c.strip()
                        if name:
                            characters.append(name)
            elif isinstance(chars, str):
                name = chars.strip()
                if name:
                    characters.append(name)
    return characters


def main():
    # key: (name, source) source 为 "txt" 或 "video"
    name_count = defaultdict(int)
    name_files = defaultdict(set)
    total_json_files = 0
    used_json_files = 0

    roots = [(TXT_JSON_ROOT, "txt"), (VIDEO_JSON_ROOT, "video")]
    for target_dir, source in roots:
        for json_file in iter_json_files(target_dir):
            total_json_files += 1
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
            except Exception:
                continue

            chars = extract_characters_from_json(data)
            if not chars:
                continue

            used_json_files += 1
            for name in chars:
                key = (name, source)
                name_count[key] += 1
                name_files[key].add(str(json_file))

    rows = []
    for (name, source), count in name_count.items():
        rows.append((name, source, count, len(name_files[(name, source)])))
    # 先按来源 txt / video，再按次数、名称
    rows.sort(key=lambda x: (0 if x[1] == "txt" else 1, -x[2], x[0]))

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["character", "source", "occurrence_count", "file_count"])
        writer.writerows(rows)

    print(f"扫描 JSON 文件总数: {total_json_files}")
    print(f"包含 characters 的文件数: {used_json_files}")
    print(f"提取行数（人物×来源去重）: {len(rows)}")
    print(f"CSV 已输出: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()

