from __future__ import annotations

import argparse
import os
from pathlib import Path

from feature2_pipeline import (
    AlignWeights,
    AlignmentConfig,
    AlignmentLLMRerankConfig,
    ClusterConfig,
    FragmentFilterConfig,
    GroundingConfig,
    run_feature2_pipeline,
)


def main() -> None:
    print("[RUN] 开始执行功能2流水线", flush=True)
    print(f"[RUN] 当前工作目录: {os.getcwd()}", flush=True)
    parser = argparse.ArgumentParser(description="功能2：跨模态事件严格一对一配对（先事件，后时间）")
    parser.add_argument("--unified-events", type=str, default="unified_events/unified_events.csv")
    parser.add_argument("--timeline", type=str, default="知识库/红楼梦时间线.csv")
    parser.add_argument("--output-dir", type=str, default="跨模态事件对齐与事件时间线构建/outputs")

    # 阶段A grounding
    parser.add_argument("--top-k-timeline", type=int, default=8)
    parser.add_argument("--accept-top1", type=float, default=0.18)
    parser.add_argument("--unknown-low", type=float, default=0.08)
    parser.add_argument("--llm-closed-set-output", type=str, default="")

    # 事件候选召回与配对
    parser.add_argument("--time-window", type=int, default=3)
    parser.add_argument("--top-k-per-source", type=int, default=5)
    parser.add_argument("--aligned-th", type=float, default=0.62)
    parser.add_argument("--related-th", type=float, default=0.45)
    parser.add_argument("--no-one-to-one", action="store_true")
    parser.add_argument("--keep-per-target", type=int, default=1)
    parser.add_argument("--require-anchor-for-alignment", action="store_true")

    # 打分权重：当前默认弱化时间因素，专注事件本体
    parser.add_argument("--alpha-sem", type=float, default=0.52)
    parser.add_argument("--beta-char", type=float, default=0.28)
    parser.add_argument("--gamma-loc", type=float, default=0.20)
    parser.add_argument("--delta-time", type=float, default=0.0)

    # LLM 精排
    parser.add_argument("--enable-alignment-llm-rerank", action="store_true")
    parser.add_argument("--llm-provider", type=str, default="dashscope")
    parser.add_argument("--llm-model", type=str, default="qwen3.6-plus")
    parser.add_argument("--llm-api-key-env", type=str, default="DASHSCOPE_API_KEY")
    parser.add_argument("--llm-api-key", type=str, default="")
    parser.add_argument("--llm-rerank-max-candidates", type=int, default=5)
    parser.add_argument("--llm-rerank-min-score", type=float, default=0.25)
    parser.add_argument("--llm-rerank-max-score", type=float, default=0.95)
    parser.add_argument("--llm-rerank-top-gap", type=float, default=0.25)
    parser.add_argument("--llm-rerank-force-first-n", type=int, default=0)
    parser.add_argument("--llm-rerank-max-items", type=int, default=400)
    parser.add_argument("--llm-rerank-timeout", type=int, default=120)
    parser.add_argument("--llm-rerank-accept-conf", type=float, default=0.70)
    parser.add_argument("--llm-min-pair-confidence", type=float, default=0.70)

    # 碎片过滤
    parser.add_argument("--disable-fragment-filter", action="store_true")
    parser.add_argument("--fragment-min-action-len", type=int, default=2)
    parser.add_argument("--fragment-min-summary-len", type=int, default=8)
    parser.add_argument("--fragment-require-char-or-loc", action="store_true")

    # 保留兼容输出
    parser.add_argument("--cluster-min-score", type=float, default=0.55)

    args = parser.parse_args()

    grounding_cfg = GroundingConfig(
        top_k_candidates=args.top_k_timeline,
        accept_top1_if_score_ge=args.accept_top1,
        unknown_if_top1_le=args.unknown_low,
    )
    align_cfg = AlignmentConfig(
        time_window=args.time_window,
        top_k_per_source=args.top_k_per_source,
        aligned_threshold=args.aligned_th,
        related_threshold=args.related_th,
        enforce_one_to_one=not args.no_one_to_one,
        one_to_one_keep_per_target=args.keep_per_target,
        require_anchor_for_alignment=args.require_anchor_for_alignment,
    )
    weights = AlignWeights(
        alpha_sem=args.alpha_sem,
        beta_char=args.beta_char,
        gamma_loc=args.gamma_loc,
        delta_time=args.delta_time,
    )
    rerank_cfg = AlignmentLLMRerankConfig(
        enabled=args.enable_alignment_llm_rerank,
        provider=args.llm_provider,
        model_name=args.llm_model,
        api_key_env=args.llm_api_key_env,
        api_key_literal=args.llm_api_key,
        max_candidates_per_source=args.llm_rerank_max_candidates,
        min_score_for_review=args.llm_rerank_min_score,
        max_score_for_review=args.llm_rerank_max_score,
        top_gap_for_review=args.llm_rerank_top_gap,
        force_first_n=args.llm_rerank_force_first_n,
        max_items=args.llm_rerank_max_items,
        timeout=args.llm_rerank_timeout,
        accept_if_aligned_conf_ge=args.llm_rerank_accept_conf,
        min_pair_confidence=args.llm_min_pair_confidence,
    )
    fragment_cfg = FragmentFilterConfig(
        enabled=not args.disable_fragment_filter,
        min_action_len=args.fragment_min_action_len,
        min_summary_len=args.fragment_min_summary_len,
        require_char_or_loc=args.fragment_require_char_or_loc,
    )
    cluster_cfg = ClusterConfig(use_edge_type="aligned", min_edge_score=args.cluster_min_score)

    llm_path = Path(args.llm_closed_set_output) if args.llm_closed_set_output else None

    print(f"[RUN] unified_events={args.unified_events}", flush=True)
    print(f"[RUN] timeline={args.timeline}", flush=True)
    print(f"[RUN] output_dir={args.output_dir}", flush=True)
    print(
        f"[RUN] LLM精排={'开启' if args.enable_alignment_llm_rerank else '关闭'} | model={args.llm_model} | max_items={args.llm_rerank_max_items} | timeout={args.llm_rerank_timeout}s",
        flush=True,
    )

    outputs = run_feature2_pipeline(
        unified_events_csv=Path(args.unified_events),
        timeline_csv=Path(args.timeline),
        output_dir=Path(args.output_dir),
        grounding_cfg=grounding_cfg,
        align_cfg=align_cfg,
        weights=weights,
        cluster_cfg=cluster_cfg,
        llm_closed_set_output_json=llm_path,
        alignment_llm_rerank_cfg=rerank_cfg,
        fragment_filter_cfg=fragment_cfg,
    )

    print("功能2流水线完成。核心产物：")
    print(f"- paired_alignments.json: {outputs.paired_alignments_json}")
    print(f"- cross_modal_event_alignment.csv: {outputs.cross_modal_event_alignment_csv}")
    print(f"- alignment_llm_rerank_audit.json: {outputs.alignment_llm_rerank_audit_json}")
    print(f"- unified_events_grounded.csv: {outputs.unified_events_grounded_csv}")
    print(f"- run_config.json: {outputs.run_config_json}")


if __name__ == "__main__":
    main()
