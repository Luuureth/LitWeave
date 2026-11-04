"""统一事件 JSON / CSV 导出。"""
import json
from pathlib import Path

import pandas as pd


def to_dataframe(unified_events: list[dict]) -> pd.DataFrame:
    rows = []
    for ev in unified_events:
        rows.append(
            {
                "ueid": ev.get("ueid"),
                "modality": ev.get("modality"),
                "source_id": ev.get("source_id"),
                "source_title": ev.get("source_title"),
                "event_id": ev.get("event_id"),
                "narrative_order": ev.get("narrative_order"),
                "action": ev.get("action"),
                "characters": "、".join(ev.get("characters") or []),
                "location": ev.get("location"),
                "time_hint": ev.get("time_hint"),
                "explicit_time": ev.get("explicit_time"),
                "relation_to_previous": ev.get("relation_to_previous"),
                "event_summary": ev.get("event_summary"),
                "source_text": ev.get("source_text"),
                "normalized_text": ev.get("normalized_text"),
                "semantic_core": ev.get("semantic_core"),
                "keywords": "、".join(ev.get("keywords") or []),
                "source_path": ev.get("source_path"),
            }
        )

    return pd.DataFrame(rows)


def export_results(unified_events: list[dict], output_json: Path, output_csv: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)

    with output_json.open("w", encoding="utf-8") as f:
        json.dump(unified_events, f, ensure_ascii=False, indent=2)

    df = to_dataframe(unified_events)
    df.to_csv(output_csv, index=False, encoding="utf-8-sig")
