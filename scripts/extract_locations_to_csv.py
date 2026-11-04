import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
TXT_JSON_ROOT = BASE_DIR / "红楼梦文本" / "hongloumeng_txt_json"
VIDEO_JSON_ROOT = BASE_DIR / "剧版红楼梦" / "hongloumeng_json"
OUTPUT_CSV = BASE_DIR / "all_locations.csv"
BY_FILE_CSV = BASE_DIR / "all_locations_by_file.csv"


def iter_json_files(root: Path):
    if not root.is_dir():
        return
    for p in root.rglob("*.json"):
        if p.is_file():
            yield p


def extract_locations_from_json(data):
    locations = []
    events = data.get("events")
    if isinstance(events, list):
        for event in events:
            if not isinstance(event, dict):
                continue
            loc = event.get("location")
            if isinstance(loc, str):
                name = loc.strip()
                if name:
                    locations.append(name)
    return locations


def main():
    name_count = defaultdict(int)
    name_files = defaultdict(set)
    total_json_files = 0
    used_json_files = 0

    # 明细：每个 JSON 文件内，每个地点字符串出现次数（便于回溯视频/章节源）
    by_file_rows = []

    roots = [(TXT_JSON_ROOT, "txt"), (VIDEO_JSON_ROOT, "video")]
    for target_dir, source in roots:
        for json_file in iter_json_files(target_dir):
            total_json_files += 1
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
            except Exception:
                continue

            locs = extract_locations_from_json(data)
            if not locs:
                continue

            used_json_files += 1
            rel = json_file.relative_to(BASE_DIR).as_posix()
            per_file = Counter(locs)
            for name, cnt in per_file.items():
                by_file_rows.append(
                    {
                        "location": name,
                        "source": source,
                        "json_path": rel,
                        "occurrence_count": cnt,
                    }
                )
                key = (name, source)
                name_count[key] += cnt
                name_files[key].add(rel)

    by_file_rows.sort(key=lambda x: (x["source"], x["location"], x["json_path"]))

    rows = []
    for (name, source), count in name_count.items():
        paths = sorted(name_files[(name, source)])
        rows.append(
            {
                "location": name,
                "source": source,
                "occurrence_count": count,
                "file_count": len(paths),
                "json_paths": "|".join(paths),
            }
        )
    rows.sort(key=lambda x: (0 if x["source"] == "txt" else 1, -x["occurrence_count"], x["location"]))

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "location",
                "source",
                "occurrence_count",
                "file_count",
                "json_paths",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    with BY_FILE_CSV.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["location", "source", "json_path", "occurrence_count"],
        )
        w.writeheader()
        w.writerows(by_file_rows)

    print(f"扫描 JSON 文件总数: {total_json_files}")
    print(f"包含 location 的文件数: {used_json_files}")
    print(f"提取行数（地点×来源去重，含 json_paths）: {len(rows)}")
    print(f"按文件明细行数: {len(by_file_rows)}")
    print(f"聚合表已输出: {OUTPUT_CSV}")
    print(f"按文件明细已输出: {BY_FILE_CSV}")


if __name__ == "__main__":
    main()
