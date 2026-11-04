from __future__ import annotations

import argparse
import json
import math
import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import dashscope
import pandas as pd
from dashscope import MultiModalConversation
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


DEFAULT_ENCODING = "utf-8-sig"

dashscope.base_http_api_url = os.getenv(
    "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/api/v1"
)


def _safe_text(x) -> str:
    if x is None:
        return ""
    s = str(x).strip()
    if s.lower() in {"nan", "none", "null", "na"}:
        return ""
    return s


def _safe_float(x, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def _split_items(value) -> List[str]:
    s = _safe_text(value)
    if not s:
        return []
    return [x.strip() for x in re.split(r"[、，,;；/|\s]+", s) if x.strip()]


def _dedup_keep_order(items: Sequence[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


class ProgressPrinter:
    def __init__(self, total: int, desc: str) -> None:
        self.total = max(total, 1)
        self.desc = desc
        self.count = 0
        print(f"[TIMELINE] {desc} | total={total}", flush=True)

    def step(self) -> None:
        self.count += 1
        if self.count == 1 or self.count % 20 == 0 or self.count == self.total:
            print(f"[TIMELINE] {self.desc}: {self.count}/{self.total}", flush=True)


@dataclass
class TimelineConfig:
    top_k_candidates: int = 5
    min_rule_score: float = 0.20
    alpha_name: float = 0.45
    beta_summary: float = 0.30
    gamma_kb: float = 0.25
    uncertain_threshold: float = 0.35


@dataclass
class LLMConfig:
    enabled: bool = True
    model_name: str = "qwen3.6-plus"
    timeout: int = 120
    max_retries: int = 3
    batch_size: int = 8
    pause_between_batches_sec: float = 0.0
    max_items: int = 200
    accept_conf_ge: float = 0.70
    verbose: bool = True


class TextSimilarityBackend:
    def __init__(self) -> None:
        self.vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(2, 4), min_df=1)

    def similarity_matrix(self, a: Sequence[str], b: Sequence[str]):
        corpus = list(a) + list(b)
        self.vectorizer.fit(corpus)
        va = self.vectorizer.transform(list(a))
        vb = self.vectorizer.transform(list(b))
        return cosine_similarity(va, vb)


def load_timeline_df(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, encoding=DEFAULT_ENCODING)
    df = df.rename(columns={"红楼年份": "timeline_year", "季节月份": "timeline_season", "事件名称": "timeline_event_name"})
    if "timeline_event_name" not in df.columns:
        raise ValueError("时间线库缺少 事件名称 列")
    df = df[[c for c in ["timeline_year", "timeline_season", "timeline_event_name"] if c in df.columns]].copy()
    df["timeline_id"] = [f"TL{idx:03d}" for idx in range(1, len(df) + 1)]
    df["timeline_ref"] = df.apply(
        lambda r: f"{_safe_text(r['timeline_id'])}｜{_safe_text(r['timeline_year'])}｜{_safe_text(r['timeline_season'])}｜{_safe_text(r['timeline_event_name'])}",
        axis=1,
    )
    df["timeline_repr"] = df.apply(
        lambda r: "；".join(
            [
                f"年份:{_safe_text(r.get('timeline_year'))}",
                f"时令:{_safe_text(r.get('timeline_season'))}",
                f"事件:{_safe_text(r.get('timeline_event_name'))}",
            ]
        ),
        axis=1,
    )
    return df


def load_links(path: Path) -> List[Dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_link_repr(link: Dict) -> Dict[str, str]:
    text_summary = _safe_text(link.get("text", {}).get("scene_summary"))
    video_summary = _safe_text(link.get("video", {}).get("scene_summary"))
    shared_chars = "、".join(link.get("shared", {}).get("characters", []) or [])
    shared_locs = "、".join(link.get("shared", {}).get("locations", []) or [])
    event_name = _safe_text(link.get("event_name"))
    kb_name = _safe_text(link.get("canonical_event_name"))
    composed = "；".join(
        x
        for x in [
            f"事件名:{event_name}",
            f"规范事件:{kb_name}",
            f"文本摘要:{text_summary}",
            f"视频摘要:{video_summary}",
            f"共享人物:{shared_chars}",
            f"共享地点:{shared_locs}",
        ]
        if x and not x.endswith(":")
    )
    short_name = "；".join(x for x in [event_name, kb_name] if x)
    return {"link_name_repr": short_name[:300], "link_full_repr": composed[:1600]}


def build_timeline_candidates(links: List[Dict], timeline_df: pd.DataFrame, cfg: TimelineConfig) -> List[Dict]:
    backend = TextSimilarityBackend()
    link_repr_rows = [build_link_repr(x) for x in links]
    link_name_reprs = [x["link_name_repr"] for x in link_repr_rows]
    link_full_reprs = [x["link_full_repr"] for x in link_repr_rows]
    timeline_name_reprs = timeline_df["timeline_event_name"].fillna("").astype(str).tolist()
    timeline_full_reprs = timeline_df["timeline_repr"].fillna("").astype(str).tolist()

    name_sim = backend.similarity_matrix(link_name_reprs, timeline_name_reprs)
    full_sim = backend.similarity_matrix(link_full_reprs, timeline_full_reprs)

    out: List[Dict] = []
    progress = ProgressPrinter(len(links), "规则候选匹配时间线")
    for i, link in enumerate(links):
        scores: List[Tuple[float, Dict]] = []
        link_kb_name = _safe_text(link.get("canonical_event_name"))
        link_event_name = _safe_text(link.get("event_name"))
        for j, row in timeline_df.iterrows():
            s_name = float(name_sim[i, j])
            s_summary = float(full_sim[i, j])
            timeline_event_name = _safe_text(row.get("timeline_event_name"))
            kb_bonus = 0.0
            if link_kb_name and link_kb_name in timeline_event_name:
                kb_bonus = 1.0
            elif link_event_name and link_event_name in timeline_event_name:
                kb_bonus = 0.8
            score = cfg.alpha_name * s_name + cfg.beta_summary * s_summary + cfg.gamma_kb * kb_bonus
            scores.append(
                (
                    score,
                    {
                        "timeline_id": _safe_text(row.get("timeline_id")),
                        "timeline_year": _safe_text(row.get("timeline_year")),
                        "timeline_season": _safe_text(row.get("timeline_season")),
                        "timeline_event_name": timeline_event_name,
                        "timeline_ref": _safe_text(row.get("timeline_ref")),
                        "rule_score": round(score, 6),
                        "name_similarity": round(s_name, 6),
                        "summary_similarity": round(s_summary, 6),
                        "kb_bonus": round(kb_bonus, 6),
                    },
                )
            )
        scores.sort(key=lambda x: x[0], reverse=True)
        candidates = [payload for _, payload in scores[: cfg.top_k_candidates]]
        strong_candidates = [payload for score, payload in scores if score >= cfg.min_rule_score][: cfg.top_k_candidates]
        top = strong_candidates[0] if strong_candidates else (candidates[0] if candidates else None)
        gap = 1.0
        if len(candidates) >= 2:
            gap = _safe_float(candidates[0].get("rule_score")) - _safe_float(candidates[1].get("rule_score"))
        out.append(
            {
                **link,
                "timeline_rule_candidates": candidates,
                "timeline_rule_top_score": _safe_float(top.get("rule_score")) if top else 0.0,
                "timeline_rule_gap": round(gap, 6),
                "timeline_id": _safe_text(top.get("timeline_id")) if strong_candidates else "不确定",
                "timeline_year": _safe_text(top.get("timeline_year")) if strong_candidates else "不确定",
                "timeline_season": _safe_text(top.get("timeline_season")) if strong_candidates else "不确定",
                "timeline_event_name": _safe_text(top.get("timeline_event_name")) if strong_candidates else "不确定",
                "timeline_ref": _safe_text(top.get("timeline_ref")) if strong_candidates else "不确定",
                "timeline_status": "rule_matched" if strong_candidates else "uncertain",
            }
        )
        progress.step()
    return out


def _call_dashscope_json(prompt: str, cfg: LLMConfig) -> Dict:
    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("未设置 DASHSCOPE_API_KEY")

    last_error = None
    for _ in range(cfg.max_retries):
        try:
            response = MultiModalConversation.call(
                api_key=api_key,
                model=cfg.model_name,
                timeout=cfg.timeout,
                messages=[
                    {
                        "role": "user",
                        "content": [{"text": prompt}],
                    }
                ],
            )
            content = response.output.choices[0].message.content  # type: ignore[attr-defined]
            if isinstance(content, list):
                text = "\n".join(str(x.get("text", "")) for x in content if isinstance(x, dict))
            else:
                text = str(content)
            text = text.strip()
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?", "", text).strip()
                text = re.sub(r"```$", "", text).strip()
            return json.loads(text)
        except Exception as e:
            last_error = e
            time.sleep(1.5)
    raise RuntimeError(f"LLM 调用失败: {last_error}")


def _build_timeline_batch_prompt(items: List[Dict]) -> str:
    prompt = {
        "role": "你是一名专业的红楼梦学者、版本学研究者和叙事时间线标注专家。",
        "task": "请根据《红楼梦》标准时间线库，为已经完成跨模态对齐的事件确定最合适的时间线位置。",
        "core_requirements": [
            "你必须把自己当作熟悉《红楼梦》前八十回主要情节顺序、人物关系、章节推进和关键事件发生时令的专家。",
            "判断时不能只看事件名称字面相似度，必须综合考虑：规范事件名、文本场景摘要、视频场景摘要、共享人物、共享地点、叙事前后关系、情节阶段。",
            "很多事件只是某个大事件中的片段、前奏、高潮或余波，你需要判断它最应该落在哪一个标准时间线条目上。",
            "如果某个跨模态事件明显属于某个标准时间线事件的组成部分、核心片段、前置铺垫或直接后续，并且归属清晰，也可以判为 aligned。",
            "只有在候选都不够合理、无法可靠确定时间位置时，才输出 unmatched。",
            "你只能从每个事件自己的 candidates 中选择 best_timeline_id，绝对不能编造新的 timeline_id。",
            "请尽量提高时间确定率，但不要为了提高覆盖率而强行乱配。",
            "输出必须是严格合法 JSON，不要输出解释性前后缀，不要输出 markdown 代码块。",
            "不要输出 schema 之外的字段。",
            "不要使用中文引号、中文逗号、中文布尔值。"
        ],
        "decision_rules": [
            "若规范事件名与候选时间线事件名高度一致，且文本/视频摘要也支持，则优先选择该候选。",
            "若事件名不完全一致，但文本摘要与视频摘要共同指向同一经典情节，也应判为 aligned。",
            "若一个事件是经典事件的前置铺垫或后续延伸，但在叙事研究上通常仍归入该事件条目，则可以选择该条目。",
            "若多个候选都相近，请选择最符合核心动作和叙事阶段的那一个，而不是最表层相似的那一个。",
            "若文本和视频本身就只体现了大事件中的局部片段，请判断其在学理上通常归属哪条时间线事件。"
        ],
        "items": items,
        "output_schema": {
            "results": [
                {
                    "link_id": "输入中的 link_id",
                    "decision": "aligned | unmatched",
                    "best_timeline_id": "候选中的 timeline_id 或 null",
                    "confidence": "0到1之间浮点数",
                    "reason": "请用一句较具体的中文理由说明为什么该事件属于这个时间线条目，或为什么仍然无法确定。"
                }
            ]
        }
    }
    return json.dumps(prompt, ensure_ascii=False, indent=2)


def review_links_with_llm(items: List[Dict], cfg: LLMConfig, uncertain_threshold: float) -> Tuple[List[Dict], List[Dict]]:
    if not cfg.enabled:
        return items, []

    out = list(items)
    audits: List[Dict] = []
    review_items: List[Dict] = []
    for item in out:
        if len(review_items) >= cfg.max_items:
            break
        score = _safe_float(item.get("timeline_rule_top_score"), 0.0)
        gap = _safe_float(item.get("timeline_rule_gap"), 1.0)
        if score <= uncertain_threshold or gap <= 0.08:
            review_items.append(
                {
                    "link_id": _safe_text(item.get("link_id")),
                    "payload": {
                        "link_id": _safe_text(item.get("link_id")),
                        "event_name": _safe_text(item.get("event_name")),
                        "canonical_event_name": _safe_text(item.get("canonical_event_name")),
                        "text_scene_name": _safe_text(item.get("text", {}).get("scene_name")),
                        "text_scene_summary": _safe_text(item.get("text", {}).get("scene_summary")),
                        "text_chapter_title": _safe_text(item.get("text", {}).get("chapter_title")),
                        "video_scene_name": _safe_text(item.get("video", {}).get("scene_name")),
                        "video_scene_summary": _safe_text(item.get("video", {}).get("scene_summary")),
                        "video_episode_title": _safe_text(item.get("video", {}).get("episode_title")),
                        "shared_characters": item.get("shared", {}).get("characters", []) or [],
                        "shared_locations": item.get("shared", {}).get("locations", []) or [],
                        "current_rule_top_score": round(score, 6),
                        "current_rule_gap": round(gap, 6),
                        "candidates": item.get("timeline_rule_candidates", [])[:5],
                    },
                }
            )

    if not review_items:
        return out, audits

    batch_size = max(1, int(cfg.batch_size))
    total_batches = math.ceil(len(review_items) / batch_size)
    print(f"[TIMELINE] LLM 待复核 {len(review_items)} 条，batch_size={batch_size}，共 {total_batches} 批", flush=True)
    progress = ProgressPrinter(total_batches, "LLM 分批复核时间线")
    index_map = {_safe_text(x.get("link_id")): idx for idx, x in enumerate(out)}

    for batch_idx in range(total_batches):
        start = batch_idx * batch_size
        end = min(len(review_items), start + batch_size)
        batch = review_items[start:end]
        if cfg.verbose:
            print(f"[TIMELINE] LLM 批次 {batch_idx + 1}/{total_batches} | items={len(batch)} | processed={end}/{len(review_items)}", flush=True)
        try:
            obj = _call_dashscope_json(_build_timeline_batch_prompt([x["payload"] for x in batch]), cfg)
            results = obj.get("results", []) if isinstance(obj, dict) else []
            if not isinstance(results, list):
                results = []
        except Exception as e:
            for item in batch:
                audits.append({
                    "type": "timeline_review",
                    "link_id": item["link_id"],
                    "status": "error",
                    "batch_index": batch_idx + 1,
                    "error": _safe_text(e),
                })
            progress.step()
            if cfg.pause_between_batches_sec > 0:
                time.sleep(cfg.pause_between_batches_sec)
            continue

        result_map = {
            _safe_text(x.get("link_id")): x
            for x in results
            if isinstance(x, dict) and _safe_text(x.get("link_id"))
        }
        for item in batch:
            link_id = item["link_id"]
            idx = index_map[link_id]
            obj_item = result_map.get(link_id, {})
            decision = _safe_text(obj_item.get("decision")).lower()
            best_timeline_id = _safe_text(obj_item.get("best_timeline_id"))
            conf = max(0.0, min(1.0, _safe_float(obj_item.get("confidence"), 0.0)))
            reason = _safe_text(obj_item.get("reason"))
            candidate_map = {
                _safe_text(c.get("timeline_id")): c for c in out[idx].get("timeline_rule_candidates", [])
            }
            if decision == "aligned" and best_timeline_id in candidate_map and conf >= cfg.accept_conf_ge:
                chosen = candidate_map[best_timeline_id]
                out[idx]["timeline_id"] = _safe_text(chosen.get("timeline_id"))
                out[idx]["timeline_year"] = _safe_text(chosen.get("timeline_year"))
                out[idx]["timeline_season"] = _safe_text(chosen.get("timeline_season"))
                out[idx]["timeline_event_name"] = _safe_text(chosen.get("timeline_event_name"))
                out[idx]["timeline_ref"] = _safe_text(chosen.get("timeline_ref"))
                out[idx]["timeline_status"] = "llm_aligned"
            elif decision == "unmatched" and conf >= cfg.accept_conf_ge:
                out[idx]["timeline_id"] = "不确定"
                out[idx]["timeline_year"] = "不确定"
                out[idx]["timeline_season"] = "不确定"
                out[idx]["timeline_event_name"] = "不确定"
                out[idx]["timeline_ref"] = "不确定"
                out[idx]["timeline_status"] = "llm_unmatched"
            out[idx]["timeline_llm_review"] = {
                "decision": decision,
                "best_timeline_id": best_timeline_id,
                "confidence": round(conf, 6),
                "reason": reason,
            }
            audits.append(
                {
                    "type": "timeline_review",
                    "link_id": link_id,
                    "status": "ok" if obj_item else "missing_result",
                    "batch_index": batch_idx + 1,
                    "decision": decision,
                    "best_timeline_id": best_timeline_id,
                    "confidence": round(conf, 6),
                    "reason": reason,
                }
            )
        progress.step()
        if cfg.pause_between_batches_sec > 0:
            time.sleep(cfg.pause_between_batches_sec)
    return out, audits


def build_timeline_index(links_with_timeline: List[Dict]) -> List[Dict]:
    groups: Dict[str, List[Dict]] = {}
    for item in links_with_timeline:
        key = _safe_text(item.get("timeline_id")) or "不确定"
        groups.setdefault(key, []).append(item)
    out: List[Dict] = []
    for timeline_id, items in groups.items():
        first = items[0]
        out.append(
            {
                "timeline_id": timeline_id,
                "timeline_year": _safe_text(first.get("timeline_year")) or "不确定",
                "timeline_season": _safe_text(first.get("timeline_season")) or "不确定",
                "timeline_event_name": _safe_text(first.get("timeline_event_name")) or "不确定",
                "timeline_ref": _safe_text(first.get("timeline_ref")) or "不确定",
                "matched_event_count": len(items),
                "event_names": _dedup_keep_order([_safe_text(x.get("canonical_event_name")) for x in items if _safe_text(x.get("canonical_event_name"))]),
                "link_ids": [_safe_text(x.get("link_id")) for x in items],
            }
        )
    out.sort(key=lambda x: (x["timeline_id"] == "不确定", x["timeline_id"]))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="将跨模态匹配事件与外置时间线库对齐")
    parser.add_argument("--links", type=str, default="跨模态事件对齐与事件时间线构建/kb_outputs_scene_first/cross_modal_scene_links.json")
    parser.add_argument("--timeline-csv", type=str, default="知识库/红楼梦时间线.csv")
    parser.add_argument("--output-dir", type=str, default="跨模态事件对齐与事件时间线构建/timeline_outputs")
    parser.add_argument("--top-k-candidates", type=int, default=5)
    parser.add_argument("--min-rule-score", type=float, default=0.20)
    parser.add_argument("--uncertain-threshold", type=float, default=0.35)
    parser.add_argument("--enable-llm-review", action="store_true")
    parser.add_argument("--llm-model", type=str, default="qwen3.6-plus")
    parser.add_argument("--llm-timeout", type=int, default=120)
    parser.add_argument("--llm-max-retries", type=int, default=3)
    parser.add_argument("--llm-batch-size", type=int, default=8)
    parser.add_argument("--llm-max-items", type=int, default=200)
    parser.add_argument("--llm-pause-between-batches-sec", type=float, default=0.0)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cfg = TimelineConfig(
        top_k_candidates=args.top_k_candidates,
        min_rule_score=args.min_rule_score,
        uncertain_threshold=args.uncertain_threshold,
    )
    llm_cfg = LLMConfig(
        enabled=args.enable_llm_review,
        model_name=args.llm_model,
        timeout=args.llm_timeout,
        max_retries=args.llm_max_retries,
        batch_size=args.llm_batch_size,
        max_items=args.llm_max_items,
        pause_between_batches_sec=args.llm_pause_between_batches_sec,
    )

    links = load_links(Path(args.links))
    timeline_df = load_timeline_df(Path(args.timeline_csv))

    print(f"[TIMELINE] 已加载匹配事件 {len(links)} 条", flush=True)
    links_with_rule = build_timeline_candidates(links, timeline_df, cfg)
    links_with_final, audits = review_links_with_llm(links_with_rule, llm_cfg, cfg.uncertain_threshold)

    uncertain_count = sum(1 for x in links_with_final if _safe_text(x.get("timeline_id")) in {"", "不确定"})
    determined_count = len(links_with_final) - uncertain_count
    print(f"[TIMELINE] 时间已确定 {determined_count} 条，不确定 {uncertain_count} 条", flush=True)

    (output_dir / "matched_events_with_timeline.json").write_text(json.dumps(links_with_final, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "timeline_event_index.json").write_text(json.dumps(build_timeline_index(links_with_final), ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "timeline_review_audit.json").write_text(json.dumps(audits, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "timeline_run_config.json").write_text(json.dumps({"timeline_config": asdict(cfg), "llm_config": asdict(llm_cfg)}, ensure_ascii=False, indent=2), encoding="utf-8")

    print("[TIMELINE] 输出文件：", flush=True)
    print(f"- {output_dir / 'matched_events_with_timeline.json'}", flush=True)
    print(f"- {output_dir / 'timeline_event_index.json'}", flush=True)
    print(f"- {output_dir / 'timeline_review_audit.json'}", flush=True)
    print(f"- {output_dir / 'timeline_run_config.json'}", flush=True)


if __name__ == "__main__":
    main()
