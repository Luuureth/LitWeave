import csv
import json
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
GROUNDED_CSV = (
    BASE_DIR
    / "功能2_事件整理归档_20260422_1541"
    / "01_过程文件"
    / "unified_events_grounded.csv"
)
TARGET_DIRS = [
    BASE_DIR / "剧版红楼梦" / "hongloumeng_json",
    BASE_DIR / "红楼梦文本" / "hongloumeng_txt_json",
]


def parse_characters(s: str) -> list[str]:
    if not s:
        return []
    return [x.strip() for x in s.split("、") if x.strip()]


def build_restore_index(csv_path: Path) -> dict[tuple[str, str], list[str]]:
    index: dict[tuple[str, str], list[str]] = {}
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            source_path = (row.get("source_path") or "").strip()
            event_id = (row.get("event_id") or "").strip()
            if not source_path or not event_id:
                continue
            chars = parse_characters((row.get("characters") or "").strip())
            index[(str(Path(source_path).resolve()), event_id)] = chars
    return index


def process_json_file(path: Path, index: dict[tuple[str, str], list[str]]) -> dict[str, int]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    stats = {"matched_events": 0, "changed_events": 0, "changed_files": 0}
    changed = False

    events = data.get("events")
    if isinstance(events, list):
        for ev in events:
            if not isinstance(ev, dict):
                continue
            event_id = ev.get("event_id")
            if not isinstance(event_id, str):
                continue
            key = (str(path.resolve()), event_id)
            if key not in index:
                continue
            stats["matched_events"] += 1
            old_chars = ev.get("characters")
            new_chars = index[key]
            if old_chars != new_chars:
                ev["characters"] = new_chars
                stats["changed_events"] += 1
                changed = True

    if changed:
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        stats["changed_files"] = 1

    return stats


def main() -> None:
    index = build_restore_index(GROUNDED_CSV)
    total = {
        "index_entries": len(index),
        "files_scanned": 0,
        "files_changed": 0,
        "matched_events": 0,
        "changed_events": 0,
    }

    for root in TARGET_DIRS:
        for path in root.rglob("*.json"):
            total["files_scanned"] += 1
            s = process_json_file(path, index)
            total["files_changed"] += s["changed_files"]
            total["matched_events"] += s["matched_events"]
            total["changed_events"] += s["changed_events"]

    print(json.dumps(total, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
