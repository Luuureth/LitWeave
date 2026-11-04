"""可复现的时间线权重敏感性实验。

本脚本只调用 run_timeline_grounding.py 中已有的候选生成与评分函数，
不调用 LLM，也不改写已有时间线输出。人工审校参照来自最终输出中
timeline_status == 'manual_confirmed' 的 14 条记录；候选池固定为当前
工程配置生成的 Top-5 候选集合。
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "跨模态事件对齐与事件时间线构建" / "run_timeline_grounding.py"
LINKS_PATH = ROOT / "跨模态事件对齐与事件时间线构建" / "kb_outputs_scene_first" / "cross_modal_scene_links.json"
TIMELINE_PATH = ROOT / "知识库" / "红楼梦时间线.csv"
MATCHED_PATH = ROOT / "跨模态事件对齐与事件时间线构建" / "timeline_outputs" / "matched_events_with_timeline.json"
CONFIG_PATH = ROOT / "跨模态事件对齐与事件时间线构建" / "timeline_outputs" / "timeline_run_config.json"
OUT_DIR = ROOT / "跨模态事件对齐与事件时间线构建" / "timeline_outputs" / "weight_experiment"

EPS = 1e-12


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_module():
    spec = importlib.util.spec_from_file_location("timeline_grounding_real_code", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载时间线代码：{MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def candidate_score(candidate: dict[str, Any], weights: tuple[float, float, float]) -> float:
    a, b, g = weights
    return (
        a * float(candidate["name_similarity"])
        + b * float(candidate["summary_similarity"])
        + g * float(candidate["kb_bonus"])
    )


def ordered_candidates(candidates: list[dict[str, Any]], weights: tuple[float, float, float]) -> list[dict[str, Any]]:
    # Python sort is stable. Existing baseline order is retained only when exact
    # weighted scores tie, so the tie policy is deterministic and reproducible.
    return sorted(candidates, key=lambda c: candidate_score(c, weights), reverse=True)


def rank_of_target(candidates: list[dict[str, Any]], target_id: str, weights: tuple[float, float, float]) -> int | None:
    ranked = ordered_candidates(candidates, weights)
    for rank, candidate in enumerate(ranked, start=1):
        if candidate["timeline_id"] == target_id:
            return rank
    return None


def metrics(records: list[dict[str, Any]], weights: tuple[float, float, float]) -> dict[str, Any]:
    ranks = [rank_of_target(x["candidates"], x["gold_id"], weights) for x in records]
    if not ranks:
        return {"n": 0, "top1": 0.0, "mrr": 0.0, "top3": 0.0, "top1_count": 0, "top3_count": 0}
    return {
        "n": len(ranks),
        "top1": sum(r == 1 for r in ranks) / len(ranks),
        "mrr": sum(1.0 / r for r in ranks) / len(ranks),
        "top3": sum(r <= 3 for r in ranks) / len(ranks),
        "top1_count": sum(r == 1 for r in ranks),
        "top3_count": sum(r <= 3 for r in ranks),
    }


def grid(step: float = 0.05) -> Iterable[tuple[float, float, float]]:
    scale = round(1 / step)
    for ia in range(scale + 1):
        for ib in range(scale - ia + 1):
            ig = scale - ia - ib
            yield (ia / scale, ib / scale, ig / scale)


def choose_best(rows: list[dict[str, Any]], predicate=lambda _: True) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    pool = [r for r in rows if predicate(r)]
    if not pool:
        raise ValueError("候选配置集合为空")
    best_top1 = max(r["top1"] for r in pool)
    best_mrr = max(r["mrr"] for r in pool if r["top1"] == best_top1)
    tied = [r for r in pool if abs(r["top1"] - best_top1) < EPS and abs(r["mrr"] - best_mrr) < EPS]
    baseline = (0.45, 0.30, 0.25)
    # Among metric ties, prefer the closest configuration to the historical setting.
    tied.sort(key=lambda r: (sum(abs(x - y) for x, y in zip((r["alpha"], r["beta"], r["gamma"]), baseline)), -max(r["alpha"], r["beta"], r["gamma"]), r["alpha"], r["beta"], r["gamma"]))
    return tied[0], tied


def choose_best_mrr(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    best_mrr = max(r["mrr"] for r in rows)
    best_top1 = max(r["top1"] for r in rows if abs(r["mrr"] - best_mrr) < EPS)
    tied = [r for r in rows if abs(r["mrr"] - best_mrr) < EPS and abs(r["top1"] - best_top1) < EPS]
    baseline = (0.45, 0.30, 0.25)
    tied.sort(key=lambda r: (sum(abs(x - y) for x, y in zip((r["alpha"], r["beta"], r["gamma"]), baseline)), r["alpha"], r["beta"], r["gamma"]))
    return tied[0], tied


def find_case(records: list[dict[str, Any]], rows: list[dict[str, Any]], baseline: tuple[float, float, float], component: int, wanted: str) -> dict[str, Any] | None:
    """Find an actual rank-change case.

    wanted == 'improve': baseline non-Top1 -> Top1 after increasing component.
    wanted == 'degrade': baseline Top1 -> non-Top1 after increasing component.
    """
    candidates: list[dict[str, Any]] = []
    for record in records:
        base_rank = rank_of_target(record["candidates"], record["gold_id"], baseline)
        for row in rows:
            w = (row["alpha"], row["beta"], row["gamma"])
            new_rank = rank_of_target(record["candidates"], record["gold_id"], w)
            if w[component] <= baseline[component] + EPS:
                continue
            if wanted == "improve" and base_rank != 1 and new_rank == 1:
                candidates.append({"record": record, "weights": w, "baseline_rank": base_rank, "new_rank": new_rank, "metrics": row})
            if wanted == "degrade" and base_rank == 1 and new_rank != 1:
                candidates.append({"record": record, "weights": w, "baseline_rank": base_rank, "new_rank": new_rank, "metrics": row})
    if not candidates:
        return None
    # Prefer the smallest actual perturbation, then better aggregate metrics.
    candidates.sort(key=lambda x: (sum(abs(a - b) for a, b in zip(x["weights"], baseline)), -x["metrics"]["top1"], -x["metrics"]["mrr"], x["record"]["link_id"]))
    return candidates[0]


def case_rows(case: dict[str, Any], baseline: tuple[float, float, float]) -> list[dict[str, Any]]:
    record = case["record"]
    new_weights = case["weights"]
    base_ranked = ordered_candidates(record["candidates"], baseline)
    new_ranked = ordered_candidates(record["candidates"], new_weights)
    base_ranks = {c["timeline_id"]: i for i, c in enumerate(base_ranked, start=1)}
    new_ranks = {c["timeline_id"]: i for i, c in enumerate(new_ranked, start=1)}
    out = []
    for c in record["candidates"]:
        out.append({
            "case_type": case.get("case_type", ""),
            "link_id": record["link_id"],
            "event_name": record["event_name"],
            "gold_timeline_id": record["gold_id"],
            "candidate_timeline_id": c["timeline_id"],
            "candidate_event_name": c["timeline_event_name"],
            "S_name": c["name_similarity"],
            "S_summary": c["summary_similarity"],
            "R_kb": c["kb_bonus"],
            "baseline_alpha": baseline[0],
            "baseline_beta": baseline[1],
            "baseline_gamma": baseline[2],
            "baseline_score": candidate_score(c, baseline),
            "baseline_rank": base_ranks[c["timeline_id"]],
            "comparison_alpha": new_weights[0],
            "comparison_beta": new_weights[1],
            "comparison_gamma": new_weights[2],
            "comparison_score": candidate_score(c, new_weights),
            "comparison_rank": new_ranks[c["timeline_id"]],
        })
    return out


def select_rank_change(record: dict[str, Any], grid_rows: list[dict[str, Any]], baseline: tuple[float, float, float], direction: str) -> dict[str, Any] | None:
    """For a supplementary reference, locate the smallest grid perturbation
    causing an improvement or degradation without treating it as human gold."""
    base_rank = rank_of_target(record["candidates"], record["gold_id"], baseline)
    if base_rank is None:
        return None
    variants = []
    for row in grid_rows:
        w = (row["alpha"], row["beta"], row["gamma"])
        new_rank = rank_of_target(record["candidates"], record["gold_id"], w)
        if (direction == "improve" and new_rank < base_rank) or (direction == "degrade" and new_rank > base_rank):
            variants.append({"weights": w, "new_rank": new_rank, "metrics": row})
    variants.sort(key=lambda x: (sum(abs(a - b) for a, b in zip(x["weights"], baseline)), -abs(x["new_rank"] - base_rank), x["weights"]))
    if not variants:
        return None
    result = {"record": record, "weights": variants[0]["weights"], "baseline_rank": base_rank, "new_rank": variants[0]["new_rank"], "metrics": variants[0]["metrics"]}
    return result


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    module = load_module()
    cfg_raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))["timeline_config"]
    baseline = (float(cfg_raw["alpha_name"]), float(cfg_raw["beta_summary"]), float(cfg_raw["gamma_kb"]))
    if baseline != (0.45, 0.30, 0.25):
        raise AssertionError(f"配置文件中的当前权重已变化：{baseline}")

    links = module.load_links(LINKS_PATH)
    timeline_df = module.load_timeline_df(TIMELINE_PATH)
    cfg = module.TimelineConfig(
        top_k_candidates=int(cfg_raw["top_k_candidates"]),
        min_rule_score=float(cfg_raw["min_rule_score"]),
        alpha_name=baseline[0],
        beta_summary=baseline[1],
        gamma_kb=baseline[2],
        uncertain_threshold=float(cfg_raw["uncertain_threshold"]),
    )
    recomputed = module.build_timeline_candidates(links, timeline_df, cfg)
    recomputed_by_id = {x["link_id"]: x for x in recomputed}
    historical = json.loads(MATCHED_PATH.read_text(encoding="utf-8"))
    manual = [x for x in historical if x.get("timeline_status") == "manual_confirmed"]
    if len(manual) != 14:
        raise AssertionError(f"人工审校记录数量不是预期的 14，而是 {len(manual)}")

    records: list[dict[str, Any]] = []
    consistency_rows: list[dict[str, Any]] = []
    for item in manual:
        link_id = item["link_id"]
        fresh = recomputed_by_id.get(link_id)
        if fresh is None:
            raise AssertionError(f"人工审校事件不在当前输入 links 中：{link_id}")
        historical_candidates = item.get("timeline_rule_candidates", [])
        fresh_candidates = fresh["timeline_rule_candidates"]
        same_ids = [c["timeline_id"] for c in historical_candidates] == [c["timeline_id"] for c in fresh_candidates]
        consistency_rows.append({"link_id": link_id, "same_top5_ids_as_historical_output": same_ids})
        records.append({
            "link_id": link_id,
            "event_name": item["event_name"],
            "gold_id": item["timeline_id"],
            "gold_event_name": item["timeline_event_name"],
            "candidates": fresh_candidates,
        })

    recall = {}
    for k in (1, 3, 5):
        count = sum(any(c["timeline_id"] == r["gold_id"] for c in r["candidates"][:k]) for r in records)
        recall[f"Recall@{k}"] = {"count": count, "n": len(records), "value": count / len(records)}
    eligible = [r for r in records if any(c["timeline_id"] == r["gold_id"] for c in r["candidates"])]

    grid_rows: list[dict[str, Any]] = []
    for alpha, beta, gamma in grid(0.05):
        result = metrics(eligible, (alpha, beta, gamma))
        grid_rows.append({"alpha": alpha, "beta": beta, "gamma": gamma, **result})
    baseline_row = next(r for r in grid_rows if (r["alpha"], r["beta"], r["gamma"]) == baseline)
    top1_best, top1_ties = choose_best(grid_rows)
    mrr_best, mrr_ties = choose_best_mrr(grid_rows)
    name_best, name_ties = choose_best(grid_rows, lambda r: r["alpha"] >= 0.50 and r["alpha"] > r["beta"] and r["alpha"] > r["gamma"])
    summary_best, summary_ties = choose_best(grid_rows, lambda r: r["beta"] >= 0.50 and r["beta"] > r["alpha"] and r["beta"] > r["gamma"])
    coverage_best, coverage_ties = choose_best(grid_rows, lambda r: r["gamma"] >= 0.50 and r["gamma"] > r["alpha"] and r["gamma"] > r["beta"])

    # Required explanatory cases. The search itself decides whether the requested
    # transition occurs; no event or score is hard-coded.
    cases = []
    for label, component, wanted in [
        ("摘要权重提高：错误变正确", 1, "improve"),
        ("名称权重提高：错误变正确", 0, "improve"),
        ("摘要权重提高：正确变错误", 1, "degrade"),
    ]:
        found = find_case(eligible, grid_rows, baseline, component, wanted)
        if found is not None:
            found["case_type"] = label
            cases.append(found)

    all_candidate_rows = []
    for r in records:
        for c in r["candidates"]:
            all_candidate_rows.append({
                "link_id": r["link_id"], "event_name": r["event_name"], "gold_timeline_id": r["gold_id"],
                "candidate_timeline_id": c["timeline_id"], "candidate_event_name": c["timeline_event_name"],
                "S_name": c["name_similarity"], "S_summary": c["summary_similarity"], "R_kb": c["kb_bonus"],
                "baseline_score": candidate_score(c, baseline),
                "baseline_rank": rank_of_target(r["candidates"], c["timeline_id"], baseline),
            })
    case_candidate_rows = [row for case in cases for row in case_rows(case, baseline)]

    # The three events previously used in the report are retained as a separate,
    # clearly labelled mechanism demonstration. Two are LLM-aligned, not manual
    # labels, so they are excluded from all Recall/Top-1/MRR statistics above.
    historical_by_id = {x["link_id"]: x for x in historical}
    supplementary_cases = []
    for link_id, direction in (("SCL_00088", "improve"), ("SCL_00073", "improve"), ("SCL_00074", "degrade")):
        item = historical_by_id.get(link_id)
        fresh = recomputed_by_id.get(link_id)
        if item is None or fresh is None:
            continue
        record = {
            "link_id": link_id, "event_name": item["event_name"], "gold_id": item["timeline_id"],
            "gold_event_name": item["timeline_event_name"], "candidates": fresh["timeline_rule_candidates"],
            "reference_status": item.get("timeline_status"),
        }
        chosen = select_rank_change(record, grid_rows, baseline, direction)
        if chosen is not None:
            chosen["case_type"] = f"补充案例（{record['reference_status']}）"
            supplementary_cases.append(chosen)
    supplementary_rows = [row for case in supplementary_cases for row in case_rows(case, baseline)]

    def dump_csv(path: Path, rows: list[dict[str, Any]]) -> None:
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["empty"])
            writer.writeheader()
            writer.writerows(rows)

    dump_csv(OUT_DIR / "timeline_weight_grid_results.csv", grid_rows)
    dump_csv(OUT_DIR / "timeline_weight_manual_event_candidates.csv", all_candidate_rows)
    dump_csv(OUT_DIR / "timeline_weight_case_candidates.csv", case_candidate_rows)
    dump_csv(OUT_DIR / "timeline_weight_supplementary_cases.csv", supplementary_rows)
    dump_csv(OUT_DIR / "timeline_weight_candidate_pool_consistency.csv", consistency_rows)

    selected = {
        "historical_engineering_configuration": baseline_row,
        "top1_best_representative": top1_best,
        "top1_best_tie_count": len(top1_ties),
        "mrr_best_representative": mrr_best,
        "mrr_best_tie_count": len(mrr_ties),
        "name_emphasis_representative": name_best,
        "name_emphasis_tie_count": len(name_ties),
        "summary_emphasis_representative": summary_best,
        "summary_emphasis_tie_count": len(summary_ties),
        "coverage_emphasis_representative": coverage_best,
        "coverage_emphasis_tie_count": len(coverage_ties),
    }
    summary = {
        "scope": {
            "candidate_generation_input_links": len(links),
            "historical_final_output_events": len(historical),
            "manual_confirmed_events": len(records),
            "fixed_top_k": cfg.top_k_candidates,
            "re_rank_eligible_events": len(eligible),
            "grid_step": 0.05,
            "grid_configurations": len(grid_rows),
        },
        "historical_status_counts": dict(Counter(x.get("timeline_status") for x in historical)),
        "config_from_timeline_run_config": cfg_raw,
        "candidate_recall_against_manual_confirmed": recall,
        "fixed_candidate_pool_note": "所有权重组合都在当前工程配置生成的 Top-5 候选集合内重新排序；因此该实验是固定候选池上的参数敏感性分析，不是随权重变化的候选召回实验。",
        "candidate_pool_recompute_consistency": {
            "manual_events_with_identical_top5_ids": sum(r["same_top5_ids_as_historical_output"] for r in consistency_rows),
            "manual_events": len(consistency_rows),
        },
        "selected_configurations": selected,
        "representative_cases_found": [
            {
                "case_type": c["case_type"], "link_id": c["record"]["link_id"], "event_name": c["record"]["event_name"],
                "gold_timeline_id": c["record"]["gold_id"], "baseline_rank": c["baseline_rank"], "comparison_rank": c["new_rank"],
                "comparison_weights": c["weights"],
            }
            for c in cases
        ],
        "missing_requested_case_types": [
            label for label in ["摘要权重提高：错误变正确", "名称权重提高：错误变正确", "摘要权重提高：正确变错误"]
            if label not in {c["case_type"] for c in cases}
        ],
        "supplementary_previous_report_cases": [
            {
                "link_id": c["record"]["link_id"], "event_name": c["record"]["event_name"],
                "reference_status": c["record"].get("reference_status"), "reference_timeline_id": c["record"]["gold_id"],
                "baseline_rank": c["baseline_rank"], "comparison_rank": c["new_rank"], "comparison_weights": c["weights"],
            }
            for c in supplementary_cases
        ],
        "input_hashes_sha256": {str(p.relative_to(ROOT)): sha256(p) for p in [MODULE_PATH, LINKS_PATH, TIMELINE_PATH, MATCHED_PATH, CONFIG_PATH]},
    }
    (OUT_DIR / "timeline_weight_experiment_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_DIR / "timeline_weight_reproducibility_manifest.json").write_text(
        json.dumps({"command": "python 跨模态事件对齐与事件时间线构建/timeline_weight_experiment.py", "inputs": summary["input_hashes_sha256"], "outputs": [
            "timeline_weight_grid_results.csv", "timeline_weight_manual_event_candidates.csv", "timeline_weight_case_candidates.csv", "timeline_weight_supplementary_cases.csv", "timeline_weight_candidate_pool_consistency.csv", "timeline_weight_experiment_summary.json"
        ]}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
