from __future__ import annotations

import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
PROJECT_ROOT = BASE.parent.parent
MATCHED_JSON = BASE / "matched_events_with_timeline.json"
INDEX_JSON = BASE / "timeline_event_index.json"
TIMELINE_CSV = PROJECT_ROOT / "知识库" / "红楼梦时间线.csv"


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


def load_canonical_timeline_map() -> dict[tuple[str, str, str], str]:
    lines = TIMELINE_CSV.read_text(encoding="utf-8-sig").splitlines()
    mapping: dict[tuple[str, str, str], str] = {}
    idx = 1
    for raw in lines[1:]:
        if not raw.strip():
            continue
        parts = raw.split(",")
        year = safe_text(parts[0]) if len(parts) > 0 else ""
        season = safe_text(parts[1]) if len(parts) > 1 else ""
        event_name = safe_text(parts[2]) if len(parts) > 2 else ""
        if not event_name:
            continue
        key = (year, season, event_name)
        if key not in mapping:
            mapping[key] = f"TL{idx:03d}"
            idx += 1
    return mapping


def build_index(items: list[dict]) -> list[dict]:
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
    canonical_map = load_canonical_timeline_map()
    items = json.loads(MATCHED_JSON.read_text(encoding="utf-8"))
    changed = 0

    for item in items:
        year = safe_text(item.get("timeline_year"))
        season = safe_text(item.get("timeline_season"))
        event_name = safe_text(item.get("timeline_event_name"))
        if not year or not season or not event_name or year == "不确定" or event_name == "不确定":
            continue
        key = (year, season, event_name)
        canonical_id = canonical_map.get(key)
        if not canonical_id:
            continue
        if safe_text(item.get("timeline_id")) != canonical_id:
            item["timeline_id"] = canonical_id
            item["timeline_ref"] = "｜".join([canonical_id, year, season, event_name])
            changed += 1
        for cand in item.get("timeline_rule_candidates", []) or []:
            cyear = safe_text(cand.get("timeline_year"))
            cseason = safe_text(cand.get("timeline_season"))
            cevent = safe_text(cand.get("timeline_event_name"))
            ckey = (cyear, cseason, cevent)
            if ckey in canonical_map and safe_text(cand.get("timeline_id")) != canonical_map[ckey]:
                cand["timeline_id"] = canonical_map[ckey]
                cand["timeline_ref"] = "｜".join([canonical_map[ckey], cyear, cseason, cevent])

    MATCHED_JSON.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    INDEX_JSON.write_text(json.dumps(build_index(items), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"normalized timeline ids: {changed}")


if __name__ == "__main__":
    main()
