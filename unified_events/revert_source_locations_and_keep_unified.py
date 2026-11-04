from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Tuple

import pandas as pd

DEFAULT_ENCODING = "utf-8-sig"
BASE_DIR = Path(__file__).resolve().parent.parent
VIDEO_ROOT = BASE_DIR / "剧版红楼梦" / "hongloumeng_json"
TEXT_ROOT = BASE_DIR / "红楼梦文本" / "hongloumeng_txt_json"
UNIFIED_EVENTS_CSV = BASE_DIR / "unified_events" / "unified_events.csv"
UNIFIED_EVENTS_JSON = BASE_DIR / "unified_events" / "unified_events.json"


def load_unified_location_map() -> Dict[Tuple[str, str], str]:
    df = pd.read_csv(UNIFIED_EVENTS_CSV, encoding=DEFAULT_ENCODING)
    mapping: Dict[Tuple[str, str], str] = {}
    for _, row in df.iterrows():
        source_path = str(Path(str(row["source_path"])).resolve())
        event_id = str(row["event_id"]).strip()
        if not event_id:
            continue
        location = "" if pd.isna(row.get("location")) else str(row.get("location"))
        mapping[(source_path, event_id)] = location
    return mapping


def restore_source_locations(root: Path, location_map: Dict[Tuple[str, str], str]) -> Tuple[int, int]:
    changed_files = 0
    changed_events = 0
    for path in root.rglob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        file_changed = False
        resolved = str(path.resolve())
        for event in data.get("events", []):
            event_id = str(event.get("event_id", "")).strip()
            if not event_id:
                continue
            key = (resolved, event_id)
            if key not in location_map:
                continue
            old_location = event.get("location")
            new_location = location_map[key]
            if old_location != new_location:
                event["location"] = new_location
                changed_events += 1
                file_changed = True
        if file_changed:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            changed_files += 1
    return changed_files, changed_events


def main() -> None:
    location_map = load_unified_location_map()
    v_files, v_events = restore_source_locations(VIDEO_ROOT, location_map)
    t_files, t_events = restore_source_locations(TEXT_ROOT, location_map)
    print(f"Video source restored files/events: {v_files}/{v_events}")
    print(f"Text source restored files/events: {t_files}/{t_events}")
    print("Unified events files were kept unchanged.")


if __name__ == "__main__":
    main()
