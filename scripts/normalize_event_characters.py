"""将事件 JSON 中 events[].characters 按 character_kb.json 统一为标准名。

- 已在知识库 canonical_name：不变
- 命中 aliases：替换为对应 canonical_name
- 未出现在知识库：保持原名称（不改为 unknown）

若某条事件的 characters 里仍含字面量 unknown（例如曾用旧版脚本写过），
会尝试用 unified_events.json 里同一路径、同一 event_id 的 characters 替换后再规范化；
平时以当前 JSON 内字段为准。
"""
from __future__ import annotations

import json
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
KB_PATH = BASE_DIR / "知识库" / "人物知识库" / "character_kb.json"
UNIFIED_PATH = BASE_DIR / "unified_events" / "unified_events.json"
DIRS = [
    BASE_DIR / "剧版红楼梦" / "hongloumeng_json",
    BASE_DIR / "红楼梦文本" / "hongloumeng_txt_json",
]


def load_kb_maps(kb_path: Path) -> tuple[set[str], dict[str, str]]:
    data = json.loads(kb_path.read_text(encoding="utf-8"))
    canonical: set[str] = set()
    alias_to_canonical: dict[str, str] = {}
    for entry in data:
        c = entry["canonical_name"]
        canonical.add(c)
        for a in entry.get("aliases") or []:
            alias_to_canonical[a] = c
    return canonical, alias_to_canonical


def load_unified_characters_index(unified_path: Path) -> dict[tuple[str, str], list]:
    """(规范化后的 source_path 字符串, event_id) -> characters 列表。"""
    if not unified_path.is_file():
        return {}
    data = json.loads(unified_path.read_text(encoding="utf-8"))
    index: dict[tuple[str, str], list] = {}
    for ev in data:
        sp = ev.get("source_path")
        eid = ev.get("event_id")
        if not sp or not eid:
            continue
        key = (str(Path(sp).resolve()), str(eid))
        index[key] = list(ev.get("characters") or [])
    return index


def normalize_character_name(
    name: str, canonical: set[str], alias_to_canonical: dict[str, str]
) -> str:
    s = name.strip()
    if s in canonical:
        return s
    if s in alias_to_canonical:
        return alias_to_canonical[s]
    return s


def process_file(
    path: Path,
    canonical: set[str],
    alias_to_canonical: dict[str, str],
    unified_index: dict[tuple[str, str], list],
) -> bool:
    path_resolved = str(path.resolve())
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    changed = False
    events = data.get("events")
    if not isinstance(events, list):
        return False
    for ev in events:
        ch = ev.get("characters")
        if not isinstance(ch, list):
            continue
        eid = ev.get("event_id")
        eid_str = str(eid) if eid is not None else ""
        raw = ch
        if unified_index and any(
            isinstance(x, str) and x.strip() == "unknown" for x in ch
        ):
            fallback = unified_index.get((path_resolved, eid_str))
            if fallback is not None:
                raw = fallback
        new_list = []
        for item in raw:
            if isinstance(item, str):
                n = normalize_character_name(item, canonical, alias_to_canonical)
                new_list.append(n)
            else:
                new_list.append(item)
        if new_list != ch:
            changed = True
            ev["characters"] = new_list
    if changed:
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return changed


def main() -> None:
    canonical, alias_to_canonical = load_kb_maps(KB_PATH)
    unified_index = load_unified_characters_index(UNIFIED_PATH)
    total_files = 0
    modified = 0
    for root in DIRS:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.json")):
            total_files += 1
            if process_file(path, canonical, alias_to_canonical, unified_index):
                modified += 1
    print(
        f"扫描 {total_files} 个 JSON，改写 {modified} 个文件。"
        f"（unified 索引条目 {len(unified_index)}）"
    )


if __name__ == "__main__":
    main()
