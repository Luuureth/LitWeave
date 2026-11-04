from __future__ import annotations

import argparse
from pathlib import Path

from kb_scene_mapping_pipeline import KBMappingConfig, LLMReviewConfig, run_kb_scene_mapping_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(
        description="四层结构：原子事件 -> 场景事件 -> 知识库规范事件 -> 跨模态场景链接"
    )
    parser.add_argument("--unified-events", type=str, default="unified_events/unified_events.csv")
    parser.add_argument("--kb-events", type=str, default="知识库/事件知识库/事件知识库.csv")
    parser.add_argument("--output-dir", type=str, default="跨模态事件对齐与事件时间线构建/kb_outputs")

    parser.add_argument("--top-k-kb", type=int, default=5)
    parser.add_argument("--min-kb-score", type=float, default=0.20)
    parser.add_argument("--no-prefer-anchor-events", action="store_true")
    parser.add_argument("--alpha-name", type=float, default=0.42)
    parser.add_argument("--beta-detail", type=float, default=0.23)
    parser.add_argument("--gamma-char", type=float, default=0.23)
    parser.add_argument("--delta-loc", type=float, default=0.12)

    parser.add_argument("--scene-max-gap", type=int, default=2)
    parser.add_argument("--scene-min-char-jaccard", type=float, default=0.15)
    parser.add_argument("--scene-min-loc-jaccard", type=float, default=0.10)
    parser.add_argument("--scene-merge-semantic-threshold", type=float, default=0.42)

    parser.add_argument("--top-k-scene-kb", type=int, default=5)
    parser.add_argument("--min-scene-kb-score", type=float, default=0.24)
    parser.add_argument("--top-k-links-per-kb", type=int, default=8)
    parser.add_argument("--min-cross-modal-score", type=float, default=0.28)

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

    cfg = KBMappingConfig(
        top_k_kb=args.top_k_kb,
        min_kb_score=args.min_kb_score,
        prefer_anchor_events=not args.no_prefer_anchor_events,
        alpha_name=args.alpha_name,
        beta_detail=args.beta_detail,
        gamma_char=args.gamma_char,
        delta_loc=args.delta_loc,
        scene_max_gap=args.scene_max_gap,
        scene_min_char_jaccard=args.scene_min_char_jaccard,
        scene_min_loc_jaccard=args.scene_min_loc_jaccard,
        scene_merge_semantic_threshold=args.scene_merge_semantic_threshold,
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

    print("[RUN] 开始执行四层结构场景映射流水线", flush=True)
    print(f"[RUN] unified_events={args.unified_events}", flush=True)
    print(f"[RUN] kb_events={args.kb_events}", flush=True)
    print(f"[RUN] output_dir={args.output_dir}", flush=True)
    print(f"[RUN] LLM review={'开启' if args.enable_llm_review else '关闭'} | model={args.llm_model}", flush=True)

    outputs = run_kb_scene_mapping_pipeline(
        unified_events_csv=Path(args.unified_events),
        kb_events_csv=Path(args.kb_events),
        output_dir=Path(args.output_dir),
        config=cfg,
        llm_review_cfg=llm_cfg,
    )

    print("[RUN] 完成。输出文件：", flush=True)
    print(f"- kb_event_nodes.json: {outputs.kb_event_nodes_json}", flush=True)
    print(f"- atomic_events_with_kb.csv: {outputs.atomic_events_with_kb_csv}", flush=True)
    print(f"- atomic_events_with_kb.json: {outputs.atomic_events_with_kb_json}", flush=True)
    print(f"- scene_events.json: {outputs.scene_events_json}", flush=True)
    print(f"- scene_events_with_kb.json: {outputs.scene_events_with_kb_json}", flush=True)
    print(f"- cross_modal_scene_links.json: {outputs.cross_modal_scene_links_json}", flush=True)
    print(f"- llm_review_audit.json: {outputs.llm_review_audit_json}", flush=True)
    print(f"- kb_scene_mapping_run_config.json: {outputs.run_config_json}", flush=True)


if __name__ == "__main__":
    main()
