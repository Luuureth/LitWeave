"""
功能2（离线算法模块）：
  阶段A：事件 -> 参考时间线锚定（候选召回 + 可选闭集判定/回退）
  阶段B：先做跨模态候选召回，再做 LLM 判断，最后做严格一对一配对
  阶段C：输出严格的一对一结果 paired_alignments.json

注意：本版本先专注“事件一对一匹配”，不把时间匹配作为主流程强约束。
保留 grounding / timeline 信息作为辅助字段，供后续单独做时间对齐时使用。
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

DEFAULT_ENCODING = "utf-8-sig"


# -----------------------------
# 进度与日志工具
# -----------------------------
def _log_stage(message: str) -> None:
    print(f"\n[PIPELINE] {message}", flush=True)


def _iter_progress(iterable, total: Optional[int] = None, desc: str = ""):
    try:
        from tqdm import tqdm  # type: ignore

        return tqdm(iterable, total=total, desc=desc, ncols=100)
    except Exception:
        if desc:
            print(f"[PIPELINE] {desc} ...", flush=True)
        return iterable


# -----------------------------
# 通用工具
# -----------------------------
def _clean_unnamed_cols(df: pd.DataFrame) -> pd.DataFrame:
    keep_cols = [c for c in df.columns if not str(c).startswith("Unnamed")]
    return df[keep_cols].copy()


def _safe_text(x: object) -> str:
    if x is None:
        return ""
    s = str(x).strip()
    if s.lower() in {"nan", "none", "null", "na"}:
        return ""
    return s


def _split_norm_items(text: str) -> List[str]:
    s = _safe_text(text)
    if not s:
        return []
    parts = re.split(r"[、，,;；/|\s]+", s)
    out = []
    for p in parts:
        p = p.strip()
        if not p or p.lower() in {"null", "none", "nan"}:
            continue
        out.append(p)
    return out


def _dedup_keep_order(items: Sequence[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _safe_int(x: object, default: int = -1) -> int:
    try:
        if x is None or str(x).strip() == "":
            return default
        return int(float(x))
    except Exception:
        return default


def _safe_float(x: object, default: float = 0.0) -> float:
    try:
        if x is None or str(x).strip() == "":
            return default
        return float(x)
    except Exception:
        return default


def _normalize_event_name(name: str, summary: str, action: str, max_len: int = 24) -> str:
    """
    统一事件名规则：
      1) 优先文本侧 action / event_name
      2) 若过长则压缩
      3) 去掉常见冗余前后缀，保留检索友好的短标题
    """
    base = _safe_text(name) or _safe_text(action) or _safe_text(summary)
    if not base:
        return "未命名事件"

    base = re.sub(r"[，。；：,.!！?？]+", " ", base)
    base = re.sub(r"\s+", " ", base).strip()

    redundant_prefixes = [
        "贾宝玉与",
        "宝玉与",
        "众人",
        "众女子",
        "众丫鬟",
        "众婆子",
    ]
    for p in redundant_prefixes:
        if base.startswith(p) and len(base) > len(p) + 4:
            base = base[len(p) :].strip()
            break

    base = base.replace("于", "在", 1) if "于" in base[:8] else base
    if len(base) <= max_len:
        return base

    summary = _safe_text(summary)
    if summary:
        s = re.sub(r"[，。；：,.!！?？]+", " ", summary)
        s = re.sub(r"\s+", " ", s).strip()
        if s:
            return s[:max_len].strip()
    return base[:max_len].strip()


# -----------------------------
# 文本相似度后端：优先 embedding，fallback TF-IDF
# -----------------------------
class TextSimilarityBackend:
    """优先使用 sentence-transformers embedding + cosine；不可用时回退 TF-IDF。"""

    def __init__(self) -> None:
        self.backend = "tfidf"
        self.model = None
        self.vectorizer: Optional[TfidfVectorizer] = None

        force_tfidf = os.environ.get("FORCE_TFIDF", "0") == "1"
        if force_tfidf:
            self.vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=1)
            self.backend = "tfidf"
            return

        try:
            from sentence_transformers import SentenceTransformer  # type: ignore

            self.model = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
            self.backend = "sentence-transformer"
        except Exception:
            self.vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=1)
            self.backend = "tfidf"

    def fit(self, corpus: Sequence[str]) -> None:
        if self.backend == "sentence-transformer":
            return
        assert self.vectorizer is not None
        self.vectorizer.fit(list(corpus))

    def encode(self, texts: Sequence[str]):
        texts = [t if t else "" for t in texts]
        if self.backend == "sentence-transformer":
            emb = self.model.encode(texts, normalize_embeddings=True, show_progress_bar=False)  # type: ignore[union-attr]
            return np.array(emb)
        assert self.vectorizer is not None
        return self.vectorizer.transform(texts)

    def similarity_matrix(self, a: Sequence[str], b: Sequence[str]) -> np.ndarray:
        if self.backend == "tfidf":
            self.fit(list(a) + list(b))
        va = self.encode(a)
        vb = self.encode(b)
        return cosine_similarity(va, vb)


# -----------------------------
# 配置
# -----------------------------
@dataclass
class GroundingConfig:
    top_k_candidates: int = 8
    accept_top1_if_score_ge: float = 0.18
    unknown_if_top1_le: float = 0.08
    sequence_prior_strength: float = 0.08
    min_conf_for_anchor: float = 0.16


@dataclass
class AlignWeights:
    alpha_sem: float = 0.52
    beta_char: float = 0.28
    gamma_loc: float = 0.20
    delta_time: float = 0.00


@dataclass
class AlignmentConfig:
    time_window: int = 3
    top_k_per_source: int = 5
    aligned_threshold: float = 0.62
    related_threshold: float = 0.45
    enforce_one_to_one: bool = True
    one_to_one_keep_per_target: int = 1
    require_anchor_for_alignment: bool = False
    weak_anchor_penalty: float = 0.03
    mismatch_time_penalty: float = 0.0
    source_confidence_weight: float = 0.02
    target_confidence_weight: float = 0.02


@dataclass
class AlignmentLLMRerankConfig:
    enabled: bool = False
    provider: str = "dashscope"
    model_name: str = "qwen3.6-plus"
    api_key_env: str = "DASHSCOPE_API_KEY"
    api_key_literal: str = ""
    max_candidates_per_source: int = 5
    min_score_for_review: float = 0.25
    max_score_for_review: float = 0.95
    top_gap_for_review: float = 0.25
    review_related_only: bool = False
    review_aligned_too: bool = True
    force_first_n: int = 0
    max_items: int = 400
    max_retries: int = 3
    timeout: int = 120
    accept_if_aligned_conf_ge: float = 0.70
    fallback_to_original: bool = True
    verbose: bool = True
    min_pair_confidence: float = 0.70


@dataclass
class ClusterConfig:
    use_edge_type: str = "aligned"
    min_edge_score: float = 0.55


@dataclass
class FragmentFilterConfig:
    enabled: bool = True
    min_action_len: int = 2
    min_summary_len: int = 8
    require_char_or_loc: bool = True
    drop_if_action_generic: bool = True
    generic_actions: Tuple[str, ...] = (
        "出现",
        "闲谈",
        "说话",
        "交谈",
        "沉思",
        "回想",
        "路过",
        "徘徊",
        "走动",
        "观看",
        "入席",
        "离去",
        "整理",
        "收拾",
    )


# -----------------------------
# 阶段A：时间线预处理 + 事件表示 + 候选召回 + 锚定
# -----------------------------
def preprocess_timeline(timeline_csv: Path, out_csv: Path) -> pd.DataFrame:
    df = pd.read_csv(timeline_csv, encoding=DEFAULT_ENCODING)
    df = _clean_unnamed_cols(df)
    required = ["红楼年份", "季节月份", "事件名称"]
    for col in required:
        if col not in df.columns:
            raise ValueError(f"时间线缺少必需字段: {col}")
    df = df[required].copy()
    df["timeline_order"] = np.arange(1, len(df) + 1)
    df["timeline_id"] = df["timeline_order"].map(lambda x: f"T{x:03d}")
    df = df[["timeline_id", "timeline_order", "红楼年份", "季节月份", "事件名称"]]
    df.to_csv(out_csv, index=False, encoding=DEFAULT_ENCODING)
    return df


def filter_fragment_events(df: pd.DataFrame, cfg: FragmentFilterConfig) -> pd.DataFrame:
    if df.empty or not cfg.enabled:
        return df.copy()

    out_rows = []
    progress = _iter_progress(df.iterrows(), total=len(df), desc="过滤碎片事件")
    for _, row in progress:
        action = _safe_text(row.get("action"))
        summary = _safe_text(row.get("event_summary"))
        core = _safe_text(row.get("semantic_core"))
        chars = _split_norm_items(_safe_text(row.get("characters")))
        locs = _split_norm_items(_safe_text(row.get("location")))
        text = " ".join([action, summary, core])

        if len(action) < cfg.min_action_len:
            continue
        if len(summary) < cfg.min_summary_len and len(core) < cfg.min_summary_len:
            continue
        if cfg.require_char_or_loc and not chars and not locs:
            continue
        if cfg.drop_if_action_generic and any(action == ga or action in ga for ga in cfg.generic_actions):
            if len(summary) < 15 and len(chars) <= 1 and len(locs) <= 1:
                continue
        if len(text) < 20 and len(chars) <= 1 and len(locs) <= 1:
            continue
        out_rows.append(row)

    return pd.DataFrame(out_rows).reset_index(drop=True)


def build_event_repr(unified_events_csv: Path, out_csv: Path, cfg: Optional[FragmentFilterConfig] = None) -> pd.DataFrame:
    df = pd.read_csv(unified_events_csv, encoding=DEFAULT_ENCODING)
    must = [
        "ueid",
        "modality",
        "source_id",
        "source_title",
        "action",
        "event_summary",
        "semantic_core",
        "keywords",
        "characters",
        "location",
        "source_path",
    ]
    miss = [c for c in must if c not in df.columns]
    if miss:
        raise ValueError(f"统一事件表缺少字段: {miss}")

    if cfg is not None:
        df = filter_fragment_events(df, cfg)

    def compose(row: pd.Series) -> str:
        action = _safe_text(row.get("action"))
        summary = _safe_text(row.get("event_summary"))
        core = _safe_text(row.get("semantic_core"))
        chars = _dedup_keep_order(_split_norm_items(_safe_text(row.get("characters"))))
        locs = _dedup_keep_order(_split_norm_items(_safe_text(row.get("location"))))
        kws = _dedup_keep_order(_split_norm_items(_safe_text(row.get("keywords"))))

        chunks: List[str] = []
        if action:
            chunks.append(f"动作:{action}")
        if summary:
            chunks.append(f"摘要:{summary}")
        if core and core not in summary:
            chunks.append(f"语义核:{core}")
        if chars:
            chunks.append(f"人物:{'、'.join(chars[:8])}")
        if locs:
            chunks.append(f"地点:{'、'.join(locs[:4])}")
        if kws:
            chunks.append(f"关键词:{'、'.join(kws[:10])}")
        return ("；".join(chunks))[:420]

    df["event_repr_text"] = df.apply(compose, axis=1)
    df.to_csv(out_csv, index=False, encoding=DEFAULT_ENCODING)
    return df


def timeline_candidate_recall(
    events_repr_csv: Path,
    timeline_nodes_csv: Path,
    out_csv: Path,
    top_k: int,
) -> Tuple[pd.DataFrame, str]:
    ev = pd.read_csv(events_repr_csv, encoding=DEFAULT_ENCODING)
    tl = pd.read_csv(timeline_nodes_csv, encoding=DEFAULT_ENCODING)
    if "event_repr_text" not in ev.columns:
        raise ValueError("事件表示文件缺少 event_repr_text")

    timeline_title_texts = tl["事件名称"].fillna("").astype(str).tolist()
    timeline_full_texts = (
        tl["红楼年份"].fillna("").astype(str)
        + "；"
        + tl["季节月份"].fillna("").astype(str)
        + "；"
        + tl["事件名称"].fillna("").astype(str)
    ).tolist()
    event_texts = ev["event_repr_text"].fillna("").astype(str).tolist()

    sim_backend = TextSimilarityBackend()
    title_sim = sim_backend.similarity_matrix(event_texts, timeline_title_texts)
    full_sim = sim_backend.similarity_matrix(event_texts, timeline_full_texts)
    sim_mat = 0.72 * title_sim + 0.28 * full_sim

    k = min(int(top_k), len(tl))
    records = []
    progress = _iter_progress(ev.iterrows(), total=len(ev), desc="召回时间线候选")
    for i, row in progress:
        sims = sim_mat[i]
        idx = np.argsort(-sims)[:k]
        cands = [str(tl.iloc[j]["timeline_id"]) for j in idx]
        scores = [float(sims[j]) for j in idx]
        score_gap = float(scores[0] - scores[1]) if len(scores) >= 2 else float(scores[0] if scores else 0.0)
        records.append(
            {
                "ueid": row["ueid"],
                "candidate_timeline_ids": json.dumps(cands, ensure_ascii=False),
                "candidate_scores": json.dumps([round(x, 6) for x in scores], ensure_ascii=False),
                "recall_backend": sim_backend.backend,
                "top1_score": round(scores[0], 6) if scores else 0.0,
                "top1_timeline_id": cands[0] if cands else "unknown",
                "top1_gap": round(score_gap, 6),
            }
        )
    out = pd.DataFrame(records)
    out.to_csv(out_csv, index=False, encoding=DEFAULT_ENCODING)
    return out, sim_backend.backend


def grounding_closed_set_optional(
    candidate_csv: Path,
    out_json: Path,
    config: GroundingConfig,
    llm_closed_set_output_json: Optional[Path] = None,
) -> List[Dict]:
    cand = pd.read_csv(candidate_csv, encoding=DEFAULT_ENCODING)
    llm_map: Dict[str, Dict] = {}
    if llm_closed_set_output_json and llm_closed_set_output_json.exists():
        raw = json.loads(llm_closed_set_output_json.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            for x in raw:
                if isinstance(x, dict) and _safe_text(x.get("ueid")):
                    llm_map[_safe_text(x["ueid"])] = x

    def validate_item(item: Dict, closed_set: Sequence[str]) -> Dict:
        ueid = _safe_text(item.get("ueid"))
        tid = _safe_text(item.get("timeline_id")) or "unknown"
        reason = _safe_text(item.get("grounding_reason")) or "未提供理由"
        conf = max(0.0, min(1.0, _safe_float(item.get("grounding_confidence"), 0.0)))
        if tid != "unknown" and tid not in set(closed_set):
            return {
                "ueid": ueid,
                "timeline_id": "unknown",
                "grounding_confidence": min(conf, 0.3),
                "grounding_reason": f"闭集校验失败：候选外timeline_id被拒绝。原始理由: {reason}",
                "grounding_method": "llm_closed_set_rejected",
                "grounding_stage": "llm_override",
            }
        return {
            "ueid": ueid,
            "timeline_id": tid,
            "grounding_confidence": conf,
            "grounding_reason": reason,
            "grounding_method": "llm_closed_set" if llm_map else "llm_closed_set_unused",
            "grounding_stage": "llm_override",
        }

    results: List[Dict] = []
    progress = _iter_progress(cand.iterrows(), total=len(cand), desc="生成 grounding 结果")
    for _, row in progress:
        ueid = _safe_text(row["ueid"])
        cids = json.loads(_safe_text(row["candidate_timeline_ids"]) or "[]")
        cscores = json.loads(_safe_text(row["candidate_scores"]) or "[]")
        top1_score = _safe_float(row.get("top1_score", cscores[0] if cscores else 0.0), 0.0)
        top1_gap = _safe_float(row.get("top1_gap", 0.0), 0.0)
        top1_tid = _safe_text(row.get("top1_timeline_id", cids[0] if cids else "unknown")) or "unknown"

        if not cids:
            results.append(
                {
                    "ueid": ueid,
                    "timeline_id": "unknown",
                    "grounding_confidence": 0.0,
                    "grounding_reason": "无候选时间节点",
                    "grounding_method": "no_candidates",
                    "grounding_stage": "retrieval",
                }
            )
            continue

        calibrated_conf = max(0.0, min(1.0, top1_score + 0.5 * top1_gap))
        if top1_score >= config.accept_top1_if_score_ge:
            provisional = {
                "ueid": ueid,
                "timeline_id": top1_tid,
                "grounding_confidence": calibrated_conf,
                "grounding_reason": f"top1 综合分数较高（score={top1_score:.3f}, gap={top1_gap:.3f}）直接接受",
                "grounding_method": "retrieval_top1_accept",
                "grounding_stage": "retrieval",
            }
        elif top1_score <= config.unknown_if_top1_le:
            provisional = {
                "ueid": ueid,
                "timeline_id": top1_tid,
                "grounding_confidence": calibrated_conf,
                "grounding_reason": f"top1 分数较低（{top1_score:.3f}），暂记为低置信候选，后续交由序列先验修正",
                "grounding_method": "retrieval_low_confidence_candidate",
                "grounding_stage": "retrieval",
            }
        else:
            provisional = {
                "ueid": ueid,
                "timeline_id": top1_tid,
                "grounding_confidence": calibrated_conf,
                "grounding_reason": f"top1 候选保留（score={top1_score:.3f}, gap={top1_gap:.3f}），等待后续时序平滑",
                "grounding_method": "retrieval_top1_fallback",
                "grounding_stage": "retrieval",
            }

        results.append(validate_item(llm_map[ueid], cids) if ueid in llm_map else provisional)

    out_json.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return results


def _smooth_grounding_by_sequence(ev: pd.DataFrame, tl_map: Dict[str, int], cfg: GroundingConfig) -> pd.DataFrame:
    ev = ev.copy()
    ev["source_id"] = ev["source_id"].fillna("").astype(str)
    ev["narrative_order"] = pd.to_numeric(ev["narrative_order"], errors="coerce").fillna(0).astype(int)

    for _, block in ev.groupby("modality", sort=False):
        block = block.sort_values(["source_id", "narrative_order", "ueid"]).copy()
        anchor_orders = []
        for _, row in block.iterrows():
            tid = _safe_text(row.get("timeline_id"))
            conf = _safe_float(row.get("grounding_confidence"), 0.0)
            if tid in tl_map and conf >= cfg.min_conf_for_anchor:
                anchor_orders.append(tl_map[tid])
        if not anchor_orders:
            continue

        for idx, row in block.iterrows():
            current_tid = _safe_text(row.get("timeline_id"))
            current_conf = _safe_float(row.get("grounding_confidence"), 0.0)
            current_order = tl_map.get(current_tid, -1)
            source_id = _safe_text(row.get("source_id"))
            same_source = block[block["source_id"] == source_id]
            local_index = list(same_source.index).index(idx)

            expected_orders: List[float] = []
            if local_index > 0:
                prev_idx = same_source.index[local_index - 1]
                prev_tid = _safe_text(ev.at[prev_idx, "timeline_id"])
                prev_conf = _safe_float(ev.at[prev_idx, "grounding_confidence"], 0.0)
                prev_order = tl_map.get(prev_tid, -1)
                if prev_order >= 0 and prev_conf >= cfg.min_conf_for_anchor:
                    expected_orders.append(float(prev_order))
            if local_index < len(same_source.index) - 1:
                next_idx = same_source.index[local_index + 1]
                next_tid = _safe_text(ev.at[next_idx, "timeline_id"])
                next_conf = _safe_float(ev.at[next_idx, "grounding_confidence"], 0.0)
                next_order = tl_map.get(next_tid, -1)
                if next_order >= 0 and next_conf >= cfg.min_conf_for_anchor:
                    expected_orders.append(float(next_order))

            if not expected_orders:
                continue

            expected_order = float(sum(expected_orders) / len(expected_orders))
            if current_order < 0:
                nearest_tid = min(tl_map.keys(), key=lambda tid: abs(tl_map[tid] - expected_order))
                ev.at[idx, "timeline_id"] = nearest_tid
                ev.at[idx, "timeline_order"] = int(tl_map[nearest_tid])
                ev.at[idx, "grounding_confidence"] = round(current_conf + cfg.sequence_prior_strength, 6)
                ev.at[idx, "grounding_reason"] = _safe_text(row.get("grounding_reason")) + f"；序列先验补锚 -> {nearest_tid}"
                ev.at[idx, "grounding_method"] = _safe_text(row.get("grounding_method")) + "+sequence_prior_fill"
                continue

            deviation = abs(current_order - expected_order)
            if deviation > 6 and current_conf < (cfg.min_conf_for_anchor + 0.08):
                nearest_tid = min(tl_map.keys(), key=lambda tid: abs(tl_map[tid] - expected_order))
                ev.at[idx, "timeline_id"] = nearest_tid
                ev.at[idx, "timeline_order"] = int(tl_map[nearest_tid])
                ev.at[idx, "grounding_confidence"] = round(current_conf + cfg.sequence_prior_strength, 6)
                ev.at[idx, "grounding_reason"] = _safe_text(row.get("grounding_reason")) + f"；序列先验校正 {current_tid}->{nearest_tid}"
                ev.at[idx, "grounding_method"] = _safe_text(row.get("grounding_method")) + "+sequence_prior_correct"

    return ev


def merge_grounding_to_events(
    events_repr_csv: Path,
    timeline_nodes_csv: Path,
    grounding_json: Path,
    out_csv: Path,
    cfg: Optional[GroundingConfig] = None,
) -> pd.DataFrame:
    ev = pd.read_csv(events_repr_csv, encoding=DEFAULT_ENCODING)
    tl = pd.read_csv(timeline_nodes_csv, encoding=DEFAULT_ENCODING)
    gr = pd.DataFrame(json.loads(grounding_json.read_text(encoding="utf-8")))

    ev = ev.merge(gr, on="ueid", how="left")
    ev["timeline_id"] = ev["timeline_id"].fillna("unknown")
    tl_small = tl[["timeline_id", "timeline_order"]].copy()
    ev = ev.merge(tl_small, on="timeline_id", how="left")
    ev["timeline_order"] = ev["timeline_order"].fillna(-1).astype(int)
    ev["grounding_confidence"] = ev["grounding_confidence"].fillna(0.0)
    ev["grounding_reason"] = ev["grounding_reason"].fillna("无锚定结果")
    ev["grounding_method"] = ev["grounding_method"].fillna("unknown_method")

    if cfg is not None:
        tl_map = {str(r["timeline_id"]): int(r["timeline_order"]) for _, r in tl.iterrows()}
        ev = _smooth_grounding_by_sequence(ev, tl_map, cfg)

    ev.to_csv(out_csv, index=False, encoding=DEFAULT_ENCODING)
    return ev


# -----------------------------
# 阶段B：跨模态候选对齐
# -----------------------------
def _jaccard(a: Sequence[str], b: Sequence[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


def _loc_match(a_locs: Sequence[str], b_locs: Sequence[str]) -> float:
    sa, sb = set(a_locs), set(b_locs)
    if not sa or not sb:
        return 0.0
    if sa & sb:
        return 1.0
    for a in sa:
        for b in sb:
            if a in b or b in a:
                return 0.5
    return 0.0


def _time_match(order_a: int, order_b: int, window_size: int) -> float:
    if order_a < 0 or order_b < 0:
        return 0.0
    d = abs(order_a - order_b)
    if d == 0:
        return 1.0
    if d <= window_size:
        return max(0.0, 1.0 - d / (window_size + 1))
    return 0.0


def _alignment_type(score: float, cfg: AlignmentConfig) -> str:
    if score >= cfg.aligned_threshold:
        return "aligned"
    if score >= cfg.related_threshold:
        return "related"
    return "unmatched"


def build_cross_modal_alignment(
    grounded_events_csv: Path,
    out_csv: Path,
    weights: AlignWeights,
    cfg: AlignmentConfig,
) -> pd.DataFrame:
    df = pd.read_csv(grounded_events_csv, encoding=DEFAULT_ENCODING)
    if "event_repr_text" not in df.columns:
        raise ValueError("grounded事件表缺少 event_repr_text")

    text_df = df[df["modality"] == "text"].copy()
    video_df = df[df["modality"] == "video"].copy()
    if text_df.empty or video_df.empty:
        out = pd.DataFrame([])
        out.to_csv(out_csv, index=False, encoding=DEFAULT_ENCODING)
        return out

    sim_backend = TextSimilarityBackend()
    corpus = df["event_repr_text"].fillna("").astype(str).tolist()
    if sim_backend.backend == "tfidf":
        sim_backend.fit(corpus)
    all_vecs = sim_backend.encode(corpus)
    ueid_to_idx = {u: i for i, u in enumerate(df["ueid"].tolist())}

    rows: List[Dict] = []
    progress = _iter_progress(text_df.iterrows(), total=len(text_df), desc="构建跨模态候选对齐")
    for _, src in progress:
        src_order = _safe_int(src.get("timeline_order"), -1)
        src_conf = _safe_float(src.get("grounding_confidence"), 0.0)
        src_chars = _split_norm_items(_safe_text(src.get("characters")))
        src_locs = _split_norm_items(_safe_text(src.get("location")))
        src_ueid = str(src["ueid"])
        src_idx = ueid_to_idx[src_ueid]

        pool_df = video_df
        if cfg.require_anchor_for_alignment and src_order >= 0:
            pool = pool_df[
                pool_df["timeline_order"].apply(
                    lambda x: _safe_int(x, -1) >= 0 and abs(_safe_int(x, -1) - src_order) <= cfg.time_window
                )
            ]
            if pool.empty:
                pool = pool_df
        else:
            pool = pool_df

        if pool.empty:
            continue

        pool_ueids = pool["ueid"].astype(str).tolist()
        pool_idxs = [ueid_to_idx[u] for u in pool_ueids]
        src_vec = all_vecs[src_idx]
        pool_vecs = all_vecs[pool_idxs]
        sem_scores = cosine_similarity(src_vec, pool_vecs).reshape(-1)

        local: List[Dict] = []
        pool_records = pool.to_dict(orient="records")
        for j, tgt in enumerate(pool_records):
            tgt_ueid = str(tgt["ueid"])
            tgt_chars = _split_norm_items(_safe_text(tgt.get("characters")))
            tgt_locs = _split_norm_items(_safe_text(tgt.get("location")))
            tgt_conf = _safe_float(tgt.get("grounding_confidence"), 0.0)

            s_sem = float(sem_scores[j])
            s_char = _jaccard(src_chars, tgt_chars)
            s_loc = _loc_match(src_locs, tgt_locs)
            s_time = _time_match(_safe_int(src.get("timeline_order"), -1), _safe_int(tgt.get("timeline_order"), -1), cfg.time_window)

            score = (
                weights.alpha_sem * s_sem
                + weights.beta_char * s_char
                + weights.gamma_loc * s_loc
                + weights.delta_time * s_time
                + cfg.source_confidence_weight * src_conf
                + cfg.target_confidence_weight * tgt_conf
            )

            if cfg.require_anchor_for_alignment and (src_conf < 0.10 or tgt_conf < 0.10):
                score -= cfg.weak_anchor_penalty
            if cfg.mismatch_time_penalty > 0 and _safe_int(src.get("timeline_order"), -1) >= 0 and _safe_int(tgt.get("timeline_order"), -1) >= 0 and s_time == 0.0:
                score -= cfg.mismatch_time_penalty

            shared_chars = sorted(list(set(src_chars) & set(tgt_chars)))
            shared_locs = sorted(list(set(src_locs) & set(tgt_locs)))

            local.append(
                {
                    "source_ueid": src_ueid,
                    "target_ueid": tgt_ueid,
                    "source_modality": "text",
                    "target_modality": "video",
                    "alignment_score": round(float(score), 6),
                    "sim_sem": round(float(s_sem), 6),
                    "overlap_char": round(float(s_char), 6),
                    "match_loc": round(float(s_loc), 6),
                    "match_time": round(float(s_time), 6),
                    "source_grounding_confidence": round(float(src_conf), 6),
                    "target_grounding_confidence": round(float(tgt_conf), 6),
                    "alignment_type": _alignment_type(float(score), cfg),
                    "shared_characters": "、".join(shared_chars),
                    "shared_location": "、".join(shared_locs),
                    "source_timeline_id": _safe_text(src.get("timeline_id", "unknown")) or "unknown",
                    "target_timeline_id": _safe_text(tgt.get("timeline_id", "unknown")) or "unknown",
                    "source_timeline_order": _safe_int(src.get("timeline_order"), -1),
                    "target_timeline_order": _safe_int(tgt.get("timeline_order"), -1),
                    "semantic_backend": sim_backend.backend,
                }
            )

        local.sort(key=lambda x: x["alignment_score"], reverse=True)
        local = [x for x in local if x["alignment_type"] != "unmatched"][: int(cfg.top_k_per_source)]
        rows.extend(local)

    out = pd.DataFrame(rows)
    out = out.sort_values(["alignment_score", "source_ueid"], ascending=[False, True]).reset_index(drop=True) if not out.empty else out
    out.to_csv(out_csv, index=False, encoding=DEFAULT_ENCODING)
    return out


# -----------------------------
# LLM 精排
# -----------------------------
def _build_alignment_llm_prompt(source_event: Dict, candidates: List[Dict]) -> str:
    payload = {
        "task": "strict_cross_modal_event_pairing",
        "instruction": [
            "你要判断一个文本事件与若干视频事件候选是否描述同一事件。",
            "判断标准优先级：核心动作 > 参与人物 > 主要地点 > 因果上下文。",
            "如果只是同人物、同场景、同话题，但不是同一件事，应输出 related 或 unmatched，不要误判为 aligned。",
            "best_target_ueid 只能从给定 candidates 中选择，或为 null。",
            "若没有任何候选与 source_event 构成真正一对一匹配，请输出 unmatched。",
            "请只输出合法 JSON，不要输出解释性前后缀。",
        ],
        "source_event": source_event,
        "candidates": candidates,
        "output_schema": {
            "source_ueid": source_event.get("source_ueid"),
            "best_target_ueid": "候选中的 target_ueid 或 null",
            "decision": "aligned | related | unmatched",
            "confidence": "0 到 1 的浮点数",
            "reason": "一句中文简洁理由",
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _extract_json_object(text: str) -> Dict:
    raw = _safe_text(text)
    if not raw:
        return {}
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?", "", raw, flags=re.IGNORECASE).strip()
        raw = re.sub(r"```$", "", raw).strip()
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        pass
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return {}
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _call_dashscope_json(prompt: str, cfg: AlignmentLLMRerankConfig) -> Dict:
    api_key = cfg.api_key_literal or os.getenv(cfg.api_key_env, "")
    if not api_key:
        raise ValueError(f"未检测到 {cfg.api_key_env}，且未提供显式 API Key，无法执行 LLM 二阶段精排")

    try:
        import dashscope  # type: ignore
        from dashscope import MultiModalConversation  # type: ignore
    except Exception as e:
        raise ImportError(f"未安装或无法导入 dashscope: {e}")

    dashscope.base_http_api_url = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/api/v1")

    last_err: Optional[Exception] = None
    for attempt in range(cfg.max_retries):
        try:
            response = MultiModalConversation.call(
                api_key=api_key,
                model=cfg.model_name,
                timeout=cfg.timeout,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
            )
            if getattr(response, "status_code", None) not in (None, 200):
                raise RuntimeError(
                    f"DashScope 调用失败: status_code={getattr(response, 'status_code', None)}, message={getattr(response, 'message', None)}"
                )
            content = response.output.choices[0].message.content
            if isinstance(content, list):
                text = "\n".join(item.get("text", "") if isinstance(item, dict) else str(item) for item in content).strip()
            else:
                text = str(content).strip()
            obj = _extract_json_object(text)
            if obj:
                return obj
            raise ValueError(f"LLM 未返回可解析 JSON: {text[:300]}")
        except Exception as e:
            last_err = e
            if attempt < cfg.max_retries - 1:
                time.sleep(min(8, 1.5 * (2**attempt)))
            else:
                raise
    raise RuntimeError(f"LLM 调用失败: {last_err}")


def rerank_ambiguous_alignment_with_llm(
    grounded_events_csv: Path,
    alignment_csv: Path,
    out_csv: Path,
    audit_json: Path,
    cfg: AlignmentLLMRerankConfig,
    align_cfg: AlignmentConfig,
) -> pd.DataFrame:
    al = pd.read_csv(alignment_csv, encoding=DEFAULT_ENCODING)
    if al.empty or not cfg.enabled:
        al.to_csv(out_csv, index=False, encoding=DEFAULT_ENCODING)
        audit_json.write_text(json.dumps({"summary": {"enabled": False}, "items": []}, ensure_ascii=False, indent=2), encoding="utf-8")
        return al

    ev = pd.read_csv(grounded_events_csv, encoding=DEFAULT_ENCODING)
    ev_map = ev.set_index("ueid").to_dict(orient="index")
    rerank_meta: List[Dict] = []

    source_blocks = []
    for src_ueid, block in al.groupby("source_ueid", sort=False):
        block = block.sort_values(["alignment_score", "match_time", "sim_sem"], ascending=False).copy()
        source_blocks.append((str(src_ueid), block))

    stats = {
        "total_sources": len(source_blocks),
        "eligible_sources": 0,
        "llm_called": 0,
        "llm_errors": 0,
        "forced_sources": 0,
        "skipped_rule_filter": 0,
        "skipped_quota": 0,
    }

    forced_source_set = {src for src, _ in source_blocks[: max(0, int(cfg.force_first_n))]}

    if cfg.verbose:
        _log_stage(
            f"LLM 精排启动：共有 {len(source_blocks)} 个文本事件需要检查，最多调用 {cfg.max_items} 次，每次超时 {cfg.timeout} 秒"
        )

    progress = _iter_progress(source_blocks, total=len(source_blocks), desc="LLM 精排")
    for idx, (src_ueid, block) in enumerate(progress, start=1):
        if cfg.verbose and (idx == 1 or idx % 10 == 0 or idx == len(source_blocks)):
            print(
                f"[LLM-RERANK] 进度 {idx}/{len(source_blocks)} | 已送审 {stats['eligible_sources']} | 已调用 {stats['llm_called']} | 错误 {stats['llm_errors']}",
                flush=True,
            )
        top1 = _safe_float(block.iloc[0].get("alignment_score"), 0.0) if len(block) >= 1 else 0.0
        top2 = _safe_float(block.iloc[1].get("alignment_score"), 0.0) if len(block) >= 2 else 0.0
        gap = top1 - top2 if len(block) >= 2 else top1
        top1_type = _safe_text(block.iloc[0].get("alignment_type")) if len(block) >= 1 else ""
        forced = src_ueid in forced_source_set

        in_score_band = cfg.min_score_for_review <= top1 <= cfg.max_score_for_review
        small_gap = gap <= cfg.top_gap_for_review
        type_ok = (cfg.review_aligned_too and top1_type == "aligned") or (not cfg.review_related_only and top1_type in {"aligned", "related"}) or (cfg.review_related_only and top1_type == "related")
        needs_review = forced or (type_ok and (in_score_band or small_gap or top1_type == "related"))

        if forced:
            stats["forced_sources"] += 1
        if not needs_review:
            stats["skipped_rule_filter"] += 1
            rerank_meta.append({
                "source_ueid": src_ueid,
                "llm_rerank_applied": False,
                "skip_reason": "rule_filter",
                "top1_score": round(top1, 6),
                "top2_score": round(top2, 6),
                "top_gap": round(gap, 6),
            })
            continue
        if stats["eligible_sources"] >= cfg.max_items:
            stats["skipped_quota"] += 1
            rerank_meta.append({
                "source_ueid": src_ueid,
                "llm_rerank_applied": False,
                "skip_reason": "quota_skip",
            })
            continue

        stats["eligible_sources"] += 1
        source = ev_map.get(str(src_ueid), {})
        source_payload = {
            "source_ueid": str(src_ueid),
            "action": _safe_text(source.get("action")),
            "event_summary": _safe_text(source.get("event_summary")),
            "semantic_core": _safe_text(source.get("semantic_core")),
            "characters": _safe_text(source.get("characters")),
            "location": _safe_text(source.get("location")),
            "timeline_id": _safe_text(source.get("timeline_id")),
            "timeline_order": _safe_int(source.get("timeline_order"), -1),
        }

        cand_payloads: List[Dict] = []
        trimmed = block.head(cfg.max_candidates_per_source)
        for _, row in trimmed.iterrows():
            tgt_ueid = str(row["target_ueid"])
            tgt = ev_map.get(tgt_ueid, {})
            cand_payloads.append(
                {
                    "target_ueid": tgt_ueid,
                    "alignment_score": round(_safe_float(row.get("alignment_score"), 0.0), 6),
                    "alignment_type": _safe_text(row.get("alignment_type")),
                    "sim_sem": round(_safe_float(row.get("sim_sem"), 0.0), 6),
                    "overlap_char": round(_safe_float(row.get("overlap_char"), 0.0), 6),
                    "match_loc": round(_safe_float(row.get("match_loc"), 0.0), 6),
                    "match_time": round(_safe_float(row.get("match_time"), 0.0), 6),
                    "action": _safe_text(tgt.get("action")),
                    "event_summary": _safe_text(tgt.get("event_summary")),
                    "semantic_core": _safe_text(tgt.get("semantic_core")),
                    "characters": _safe_text(tgt.get("characters")),
                    "location": _safe_text(tgt.get("location")),
                    "timeline_id": _safe_text(tgt.get("timeline_id")),
                    "timeline_order": _safe_int(tgt.get("timeline_order"), -1),
                }
            )

        prompt = _build_alignment_llm_prompt(source_payload, cand_payloads)
        if cfg.verbose:
            print(
                f"[LLM-RERANK] 正在调用 LLM: source={src_ueid} | candidates={len(cand_payloads)} | top1={top1:.4f} | gap={gap:.4f}",
                flush=True,
            )
        try:
            llm_obj = _call_dashscope_json(prompt, cfg)
            stats["llm_called"] += 1
        except Exception as e:
            stats["llm_errors"] += 1
            if cfg.verbose:
                print(f"[LLM-RERANK] 调用失败 source={src_ueid}: {_safe_text(e)}", flush=True)
            rerank_meta.append(
                {
                    "source_ueid": str(src_ueid),
                    "llm_rerank_applied": False,
                    "skip_reason": "llm_error",
                    "llm_reason": _safe_text(e),
                }
            )
            continue

        best_target = _safe_text(llm_obj.get("best_target_ueid"))
        decision = _safe_text(llm_obj.get("decision")).lower()
        reason = _safe_text(llm_obj.get("reason"))
        conf = max(0.0, min(1.0, _safe_float(llm_obj.get("confidence"), 0.0)))

        valid_targets = {c["target_ueid"] for c in cand_payloads}
        if best_target and best_target not in valid_targets:
            best_target = ""
            decision = "unmatched"
            reason = f"LLM 选择了候选外目标，已拒绝。{reason}"

        mask = al["source_ueid"].astype(str) == str(src_ueid)
        al.loc[mask, "llm_rerank_applied"] = True
        al.loc[mask, "llm_decision"] = decision
        al.loc[mask, "llm_reason"] = reason
        al.loc[mask, "llm_confidence"] = round(conf, 6)

        if not best_target or decision == "unmatched":
            if not cfg.fallback_to_original:
                al = al.loc[~mask].copy()
            rerank_meta.append(
                {
                    "source_ueid": str(src_ueid),
                    "llm_rerank_applied": True,
                    "llm_decision": decision or "unmatched",
                    "llm_best_target_ueid": best_target or None,
                    "llm_reason": reason,
                    "llm_confidence": round(conf, 6),
                }
            )
            continue

        chosen_mask = mask & (al["target_ueid"].astype(str) == best_target)
        if decision == "aligned" and conf >= cfg.accept_if_aligned_conf_ge:
            al.loc[chosen_mask, "alignment_score"] = np.maximum(al.loc[chosen_mask, "alignment_score"].astype(float), conf)
            al.loc[chosen_mask, "alignment_type"] = "aligned"
        elif decision == "related":
            al.loc[chosen_mask, "alignment_type"] = "related"
        elif decision not in {"aligned", "related", "unmatched"}:
            al.loc[chosen_mask, "alignment_type"] = "related"

        al = al.loc[(~mask) | chosen_mask].copy()
        rerank_meta.append(
            {
                "source_ueid": str(src_ueid),
                "llm_rerank_applied": True,
                "llm_decision": decision,
                "llm_best_target_ueid": best_target,
                "llm_reason": reason,
                "llm_confidence": round(conf, 6),
            }
        )

    if "llm_rerank_applied" not in al.columns:
        al["llm_rerank_applied"] = False
    if "llm_decision" not in al.columns:
        al["llm_decision"] = ""
    if "llm_reason" not in al.columns:
        al["llm_reason"] = ""
    if "llm_confidence" not in al.columns:
        al["llm_confidence"] = 0.0

    al = al.sort_values(["alignment_score", "source_ueid"], ascending=[False, True]).reset_index(drop=True)
    al.to_csv(out_csv, index=False, encoding=DEFAULT_ENCODING)
    audit_json.write_text(json.dumps({"summary": stats, "items": rerank_meta}, ensure_ascii=False, indent=2), encoding="utf-8")
    return al


# -----------------------------
# 阶段C：严格一对一最终配对
# -----------------------------
def _build_event_name_for_pair(text_row: Dict, video_row: Dict) -> str:
    text_name = _safe_text(text_row.get("action")) or _safe_text(text_row.get("event_summary"))
    video_name = _safe_text(video_row.get("action")) or _safe_text(video_row.get("event_summary"))
    return _normalize_event_name(text_name or video_name, _safe_text(text_row.get("event_summary")), _safe_text(text_row.get("action")))


def _build_side_payload(row: Dict, modality: str) -> Dict:
    source_title = _safe_text(row.get("source_title"))
    source_path = _safe_text(row.get("source_path"))
    payload = {
        "ueid": _safe_text(row.get("ueid")),
        "source_path": source_path,
    }
    if modality == "text":
        payload.update(
            {
                "chapter_id": _safe_text(row.get("source_id")),
                "chapter_title": source_title,
                "source_text": _safe_text(row.get("source_text")),
            }
        )
    else:
        payload.update(
            {
                "episode_id": _safe_text(row.get("source_id")),
                "episode_title": source_title,
                "video_source_path": source_path,
            }
        )
    return payload


def build_strict_one_to_one_pairs(
    grounded_events_csv: Path,
    alignment_csv: Path,
    out_json: Path,
    align_cfg: AlignmentConfig,
    llm_cfg: Optional[AlignmentLLMRerankConfig] = None,
) -> List[Dict]:
    ev = pd.read_csv(grounded_events_csv, encoding=DEFAULT_ENCODING)
    al = pd.read_csv(alignment_csv, encoding=DEFAULT_ENCODING)

    if al.empty:
        out_json.write_text("[]", encoding="utf-8")
        return []

    ev_map = ev.set_index("ueid").to_dict(orient="index")

    work = al.copy()
    work = work[work["alignment_type"].astype(str) == "aligned"].copy()
    if work.empty:
        out_json.write_text("[]", encoding="utf-8")
        return []

    if "llm_decision" in work.columns:
        work = work[~work["llm_decision"].astype(str).eq("unmatched")].copy()
    if llm_cfg is not None and llm_cfg.enabled and "llm_rerank_applied" in work.columns and "llm_confidence" in work.columns:
        llm_mask = work["llm_rerank_applied"].fillna(False).astype(bool)
        work = work[(~llm_mask) | (work["llm_confidence"].astype(float) >= llm_cfg.min_pair_confidence)].copy()
        if work.empty:
            out_json.write_text("[]", encoding="utf-8")
            return []

    work = work.sort_values(
        ["alignment_score", "sim_sem", "overlap_char", "match_loc", "match_time"],
        ascending=[False, False, False, False, False],
    ).reset_index(drop=True)

    used_text = set()
    used_video = set()
    pairs: List[Dict] = []

    progress = _iter_progress(work.iterrows(), total=len(work), desc="生成严格一对一结果")
    for _, row in progress:
        text_ueid = _safe_text(row.get("source_ueid"))
        video_ueid = _safe_text(row.get("target_ueid"))
        if not text_ueid or not video_ueid:
            continue
        if text_ueid in used_text or video_ueid in used_video:
            continue

        text_row = ev_map.get(text_ueid, {})
        video_row = ev_map.get(video_ueid, {})
        if not text_row or not video_row:
            continue
        if _safe_text(text_row.get("modality")) != "text":
            continue
        if _safe_text(video_row.get("modality")) != "video":
            continue

        used_text.add(text_ueid)
        used_video.add(video_ueid)

        shared_chars = _dedup_keep_order(
            sorted(
                list(
                    set(_split_norm_items(_safe_text(text_row.get("characters"))))
                    & set(_split_norm_items(_safe_text(video_row.get("characters"))))
                )
            )
        )
        shared_locs = _dedup_keep_order(
            sorted(
                list(
                    set(_split_norm_items(_safe_text(text_row.get("location"))))
                    & set(_split_norm_items(_safe_text(video_row.get("location"))))
                )
            )
        )

        timeline_id = _safe_text(text_row.get("timeline_id")) or _safe_text(video_row.get("timeline_id")) or "unknown"
        pair_id = f"PAIR_{len(pairs) + 1:04d}"
        pair_item = {
            "pair_id": pair_id,
            "event_name": _build_event_name_for_pair(text_row, video_row),
            "alignment_score": round(_safe_float(row.get("alignment_score"), 0.0), 6),
            "alignment_type": "aligned",
            "text": _build_side_payload({**text_row, "ueid": text_ueid}, modality="text"),
            "video": _build_side_payload({**video_row, "ueid": video_ueid}, modality="video"),
            "shared": {
                "characters": shared_chars,
                "locations": shared_locs,
                "timeline_id": timeline_id or "unknown",
            },
        }
        pairs.append(pair_item)

    out_json.write_text(json.dumps(pairs, ensure_ascii=False, indent=2), encoding="utf-8")
    return pairs


# -----------------------------
# 兼容保留：事件簇 / 全局时间线
# -----------------------------
class UnionFind:
    def __init__(self) -> None:
        self.parent: Dict[str, str] = {}
        self.rank: Dict[str, int] = {}

    def find(self, x: str) -> str:
        if x not in self.parent:
            self.parent[x] = x
            self.rank[x] = 0
            return x
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            self.parent[ra] = rb
        elif self.rank[ra] > self.rank[rb]:
            self.parent[rb] = ra
        else:
            self.parent[rb] = ra
            self.rank[ra] += 1


def build_event_clusters(
    grounded_events_csv: Path,
    alignment_csv: Path,
    out_clusters_json: Path,
    out_members_csv: Path,
    tl_nodes_csv: Path,
    cfg: ClusterConfig,
) -> Tuple[List[Dict], pd.DataFrame]:
    ev = pd.read_csv(grounded_events_csv, encoding=DEFAULT_ENCODING)
    al = pd.read_csv(alignment_csv, encoding=DEFAULT_ENCODING)
    tl = pd.read_csv(tl_nodes_csv, encoding=DEFAULT_ENCODING)

    ev_map = ev.set_index("ueid").to_dict(orient="index")
    uf = UnionFind()
    if not al.empty:
        for _, r in al.iterrows():
            if _safe_text(r.get("alignment_type")) != cfg.use_edge_type:
                continue
            if _safe_float(r.get("alignment_score"), 0.0) < cfg.min_edge_score:
                continue
            a = _safe_text(r.get("source_ueid"))
            b = _safe_text(r.get("target_ueid"))
            if a and b:
                uf.union(a, b)

    for u in ev["ueid"].tolist():
        uf.find(str(u))

    comp: Dict[str, List[str]] = {}
    for u in ev["ueid"].tolist():
        comp.setdefault(uf.find(str(u)), []).append(str(u))

    tl_map = tl.set_index("timeline_id").to_dict(orient="index")
    tl_order_map = {k: _safe_int(v.get("timeline_order"), -1) for k, v in tl_map.items()}

    def cluster_timeline_vote(members: List[str]) -> Tuple[str, int, Dict[str, int]]:
        votes: Dict[str, int] = {}
        for u in members:
            tid = _safe_text(ev_map.get(u, {}).get("timeline_id", "unknown")) or "unknown"
            votes[tid] = votes.get(tid, 0) + 1
        votes_no_unknown = {k: v for k, v in votes.items() if k != "unknown"}
        if not votes_no_unknown:
            return "unknown", -1, votes
        chosen = sorted(votes_no_unknown.items(), key=lambda kv: (-kv[1], tl_order_map.get(kv[0], 10**9)))[0][0]
        return chosen, tl_order_map.get(chosen, -1), votes

    clusters: List[Dict] = []
    member_rows: List[Dict] = []
    roots_sorted = sorted(comp.keys(), key=lambda r: (-len(comp[r]), r))

    for idx, root in enumerate(roots_sorted, start=1):
        members = sorted(comp[root])
        cid = f"EC{idx:04d}"
        text_members = [m for m in members if _safe_text(ev_map.get(m, {}).get("modality")) == "text"]
        video_members = [m for m in members if _safe_text(ev_map.get(m, {}).get("modality")) == "video"]

        rep_ueid = text_members[0] if text_members else members[0]
        rep = ev_map.get(rep_ueid, {})
        voted_tid, voted_order, vote_detail = cluster_timeline_vote(members)
        tl_meta = tl_map.get(voted_tid, {})

        clusters.append(
            {
                "cluster_id": cid,
                "member_ueids": members,
                "text_event_count": len(text_members),
                "video_event_count": len(video_members),
                "representative_ueid": rep_ueid,
                "representative_action": _safe_text(rep.get("action")),
                "representative_summary": _safe_text(rep.get("event_summary")),
                "timeline_id": voted_tid,
                "timeline_order": voted_order,
                "timeline_vote_detail": vote_detail,
                "红楼年份": _safe_text(tl_meta.get("红楼年份")),
                "季节月份": _safe_text(tl_meta.get("季节月份")),
                "event_name": _safe_text(tl_meta.get("事件名称")),
            }
        )

        for u in members:
            e = ev_map.get(u, {})
            member_rows.append(
                {
                    "cluster_id": cid,
                    "ueid": u,
                    "modality": _safe_text(e.get("modality")),
                    "timeline_id": _safe_text(e.get("timeline_id", "unknown")) or "unknown",
                    "timeline_order": _safe_int(e.get("timeline_order"), -1),
                    "action": _safe_text(e.get("action")),
                    "event_summary": _safe_text(e.get("event_summary")),
                }
            )

    out_members = pd.DataFrame(member_rows)
    out_members.to_csv(out_members_csv, index=False, encoding=DEFAULT_ENCODING)
    out_clusters_json.write_text(json.dumps(clusters, ensure_ascii=False, indent=2), encoding="utf-8")
    return clusters, out_members


def build_global_event_timeline(
    clusters_json: Path,
    tl_nodes_csv: Path,
    grounded_events_csv: Path,
    out_json: Path,
) -> List[Dict]:
    clusters = json.loads(clusters_json.read_text(encoding="utf-8"))
    tl = pd.read_csv(tl_nodes_csv, encoding=DEFAULT_ENCODING)
    ev = pd.read_csv(grounded_events_csv, encoding=DEFAULT_ENCODING)

    tl_map = tl.set_index("timeline_id").to_dict(orient="index")
    ev_map = ev.set_index("ueid").to_dict(orient="index")

    timeline_items: List[Dict] = []
    for c in clusters:
        cid = c["cluster_id"]
        tid = _safe_text(c.get("timeline_id", "unknown")) or "unknown"
        order = _safe_int(c.get("timeline_order"), -1)
        tl_meta = tl_map.get(tid, {})
        members = c.get("member_ueids", []) or []
        text_events = [ev_map[m] for m in members if _safe_text(ev_map.get(m, {}).get("modality")) == "text"]
        video_events = [ev_map[m] for m in members if _safe_text(ev_map.get(m, {}).get("modality")) == "video"]

        timeline_items.append(
            {
                "cluster_id": cid,
                "timeline_id": tid,
                "timeline_order": order,
                "红楼年份": _safe_text(tl_meta.get("红楼年份")),
                "季节月份": _safe_text(tl_meta.get("季节月份")),
                "event_name": _safe_text(tl_meta.get("事件名称")),
                "representative_action": _safe_text(c.get("representative_action")),
                "representative_summary": _safe_text(c.get("representative_summary")),
                "timeline_vote_detail": c.get("timeline_vote_detail", {}),
                "text_events": text_events,
                "video_events": video_events,
            }
        )

    timeline_items.sort(key=lambda x: (10**9 if _safe_int(x.get("timeline_order"), -1) < 0 else _safe_int(x.get("timeline_order"), -1), str(x.get("cluster_id"))))
    out_json.write_text(json.dumps(timeline_items, ensure_ascii=False, indent=2), encoding="utf-8")
    return timeline_items


# -----------------------------
# 一键流水线
# -----------------------------
@dataclass
class Feature2Outputs:
    timeline_nodes_csv: Path
    unified_events_repr_csv: Path
    timeline_candidate_recall_csv: Path
    timeline_grounding_results_json: Path
    unified_events_grounded_csv: Path
    cross_modal_event_alignment_csv: Path
    alignment_llm_rerank_audit_json: Path
    paired_alignments_json: Path
    event_cluster_members_csv: Path
    event_clusters_json: Path
    global_event_timeline_json: Path
    run_config_json: Path


def run_feature2_pipeline(
    unified_events_csv: Path,
    timeline_csv: Path,
    output_dir: Path,
    grounding_cfg: GroundingConfig,
    align_cfg: AlignmentConfig,
    weights: AlignWeights,
    cluster_cfg: ClusterConfig,
    llm_closed_set_output_json: Optional[Path] = None,
    alignment_llm_rerank_cfg: Optional[AlignmentLLMRerankConfig] = None,
    fragment_filter_cfg: Optional[FragmentFilterConfig] = None,
) -> Feature2Outputs:
    _ensure_dir(output_dir)

    p_tl = output_dir / "timeline_nodes.csv"
    p_repr = output_dir / "unified_events_repr.csv"
    p_cand = output_dir / "timeline_candidate_recall.csv"
    p_ground = output_dir / "timeline_grounding_results.json"
    p_grounded = output_dir / "unified_events_grounded.csv"
    p_align = output_dir / "cross_modal_event_alignment.csv"
    p_align_rerank_audit = output_dir / "alignment_llm_rerank_audit.json"
    p_pairs = output_dir / "paired_alignments.json"
    p_members = output_dir / "event_cluster_members.csv"
    p_clusters = output_dir / "event_clusters.json"
    p_global = output_dir / "global_event_timeline.json"
    p_cfg = output_dir / "run_config.json"

    _log_stage("阶段 1/8：预处理时间线")
    preprocess_timeline(timeline_csv, p_tl)

    _log_stage("阶段 2/8：构建事件表示并过滤碎片事件")
    build_event_repr(unified_events_csv, p_repr, cfg=fragment_filter_cfg)

    _log_stage("阶段 3/8：召回时间线候选")
    timeline_candidate_recall(p_repr, p_tl, p_cand, top_k=grounding_cfg.top_k_candidates)

    _log_stage("阶段 4/8：生成 grounding 结果")
    grounding_closed_set_optional(
        candidate_csv=p_cand,
        out_json=p_ground,
        config=grounding_cfg,
        llm_closed_set_output_json=llm_closed_set_output_json,
    )

    _log_stage("阶段 5/8：合并 grounding 到统一事件")
    merge_grounding_to_events(p_repr, p_tl, p_ground, p_grounded, cfg=grounding_cfg)

    _log_stage("阶段 6/8：构建跨模态候选对齐")
    build_cross_modal_alignment(p_grounded, p_align, weights=weights, cfg=align_cfg)

    rerank_cfg = alignment_llm_rerank_cfg or AlignmentLLMRerankConfig(enabled=False)
    _log_stage("阶段 7/8：LLM 精排候选并生成严格一对一配对")
    rerank_ambiguous_alignment_with_llm(
        grounded_events_csv=p_grounded,
        alignment_csv=p_align,
        out_csv=p_align,
        audit_json=p_align_rerank_audit,
        cfg=rerank_cfg,
        align_cfg=align_cfg,
    )
    build_strict_one_to_one_pairs(
        grounded_events_csv=p_grounded,
        alignment_csv=p_align,
        out_json=p_pairs,
        align_cfg=align_cfg,
        llm_cfg=rerank_cfg,
    )

    _log_stage("阶段 8/8：输出兼容簇结果与全局时间线")
    build_event_clusters(
        grounded_events_csv=p_grounded,
        alignment_csv=p_align,
        out_clusters_json=p_clusters,
        out_members_csv=p_members,
        tl_nodes_csv=p_tl,
        cfg=cluster_cfg,
    )
    build_global_event_timeline(
        clusters_json=p_clusters,
        tl_nodes_csv=p_tl,
        grounded_events_csv=p_grounded,
        out_json=p_global,
    )

    p_cfg.write_text(
        json.dumps(
            {
                "grounding_config": asdict(grounding_cfg),
                "alignment_config": asdict(align_cfg),
                "align_weights": asdict(weights),
                "cluster_config": asdict(cluster_cfg),
                "alignment_llm_rerank_config": asdict(rerank_cfg),
                "fragment_filter_config": asdict(fragment_filter_cfg) if fragment_filter_cfg else None,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return Feature2Outputs(
        timeline_nodes_csv=p_tl,
        unified_events_repr_csv=p_repr,
        timeline_candidate_recall_csv=p_cand,
        timeline_grounding_results_json=p_ground,
        unified_events_grounded_csv=p_grounded,
        cross_modal_event_alignment_csv=p_align,
        alignment_llm_rerank_audit_json=p_align_rerank_audit,
        paired_alignments_json=p_pairs,
        event_cluster_members_csv=p_members,
        event_clusters_json=p_clusters,
        global_event_timeline_json=p_global,
        run_config_json=p_cfg,
    )
