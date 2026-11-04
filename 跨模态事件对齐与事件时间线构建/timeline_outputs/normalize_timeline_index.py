from __future__ import annotations

import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
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


def build_canonical_key(item: dict) -> str:
    timeline_id = safe_text(item.get("timeline_id"))
    if timeline_id in {"", "不确定"}:
        return "不确定"
    year = safe_text(item.get("timeline_year"))
    season = safe_text(item.get("timeline_season"))
    event_name = safe_text(item.get("timeline_event_name"))
    return "｜".join([year, season, event_name])


def build_canonical_id(index: int) -> str:
    return f"CTL{index:03d}"


def main() -> None:
    matched = json.loads(MATCHED_JSON.read_text(encoding="utf-8"))

    key_order: list[str] = []
    for item in matched:
        key = build_canonical_key(item)
        if key not in key_order:
            key_order.append(key)

    key_to_canonical_id: dict[str, str] = {}
    canonical_counter = 1
    for key in key_order:
        if key == "不确定":
            key_to_canonical_id[key] = "不确定"
        else:
            key_to_canonical_id[key] = build_canonical_id(canonical_counter)
            canonical_counter += 1

    groups: dict[str, list[dict]] = {}
    for item in matched:
        key = build_canonical_key(item)
        canonical_id = key_to_canonical_id[key]
        item["canonical_timeline_id"] = canonical_id
        item["canonical_timeline_key"] = key
        groups.setdefault(canonical_id, []).append(item)

    MATCHED_JSON.write_text(json.dumps(matched, ensure_ascii=False, indent=2), encoding="utf-8")

    index_items: list[dict] = []
    for canonical_id, rows in groups.items():
        first = rows[0]
        timeline_id_variants = dedup_keep_order([safe_text(x.get("timeline_id")) for x in rows if safe_text(x.get("timeline_id"))])
        timeline_statuses = dedup_keep_order([safe_text(x.get("timeline_status")) for x in rows if safe_text(x.get("timeline_status"))])
        index_items.append(
            {
                "canonical_timeline_id": canonical_id,
                "timeline_year": safe_text(first.get("timeline_year")) or "不确定",
                "timeline_season": safe_text(first.get("timeline_season")) or "不确定",
                "timeline_event_name": safe_text(first.get("timeline_event_name")) or "不确定",
                "timeline_ref": safe_text(first.get("timeline_ref")) or "不确定",
                "source_timeline_ids": timeline_id_variants,
                "timeline_statuses": timeline_statuses,
                "matched_event_count": len(rows),
                "event_names": dedup_keep_order([safe_text(x.get("canonical_event_name")) for x in rows]),
                "link_ids": [safe_text(x.get("link_id")) for x in rows],
            }
        )

    index_items.sort(key=lambda x: (x["canonical_timeline_id"] == "不确定", x["canonical_timeline_id"]))
    INDEX_JSON.write_text(json.dumps(index_items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"canonical timeline groups: {len(index_items)}")


if __name__ == "__main__":
    main()
