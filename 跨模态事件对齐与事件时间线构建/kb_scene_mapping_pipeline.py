from __future__ import annotations

import json
import math
import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

DEFAULT_ENCODING = "utf-8-sig"


def _safe_text(x: object) -> str:
    if x is None:
        return ""
    s = str(x).strip()
    if s.lower() in {"nan", "none", "null", "na"}:
        return ""
    return s


def _safe_float(x: object, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def _safe_int(x: object, default: int = -1) -> int:
    try:
        return int(float(x))
    except Exception:
        return default


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _split_items(text: str) -> List[str]:
    s = _safe_text(text)
    if not s:
        return []
    return [x.strip() for x in re.split(r"[、，,;；/|\s]+", s) if x.strip()]


def _dedup_keep_order(items: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _norm_text_for_display(text: str) -> str:
    s = _safe_text(text)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _compact_title(*parts: str, max_len: int = 28) -> str:
    for part in parts:
        s = _norm_text_for_display(part)
        if not s:
            continue
        s = re.sub(r"[，。；：,.!！?？]+", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        if s:
            return s[:max_len]
    return "未命名场景"


def _timeline_id_from_ref(ref: str) -> str:
    s = _safe_text(ref)
    if not s:
        return "unknown"
    return s.split("｜")[0].strip() or "unknown"


class ProgressPrinter:
    def __init__(self, total: int, desc: str) -> None:
        self.total = max(total, 1)
        self.desc = desc
        self.count = 0
        print(f"[PIPELINE] {desc} | total={total}", flush=True)

    def step(self) -> None:
        self.count += 1
        if self.count == 1 or self.count % 50 == 0 or self.count == self.total:
            print(f"[PIPELINE] {self.desc}: {self.count}/{self.total}", flush=True)


class TextSimilarityBackend:
    def __init__(self) -> None:
        self.backend = "tfidf"
        self.model = None
        self.vectorizer: Optional[TfidfVectorizer] = None

        force_tfidf = os.environ.get("FORCE_TFIDF", "0") == "1"
        if force_tfidf:
            self.vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=1)
            return

        try:
            from sentence_transformers import SentenceTransformer  # type: ignore

            self.model = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
            self.backend = "sentence-transformer"
        except Exception:
            self.vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=1)

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


@dataclass
class KBMappingConfig:
    top_k_kb: int = 5
    min_kb_score: float = 0.20
    prefer_anchor_events: bool = True
    alpha_name: float = 0.42
    beta_detail: float = 0.23
    gamma_char: float = 0.23
    delta_loc: float = 0.12

    # scene 聚类
    scene_max_gap: int = 2
    scene_min_char_jaccard: float = 0.15
    scene_min_loc_jaccard: float = 0.10
    scene_merge_semantic_threshold: float = 0.42

    # scene -> kb
    top_k_scene_kb: int = 5
    min_scene_kb_score: float = 0.24

    # cross modal
    top_k_links_per_kb: int = 8
    min_cross_modal_score: float = 0.28


@dataclass
class LLMReviewConfig:
    enabled: bool = False
    provider: str = "dashscope"
    model_name: str = "qwen3.6-plus"
    api_key_env: str = "DASHSCOPE_API_KEY"
    api_key_literal: str = ""
    timeout: int = 120
    max_retries: int = 3

    review_scene_kb_mapping: bool = True
    review_cross_modal_links: bool = True
    max_scene_items: int = 150
    max_link_items: int = 120

    scene_score_low: float = 0.24
    scene_score_high: float = 0.72
    scene_gap_threshold: float = 0.12
    link_score_low: float = 0.28
    link_score_high: float = 0.78

    scene_batch_size: int = 8
    link_batch_size: int = 8
    scene_pause_between_batches_sec: float = 0.0
    link_pause_between_batches_sec: float = 0.0

    accept_if_aligned_conf_ge: float = 0.70
    verbose: bool = True


@dataclass
class KBSceneOutputs:
    kb_event_nodes_json: Path
    atomic_events_with_kb_csv: Path
    atomic_events_with_kb_json: Path
    scene_events_json: Path
    scene_events_with_kb_json: Path
    cross_modal_scene_links_json: Path
    llm_review_audit_json: Path
    run_config_json: Path


REQUIRED_EVENT_COLUMNS = [
    "ueid",
    "modality",
    "source_id",
    "source_title",
    "narrative_order",
    "action",
    "characters",
    "location",
    "event_summary",
    "source_text",
    "semantic_core",
    "keywords",
    "source_path",
]

REQUIRED_KB_COLUMNS = [
    "kb_event_id",
    "事件名",
    "event_aliases",
    "main_characters",
    "main_locations",
    "is_cross_modal_anchor",
    "timeline_ref",
    "事件详情",
]


def load_atomic_events(unified_events_csv: Path) -> pd.DataFrame:
    df = pd.read_csv(unified_events_csv, encoding=DEFAULT_ENCODING)
    missing = [c for c in REQUIRED_EVENT_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"原子事件表缺少字段: {missing}")
    return df.copy()


def load_kb_events(kb_events_csv: Path) -> pd.DataFrame:
    df = pd.read_csv(kb_events_csv, encoding=DEFAULT_ENCODING)
    missing = [c for c in REQUIRED_KB_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"知识库事件表缺少字段: {missing}")
    return df.copy()


def build_atomic_event_repr(row: pd.Series) -> str:
    action = _safe_text(row.get("action"))
    summary = _safe_text(row.get("event_summary"))
    core = _safe_text(row.get("semantic_core"))
    chars = "、".join(_split_items(_safe_text(row.get("characters")))[:8])
    locs = "、".join(_split_items(_safe_text(row.get("location")))[:4])
    keywords = "、".join(_split_items(_safe_text(row.get("keywords")))[:10])

    parts = []
    if action:
        parts.append(f"动作:{action}")
    if summary:
        parts.append(f"摘要:{summary}")
    if core and core not in summary:
        parts.append(f"语义核:{core}")
    if chars:
        parts.append(f"人物:{chars}")
    if locs:
        parts.append(f"地点:{locs}")
    if keywords:
        parts.append(f"关键词:{keywords}")
    return "；".join(parts)[:500]


def build_kb_event_repr(row: pd.Series) -> Dict[str, str]:
    event_name = _safe_text(row.get("事件名"))
    aliases = _safe_text(row.get("event_aliases"))
    detail = _safe_text(row.get("事件详情"))
    chars = _safe_text(row.get("main_characters"))
    locs = _safe_text(row.get("main_locations"))
    timeline_ref = _safe_text(row.get("timeline_ref"))

    name_text = "；".join([x for x in [event_name, aliases] if x])
    detail_text = "；".join([x for x in [event_name, aliases, detail, chars, locs, timeline_ref] if x])
    return {
        "kb_name_repr": name_text[:300],
        "kb_detail_repr": detail_text[:800],
    }


def _coerce_to_str_list(value: object) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, tuple):
        return [str(x).strip() for x in value if str(x).strip()]

    text = _safe_text(value)
    if not text:
        return []

    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(x).strip() for x in parsed if str(x).strip()]
    except Exception:
        pass

    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        parts = [p.strip().strip("'\"") for p in inner.split(",")]
        return [p for p in parts if p]

    return _split_items(text)


def _jaccard(a: Sequence[str], b: Sequence[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 0.0
    union = sa | sb
    if not union:
        return 0.0
    return len(sa & sb) / len(union)


def prepare_kb_nodes(kb_df: pd.DataFrame) -> pd.DataFrame:
    kb_df = kb_df.copy()
    repr_rows = kb_df.apply(build_kb_event_repr, axis=1, result_type="expand")
    kb_df = pd.concat([kb_df, repr_rows], axis=1)
    kb_df["kb_char_list"] = kb_df["main_characters"].fillna("").astype(str).apply(_split_items)
    kb_df["kb_loc_list"] = kb_df["main_locations"].fillna("").astype(str).apply(_split_items)
    kb_df["is_anchor_bool"] = kb_df["is_cross_modal_anchor"].fillna(0).astype(str).isin(["1", "true", "True"])
    return kb_df


def map_atomic_events_to_kb(events_df: pd.DataFrame, kb_df: pd.DataFrame, cfg: KBMappingConfig) -> pd.DataFrame:
    events = events_df.copy()
    kb = prepare_kb_nodes(kb_df)

    events["event_repr_text"] = events.apply(build_atomic_event_repr, axis=1)
    events["event_char_list"] = events["characters"].fillna("").astype(str).apply(_split_items)
    events["event_loc_list"] = events["location"].fillna("").astype(str).apply(_split_items)

    backend = TextSimilarityBackend()
    event_reprs = events["event_repr_text"].fillna("").astype(str).tolist()
    kb_name_reprs = kb["kb_name_repr"].fillna("").astype(str).tolist()
    kb_detail_reprs = kb["kb_detail_repr"].fillna("").astype(str).tolist()

    name_sim = backend.similarity_matrix(event_reprs, kb_name_reprs)
    detail_sim = backend.similarity_matrix(event_reprs, kb_detail_reprs)

    top1_ids: List[str] = []
    top1_names: List[str] = []
    top1_scores: List[float] = []
    top1_timeline_ids: List[str] = []
    topk_payloads: List[str] = []

    progress = ProgressPrinter(len(events), "原子事件匹配知识库")
    for i, row in events.iterrows():
        event_chars = row["event_char_list"]
        event_locs = row["event_loc_list"]
        scores: List[Tuple[float, Dict[str, object]]] = []
        for j, kb_row in kb.iterrows():
            s_name = float(name_sim[i, j])
            s_detail = float(detail_sim[i, j])
            s_char = _jaccard(event_chars, kb_row["kb_char_list"])
            s_loc = _jaccard(event_locs, kb_row["kb_loc_list"])
            score = (
                cfg.alpha_name * s_name
                + cfg.beta_detail * s_detail
                + cfg.gamma_char * s_char
                + cfg.delta_loc * s_loc
            )
            if cfg.prefer_anchor_events and bool(kb_row["is_anchor_bool"]):
                score += 0.03
            scores.append(
                (
                    score,
                    {
                        "kb_event_id": _safe_text(kb_row["kb_event_id"]),
                        "kb_event_name": _safe_text(kb_row["事件名"]),
                        "kb_score": round(score, 6),
                        "name_similarity": round(s_name, 6),
                        "detail_similarity": round(s_detail, 6),
                        "char_overlap": round(s_char, 6),
                        "loc_overlap": round(s_loc, 6),
                        "timeline_ref": _safe_text(kb_row["timeline_ref"]),
                        "is_cross_modal_anchor": bool(kb_row["is_anchor_bool"]),
                    },
                )
            )
        scores.sort(key=lambda x: x[0], reverse=True)
        filtered = [payload for score, payload in scores if score >= cfg.min_kb_score][: cfg.top_k_kb]
        top1 = filtered[0] if filtered else None
        if top1 is None:
            top1_ids.append("")
            top1_names.append("")
            top1_scores.append(0.0)
            top1_timeline_ids.append("unknown")
            topk_payloads.append(json.dumps([], ensure_ascii=False))
        else:
            top1_ids.append(_safe_text(top1["kb_event_id"]))
            top1_names.append(_safe_text(top1["kb_event_name"]))
            top1_scores.append(_safe_float(top1["kb_score"]))
            top1_timeline_ids.append(_timeline_id_from_ref(_safe_text(top1["timeline_ref"])))
            topk_payloads.append(json.dumps(filtered, ensure_ascii=False))
        progress.step()

    events["kb_event_id"] = top1_ids
    events["kb_event_name"] = top1_names
    events["kb_top1_score"] = top1_scores
    events["timeline_id"] = top1_timeline_ids
    events["kb_topk_candidates"] = topk_payloads
    events["semantic_backend"] = backend.backend
    return events


def _scene_char_loc_gate(prev_row: pd.Series, cur_row: pd.Series, cfg: KBMappingConfig) -> bool:
    prev_chars = _split_items(_safe_text(prev_row.get("characters")))
    cur_chars = _split_items(_safe_text(cur_row.get("characters")))
    prev_locs = _split_items(_safe_text(prev_row.get("location")))
    cur_locs = _split_items(_safe_text(cur_row.get("location")))

    char_j = _jaccard(prev_chars, cur_chars)
    loc_j = _jaccard(prev_locs, cur_locs)
    return char_j >= cfg.scene_min_char_jaccard or loc_j >= cfg.scene_min_loc_jaccard


def build_scene_repr_from_block(block: pd.DataFrame) -> Dict[str, object]:
    first = block.iloc[0].to_dict()
    chars = _dedup_keep_order(
        c for cell in block["characters"].fillna("").astype(str).tolist() for c in _split_items(cell)
    )
    locs = _dedup_keep_order(
        c for cell in block["location"].fillna("").astype(str).tolist() for c in _split_items(cell)
    )
    event_names = [_compact_title(r.get("action"), r.get("event_summary"), r.get("semantic_core")) for r in block.to_dict(orient="records")]
    summary_parts = []
    for row in block.to_dict(orient="records"):
        part = _safe_text(row.get("event_summary")) or _safe_text(row.get("action"))
        if part:
            summary_parts.append(part)
    scene_summary = "；".join(summary_parts[:6])[:600]
    scene_name = _compact_title(_safe_text(first.get("kb_event_name")), event_names[0] if event_names else "", scene_summary)
    scene_repr = "；".join(
        x
        for x in [
            f"场景名:{scene_name}" if scene_name else "",
            f"摘要:{scene_summary}" if scene_summary else "",
            f"人物:{'、'.join(chars[:8])}" if chars else "",
            f"地点:{'、'.join(locs[:4])}" if locs else "",
            f"知识库:{_safe_text(first.get('kb_event_name'))}" if _safe_text(first.get("kb_event_name")) else "",
        ]
        if x
    )
    return {
        "scene_name": scene_name,
        "scene_summary": scene_summary,
        "scene_characters": chars,
        "scene_locations": locs,
        "scene_repr_text": scene_repr[:900],
        "representative_ueid": _safe_text(first.get("ueid")),
    }


def build_scene_events(events_with_kb: pd.DataFrame, cfg: KBMappingConfig) -> pd.DataFrame:
    rows: List[Dict] = []
    scene_counter = 1

    progress_groups = list(events_with_kb.groupby(["modality", "source_id"], sort=False))
    progress = ProgressPrinter(len(progress_groups), "原子事件聚类为 scene_event")
    for (modality, source_id), group in progress_groups:
        group = group.sort_values("narrative_order").reset_index(drop=True)
        if group.empty:
            progress.step()
            continue

        current_block = [group.iloc[0]]
        for idx in range(1, len(group)):
            prev_row = current_block[-1]
            cur_row = group.iloc[idx]
            gap = abs(_safe_int(cur_row.get("narrative_order"), idx) - _safe_int(prev_row.get("narrative_order"), idx - 1))
            same_kb = _safe_text(cur_row.get("kb_event_id")) and _safe_text(cur_row.get("kb_event_id")) == _safe_text(prev_row.get("kb_event_id"))
            same_loc = _jaccard(_split_items(_safe_text(cur_row.get("location"))), _split_items(_safe_text(prev_row.get("location")))) >= cfg.scene_min_loc_jaccard
            char_or_loc_ok = _scene_char_loc_gate(prev_row, cur_row, cfg)

            if gap <= cfg.scene_max_gap and (same_kb or same_loc or char_or_loc_ok):
                current_block.append(cur_row)
            else:
                block_df = pd.DataFrame(current_block)
                meta = build_scene_repr_from_block(block_df)
                rows.append(
                    {
                        "scene_id": f"SCN_{scene_counter:05d}",
                        "modality": _safe_text(modality),
                        "source_id": _safe_text(source_id),
                        "source_title": _safe_text(block_df.iloc[0].get("source_title")),
                        "source_path": _safe_text(block_df.iloc[0].get("source_path")),
                        "member_ueids": json.dumps(block_df["ueid"].astype(str).tolist(), ensure_ascii=False),
                        "member_count": int(len(block_df)),
                        "start_order": int(block_df["narrative_order"].min()),
                        "end_order": int(block_df["narrative_order"].max()),
                        "representative_ueid": meta["representative_ueid"],
                        "scene_name": meta["scene_name"],
                        "scene_summary": meta["scene_summary"],
                        "scene_repr_text": meta["scene_repr_text"],
                        "scene_characters": json.dumps(meta["scene_characters"], ensure_ascii=False),
                        "scene_locations": json.dumps(meta["scene_locations"], ensure_ascii=False),
                        "chapter_id": _safe_text(source_id) if _safe_text(modality) == "text" else "",
                        "chapter_title": _safe_text(block_df.iloc[0].get("source_title")) if _safe_text(modality) == "text" else "",
                        "episode_id": _safe_text(source_id) if _safe_text(modality) == "video" else "",
                        "episode_title": _safe_text(block_df.iloc[0].get("source_title")) if _safe_text(modality) == "video" else "",
                    }
                )
                scene_counter += 1
                current_block = [cur_row]

        if current_block:
            block_df = pd.DataFrame(current_block)
            meta = build_scene_repr_from_block(block_df)
            rows.append(
                {
                    "scene_id": f"SCN_{scene_counter:05d}",
                    "modality": _safe_text(modality),
                    "source_id": _safe_text(source_id),
                    "source_title": _safe_text(block_df.iloc[0].get("source_title")),
                    "source_path": _safe_text(block_df.iloc[0].get("source_path")),
                    "member_ueids": json.dumps(block_df["ueid"].astype(str).tolist(), ensure_ascii=False),
                    "member_count": int(len(block_df)),
                    "start_order": int(block_df["narrative_order"].min()),
                    "end_order": int(block_df["narrative_order"].max()),
                    "representative_ueid": meta["representative_ueid"],
                    "scene_name": meta["scene_name"],
                    "scene_summary": meta["scene_summary"],
                    "scene_repr_text": meta["scene_repr_text"],
                    "scene_characters": json.dumps(meta["scene_characters"], ensure_ascii=False),
                    "scene_locations": json.dumps(meta["scene_locations"], ensure_ascii=False),
                    "chapter_id": _safe_text(source_id) if _safe_text(modality) == "text" else "",
                    "chapter_title": _safe_text(block_df.iloc[0].get("source_title")) if _safe_text(modality) == "text" else "",
                    "episode_id": _safe_text(source_id) if _safe_text(modality) == "video" else "",
                    "episode_title": _safe_text(block_df.iloc[0].get("source_title")) if _safe_text(modality) == "video" else "",
                }
            )
            scene_counter += 1
        progress.step()

    return pd.DataFrame(rows)


def map_scene_events_to_kb(scene_df: pd.DataFrame, kb_df: pd.DataFrame, cfg: KBMappingConfig) -> pd.DataFrame:
    scenes = scene_df.copy()
    kb = prepare_kb_nodes(kb_df)

    backend = TextSimilarityBackend()
    scene_reprs = scenes["scene_repr_text"].fillna("").astype(str).tolist()
    kb_name_reprs = kb["kb_name_repr"].fillna("").astype(str).tolist()
    kb_detail_reprs = kb["kb_detail_repr"].fillna("").astype(str).tolist()

    name_sim = backend.similarity_matrix(scene_reprs, kb_name_reprs)
    detail_sim = backend.similarity_matrix(scene_reprs, kb_detail_reprs)

    scene_top1_ids: List[str] = []
    scene_top1_names: List[str] = []
    scene_top1_scores: List[float] = []
    scene_timeline_ids: List[str] = []
    scene_topk_payloads: List[str] = []

    progress = ProgressPrinter(len(scenes), "scene_event 匹配知识库")
    for i, row in scenes.iterrows():
        scene_chars = _coerce_to_str_list(row.get("scene_characters"))
        scene_locs = _coerce_to_str_list(row.get("scene_locations"))
        scores: List[Tuple[float, Dict[str, object]]] = []
        for j, kb_row in kb.iterrows():
            s_name = float(name_sim[i, j])
            s_detail = float(detail_sim[i, j])
            s_char = _jaccard(scene_chars, kb_row["kb_char_list"])
            s_loc = _jaccard(scene_locs, kb_row["kb_loc_list"])
            score = (
                cfg.alpha_name * s_name
                + cfg.beta_detail * s_detail
                + cfg.gamma_char * s_char
                + cfg.delta_loc * s_loc
            )
            if cfg.prefer_anchor_events and bool(kb_row["is_anchor_bool"]):
                score += 0.03
            scores.append(
                (
                    score,
                    {
                        "kb_event_id": _safe_text(kb_row["kb_event_id"]),
                        "kb_event_name": _safe_text(kb_row["事件名"]),
                        "kb_score": round(score, 6),
                        "name_similarity": round(s_name, 6),
                        "detail_similarity": round(s_detail, 6),
                        "char_overlap": round(s_char, 6),
                        "loc_overlap": round(s_loc, 6),
                        "timeline_ref": _safe_text(kb_row["timeline_ref"]),
                        "is_cross_modal_anchor": bool(kb_row["is_anchor_bool"]),
                    },
                )
            )
        scores.sort(key=lambda x: x[0], reverse=True)
        filtered = [payload for score, payload in scores if score >= cfg.min_scene_kb_score][: cfg.top_k_scene_kb]
        top1 = filtered[0] if filtered else None
        if top1 is None:
            scene_top1_ids.append("")
            scene_top1_names.append("")
            scene_top1_scores.append(0.0)
            scene_timeline_ids.append("unknown")
            scene_topk_payloads.append(json.dumps([], ensure_ascii=False))
        else:
            scene_top1_ids.append(_safe_text(top1["kb_event_id"]))
            scene_top1_names.append(_safe_text(top1["kb_event_name"]))
            scene_top1_scores.append(_safe_float(top1["kb_score"]))
            scene_timeline_ids.append(_timeline_id_from_ref(_safe_text(top1["timeline_ref"])))
            scene_topk_payloads.append(json.dumps(filtered, ensure_ascii=False))
        progress.step()

    scenes["kb_event_id"] = scene_top1_ids
    scenes["kb_event_name"] = scene_top1_names
    scenes["kb_top1_score"] = scene_top1_scores
    scenes["timeline_id"] = scene_timeline_ids
    scenes["kb_topk_candidates"] = scene_topk_payloads
    scenes["semantic_backend"] = backend.backend
    return scenes


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


def _call_dashscope_json(prompt: str, cfg: LLMReviewConfig) -> Dict:
    api_key = cfg.api_key_literal or os.getenv(cfg.api_key_env, "")
    if not api_key:
        raise ValueError(f"未检测到 {cfg.api_key_env}，且未提供显式 API Key，无法执行 LLM 复核")

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


def _build_scene_kb_review_prompt(scene_row: Dict, candidates: List[Dict]) -> str:
    payload = {
        "task": "scene_to_kb_mapping_review",
        "instruction": [
            "你要判断一个 scene_event 最匹配哪一个知识库规范事件。",
            "优先依据：核心动作、主要人物、主要地点、事件背景，而不是表面词重复。",
            "只能从给定候选中选择 best_kb_event_id，或输出 null。",
            "若所有候选都不合适，请输出 unmatched。",
            "只输出合法 JSON。",
        ],
        "scene_event": scene_row,
        "candidates": candidates,
        "output_schema": {
            "scene_id": scene_row.get("scene_id"),
            "best_kb_event_id": "候选中的 kb_event_id 或 null",
            "decision": "aligned | unmatched",
            "confidence": "0到1之间浮点数",
            "reason": "一句中文简洁理由",
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _build_scene_kb_batch_review_prompt(items: List[Dict]) -> str:
    payload = {
        "task": "scene_to_kb_mapping_batch_review",
        "instruction": [
            "你要批量判断多个 scene_event 最匹配哪一个知识库规范事件。",
            "对每个 scene，只能从它自己的 candidates 中选择 best_kb_event_id，或输出 null。",
            "优先依据：核心动作、主要人物、主要地点、事件背景，而不是表面词重复。",
            "若所有候选都不合适，请输出 unmatched。",
            "只输出合法 JSON。",
        ],
        "items": items,
        "output_schema": {
            "results": [
                {
                    "scene_id": "输入中的 scene_id",
                    "best_kb_event_id": "该 scene 候选中的 kb_event_id 或 null",
                    "decision": "aligned | unmatched",
                    "confidence": "0到1之间浮点数",
                    "reason": "一句中文简洁理由",
                }
            ]
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _build_cross_modal_review_prompt(link_row: Dict) -> str:
    payload = {
        "task": "cross_modal_scene_link_review",
        "instruction": [
            "你要判断一个文本场景与一个视频场景是否真的属于同一叙事场景。",
            "优先依据：共享的规范事件、主要人物、主要地点、关键动作。",
            "如果只是同章节附近或同人物出场，但不是同一场景，应输出 unmatched。",
            "只输出合法 JSON。",
        ],
        "scene_link": link_row,
        "output_schema": {
            "link_id": link_row.get("link_id"),
            "decision": "aligned | unmatched",
            "confidence": "0到1之间浮点数",
            "reason": "一句中文简洁理由",
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _build_cross_modal_batch_review_prompt(items: List[Dict]) -> str:
    payload = {
        "task": "cross_modal_scene_link_batch_review",
        "instruction": [
            "你要批量判断多个文本场景与视频场景是否真的属于同一叙事场景。",
            "优先依据：共享的规范事件、主要人物、主要地点、关键动作。",
            "如果只是同章节附近或同人物出场，但不是同一场景，应输出 unmatched。",
            "只输出合法 JSON。",
        ],
        "items": items,
        "output_schema": {
            "results": [
                {
                    "link_id": "输入中的 link_id",
                    "decision": "aligned | unmatched",
                    "confidence": "0到1之间浮点数",
                    "reason": "一句中文简洁理由",
                }
            ]
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def review_scene_kb_mappings_with_llm(scene_df: pd.DataFrame, llm_cfg: LLMReviewConfig) -> Tuple[pd.DataFrame, List[Dict]]:
    if not llm_cfg.enabled or not llm_cfg.review_scene_kb_mapping or scene_df.empty:
        return scene_df, []

    out = scene_df.copy()
    audits: List[Dict] = []
    review_items: List[Dict] = []

    for idx, row in out.iterrows():
        score = _safe_float(row.get("kb_top1_score"), 0.0)
        candidates = json.loads(_safe_text(row.get("kb_topk_candidates")) or "[]")
        gap = 1.0
        if len(candidates) >= 2:
            gap = _safe_float(candidates[0].get("kb_score"), 0.0) - _safe_float(candidates[1].get("kb_score"), 0.0)
        needs_review = (
            llm_cfg.scene_score_low <= score <= llm_cfg.scene_score_high
            and gap <= llm_cfg.scene_gap_threshold
            and len(review_items) < llm_cfg.max_scene_items
        )
        if not needs_review:
            continue

        review_items.append(
            {
                "row_idx": idx,
                "scene_id": _safe_text(row.get("scene_id")),
                "scene_payload": {
                    "scene_id": _safe_text(row.get("scene_id")),
                    "modality": _safe_text(row.get("modality")),
                    "scene_name": _safe_text(row.get("scene_name")),
                    "scene_summary": _safe_text(row.get("scene_summary")),
                    "scene_characters": _coerce_to_str_list(row.get("scene_characters")),
                    "scene_locations": _coerce_to_str_list(row.get("scene_locations")),
                    "source_title": _safe_text(row.get("source_title")),
                },
                "candidates": candidates[:5],
            }
        )

    if not review_items:
        return out, audits

    batch_size = max(1, int(llm_cfg.scene_batch_size))
    total_batches = math.ceil(len(review_items) / batch_size)
    print(
        f"[LLM-REVIEW] scene->kb 待复核 {len(review_items)} 条，batch_size={batch_size}，共 {total_batches} 批",
        flush=True,
    )
    progress = ProgressPrinter(total_batches, "LLM 分批复核 scene_event -> KB 映射")

    for batch_idx in range(total_batches):
        start = batch_idx * batch_size
        end = min(len(review_items), start + batch_size)
        batch = review_items[start:end]
        prompt_items = [
            {
                "scene_event": item["scene_payload"],
                "candidates": item["candidates"],
            }
            for item in batch
        ]
        if llm_cfg.verbose:
            print(
                f"[LLM-REVIEW] scene->kb 批次 {batch_idx + 1}/{total_batches} | items={len(batch)} | processed={end}/{len(review_items)}",
                flush=True,
            )
        try:
            obj = _call_dashscope_json(_build_scene_kb_batch_review_prompt(prompt_items), llm_cfg)
            results = obj.get("results", []) if isinstance(obj, dict) else []
            if not isinstance(results, list):
                results = []
        except Exception as e:
            for item in batch:
                audits.append(
                    {
                        "type": "scene_kb_review",
                        "scene_id": item["scene_id"],
                        "status": "error",
                        "error": _safe_text(e),
                        "batch_index": batch_idx + 1,
                    }
                )
            progress.step()
            if llm_cfg.scene_pause_between_batches_sec > 0:
                time.sleep(llm_cfg.scene_pause_between_batches_sec)
            continue

        result_map = {
            _safe_text(x.get("scene_id")): x
            for x in results
            if isinstance(x, dict) and _safe_text(x.get("scene_id"))
        }

        for item in batch:
            row_idx = item["row_idx"]
            scene_id = item["scene_id"]
            candidates = item["candidates"]
            obj_item = result_map.get(scene_id, {})
            best_kb_event_id = _safe_text(obj_item.get("best_kb_event_id"))
            decision = _safe_text(obj_item.get("decision")).lower()
            conf = max(0.0, min(1.0, _safe_float(obj_item.get("confidence"), 0.0)))
            reason = _safe_text(obj_item.get("reason"))
            valid_candidate_ids = {str(c.get("kb_event_id")) for c in candidates}

            if best_kb_event_id and best_kb_event_id in valid_candidate_ids and decision == "aligned" and conf >= llm_cfg.accept_if_aligned_conf_ge:
                chosen = next((c for c in candidates if _safe_text(c.get("kb_event_id")) == best_kb_event_id), None)
                if chosen is not None:
                    out.at[row_idx, "kb_event_id"] = _safe_text(chosen.get("kb_event_id"))
                    out.at[row_idx, "kb_event_name"] = _safe_text(chosen.get("kb_event_name"))
                    out.at[row_idx, "kb_top1_score"] = max(_safe_float(chosen.get("kb_score"), 0.0), conf)
                    out.at[row_idx, "timeline_id"] = _timeline_id_from_ref(_safe_text(chosen.get("timeline_ref")))
            elif decision == "unmatched" and conf >= llm_cfg.accept_if_aligned_conf_ge:
                out.at[row_idx, "kb_event_id"] = ""
                out.at[row_idx, "kb_event_name"] = ""
                out.at[row_idx, "kb_top1_score"] = 0.0
                out.at[row_idx, "timeline_id"] = "unknown"

            audits.append(
                {
                    "type": "scene_kb_review",
                    "scene_id": scene_id,
                    "status": "ok" if obj_item else "missing_result",
                    "batch_index": batch_idx + 1,
                    "llm_best_kb_event_id": best_kb_event_id,
                    "llm_decision": decision,
                    "llm_confidence": round(conf, 6),
                    "llm_reason": reason,
                }
            )
        progress.step()
        if llm_cfg.scene_pause_between_batches_sec > 0:
            time.sleep(llm_cfg.scene_pause_between_batches_sec)
    return out, audits


def _build_event_side_payload_from_scene(scene_row: Dict, atomic_map: Dict[str, Dict]) -> Dict:
    member_ueids = _coerce_to_str_list(scene_row.get("member_ueids"))
    members = [atomic_map[u] for u in member_ueids if u in atomic_map]
    representative = members[0] if members else {}
    payload = {
        "scene_id": _safe_text(scene_row.get("scene_id")),
        "scene_name": _safe_text(scene_row.get("scene_name")),
        "scene_summary": _safe_text(scene_row.get("scene_summary")),
        "source_path": _safe_text(scene_row.get("source_path")),
        "member_count": _safe_int(scene_row.get("member_count"), len(members)),
        "members": [
            {
                "ueid": _safe_text(m.get("ueid")),
                "event_name": _compact_title(m.get("action"), m.get("event_summary"), m.get("semantic_core")),
                "source_text": _safe_text(m.get("source_text")),
                "source_path": _safe_text(m.get("source_path")),
            }
            for m in members
        ],
        "representative": {
            "ueid": _safe_text(representative.get("ueid")),
            "source_text": _safe_text(representative.get("source_text")),
            "source_path": _safe_text(representative.get("source_path")),
        },
    }
    if _safe_text(scene_row.get("modality")) == "text":
        payload["chapter_id"] = _safe_text(scene_row.get("chapter_id"))
        payload["chapter_title"] = _safe_text(scene_row.get("chapter_title"))
    else:
        payload["episode_id"] = _safe_text(scene_row.get("episode_id"))
        payload["episode_title"] = _safe_text(scene_row.get("episode_title"))
        payload["video_source_path"] = _safe_text(scene_row.get("source_path"))
    return payload


def build_kb_event_nodes_json(kb_df: pd.DataFrame, scene_with_kb: pd.DataFrame, out_json: Path) -> List[Dict]:
    kb_map = kb_df.set_index("kb_event_id").to_dict(orient="index")
    items: List[Dict] = []
    for kb_event_id, block in scene_with_kb.groupby("kb_event_id", dropna=False):
        kb_event_id = _safe_text(kb_event_id)
        if not kb_event_id:
            continue
        kb_info = kb_map.get(kb_event_id, {})
        text_members = block[block["modality"].astype(str) == "text"]
        video_members = block[block["modality"].astype(str) == "video"]
        chars = _dedup_keep_order(
            c
            for cell in block["scene_characters"].tolist()
            for c in _coerce_to_str_list(cell)
        )
        locs = _dedup_keep_order(
            c
            for cell in block["scene_locations"].tolist()
            for c in _coerce_to_str_list(cell)
        )
        items.append(
            {
                "kb_event_id": kb_event_id,
                "event_name": _safe_text(kb_info.get("事件名")),
                "event_aliases": _safe_text(kb_info.get("event_aliases")),
                "timeline_ref": _safe_text(kb_info.get("timeline_ref")),
                "timeline_id": _timeline_id_from_ref(_safe_text(kb_info.get("timeline_ref"))),
                "event_detail": _safe_text(kb_info.get("事件详情")),
                "is_cross_modal_anchor": _safe_text(kb_info.get("is_cross_modal_anchor")),
                "main_characters": _split_items(_safe_text(kb_info.get("main_characters"))),
                "main_locations": _split_items(_safe_text(kb_info.get("main_locations"))),
                "mapped_text_scene_count": int(len(text_members)),
                "mapped_video_scene_count": int(len(video_members)),
                "mapped_text_scene_ids": text_members["scene_id"].astype(str).tolist(),
                "mapped_video_scene_ids": video_members["scene_id"].astype(str).tolist(),
                "observed_characters": chars,
                "observed_locations": locs,
            }
        )
    items.sort(key=lambda x: (x["timeline_id"] == "unknown", x["timeline_id"], x["kb_event_id"]))
    out_json.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    return items


def build_cross_modal_scene_links(
    scene_with_kb: pd.DataFrame,
    atomic_with_kb: pd.DataFrame,
    out_json: Path,
    cfg: KBMappingConfig,
) -> List[Dict]:
    work = scene_with_kb.copy()
    work = work[work["kb_event_id"].fillna("").astype(str) != ""].copy()
    atomic_map = atomic_with_kb.set_index("ueid").to_dict(orient="index")

    items: List[Dict] = []
    link_idx = 1
    for kb_event_id, block in work.groupby("kb_event_id", sort=False):
        text_block = block[block["modality"].astype(str) == "text"].copy()
        video_block = block[block["modality"].astype(str) == "video"].copy()
        if text_block.empty or video_block.empty:
            continue

        text_block = text_block.sort_values(["kb_top1_score", "member_count", "start_order"], ascending=[False, False, True]).head(cfg.top_k_links_per_kb)
        video_block = video_block.sort_values(["kb_top1_score", "member_count", "start_order"], ascending=[False, False, True]).head(cfg.top_k_links_per_kb)

        for _, text_row in text_block.iterrows():
            for _, video_row in video_block.iterrows():
                text_chars = _coerce_to_str_list(text_row.get("scene_characters"))
                video_chars = _coerce_to_str_list(video_row.get("scene_characters"))
                text_locs = _coerce_to_str_list(text_row.get("scene_locations"))
                video_locs = _coerce_to_str_list(video_row.get("scene_locations"))

                char_overlap = _jaccard(text_chars, video_chars)
                loc_overlap = _jaccard(text_locs, video_locs)
                score = round(
                    0.45 * _safe_float(text_row.get("kb_top1_score"), 0.0)
                    + 0.35 * _safe_float(video_row.get("kb_top1_score"), 0.0)
                    + 0.12 * char_overlap
                    + 0.08 * loc_overlap,
                    6,
                )
                if score < cfg.min_cross_modal_score:
                    continue

                kb_name = _safe_text(text_row.get("kb_event_name") or video_row.get("kb_event_name"))
                timeline_id = _safe_text(text_row.get("timeline_id") or video_row.get("timeline_id")) or "unknown"
                representative_text_payload = _build_event_side_payload_from_scene(text_row.to_dict(), atomic_map)
                representative_video_payload = _build_event_side_payload_from_scene(video_row.to_dict(), atomic_map)

                items.append(
                    {
                        "link_id": f"SCL_{link_idx:05d}",
                        "kb_event_id": _safe_text(kb_event_id),
                        "event_name": _compact_title(kb_name, _safe_text(text_row.get("scene_name")), _safe_text(video_row.get("scene_name"))),
                        "canonical_event_name": kb_name,
                        "alignment_score": score,
                        "alignment_type": "kb_scene_link",
                        "relation": "shared_kb_event",
                        "text": representative_text_payload,
                        "video": representative_video_payload,
                        "shared": {
                            "characters": _dedup_keep_order(sorted(list(set(text_chars) & set(video_chars)))),
                            "locations": _dedup_keep_order(sorted(list(set(text_locs) & set(video_locs)))),
                            "timeline_id": timeline_id,
                        },
                        "kb_event": {
                            "kb_event_id": _safe_text(kb_event_id),
                            "event_name": kb_name,
                            "kb_score_text": round(_safe_float(text_row.get("kb_top1_score"), 0.0), 6),
                            "kb_score_video": round(_safe_float(video_row.get("kb_top1_score"), 0.0), 6),
                        },
                    }
                )
                link_idx += 1

    items.sort(key=lambda x: (-_safe_float(x.get("alignment_score")), x.get("kb_event_id", "")))
    out_json.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    return items


def review_cross_modal_links_with_llm(links: List[Dict], llm_cfg: LLMReviewConfig) -> Tuple[List[Dict], List[Dict]]:
    if not llm_cfg.enabled or not llm_cfg.review_cross_modal_links or not links:
        return links, []

    out: List[Dict] = []
    audits: List[Dict] = []
    review_items: List[Dict] = []

    for link in links:
        score = _safe_float(link.get("alignment_score"), 0.0)
        needs_review = (
            llm_cfg.link_score_low <= score <= llm_cfg.link_score_high
            and len(review_items) < llm_cfg.max_link_items
        )
        if needs_review:
            review_items.append({"link": link})
        else:
            out.append(link)

    if not review_items:
        out.sort(key=lambda x: (-_safe_float(x.get("alignment_score")), x.get("kb_event_id", "")))
        return out, audits

    batch_size = max(1, int(llm_cfg.link_batch_size))
    total_batches = math.ceil(len(review_items) / batch_size)
    print(
        f"[LLM-REVIEW] cross-modal link 待复核 {len(review_items)} 条，batch_size={batch_size}，共 {total_batches} 批",
        flush=True,
    )
    progress = ProgressPrinter(total_batches, "LLM 分批复核跨模态 scene_link")

    for batch_idx in range(total_batches):
        start = batch_idx * batch_size
        end = min(len(review_items), start + batch_size)
        batch = review_items[start:end]
        prompt_items = [item["link"] for item in batch]
        if llm_cfg.verbose:
            print(
                f"[LLM-REVIEW] cross-modal 批次 {batch_idx + 1}/{total_batches} | items={len(batch)} | processed={end}/{len(review_items)}",
                flush=True,
            )
        try:
            obj = _call_dashscope_json(_build_cross_modal_batch_review_prompt(prompt_items), llm_cfg)
            results = obj.get("results", []) if isinstance(obj, dict) else []
            if not isinstance(results, list):
                results = []
        except Exception as e:
            for item in batch:
                link = item["link"]
                audits.append(
                    {
                        "type": "cross_modal_link_review",
                        "link_id": _safe_text(link.get("link_id")),
                        "status": "error",
                        "error": _safe_text(e),
                        "batch_index": batch_idx + 1,
                    }
                )
                out.append(link)
            progress.step()
            if llm_cfg.link_pause_between_batches_sec > 0:
                time.sleep(llm_cfg.link_pause_between_batches_sec)
            continue

        result_map = {
            _safe_text(x.get("link_id")): x
            for x in results
            if isinstance(x, dict) and _safe_text(x.get("link_id"))
        }

        for item in batch:
            link = item["link"]
            link_id = _safe_text(link.get("link_id"))
            obj_item = result_map.get(link_id, {})
            score = _safe_float(link.get("alignment_score"), 0.0)
            decision = _safe_text(obj_item.get("decision")).lower()
            conf = max(0.0, min(1.0, _safe_float(obj_item.get("confidence"), 0.0)))
            reason = _safe_text(obj_item.get("reason"))
            if decision == "unmatched" and conf >= llm_cfg.accept_if_aligned_conf_ge:
                audits.append(
                    {
                        "type": "cross_modal_link_review",
                        "link_id": link_id,
                        "status": "drop",
                        "batch_index": batch_idx + 1,
                        "llm_confidence": round(conf, 6),
                        "llm_reason": reason,
                    }
                )
                continue

            if decision == "aligned" and conf >= llm_cfg.accept_if_aligned_conf_ge:
                link = {
                    **link,
                    "alignment_score": round(max(score, conf), 6),
                    "llm_review": {"decision": decision, "confidence": round(conf, 6), "reason": reason},
                }
            else:
                link = {
                    **link,
                    "llm_review": {"decision": decision, "confidence": round(conf, 6), "reason": reason},
                }
            out.append(link)
            audits.append(
                {
                    "type": "cross_modal_link_review",
                    "link_id": _safe_text(link.get("link_id")),
                    "status": "keep" if obj_item else "missing_result",
                    "batch_index": batch_idx + 1,
                    "llm_confidence": round(conf, 6),
                    "llm_reason": reason,
                }
            )
        progress.step()
        if llm_cfg.link_pause_between_batches_sec > 0:
            time.sleep(llm_cfg.link_pause_between_batches_sec)

    out.sort(key=lambda x: (-_safe_float(x.get("alignment_score")), x.get("kb_event_id", "")))
    return out, audits


def export_atomic_events_json(events_with_kb: pd.DataFrame, out_json: Path) -> List[Dict]:
    rows = []
    for _, row in events_with_kb.iterrows():
        rows.append(
            {
                "ueid": _safe_text(row.get("ueid")),
                "modality": _safe_text(row.get("modality")),
                "event_name": _compact_title(row.get("action"), row.get("event_summary"), row.get("semantic_core")),
                "action": _safe_text(row.get("action")),
                "event_summary": _safe_text(row.get("event_summary")),
                "source_text": _safe_text(row.get("source_text")),
                "source_id": _safe_text(row.get("source_id")),
                "source_title": _safe_text(row.get("source_title")),
                "source_path": _safe_text(row.get("source_path")),
                "timeline_id": _safe_text(row.get("timeline_id")) or "unknown",
                "characters": _split_items(_safe_text(row.get("characters"))),
                "locations": _split_items(_safe_text(row.get("location"))),
                "kb_event_id": _safe_text(row.get("kb_event_id")),
                "kb_event_name": _safe_text(row.get("kb_event_name")),
                "kb_top1_score": round(_safe_float(row.get("kb_top1_score")), 6),
                "kb_topk_candidates": json.loads(_safe_text(row.get("kb_topk_candidates")) or "[]"),
            }
        )
    out_json.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return rows


def export_scene_events_json(scene_df: pd.DataFrame, out_json: Path) -> List[Dict]:
    items = []
    for _, row in scene_df.iterrows():
        items.append(
            {
                "scene_id": _safe_text(row.get("scene_id")),
                "modality": _safe_text(row.get("modality")),
                "scene_name": _safe_text(row.get("scene_name")),
                "scene_summary": _safe_text(row.get("scene_summary")),
                "source_id": _safe_text(row.get("source_id")),
                "source_title": _safe_text(row.get("source_title")),
                "source_path": _safe_text(row.get("source_path")),
                "member_ueids": _coerce_to_str_list(row.get("member_ueids")),
                "member_count": _safe_int(row.get("member_count"), 0),
                "timeline_id": _safe_text(row.get("timeline_id")) or "unknown",
                "scene_characters": _coerce_to_str_list(row.get("scene_characters")),
                "scene_locations": _coerce_to_str_list(row.get("scene_locations")),
                "kb_event_id": _safe_text(row.get("kb_event_id")),
                "kb_event_name": _safe_text(row.get("kb_event_name")),
                "kb_top1_score": round(_safe_float(row.get("kb_top1_score")), 6),
                "kb_topk_candidates": json.loads(_safe_text(row.get("kb_topk_candidates")) or "[]"),
                "chapter_id": _safe_text(row.get("chapter_id")),
                "chapter_title": _safe_text(row.get("chapter_title")),
                "episode_id": _safe_text(row.get("episode_id")),
                "episode_title": _safe_text(row.get("episode_title")),
            }
        )
    out_json.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    return items


def run_kb_scene_mapping_pipeline(
    unified_events_csv: Path,
    kb_events_csv: Path,
    output_dir: Path,
    config: KBMappingConfig,
    llm_review_cfg: Optional[LLMReviewConfig] = None,
) -> KBSceneOutputs:
    _ensure_dir(output_dir)

    p_kb_nodes = output_dir / "kb_event_nodes.json"
    p_atomic_csv = output_dir / "atomic_events_with_kb.csv"
    p_atomic_json = output_dir / "atomic_events_with_kb.json"
    p_scene_json = output_dir / "scene_events.json"
    p_scene_kb_json = output_dir / "scene_events_with_kb.json"
    p_links = output_dir / "cross_modal_scene_links.json"
    p_llm_audit = output_dir / "llm_review_audit.json"
    p_cfg = output_dir / "kb_scene_mapping_run_config.json"

    print("[PIPELINE] 阶段 1/6：读取原子事件与知识库", flush=True)
    events_df = load_atomic_events(unified_events_csv)
    kb_df = load_kb_events(kb_events_csv)

    print("[PIPELINE] 阶段 2/6：原子事件匹配到知识库规范事件", flush=True)
    atomic_with_kb = map_atomic_events_to_kb(events_df, kb_df, config)
    atomic_with_kb.to_csv(p_atomic_csv, index=False, encoding=DEFAULT_ENCODING)
    export_atomic_events_json(atomic_with_kb, p_atomic_json)

    print("[PIPELINE] 阶段 3/6：原子事件聚类为 scene_event", flush=True)
    scene_df = build_scene_events(atomic_with_kb, config)
    export_scene_events_json(scene_df, p_scene_json)

    print("[PIPELINE] 阶段 4/6：scene_event 匹配知识库规范事件", flush=True)
    scene_with_kb = map_scene_events_to_kb(scene_df, kb_df, config)

    llm_cfg = llm_review_cfg or LLMReviewConfig(enabled=False)
    llm_audits: List[Dict] = []
    scene_with_kb, scene_llm_audits = review_scene_kb_mappings_with_llm(scene_with_kb, llm_cfg)
    llm_audits.extend(scene_llm_audits)
    export_scene_events_json(scene_with_kb, p_scene_kb_json)

    print("[PIPELINE] 阶段 5/6：生成知识库节点与跨模态 scene_link", flush=True)
    build_kb_event_nodes_json(kb_df, scene_with_kb, p_kb_nodes)
    links = build_cross_modal_scene_links(scene_with_kb, atomic_with_kb, p_links, config)

    print("[PIPELINE] 阶段 6/6：可选 LLM 复核跨模态 scene_link", flush=True)
    links, link_llm_audits = review_cross_modal_links_with_llm(links, llm_cfg)
    llm_audits.extend(link_llm_audits)
    p_links.write_text(json.dumps(links, ensure_ascii=False, indent=2), encoding="utf-8")
    p_llm_audit.write_text(json.dumps(llm_audits, ensure_ascii=False, indent=2), encoding="utf-8")

    p_cfg.write_text(
        json.dumps(
            {
                "kb_mapping_config": asdict(config),
                "llm_review_config": asdict(llm_cfg),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return KBSceneOutputs(
        kb_event_nodes_json=p_kb_nodes,
        atomic_events_with_kb_csv=p_atomic_csv,
        atomic_events_with_kb_json=p_atomic_json,
        scene_events_json=p_scene_json,
        scene_events_with_kb_json=p_scene_kb_json,
        cross_modal_scene_links_json=p_links,
        llm_review_audit_json=p_llm_audit,
        run_config_json=p_cfg,
    )
