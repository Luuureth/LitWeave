from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parent
MATCHED_JSON = BASE / "matched_events_with_timeline.json"
INDEX_JSON = BASE / "timeline_event_index.json"
AUDIT_JSON = BASE / "timeline_data_quality_report.json"
PERSON_INDEX_JSON = BASE / "person_event_timeline_index.json"
LOCATION_INDEX_JSON = BASE / "location_event_timeline_index.json"

YEAR_ORDER = {
    "红楼元年": 1,
    "红楼一年": 1,
    "红楼二年": 2,
    "红楼三年": 3,
    "红楼四年": 4,
    "红楼五年": 5,
    "红楼六年": 6,
    "红楼七年": 7,
    "红楼八年": 8,
    "红楼九年": 9,
    "红楼十年": 10,
    "红楼十一年": 11,
    "红楼十二年": 12,
    "红楼十三年": 13,
    "红楼十四年": 14,
    "红楼十五年": 15,
    "红楼十六年": 16,
    "红楼十七年": 17,
    "红楼十八年": 18,
    "红楼十九年": 19,
}
SEASON_ORDER = {
    "全年": 0,
    "春初": 1,
    "春季": 2,
    "二月十二": 2.12,
    "二月廿二": 2.22,
    "三月": 3,
    "三月十五": 3.15,
    "三月中浣": 3.2,
    "四月二十六": 4.26,
    "五月初一": 5.01,
    "五月初二": 5.02,
    "五月初四": 5.04,
    "五月中": 5.2,
    "夏季": 6,
    "八月": 8,
    "八月初三": 8.03,
    "八月十六": 8.16,
    "秋季": 9,
    "秋末冬初": 9.8,
    "九月": 9.1,
    "九月初二": 9.02,
    "冬季": 12,
    "冬末": 12.8,
    "秋冬": 10,
    "腊月": 12.9,
    "正月十五": 1.15,
    "正月十六后": 1.16,
    "正月内": 1.2,
}


def safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def dedup(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for item in items:
        item = safe_text(item)
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def timeline_sort_key(item: dict) -> tuple:
    year = safe_text(item.get("timeline_year"))
    season = safe_text(item.get("timeline_season"))
    timeline_id = safe_text(item.get("timeline_id"))
    return (
        year in {"", "不确定"},
        YEAR_ORDER.get(year, 999),
        SEASON_ORDER.get(season, 99),
        timeline_id,
    )


INFERRED_CHARACTERS_BY_LINK = {
    "SCL_00129": ["王熙凤", "贾瑞"],
    "SCL_00105": ["王熙凤", "贾珍", "贾蓉", "尤氏"],
    "SCL_00106": ["王熙凤", "贾珍", "贾蓉", "尤氏"],
    "SCL_00113": ["王熙凤", "贾珍", "贾蓉", "尤氏"],
}

INFERRED_CHARACTERS_BY_EVENT = {
    "王熙凤毒设相思局": ["王熙凤", "贾瑞"],
    "王熙凤协理宁国府": ["王熙凤", "贾珍", "贾蓉", "尤氏"],
}


def collect_characters(item: dict) -> list[str]:
    chars = list(item.get("shared", {}).get("characters", []) or [])
    link_id = safe_text(item.get("link_id"))
    canonical_event_name = safe_text(item.get("canonical_event_name"))
    chars.extend(INFERRED_CHARACTERS_BY_LINK.get(link_id, []))
    chars.extend(INFERRED_CHARACTERS_BY_EVENT.get(canonical_event_name, []))
    return dedup(chars)


INFERRED_LOCATION_BY_EVENT = {
    "贾雨村判案": ["应天府衙"],
    "王熙凤毒设相思局": ["荣国府"],
    "王熙凤协理宁国府": ["宁国府"],
    "林黛玉进贾府": ["荣国府", "贾母院"],
    "宝钗扑蝶": ["大观园", "滴翠亭"],
    "黛玉葬花": ["大观园", "花冢"],
    "金钏之死": ["荣国府", "王夫人房"],
    "晴雯撕扇": ["怡红院"],
    "宝玉挨打": ["荣国府"],
    "风雨夕闷制风雨词": ["潇湘馆"],
    "香菱学诗": ["大观园", "潇湘馆"],
    "勇晴雯病补孔雀裘": ["怡红院"],
    "听曲文宝玉悟禅机": ["荣国府"],
}


def collect_locations(item: dict) -> list[str]:
    locs = list(item.get("shared", {}).get("locations", []) or [])
    # 如果 shared.locations 为空，保守补充场景地点字段，避免地点时间线完全断裂。
    for side in ["text", "video"]:
        side_obj = item.get(side, {}) or {}
        for key in ["scene_locations", "locations", "location"]:
            value = side_obj.get(key)
            if isinstance(value, list):
                locs.extend(value)
            elif safe_text(value):
                locs.append(safe_text(value))

    canonical_event_name = safe_text(item.get("canonical_event_name"))
    locs.extend(INFERRED_LOCATION_BY_EVENT.get(canonical_event_name, []))
    return dedup(locs)


def compact_event(item: dict) -> dict:
    return {
        "link_id": safe_text(item.get("link_id")),
        "kb_event_id": safe_text(item.get("kb_event_id")),
        "event_name": safe_text(item.get("event_name")),
        "canonical_event_name": safe_text(item.get("canonical_event_name")),
        "alignment_score": item.get("alignment_score"),
        "timeline_id": safe_text(item.get("timeline_id")),
        "timeline_year": safe_text(item.get("timeline_year")),
        "timeline_season": safe_text(item.get("timeline_season")),
        "timeline_event_name": safe_text(item.get("timeline_event_name")),
        "timeline_status": safe_text(item.get("timeline_status")),
        "characters": collect_characters(item),
        "locations": collect_locations(item),
        "text_scene": {
            "scene_id": safe_text(item.get("text", {}).get("scene_id")),
            "scene_name": safe_text(item.get("text", {}).get("scene_name")),
            "chapter_title": safe_text(item.get("text", {}).get("chapter_title")),
            "summary": safe_text(item.get("text", {}).get("scene_summary")),
        },
        "video_scene": {
            "scene_id": safe_text(item.get("video", {}).get("scene_id")),
            "scene_name": safe_text(item.get("video", {}).get("scene_name")),
            "episode_title": safe_text(item.get("video", {}).get("episode_title")),
            "summary": safe_text(item.get("video", {}).get("scene_summary")),
        },
    }


def build_entity_index(items: list[dict], entity_type: str) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        entities = collect_characters(item) if entity_type == "person" else collect_locations(item)
        for entity in entities:
            grouped[entity].append(item)

    out = []
    for entity, rows in grouped.items():
        rows = sorted(rows, key=timeline_sort_key)
        events = [compact_event(x) for x in rows]
        out.append(
            {
                "entity": entity,
                "entity_type": entity_type,
                "event_count": len(events),
                "timeline_span": {
                    "start": {
                        "timeline_id": events[0]["timeline_id"],
                        "timeline_year": events[0]["timeline_year"],
                        "timeline_season": events[0]["timeline_season"],
                    },
                    "end": {
                        "timeline_id": events[-1]["timeline_id"],
                        "timeline_year": events[-1]["timeline_year"],
                        "timeline_season": events[-1]["timeline_season"],
                    },
                },
                "events": events,
            }
        )
    out.sort(key=lambda x: (-x["event_count"], x["entity"]))
    return out


def build_timeline_index(items: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        key = safe_text(item.get("timeline_id")) or "不确定"
        groups[key].append(item)
    out = []
    for timeline_id, rows in groups.items():
        first = rows[0]
        all_chars = dedup([c for item in rows for c in collect_characters(item)])
        all_locs = dedup([loc for item in rows for loc in collect_locations(item)])
        out.append(
            {
                "timeline_id": timeline_id,
                "timeline_year": safe_text(first.get("timeline_year")) or "不确定",
                "timeline_season": safe_text(first.get("timeline_season")) or "不确定",
                "timeline_event_name": safe_text(first.get("timeline_event_name")) or "不确定",
                "timeline_ref": safe_text(first.get("timeline_ref")) or "不确定",
                "matched_event_count": len(rows),
                "event_names": dedup([safe_text(x.get("canonical_event_name")) for x in rows]),
                "characters": all_chars,
                "locations": all_locs,
                "link_ids": [safe_text(x.get("link_id")) for x in rows],
            }
        )
    out.sort(key=timeline_sort_key)
    return out


def main() -> None:
    data = json.loads(MATCHED_JSON.read_text(encoding="utf-8"))

    # 统一重复时间线 ID：同一时间线内容只保留已有标准库中的较早 ID。
    canonical_by_content: dict[tuple[str, str, str], str] = {}
    changed_ids: dict[str, str] = {}
    for item in sorted(data, key=timeline_sort_key):
        content_key = (
            safe_text(item.get("timeline_year")),
            safe_text(item.get("timeline_season")),
            safe_text(item.get("timeline_event_name")),
        )
        timeline_id = safe_text(item.get("timeline_id"))
        if not timeline_id or timeline_id == "不确定":
            continue
        if content_key in canonical_by_content:
            canonical_id = canonical_by_content[content_key]
            if timeline_id != canonical_id:
                changed_ids[timeline_id] = canonical_id
                item["timeline_id"] = canonical_id
                item["timeline_ref"] = "｜".join(
                    [
                        canonical_id,
                        safe_text(item.get("timeline_year")),
                        safe_text(item.get("timeline_season")),
                        safe_text(item.get("timeline_event_name")),
                    ]
                )
        else:
            canonical_by_content[content_key] = timeline_id

    for item in data:
        # 为后续人物/地点功能补充顶层索引字段，不破坏原始 shared 结构。
        item["event_characters"] = collect_characters(item)
        item["event_locations"] = collect_locations(item)
        item["timeline_sort"] = {
            "year_order": YEAR_ORDER.get(safe_text(item.get("timeline_year")), 999),
            "season_order": SEASON_ORDER.get(safe_text(item.get("timeline_season")), 99),
        }

    timeline_index = build_timeline_index(data)
    person_index = build_entity_index(data, "person")
    location_index = build_entity_index(data, "location")

    status_counter = Counter(safe_text(x.get("timeline_status")) for x in data)
    determined = sum(1 for x in data if safe_text(x.get("timeline_id")) not in {"", "不确定"})
    uncertain = len(data) - determined
    missing_chars = sum(1 for x in data if not collect_characters(x))
    missing_locs = sum(1 for x in data if not collect_locations(x))
    audit = {
        "total_matched_events": len(data),
        "determined_timeline_events": determined,
        "uncertain_timeline_events": uncertain,
        "timeline_status_counts": dict(status_counter),
        "unique_timeline_nodes": len([x for x in timeline_index if x["timeline_id"] != "不确定"]),
        "unique_person_nodes": len(person_index),
        "unique_location_nodes": len(location_index),
        "events_without_characters": missing_chars,
        "events_without_locations": missing_locs,
        "canonical_timeline_id_merges": changed_ids,
        "outputs": {
            "matched_events_with_timeline": str(MATCHED_JSON),
            "timeline_event_index": str(INDEX_JSON),
            "person_event_timeline_index": str(PERSON_INDEX_JSON),
            "location_event_timeline_index": str(LOCATION_INDEX_JSON),
        },
    }

    MATCHED_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    INDEX_JSON.write_text(json.dumps(timeline_index, ensure_ascii=False, indent=2), encoding="utf-8")
    PERSON_INDEX_JSON.write_text(json.dumps(person_index, ensure_ascii=False, indent=2), encoding="utf-8")
    LOCATION_INDEX_JSON.write_text(json.dumps(location_index, ensure_ascii=False, indent=2), encoding="utf-8")
    AUDIT_JSON.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
