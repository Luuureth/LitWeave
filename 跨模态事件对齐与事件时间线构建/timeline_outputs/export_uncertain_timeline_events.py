from __future__ import annotations

import csv
import json
from pathlib import Path

SRC = Path(__file__).resolve().parent / "matched_events_with_timeline.json"
OUT_JSON = SRC.parent / "uncertain_timeline_events_for_manual_review.json"
OUT_CSV = SRC.parent / "uncertain_timeline_events_for_manual_review.csv"


def fmt_candidate(candidate: dict | None) -> str:
    if not candidate:
        return ""
    return "｜".join(
        [
            str(candidate.get("timeline_id", "") or ""),
            str(candidate.get("timeline_year", "") or ""),
            str(candidate.get("timeline_season", "") or ""),
            str(candidate.get("timeline_event_name", "") or ""),
        ]
    )


def main() -> None:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    uncertain = [
        x
        for x in data
        if str(x.get("timeline_id", "")).strip() in {"", "不确定"}
        or str(x.get("timeline_status", "")).strip() in {"uncertain", "llm_unmatched"}
    ]

    OUT_JSON.write_text(json.dumps(uncertain, ensure_ascii=False, indent=2), encoding="utf-8")

    fields = [
        "link_id",
        "kb_event_id",
        "event_name",
        "canonical_event_name",
        "timeline_status",
        "text_scene_id",
        "text_scene_name",
        "text_chapter_title",
        "video_scene_id",
        "video_scene_name",
        "video_episode_title",
        "shared_characters",
        "shared_locations",
        "suggested_candidate_1",
        "suggested_candidate_2",
        "suggested_candidate_3",
        "manual_timeline_id",
        "manual_timeline_year",
        "manual_timeline_season",
        "manual_timeline_event_name",
        "manual_notes",
    ]

    rows = []
    for item in uncertain:
        candidates = item.get("timeline_rule_candidates", [])[:3]
        rows.append(
            {
                "link_id": item.get("link_id", ""),
                "kb_event_id": item.get("kb_event_id", ""),
                "event_name": item.get("event_name", ""),
                "canonical_event_name": item.get("canonical_event_name", ""),
                "timeline_status": item.get("timeline_status", ""),
                "text_scene_id": item.get("text", {}).get("scene_id", ""),
                "text_scene_name": item.get("text", {}).get("scene_name", ""),
                "text_chapter_title": item.get("text", {}).get("chapter_title", ""),
                "video_scene_id": item.get("video", {}).get("scene_id", ""),
                "video_scene_name": item.get("video", {}).get("scene_name", ""),
                "video_episode_title": item.get("video", {}).get("episode_title", ""),
                "shared_characters": "、".join(item.get("shared", {}).get("characters", []) or []),
                "shared_locations": "、".join(item.get("shared", {}).get("locations", []) or []),
                "suggested_candidate_1": fmt_candidate(candidates[0] if len(candidates) > 0 else None),
                "suggested_candidate_2": fmt_candidate(candidates[1] if len(candidates) > 1 else None),
                "suggested_candidate_3": fmt_candidate(candidates[2] if len(candidates) > 2 else None),
                "manual_timeline_id": "",
                "manual_timeline_year": "",
                "manual_timeline_season": "",
                "manual_timeline_event_name": "",
                "manual_notes": "",
            }
        )

    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    print(f"uncertain_count={len(uncertain)}")
    print(OUT_JSON)
    print(OUT_CSV)


if __name__ == "__main__":
    main()
