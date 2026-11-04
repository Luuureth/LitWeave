import json
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
KB_PATH = BASE_DIR / "知识库" / "人物知识库" / "character_kb.json"
TARGET_DIRS = [
    BASE_DIR / "剧版红楼梦" / "hongloumeng_json",
    BASE_DIR / "红楼梦文本" / "hongloumeng_txt_json",
]


def build_name_map(kb_path: Path) -> dict[str, str]:
    with kb_path.open("r", encoding="utf-8") as f:
        kb = json.load(f)

    name_map: dict[str, str] = {}
    for item in kb:
        canonical = item.get("canonical_name")
        if not canonical:
            continue
        name_map[canonical] = canonical
        for alias in item.get("aliases", []) or []:
            if alias:
                name_map[alias] = canonical
    return name_map


def normalize_characters_list(chars: list, name_map: dict[str, str]) -> tuple[list[str], int, int]:
    if not isinstance(chars, list):
        return chars, 0, 0

    normalized: list[str] = []
    seen = set()
    converted_count = 0
    removed_count = 0

    for name in chars:
        if not isinstance(name, str):
            removed_count += 1
            continue
        canonical = name_map.get(name)
        if not canonical:
            removed_count += 1
            continue
        if canonical != name:
            converted_count += 1
        if canonical not in seen:
            seen.add(canonical)
            normalized.append(canonical)

    return normalized, converted_count, removed_count


def process_json_file(path: Path, name_map: dict[str, str]) -> dict[str, int]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    stats = {
        "changed_files": 0,
        "converted_names": 0,
        "removed_names": 0,
        "characters_fields": 0,
    }

    changed = False
    events = data.get("events")
    if isinstance(events, list):
        for event in events:
            if not isinstance(event, dict) or "characters" not in event:
                continue
            stats["characters_fields"] += 1
            old_chars = event.get("characters")
            new_chars, converted_count, removed_count = normalize_characters_list(old_chars, name_map)
            stats["converted_names"] += converted_count
            stats["removed_names"] += removed_count
            if new_chars != old_chars:
                event["characters"] = new_chars
                changed = True

    if changed:
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        stats["changed_files"] = 1

    return stats


def main() -> None:
    name_map = build_name_map(KB_PATH)

    total = {
        "files_scanned": 0,
        "files_changed": 0,
        "characters_fields": 0,
        "converted_names": 0,
        "removed_names": 0,
    }

    for target_dir in TARGET_DIRS:
        for json_file in target_dir.rglob("*.json"):
            total["files_scanned"] += 1
            stats = process_json_file(json_file, name_map)
            total["files_changed"] += stats["changed_files"]
            total["characters_fields"] += stats["characters_fields"]
            total["converted_names"] += stats["converted_names"]
            total["removed_names"] += stats["removed_names"]

    print(json.dumps(total, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
