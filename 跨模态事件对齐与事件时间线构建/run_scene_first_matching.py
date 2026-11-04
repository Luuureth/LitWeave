from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import List

import pandas as pd

from kb_scene_mapping_pipeline import (
    KBMappingConfig,
    LLMReviewConfig,
    build_cross_modal_scene_links,
    build_kb_event_nodes_json,
    export_scene_events_json,
    load_kb_events,
    review_cross_modal_links_with_llm,
    review_scene_kb_mappings_with_llm,
    map_scene_events_to_kb,
)


def _safe_text(x) -> str:
    if x is None:
        return ""
    s = str(x).strip()
    if s.lower() in {"nan", "none", "null", "na"}:
        return ""
    return s


def _split_items(value) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    s = _safe_text(value)
    if not s:
        return []
    for sep in ["、", "，", ",", ";", "；", "|"]:
        s = s.replace(sep, "|")
    return [x.strip() for x in s.split("|") if x.strip()]


def prepare_scene_df(scene_json_path: Path) -> pd.DataFrame:
    data = json.loads(scene_json_path.read_text(encoding="utf-8"))
    df = pd.DataFrame(data)
    if df.empty:
        raise ValueError(f"scene 文件为空: {scene_json_path}")

    if "scene_characters" not in df.columns:
        df["scene_characters"] = [[] for _ in range(len(df))]
    if "scene_locations" not in df.columns:
        df["scene_locations"] = [[] for _ in range(len(df))]
    if "member_ueids" not in df.columns:
        df["member_ueids"] = [[] for _ in range(len(df))]
    if "member_count" not in df.columns:
        df["member_count"] = df["member_ueids"].apply(lambda x: len(x) if isinstance(x, list) else 0)
    if "timeline_id" not in df.columns:
        df["timeline_id"] = "unknown"
    if "start_order" not in df.columns:
        df["start_order"] = list(range(1, len(df) + 1))
    if "end_order" not in df.columns:
        df["end_order"] = df["start_order"]

    df["scene_characters"] = df["scene_characters"].apply(_split_items)
    df["scene_locations"] = df["scene_locations"].apply(_split_items)
    df["member_ueids"] = df["member_ueids"].apply(lambda x: x if isinstance(x, list) else _split_items(x))
    df["member_count"] = df["member_count"].fillna(0).astype(int)
    df["start_order"] = df["start_order"].fillna(0).astype(int)
    df["end_order"] = df["end_order"].fillna(df["start_order"]).astype(int)

    if "scene_repr_text" not in df.columns:
        df["scene_repr_text"] = df.apply(
            lambda row: "；".join(
                x for x in [
                    f"场景名:{_safe_text(row.get('scene_name'))}",
                    f"摘要:{_safe_text(row.get('scene_summary'))}",
                    f"人物:{'、'.join(_split_items(row.get('scene_characters')))}",
                    f"地点:{'、'.join(_split_items(row.get('scene_locations')))}",
                    f"来源标题:{_safe_text(row.get('source_title'))}",
                ] if x and not x.endswith(":")
            )[:1200],
            axis=1,
        )

    for col in [
        "kb_event_id",
        "kb_event_name",
        "kb_top1_score",
        "kb_topk_candidates",
        "semantic_backend",
        "chapter_id",
        "chapter_title",
        "episode_id",
        "episode_title",
    ]:
        if col not in df.columns:
            df[col] = "" if col != "kb_top1_score" else 0.0

    return df


def main() -> None:
    parser = argparse.ArgumentParser(description="直接从 scene_events.json 开始做 scene->kb 和跨模态匹配")
    parser.add_argument("--scene-events", type=str, default="跨模态事件对齐与事件时间线构建/kb_outputs/scene_events.json")
    parser.add_argument("--scene-events-with-kb", type=str, default="跨模态事件对齐与事件时间线构建/kb_outputs/scene_events_with_kb.json")
    parser.add_argument("--kb-events", type=str, default="知识库/事件知识库/事件知识库.csv")
    parser.add_argument("--output-dir", type=str, default="跨模态事件对齐与事件时间线构建/kb_outputs_scene_first")

    parser.add_argument("--top-k-scene-kb", type=int, default=5)
    parser.add_argument("--min-scene-kb-score", type=float, default=0.24)
    parser.add_argument("--alpha-name", type=float, default=0.42)
    parser.add_argument("--beta-detail", type=float, default=0.23)
    parser.add_argument("--gamma-char", type=float, default=0.23)
    parser.add_argument("--delta-loc", type=float, default=0.12)
    parser.add_argument("--top-k-links-per-kb", type=int, default=8)
    parser.add_argument("--min-cross-modal-score", type=float, default=0.28)
    parser.add_argument("--no-prefer-anchor-events", action="store_true")

    parser.add_argument("--enable-llm-review", action="store_true")
    parser.add_argument("--llm-model", type=str, default="qwen3.6-plus")
    parser.add_argument("--llm-timeout", type=int, default=120)
    parser.add_argument("--llm-max-retries", type=int, default=3)
    parser.add_argument("--llm-max-scene-items", type=int, default=150)
    parser.add_argument("--llm-max-link-items", type=int, default=120)
    parser.add_argument("--llm-scene-score-low", type=float, default=0.24)
    parser.add_argument("--llm-scene-score-high", type=float, default=0.72)
    parser.add_argument("--llm-scene-gap-threshold", type=float, default=0.12)
    parser.add_argument("--llm-link-score-low", type=float, default=0.28)
    parser.add_argument("--llm-link-score-high", type=float, default=0.78)
    parser.add_argument("--llm-scene-batch-size", type=int, default=8)
    parser.add_argument("--llm-link-batch-size", type=int, default=8)
    parser.add_argument("--llm-scene-pause-between-batches-sec", type=float, default=0.0)
    parser.add_argument("--llm-link-pause-between-batches-sec", type=float, default=0.0)
    parser.add_argument("--llm-accept-if-aligned-conf-ge", type=float, default=0.70)

    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cfg = KBMappingConfig(
        top_k_kb=5,
        min_kb_score=0.20,
        prefer_anchor_events=not args.no_prefer_anchor_events,
        alpha_name=args.alpha_name,
        beta_detail=args.beta_detail,
        gamma_char=args.gamma_char,
        delta_loc=args.delta_loc,
        scene_max_gap=2,
        scene_min_char_jaccard=0.15,
        scene_min_loc_jaccard=0.10,
        scene_merge_semantic_threshold=0.42,
        top_k_scene_kb=args.top_k_scene_kb,
        min_scene_kb_score=args.min_scene_kb_score,
        top_k_links_per_kb=args.top_k_links_per_kb,
        min_cross_modal_score=args.min_cross_modal_score,
    )

    llm_cfg = LLMReviewConfig(
        enabled=args.enable_llm_review,
        model_name=args.llm_model,
        timeout=args.llm_timeout,
        max_retries=args.llm_max_retries,
        max_scene_items=args.llm_max_scene_items,
        max_link_items=args.llm_max_link_items,
        scene_score_low=args.llm_scene_score_low,
        scene_score_high=args.llm_scene_score_high,
        scene_gap_threshold=args.llm_scene_gap_threshold,
        link_score_low=args.llm_link_score_low,
        link_score_high=args.llm_link_score_high,
        scene_batch_size=args.llm_scene_batch_size,
        link_batch_size=args.llm_link_batch_size,
        scene_pause_between_batches_sec=args.llm_scene_pause_between_batches_sec,
        link_pause_between_batches_sec=args.llm_link_pause_between_batches_sec,
        accept_if_aligned_conf_ge=args.llm_accept_if_aligned_conf_ge,
    )

    scene_input_path = Path(args.scene_events)
    scene_df = prepare_scene_df(scene_input_path)
    kb_df = load_kb_events(Path(args.kb_events))

    print("[SCENE-FIRST] 阶段 1/4：scene_event 匹配知识库", flush=True)
    scene_with_kb = map_scene_events_to_kb(scene_df, kb_df, cfg)

    print("[SCENE-FIRST] 阶段 2/4：可选 LLM 复核 scene->kb", flush=True)
    scene_with_kb, scene_llm_audits = review_scene_kb_mappings_with_llm(scene_with_kb, llm_cfg)

    scene_with_kb_json_path = Path(args.scene_events_with_kb)
    export_scene_events_json(scene_with_kb, scene_with_kb_json_path)
    export_scene_events_json(scene_with_kb, output_dir / "scene_events_with_kb.json")

    print("[SCENE-FIRST] 阶段 3/4：生成 kb_event 节点与跨模态 scene link", flush=True)
    build_kb_event_nodes_json(kb_df, scene_with_kb, output_dir / "kb_event_nodes.json")
    links = build_cross_modal_scene_links(
        scene_with_kb=scene_with_kb,
        atomic_with_kb=pd.DataFrame(columns=["ueid"]),
        out_json=output_dir / "cross_modal_scene_links.json",
        cfg=cfg,
    )

    print("[SCENE-FIRST] 阶段 4/4：可选 LLM 复核 scene link", flush=True)
    links, link_llm_audits = review_cross_modal_links_with_llm(links, llm_cfg)
    (output_dir / "cross_modal_scene_links.json").write_text(
        json.dumps(links, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "llm_review_audit.json").write_text(
        json.dumps(scene_llm_audits + link_llm_audits, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "scene_first_run_config.json").write_text(
        json.dumps({"kb_mapping_config": asdict(cfg), "llm_review_config": asdict(llm_cfg)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("[SCENE-FIRST] 完成。输出文件：", flush=True)
    print(f"- {scene_with_kb_json_path}", flush=True)
    print(f"- {output_dir / 'scene_events_with_kb.json'}", flush=True)
    print(f"- {output_dir / 'kb_event_nodes.json'}", flush=True)
    print(f"- {output_dir / 'cross_modal_scene_links.json'}", flush=True)
    print(f"- {output_dir / 'llm_review_audit.json'}", flush=True)
    print(f"- {output_dir / 'scene_first_run_config.json'}", flush=True)


if __name__ == "__main__":
    main()
