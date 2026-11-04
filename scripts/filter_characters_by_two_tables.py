import csv
import json
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
KB_PATH = BASE_DIR / "知识库" / "人物知识库" / "character_kb.json"
TABLE_PATH = BASE_DIR / "知识库" / "人物知识库" / "红楼梦人物表.csv"
TARGET_DIRS = [
    BASE_DIR / "剧版红楼梦" / "hongloumeng_json",
    BASE_DIR / "红楼梦文本" / "hongloumeng_txt_json",
]


def build_allowed_names() -> set[str]:
    allowed: set[str] = set()

    kb_data = json.loads(KB_PATH.read_text(encoding="utf-8"))
    for item in kb_data:
        canonical = (item.get("canonical_name") or "").strip()
        if canonical:
            allowed.add(canonical)
        for alias in (item.get("aliases") or []):
            if isinstance(alias, str):
                a = alias.strip()
                if a:
                    allowed.add(a)

    with TABLE_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("姓名") or "").strip()
            if name:
                allowed.add(name)

    return allowed


def filter_characters_list(chars: list, allowed: set[str]) -> tuple[list[str], int]:
    if not isinstance(chars, list):
        return chars, 0

    new_chars: list[str] = []
    seen = set()
    removed = 0

    for x in chars:
        if not isinstance(x, str):
            removed += 1
            continue
        s = x.strip()
        if not s or s not in allowed:
            removed += 1
            continue
        if s not in seen:
            seen.add(s)
            new_chars.append(s)

    return new_chars, removed


def process_file(path: Path, allowed: set[str]) -> dict[str, int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    stats = {"changed_files": 0, "changed_events": 0, "removed_names": 0, "characters_fields": 0}
    changed = False

    events = data.get("events")
    if isinstance(events, list):
        for ev in events:
            if not isinstance(ev, dict) or "characters" not in ev:
                continue
            old_chars = ev.get("characters")
            if not isinstance(old_chars, list):
                continue
            stats["characters_fields"] += 1
            new_chars, removed = filter_characters_list(old_chars, allowed)
            stats["removed_names"] += removed
            if new_chars != old_chars:
                ev["characters"] = new_chars
                stats["changed_events"] += 1
                changed = True

    if changed:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        stats["changed_files"] = 1

    return stats


def main() -> None:
    allowed = build_allowed_names()
    total = {
        "allowed_names": len(allowed),
        "files_scanned": 0,
        "files_changed": 0,
        "events_changed": 0,
        "characters_fields": 0,
        "removed_names": 0,
    }

    for root in TARGET_DIRS:
        for path in root.rglob("*.json"):
            total["files_scanned"] += 1
            s = process_file(path, allowed)
            total["files_changed"] += s["changed_files"]
            total["events_changed"] += s["changed_events"]
            total["characters_fields"] += s["characters_fields"]
            total["removed_names"] += s["removed_names"]

    print(json.dumps(total, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
