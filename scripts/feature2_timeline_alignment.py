import argparse
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


# -----------------------------------------------------------------------------
# 功能2：基于外部参考时间线约束的两阶段跨模态事件关联算法
# 核心思想：
#   阶段A：先做“事件 -> 时间线”锚定（Event-to-Timeline Grounding）
#   阶段B：再做“时间约束下的视频-文本事件对齐”（Cross-modal Alignment）
#   阶段C：最后做“事件链展开”（Timeline Expansion）
# -----------------------------------------------------------------------------


DEFAULT_ENCODING = "utf-8-sig"


@dataclass
class AlignWeights:
    alpha_sem: float = 0.55
    beta_char: float = 0.25
    gamma_loc: float = 0.10
    delta_time: float = 0.10


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
    out = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out


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


def build_event_repr(unified_csv: Path, out_csv: Path) -> pd.DataFrame:
    df = pd.read_csv(unified_csv, encoding=DEFAULT_ENCODING)
    fields = [
        "ueid",
        "modality",
        "action",
        "event_summary",
        "semantic_core",
        "keywords",
        "characters",
        "location",
    ]
    miss = [c for c in fields if c not in df.columns]
    if miss:
        raise ValueError(f"统一事件表缺少字段: {miss}")

    def compose_repr(row: pd.Series) -> str:
        action = _safe_text(row.get("action"))
        summary = _safe_text(row.get("event_summary"))
        semantic_core = _safe_text(row.get("semantic_core"))
        chars = _dedup_keep_order(_split_norm_items(_safe_text(row.get("characters"))))
        locs = _dedup_keep_order(_split_norm_items(_safe_text(row.get("location"))))
        kws = _dedup_keep_order(_split_norm_items(_safe_text(row.get("keywords"))))

        # 非机械拼接：优先动作+核心语义，再补人物地点与关键词，限制长度并去重
        chunks = []
        if action:
            chunks.append(f"动作:{action}")
        if summary:
            chunks.append(f"摘要:{summary}")
        if semantic_core and semantic_core not in summary:
            chunks.append(f"语义核:{semantic_core}")
        if chars:
            chunks.append(f"人物:{'、'.join(chars[:8])}")
        if locs:
            chunks.append(f"地点:{'、'.join(locs[:4])}")
        if kws:
            chunks.append(f"关键词:{'、'.join(kws[:10])}")
        text = "；".join(chunks)
        return text[:420]

    df["event_repr_text"] = df.apply(compose_repr, axis=1)
    df.to_csv(out_csv, index=False, encoding=DEFAULT_ENCODING)
    return df


class TextSimilarityBackend:
    """优先使用 sentence-transformers，不可用时回退 TF-IDF。"""

    def __init__(self):
        self.backend = "tfidf"
        self.model = None
        self.vectorizer = None

        force_tfidf = os.environ.get("FORCE_TFIDF", "0") == "1"
        if force_tfidf:
            self.vectorizer = TfidfVectorizer(
                analyzer="char_wb",
                ngram_range=(2, 4),
                min_df=1,
            )
            self.backend = "tfidf"
            return

        try:
            from sentence_transformers import SentenceTransformer  # type: ignore[reportMissingImports]

            self.model = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
            self.backend = "sentence-transformer"
        except Exception:
            self.vectorizer = TfidfVectorizer(
                analyzer="char_wb",
                ngram_range=(2, 4),
                min_df=1,
            )
            self.backend = "tfidf"

    def fit(self, corpus: Sequence[str]) -> None:
        if self.backend == "sentence-transformer":
            return
        self.vectorizer.fit(list(corpus))

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        texts = [t if t else "" for t in texts]
        if self.backend == "sentence-transformer":
            emb = self.model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
            return np.array(emb)
        mat = self.vectorizer.transform(texts)
        return mat

    def similarity(self, a: Sequence[str], b: Sequence[str]) -> np.ndarray:
        if self.backend == "tfidf":
            self.fit(list(a) + list(b))
        va = self.encode(a)
        vb = self.encode(b)
        return cosine_similarity(va, vb)


def timeline_candidate_recall(
    events_repr_csv: Path,
    timeline_nodes_csv: Path,
    out_csv: Path,
    top_k: int = 5,
) -> Tuple[pd.DataFrame, str]:
    ev = pd.read_csv(events_repr_csv, encoding=DEFAULT_ENCODING)
    tl = pd.read_csv(timeline_nodes_csv, encoding=DEFAULT_ENCODING)
    if "event_repr_text" not in ev.columns:
        raise ValueError("统一事件表示文件缺少 event_repr_text")

    timeline_texts = (
        tl["红楼年份"].fillna("").astype(str)
        + " "
        + tl["季节月份"].fillna("").astype(str)
        + " "
        + tl["事件名称"].fillna("").astype(str)
    ).tolist()
    event_texts = ev["event_repr_text"].fillna("").astype(str).tolist()

    sim_backend = TextSimilarityBackend()
    sim_mat = sim_backend.similarity(event_texts, timeline_texts)

    records = []
    k = min(top_k, len(tl))
    for i, row in ev.iterrows():
        sims = sim_mat[i]
        idx = np.argsort(-sims)[:k]
        cands = [tl.iloc[j]["timeline_id"] for j in idx]
        scores = [float(sims[j]) for j in idx]
        records.append(
            {
                "ueid": row["ueid"],
                "candidate_timeline_ids": json.dumps(cands, ensure_ascii=False),
                "candidate_scores": json.dumps([round(x, 6) for x in scores], ensure_ascii=False),
                "recall_backend": sim_backend.backend,
            }
        )
    out = pd.DataFrame(records)
    out.to_csv(out_csv, index=False, encoding=DEFAULT_ENCODING)
    return out, sim_backend.backend


def build_grounding_input_json(
    events_repr_csv: Path,
    timeline_nodes_csv: Path,
    candidate_csv: Path,
    out_json: Path,
) -> List[Dict]:
    ev = pd.read_csv(events_repr_csv, encoding=DEFAULT_ENCODING)
    tl = pd.read_csv(timeline_nodes_csv, encoding=DEFAULT_ENCODING)
    cand = pd.read_csv(candidate_csv, encoding=DEFAULT_ENCODING)

    tl_map = tl.set_index("timeline_id").to_dict(orient="index")
    ev_map = ev.set_index("ueid").to_dict(orient="index")

    packets = []
    for _, row in cand.iterrows():
        ueid = row["ueid"]
        cands = json.loads(_safe_text(row["candidate_timeline_ids"]) or "[]")
        scores = json.loads(_safe_text(row["candidate_scores"]) or "[]")
        candidate_nodes = []
        for tid, score in zip(cands, scores):
            meta = tl_map.get(tid, {})
            candidate_nodes.append(
                {
                    "timeline_id": tid,
                    "timeline_order": meta.get("timeline_order"),
                    "红楼年份": meta.get("红楼年份", ""),
                    "季节月份": meta.get("季节月份", ""),
                    "事件名称": meta.get("事件名称", ""),
                    "retrieval_score": float(score),
                }
            )
        e = ev_map[ueid]
        packets.append(
            {
                "ueid": ueid,
                "event_repr_text": _safe_text(e.get("event_repr_text")),
                "event_summary": _safe_text(e.get("event_summary")),
                "semantic_core": _safe_text(e.get("semantic_core")),
                "characters": _safe_text(e.get("characters")),
                "location": _safe_text(e.get("location")),
                "candidate_nodes": candidate_nodes,
                "instruction": (
                    "闭集时间锚定：只能从 candidate_nodes 的 timeline_id 里选择一个，"
                    "或输出 unknown。返回 JSON: {ueid,timeline_id,grounding_confidence,grounding_reason}"
                ),
            }
        )
    out_json.write_text(json.dumps(packets, ensure_ascii=False, indent=2), encoding="utf-8")
    return packets


def validate_closed_set_grounding_item(
    item: Dict, candidate_ids: Sequence[str]
) -> Dict:
    ueid = item.get("ueid", "")
    timeline_id = item.get("timeline_id", "unknown")
    conf = float(item.get("grounding_confidence", 0.0) or 0.0)
    reason = _safe_text(item.get("grounding_reason")) or "未提供理由"

    if timeline_id != "unknown" and timeline_id not in set(candidate_ids):
        timeline_id = "unknown"
        conf = min(conf, 0.3)
        reason = f"闭集校验失败，候选外timeline_id被拒绝。原因为: {reason}"
    conf = max(0.0, min(1.0, conf))
    return {
        "ueid": ueid,
        "timeline_id": timeline_id,
        "grounding_confidence": conf,
        "grounding_reason": reason,
    }


def grounding_with_fallback(
    candidate_csv: Path,
    out_json: Path,
    llm_output_json: Optional[Path] = None,
) -> List[Dict]:
    cand = pd.read_csv(candidate_csv, encoding=DEFAULT_ENCODING)
    cand_map = {}
    for _, row in cand.iterrows():
        cids = json.loads(_safe_text(row["candidate_timeline_ids"]) or "[]")
        cscores = json.loads(_safe_text(row["candidate_scores"]) or "[]")
        cand_map[row["ueid"]] = (cids, cscores)

    results = []
    if llm_output_json and llm_output_json.exists():
        raw = json.loads(llm_output_json.read_text(encoding="utf-8"))
        raw_map = {x.get("ueid"): x for x in raw if isinstance(x, dict)}
        for ueid, (cids, cscores) in cand_map.items():
            if ueid in raw_map:
                results.append(validate_closed_set_grounding_item(raw_map[ueid], cids))
            else:
                # 缺失则回退top1
                if cids:
                    results.append(
                        {
                            "ueid": ueid,
                            "timeline_id": cids[0],
                            "grounding_confidence": float(cscores[0]) if cscores else 0.45,
                            "grounding_reason": "LLM结果缺失，fallback到候选top-1",
                        }
                    )
                else:
                    results.append(
                        {
                            "ueid": ueid,
                            "timeline_id": "unknown",
                            "grounding_confidence": 0.0,
                            "grounding_reason": "无候选时间节点",
                        }
                    )
    else:
        for ueid, (cids, cscores) in cand_map.items():
            if cids:
                results.append(
                    {
                        "ueid": ueid,
                        "timeline_id": cids[0],
                        "grounding_confidence": float(cscores[0]) if cscores else 0.45,
                        "grounding_reason": "本地调试fallback：使用候选召回top-1",
                    }
                )
            else:
                results.append(
                    {
                        "ueid": ueid,
                        "timeline_id": "unknown",
                        "grounding_confidence": 0.0,
                        "grounding_reason": "无候选时间节点",
                    }
                )

    out_json.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return results


def merge_grounding_to_events(
    events_repr_csv: Path,
    timeline_nodes_csv: Path,
    grounding_json: Path,
    out_csv: Path,
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
    ev.to_csv(out_csv, index=False, encoding=DEFAULT_ENCODING)
    return ev


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
    return 1.0 if len(sa & sb) > 0 else 0.0


def _time_match(order_a: int, order_b: int, window_size: int) -> float:
    if order_a < 0 or order_b < 0:
        return 0.0
    d = abs(order_a - order_b)
    if d == 0:
        return 1.0
    if d <= window_size:
        # 相邻窗口衰减
        return max(0.0, 1.0 - d / (window_size + 1))
    return 0.0


def build_cross_modal_alignment(
    grounded_events_csv: Path,
    out_csv: Path,
    window_size: int = 2,
    top_k_per_event: int = 5,
    weights: AlignWeights = AlignWeights(),
) -> pd.DataFrame:
    df = pd.read_csv(grounded_events_csv, encoding=DEFAULT_ENCODING)
    if "event_repr_text" not in df.columns:
        raise ValueError("grounded事件表缺少event_repr_text")

    text_df = df[df["modality"] == "text"].copy()
    video_df = df[df["modality"] == "video"].copy()

    # 全局语义编码（一次编码，重复复用，避免逐pair重建向量）
    sim_backend = TextSimilarityBackend()
    corpus = df["event_repr_text"].fillna("").astype(str).tolist()
    if sim_backend.backend == "tfidf":
        sim_backend.fit(corpus)
    all_vecs = sim_backend.encode(corpus)
    ueid_to_idx = {u: i for i, u in enumerate(df["ueid"].tolist())}

    def row_sem_sim_by_ueid(ueid_a: str, ueid_b: str) -> float:
        ia = ueid_to_idx[ueid_a]
        ib = ueid_to_idx[ueid_b]
        va = all_vecs[ia]
        vb = all_vecs[ib]
        mat = cosine_similarity(va, vb)
        return float(mat[0][0])

    rows = []
    for _, q in df.iterrows():
        q_mod = q["modality"]
        cand_pool = text_df if q_mod == "video" else video_df
        if cand_pool.empty:
            continue

        q_order = int(q["timeline_order"])
        if q_order >= 0:
            pool = cand_pool[
                cand_pool["timeline_order"].apply(
                    lambda x: x >= 0 and abs(int(x) - q_order) <= window_size
                )
            ]
        else:
            # unknown 时间锚点时，不做时间过滤但Match_time会给0
            pool = cand_pool

        if pool.empty:
            continue

        q_chars = _split_norm_items(_safe_text(q.get("characters")))
        q_locs = _split_norm_items(_safe_text(q.get("location")))
        local_scores = []
        for _, c in pool.iterrows():
            c_chars = _split_norm_items(_safe_text(c.get("characters")))
            c_locs = _split_norm_items(_safe_text(c.get("location")))
            sem = row_sem_sim_by_ueid(q["ueid"], c["ueid"])
            char = _jaccard(q_chars, c_chars)
            loc = _loc_match(q_locs, c_locs)
            tmatch = _time_match(int(q["timeline_order"]), int(c["timeline_order"]), window_size)
            score = (
                weights.alpha_sem * sem
                + weights.beta_char * char
                + weights.gamma_loc * loc
                + weights.delta_time * tmatch
            )
            shared_chars = sorted(list(set(q_chars) & set(c_chars)))
            shared_locs = sorted(list(set(q_locs) & set(c_locs)))
            timeline_match = "same" if int(q["timeline_order"]) == int(c["timeline_order"]) else "near"
            local_scores.append(
                {
                    "source_ueid": q["ueid"],
                    "target_ueid": c["ueid"],
                    "source_modality": q_mod,
                    "target_modality": c["modality"],
                    "alignment_score": round(float(score), 6),
                    "sim_sem": round(sem, 6),
                    "overlap_char": round(char, 6),
                    "match_loc": round(loc, 6),
                    "match_time": round(tmatch, 6),
                    "alignment_type": "aligned" if score >= 0.55 else "related",
                    "shared_characters": "、".join(shared_chars),
                    "shared_location": "、".join(shared_locs),
                    "timeline_match": timeline_match,
                    "source_timeline_id": q.get("timeline_id", "unknown"),
                    "target_timeline_id": c.get("timeline_id", "unknown"),
                }
            )

        local_scores.sort(key=lambda x: x["alignment_score"], reverse=True)
        rows.extend(local_scores[:top_k_per_event])

    out = pd.DataFrame(rows)
    out.to_csv(out_csv, index=False, encoding=DEFAULT_ENCODING)
    return out


def build_event_timeline_chains(
    grounded_events_csv: Path,
    alignment_csv: Path,
    timeline_nodes_csv: Path,
    out_json: Path,
    chain_window_h: int = 2,
    align_top_k: int = 5,
) -> List[Dict]:
    ev = pd.read_csv(grounded_events_csv, encoding=DEFAULT_ENCODING)
    al = pd.read_csv(alignment_csv, encoding=DEFAULT_ENCODING)
    tl = pd.read_csv(timeline_nodes_csv, encoding=DEFAULT_ENCODING)

    tl_by_order = tl.set_index("timeline_order").to_dict(orient="index")
    ev_by_ueid = ev.set_index("ueid")

    all_items = []
    for _, q in ev.iterrows():
        q_ueid = q["ueid"]
        order = int(q["timeline_order"])
        if order >= 0:
            anchor_meta = tl_by_order.get(order, {})
            anchor = {
                "timeline_id": q["timeline_id"],
                "timeline_order": order,
                "红楼年份": anchor_meta.get("红楼年份", ""),
                "季节月份": anchor_meta.get("季节月份", ""),
                "事件名称": anchor_meta.get("事件名称", ""),
                "grounding_confidence": float(q.get("grounding_confidence", 0.0)),
                "grounding_reason": _safe_text(q.get("grounding_reason")),
            }
            min_o, max_o = order - chain_window_h, order + chain_window_h
            chain_df = ev[(ev["timeline_order"] >= min_o) & (ev["timeline_order"] <= max_o)].copy()
            chain_df = chain_df.sort_values(["timeline_order", "modality", "narrative_order"], ascending=True)
        else:
            anchor = {
                "timeline_id": "unknown",
                "timeline_order": -1,
                "红楼年份": "",
                "季节月份": "",
                "事件名称": "",
                "grounding_confidence": float(q.get("grounding_confidence", 0.0)),
                "grounding_reason": _safe_text(q.get("grounding_reason")),
            }
            chain_df = pd.DataFrame(columns=ev.columns)

        q_align = al[al["source_ueid"] == q_ueid].sort_values("alignment_score", ascending=False).head(align_top_k)
        aligned = q_align.to_dict(orient="records")

        chain_records = []
        for _, c in chain_df.iterrows():
            chain_records.append(
                {
                    "ueid": c["ueid"],
                    "modality": c.get("modality", ""),
                    "timeline_id": c.get("timeline_id", "unknown"),
                    "timeline_order": int(c.get("timeline_order", -1)),
                    "action": _safe_text(c.get("action")),
                    "event_summary": _safe_text(c.get("event_summary")),
                    "characters": _safe_text(c.get("characters")),
                    "location": _safe_text(c.get("location")),
                }
            )

        query_event = ev_by_ueid.loc[q_ueid].to_dict()
        all_items.append(
            {
                "query_event": query_event,
                "timeline_anchor": anchor,
                "aligned_events": aligned,
                "timeline_chain": chain_records,
            }
        )

    out_json.write_text(json.dumps(all_items, ensure_ascii=False, indent=2), encoding="utf-8")
    return all_items


def query_event_or_segment(
    ueid: str,
    grounded_events_path: str,
    alignment_path: str,
    timeline_nodes_path: str,
    chain_window_h: int = 2,
    align_top_k: int = 5,
) -> Dict:
    ev = pd.read_csv(grounded_events_path, encoding=DEFAULT_ENCODING)
    al = pd.read_csv(alignment_path, encoding=DEFAULT_ENCODING)
    tl = pd.read_csv(timeline_nodes_path, encoding=DEFAULT_ENCODING)

    hit = ev[ev["ueid"] == ueid]
    if hit.empty:
        return {
            "query_event": {"ueid": ueid},
            "timeline_anchor": {"timeline_id": "unknown"},
            "aligned_events": [],
            "timeline_chain": [],
            "error": f"未找到事件: {ueid}",
        }

    q = hit.iloc[0]
    order = int(q.get("timeline_order", -1))
    if order >= 0:
        tl_hit = tl[tl["timeline_order"] == order]
        tl_meta = tl_hit.iloc[0].to_dict() if not tl_hit.empty else {}
    else:
        tl_meta = {}

    anchor = {
        "timeline_id": q.get("timeline_id", "unknown"),
        "timeline_order": order,
        "红楼年份": tl_meta.get("红楼年份", ""),
        "季节月份": tl_meta.get("季节月份", ""),
        "事件名称": tl_meta.get("事件名称", ""),
        "grounding_confidence": float(q.get("grounding_confidence", 0.0)),
        "grounding_reason": _safe_text(q.get("grounding_reason")),
    }

    aligns = (
        al[al["source_ueid"] == ueid]
        .sort_values("alignment_score", ascending=False)
        .head(align_top_k)
        .to_dict(orient="records")
    )

    if order >= 0:
        chain = ev[(ev["timeline_order"] >= order - chain_window_h) & (ev["timeline_order"] <= order + chain_window_h)].copy()
        chain = chain.sort_values(["timeline_order", "modality", "narrative_order"], ascending=True)
        chain_records = chain.to_dict(orient="records")
    else:
        chain_records = []

    return {
        "query_event": q.to_dict(),
        "timeline_anchor": anchor,
        "aligned_events": aligns,
        "timeline_chain": chain_records,
    }


def run_pipeline(
    unified_events_csv: Path,
    timeline_csv: Path,
    output_dir: Path,
    top_k_timeline: int = 5,
    window_size: int = 2,
    chain_window_h: int = 2,
    align_top_k: int = 5,
    llm_output_json: Optional[Path] = None,
) -> Dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)

    p1 = output_dir / "timeline_nodes.csv"
    p2 = output_dir / "unified_events_repr.csv"
    p3 = output_dir / "timeline_candidate_recall.csv"
    p4 = output_dir / "timeline_grounding_input.json"
    p5 = output_dir / "timeline_grounding_results.json"
    p6 = output_dir / "unified_events_grounded.csv"
    p7 = output_dir / "cross_modal_event_alignment.csv"
    p8 = output_dir / "event_timeline_chains.json"

    preprocess_timeline(timeline_csv, p1)
    build_event_repr(unified_events_csv, p2)
    timeline_candidate_recall(p2, p1, p3, top_k=top_k_timeline)
    build_grounding_input_json(p2, p1, p3, p4)
    grounding_with_fallback(p3, p5, llm_output_json=llm_output_json)
    merge_grounding_to_events(p2, p1, p5, p6)
    build_cross_modal_alignment(p6, p7, window_size=window_size, top_k_per_event=align_top_k)
    build_event_timeline_chains(p6, p7, p1, p8, chain_window_h=chain_window_h, align_top_k=align_top_k)

    return {
        "timeline_nodes.csv": p1,
        "unified_events_repr.csv": p2,
        "timeline_candidate_recall.csv": p3,
        "timeline_grounding_input.json": p4,
        "timeline_grounding_results.json": p5,
        "unified_events_grounded.csv": p6,
        "cross_modal_event_alignment.csv": p7,
        "event_timeline_chains.json": p8,
    }


def main():
    parser = argparse.ArgumentParser(description="功能2：参考时间线约束的跨模态事件对齐与时间线构建")
    parser.add_argument(
        "--unified-events",
        type=str,
        default="unified_events/unified_events.csv",
        help="统一事件CSV路径",
    )
    parser.add_argument(
        "--timeline",
        type=str,
        default="知识库/红楼梦时间线.csv",
        help="参考时间线CSV路径",
    )
    parser.add_argument("--output-dir", type=str, default=".", help="输出目录")
    parser.add_argument("--top-k-timeline", type=int, default=5, help="时间线候选召回top-k")
    parser.add_argument("--window-size", type=int, default=2, help="跨模态对齐时间窗口")
    parser.add_argument("--chain-window-h", type=int, default=2, help="事件链展开窗口h")
    parser.add_argument("--align-top-k", type=int, default=5, help="每个查询事件保留top-k对齐")
    parser.add_argument(
        "--llm-output-json",
        type=str,
        default="",
        help="可选：外部LLM闭集锚定输出JSON路径，不提供则fallback top-1",
    )
    parser.add_argument("--query-ueid", type=str, default="", help="可选：运行后查询某个ueid")
    args = parser.parse_args()

    llm_path = Path(args.llm_output_json) if args.llm_output_json else None
    outputs = run_pipeline(
        unified_events_csv=Path(args.unified_events),
        timeline_csv=Path(args.timeline),
        output_dir=Path(args.output_dir),
        top_k_timeline=args.top_k_timeline,
        window_size=args.window_size,
        chain_window_h=args.chain_window_h,
        align_top_k=args.align_top_k,
        llm_output_json=llm_path,
    )

    print("Pipeline完成，输出文件：")
    for name, path in outputs.items():
        print(f"- {name}: {path}")

    if args.query_ueid:
        qres = query_event_or_segment(
            ueid=args.query_ueid,
            grounded_events_path=str(outputs["unified_events_grounded.csv"]),
            alignment_path=str(outputs["cross_modal_event_alignment.csv"]),
            timeline_nodes_path=str(outputs["timeline_nodes.csv"]),
            chain_window_h=args.chain_window_h,
            align_top_k=args.align_top_k,
        )
        print("\n查询结果(JSON)：")
        print(json.dumps(qres, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
