from __future__ import annotations

import csv
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
CSV_PATH = BASE / "uncertain_timeline_events_for_manual_review.csv"
MATCHED_JSON = BASE / "matched_events_with_timeline.json"
INDEX_JSON = BASE / "timeline_event_index.json"


def safe_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def dedup_keep_order(items: list[str]) -> list[str]:
    seen = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def load_manual_map() -> dict[str, dict[str, str]]:
    manual_map: dict[str, dict[str, str]] = {}
    with CSV_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            link_id = safe_text(row.get("link_id"))
            if not link_id:
                continue
            manual_map[link_id] = {
                "manual_timeline_id": safe_text(row.get("manual_timeline_id")),
                "manual_timeline_year": safe_text(row.get("manual_timeline_year")),
                "manual_timeline_season": safe_text(row.get("manual_timeline_season")),
                "manual_timeline_event_name": safe_text(row.get("manual_timeline_event_name")),
                "manual_notes": safe_text(row.get("manual_notes")),
            }
    return manual_map


def build_timeline_index(items: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for item in items:
        key = safe_text(item.get("timeline_id")) or "不确定"
        groups.setdefault(key, []).append(item)

    out: list[dict] = []
    for timeline_id, rows in groups.items():
        first = rows[0]
        out.append(
            {
                "timeline_id": timeline_id,
                "timeline_year": safe_text(first.get("timeline_year")) or "不确定",
                "timeline_season": safe_text(first.get("timeline_season")) or "不确定",
                "timeline_event_name": safe_text(first.get("timeline_event_name")) or "不确定",
                "timeline_ref": safe_text(first.get("timeline_ref")) or "不确定",
                "matched_event_count": len(rows),
                "event_names": dedup_keep_order([safe_text(x.get("canonical_event_name")) for x in rows]),
                "link_ids": [safe_text(x.get("link_id")) for x in rows],
            }
        )
    out.sort(key=lambda x: (x["timeline_id"] == "不确定", x["timeline_id"]))
    return out


def main() -> None:
    manual_map = load_manual_map()
    matched = json.loads(MATCHED_JSON.read_text(encoding="utf-8"))

    updated = 0
    for item in matched:
        link_id = safe_text(item.get("link_id"))
        manual = manual_map.get(link_id)
        if not manual:
            continue
        manual_id = manual["manual_timeline_id"]
        if manual_id and manual_id != "不确定":
            item["timeline_id"] = manual_id
            item["timeline_year"] = manual["manual_timeline_year"] or "不确定"
            item["timeline_season"] = manual["manual_timeline_season"] or "不确定"
            item["timeline_event_name"] = manual["manual_timeline_event_name"] or "不确定"
            item["timeline_ref"] = "｜".join(
                [
                    item["timeline_id"],
                    item["timeline_year"],
                    item["timeline_season"],
                    item["timeline_event_name"],
                ]
            )
            item["timeline_status"] = "manual_confirmed"
            item["timeline_manual_review"] = {
                "notes": manual["manual_notes"],
                "source": "uncertain_timeline_events_for_manual_review.csv",
            }
            updated += 1
        elif safe_text(manual["manual_notes"]):
            item["timeline_manual_review"] = {
                "notes": manual["manual_notes"],
                "source": "uncertain_timeline_events_for_manual_review.csv",
            }

    MATCHED_JSON.write_text(json.dumps(matched, ensure_ascii=False, indent=2), encoding="utf-8")
    INDEX_JSON.write_text(json.dumps(build_timeline_index(matched), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"manual timeline updates applied: {updated}")


if __name__ == "__main__":
    main()
