"""
统一事件表示：结构统一、规则 semantic_core、关键词、加载与单条组装（不含 LLM 调用）。
"""
import json
import re
from pathlib import Path
from typing import Any

# =========================
# 文本清洗与工具函数
# =========================
CHINESE_PUNCT_PATTERN = re.compile(r"[，。！？；：、“”‘’（）《》【】—…·]")
MULTI_SPACE_PATTERN = re.compile(r"\s+")


def to_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text if text else None
    text = str(value).strip()
    return text if text else None


def clean_text(text: str | None) -> str | None:
    if not text:
        return None
    text = CHINESE_PUNCT_PATTERN.sub(" ", text)
    text = re.sub(r"[,.!?;:\"'()\[\]{}<>/\-]+", " ", text)
    text = MULTI_SPACE_PATTERN.sub(" ", text).strip()
    return text if text else None


def normalize_characters(characters: Any) -> list[str]:
    if not characters:
        return []

    if isinstance(characters, str):
        candidates = re.split(r"[、,，/;；\s]+", characters.strip())
    elif isinstance(characters, list):
        candidates = []
        for item in characters:
            if isinstance(item, str):
                candidates.extend(re.split(r"[、,，/;；\s]+", item.strip()))
            elif item is not None:
                candidates.append(str(item).strip())
    else:
        candidates = [str(characters).strip()]

    unique_chars = []
    seen = set()
    for c in candidates:
        c = c.strip()
        if not c or c in seen:
            continue
        seen.add(c)
        unique_chars.append(c)
    return unique_chars


def normalize_event_id(event_id: Any, default_prefix: str = "E") -> str:
    event_id_str = to_str(event_id)
    if not event_id_str:
        return f"{default_prefix}00"

    match = re.search(r"(\d+)", event_id_str)
    if match:
        return f"{default_prefix}{int(match.group(1)):02d}"
    return event_id_str


def normalize_episode_id(episode_id: Any) -> str:
    eid = to_str(episode_id)
    if not eid:
        return "E00"
    m = re.search(r"(\d+)", eid)
    if m:
        return f"E{int(m.group(1)):02d}"
    return eid


def normalize_segment_id(segment_id: Any) -> str:
    sid = to_str(segment_id)
    if not sid:
        return "S00"
    m = re.search(r"(\d+)", sid)
    if m:
        return f"S{int(m.group(1)):02d}"
    return sid


def normalize_chapter_id(chapter_id: Any) -> str:
    cid = to_str(chapter_id)
    if not cid:
        return "C000"
    m = re.search(r"(\d+)", cid)
    if m:
        return f"C{int(m.group(1)):03d}"
    return cid


def dedupe_preserve_order(items: list[str]) -> list[str]:
    result = []
    seen = set()
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


KEYWORD_STOP = frozenset(
    {
        "的",
        "地",
        "得",
        "了",
        "着",
        "过",
        "与",
        "及",
        "和",
        "并",
        "而",
        "于",
        "在",
        "对",
        "向",
        "为",
        "将",
        "被",
        "所",
        "以",
        "其",
        "等",
        "某",
        "彼此",
        "互相",
        "随后",
        "于是",
        "接着",
        "之后",
        "当场",
        "开始",
        "继续",
        "随即",
        "此时",
        "彼时",
        "众人",
        "大家",
        "他们",
        "她们",
        "有人",
    }
)

KNOWN_HIGH_INFO_SUBSTRINGS = (
    "风月宝鉴",
    "通灵宝玉",
    "好了歌",
    "石头记",
    "金陵十二钗",
    "太虚幻境",
    "西厢记",
    "情僧录",
    "大观园",
    "荣国府",
    "宁国府",
)


def _han_len(s: str) -> int:
    return sum(1 for ch in s if "\u4e00" <= ch <= "\u9fff")


def clamp_semantic_core(text: str | None, max_han: int = 30) -> str | None:
    if not text:
        return None
    t = text.strip()
    t = re.sub(r'^[\"\'「『【]+', "", t)
    t = re.sub(r'[\"\'」』】]+$', "", t)
    t = re.sub(r"\s+", "", t)
    if not t:
        return None
    out = []
    n = 0
    for ch in t:
        if "\u4e00" <= ch <= "\u9fff":
            if n >= max_han:
                break
            n += 1
        out.append(ch)
    return "".join(out).strip("，。！？；：、")


def _shorten_summary_to_core(summary: str) -> str:
    s = CHINESE_PUNCT_PATTERN.sub("，", summary)
    s = s.split("，")[0].strip()
    return s[:20] if s else ""


def _extract_action_core_phrase(text: str | None, max_len: int = 8) -> str | None:
    if not text:
        return None
    t = text.strip()
    chunks = re.split(r"[，。！？；：、\n]+", t)
    chunk = next((c.strip() for c in chunks if c.strip()), t)
    chunk = re.sub(r"(互相|彼此|随后|于是|接着|之后|当场|开始|随即)", "", chunk)
    chunk = chunk.strip("，。 ")
    if not chunk:
        return None
    if len(chunk) > 12:
        chunk = chunk[-max_len:]
    chunk = re.sub(r"(的|地|得|了|着|过)$", "", chunk)
    if _han_len(chunk) < 2:
        return None
    return chunk


def _strip_leading_character_from_phrase(phrase: str, characters: list[str]) -> str:
    if not phrase or not characters:
        return phrase
    for name in sorted((c for c in characters if c), key=len, reverse=True):
        if phrase.startswith(name):
            return phrase[len(name) :].lstrip("，、 ")
    return phrase


def build_semantic_core_fallback(
    characters: list[str],
    location: str | None,
    action: str | None,
    event_summary: str | None,
) -> str:
    parts: list[str] = []

    if characters:
        if len(characters) >= 4:
            parts.append("众人")
        elif len(characters) == 2:
            parts.append(f"{characters[0]}与{characters[1]}")
        elif len(characters) == 3:
            parts.append(f"{characters[0]}等")
        else:
            parts.append(characters[0])

    action_core = _extract_action_core_phrase(action)
    if action_core:
        action_core = _strip_leading_character_from_phrase(action_core, characters)
        if action_core:
            parts.append(action_core)
    elif event_summary:
        action_core = _extract_action_core_phrase(event_summary)
        if action_core:
            action_core = _strip_leading_character_from_phrase(action_core, characters)
            if action_core:
                parts.append(action_core)

    loc = to_str(location)
    if loc and len(loc) <= 12:
        if parts:
            parts.append(f"于{loc}")
        else:
            parts.append(loc)

    core = "".join(parts)
    core = clamp_semantic_core(core, max_han=30) or ""

    summary = to_str(event_summary)
    if summary and core and (summary.startswith(core) or core == summary[: len(core)]):
        core = clamp_semantic_core(
            _extract_action_core_phrase(action or summary) or core,
            max_han=30,
        ) or core

    if not core and summary:
        core = clamp_semantic_core(_shorten_summary_to_core(summary), max_han=30) or ""

    return core or (clamp_semantic_core(action, max_han=30) or "事件推进")


def _normalize_keyword_token(token: str) -> str | None:
    t = token.strip()
    if not t or t in KEYWORD_STOP:
        return None
    if len(t) < 2:
        return None
    if len(t) > 10:
        t = t[:10]
    return t


def _compact_location_keyword(location: str | None) -> str | None:
    loc = to_str(location)
    if not loc:
        return None
    if len(loc) <= 8:
        return _normalize_keyword_token(loc)
    m = re.search(
        r"([\u4e00-\u9fff]{2,8})(?:府|园|院|房|斋|馆|峰|街|巷|衙|庙|亭|台|阁|殿)$",
        loc,
    )
    if m:
        return _normalize_keyword_token(m.group(0))
    return _normalize_keyword_token(loc[-8:])


def _action_keyword_fragments(action: str | None, max_fragments: int = 2) -> list[str]:
    if not action:
        return []
    a = action.strip()
    segs = re.split(r"[，。！？；：、/／\s]+", a)
    out: list[str] = []
    for seg in segs:
        seg = seg.strip()
        if not seg:
            continue
        seg = re.sub(
            r"^(互相|彼此|随后|于是|接着|之后|当场|开始|随即|众人|大家)", "", seg
        ).strip()
        if not seg:
            continue
        if len(seg) > 6:
            tail = seg[-4:]
            seg = tail if _han_len(tail) >= 2 else seg[-6:]
        tok = _normalize_keyword_token(seg)
        if tok:
            out.append(tok)
        if len(out) >= max_fragments:
            break
    return out


def _book_titles_from_text(text: str | None) -> list[str]:
    if not text:
        return []
    return [m.group(1).strip() for m in re.finditer(r"《([^》]{1,12})》", text)]


def _known_entities_from_summary(summary: str | None) -> list[str]:
    if not summary:
        return []
    found = []
    for name in KNOWN_HIGH_INFO_SUBSTRINGS:
        if name in summary:
            found.append(name)
    return found


def extract_compact_keywords(
    action: str | None,
    characters: list[str],
    location: str | None,
    event_summary: str | None,
    min_k: int = 4,
    max_k: int = 8,
) -> list[str]:
    kws: list[str] = []
    seen: set[str] = set()

    def add(x: str | None) -> None:
        if not x or x in seen:
            return
        nx = _normalize_keyword_token(x)
        if not nx:
            return
        seen.add(nx)
        kws.append(nx)

    for c in characters[:4]:
        add(c)

    loc_kw = _compact_location_keyword(location)
    if loc_kw:
        add(loc_kw)

    for frag in _action_keyword_fragments(action, max_fragments=2):
        add(frag)

    if event_summary:
        for title in _book_titles_from_text(event_summary):
            add(title)
        for ent in _known_entities_from_summary(event_summary):
            add(ent)

    if len(kws) < min_k and event_summary:
        summary_clean = re.sub(r"[，。！？；：、“”‘’（）《》\s]+", " ", event_summary)
        for raw in summary_clean.split():
            raw = raw.strip()
            if 2 <= len(raw) <= 6 and raw not in KEYWORD_STOP:
                add(raw)
            if len(kws) >= min_k:
                break

    if len(kws) < min_k and action:
        for frag in _action_keyword_fragments(action, max_fragments=4):
            add(frag)
            if len(kws) >= min_k:
                break

    return kws[:max_k]


def build_normalized_text(
    characters: list[str],
    location: str | None,
    action: str | None,
    event_summary: str | None,
) -> str:
    parts: list[str] = []

    if characters:
        parts.append(" ".join(characters))

    if location:
        parts.append(location)

    if action:
        parts.append(action)

    if event_summary:
        parts.append(event_summary)

    cleaned_parts = []
    for part in parts:
        cleaned = clean_text(part)
        if cleaned:
            cleaned_parts.append(cleaned)

    cleaned_parts = dedupe_preserve_order(cleaned_parts)
    return " ".join(cleaned_parts).strip()


def load_json_file(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_video_events(video_dir: Path) -> list[dict]:
    rows: list[dict] = []
    for json_path in sorted(video_dir.rglob("*.json")):
        try:
            data = load_json_file(json_path)
        except Exception:
            continue

        episode_id = data.get("episode_id")
        episode_title = data.get("episode_title")
        segment_id = data.get("segment_id")
        events = data.get("events") or []
        if not isinstance(events, list):
            continue

        for event in events:
            if not isinstance(event, dict):
                continue
            rows.append(
                {
                    "modality": "video",
                    "episode_id": episode_id,
                    "episode_title": episode_title,
                    "segment_id": segment_id,
                    "event": event,
                    "source_path": str(json_path),
                }
            )
    return rows


def load_text_events(text_dir: Path) -> list[dict]:
    rows: list[dict] = []
    for json_path in sorted(text_dir.rglob("*.json")):
        try:
            data = load_json_file(json_path)
        except Exception:
            continue

        chapter_id = data.get("chapter_id")
        chapter_title = data.get("chapter_title")
        events = data.get("events") or []
        if not isinstance(events, list):
            continue

        for event in events:
            if not isinstance(event, dict):
                continue
            rows.append(
                {
                    "modality": "text",
                    "chapter_id": chapter_id,
                    "chapter_title": chapter_title,
                    "event": event,
                    "source_path": str(json_path),
                }
            )
    return rows


def build_video_ueid(episode_id: Any, segment_id: Any, event_id: Any) -> str:
    ep = normalize_episode_id(episode_id)
    seg = normalize_segment_id(segment_id)
    ev = normalize_event_id(event_id)
    return f"V_{ep}_{seg}_{ev}"


def build_text_ueid(chapter_id: Any, event_id: Any) -> str:
    ch = normalize_chapter_id(chapter_id)
    ev = normalize_event_id(event_id)
    return f"T_{ch}_{ev}"


def build_unified_event(item: dict) -> dict:
    """
    单条 UEO：结构统一 + 规则 semantic_core + 关键词。
    """
    modality = item["modality"]
    event = item["event"]

    event_id = to_str(event.get("event_id")) or "E00"
    narrative_order = event.get("narrative_order")
    action = to_str(event.get("action"))
    characters = normalize_characters(event.get("characters"))
    location = to_str(event.get("location"))
    time_hint = event.get("time_hint")
    explicit_time = event.get("explicit_time")
    relation_to_previous = to_str(event.get("relation_to_previous"))
    event_summary = to_str(event.get("event_summary"))

    if modality == "video":
        episode_id = item.get("episode_id")
        segment_id = item.get("segment_id")
        source_id = f"{to_str(episode_id) or ''}_{to_str(segment_id) or ''}".strip("_")
        source_title = to_str(item.get("episode_title"))
        source_text = None
        ueid = build_video_ueid(episode_id, segment_id, event_id)
    else:
        chapter_id = item.get("chapter_id")
        source_id = to_str(chapter_id)
        source_title = to_str(item.get("chapter_title"))
        source_text = to_str(event.get("source_text"))
        ueid = build_text_ueid(chapter_id, event_id)

    normalized_text = build_normalized_text(
        characters=characters,
        location=location,
        action=action,
        event_summary=event_summary,
    )

    semantic_core = build_semantic_core_fallback(
        characters=characters,
        location=location,
        action=action,
        event_summary=event_summary,
    )

    keywords = extract_compact_keywords(
        action=action,
        characters=characters,
        location=location,
        event_summary=event_summary,
    )

    return {
        "ueid": ueid,
        "modality": modality,
        "source_id": source_id,
        "source_title": source_title,
        "event_id": event_id,
        "narrative_order": narrative_order,
        "action": action,
        "characters": characters,
        "location": location,
        "time_hint": time_hint,
        "explicit_time": explicit_time,
        "relation_to_previous": relation_to_previous,
        "event_summary": event_summary,
        "source_text": source_text,
        "normalized_text": normalized_text,
        "semantic_core": semantic_core,
        "keywords": keywords,
        "source_path": item.get("source_path"),
    }
