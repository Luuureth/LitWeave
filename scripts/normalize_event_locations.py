"""将事件 JSON 中 events[].location 按 location_kb.json 统一为标准地名。

- 与 canonical_location 一致：输出知识库中的标准写法（去除首尾空白后匹配）
- 命中 aliases：替换为对应 canonical_location
- 不在知识库：保持原字段内容不变（含空白等）
"""
from __future__ import annotations

import json
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
KB_PATH = BASE_DIR / "知识库" / "地点知识库" / "location_kb.json"
DIRS = [
    BASE_DIR / "剧版红楼梦" / "hongloumeng_json",
    BASE_DIR / "红楼梦文本" / "hongloumeng_txt_json",
]


def load_kb_maps(kb_path: Path) -> tuple[set[str], dict[str, str]]:
    root = json.loads(kb_path.read_text(encoding="utf-8"))
    rows = root.get("locations") or []
    canonical: set[str] = set()
    alias_to_canonical: dict[str, str] = {}
    for entry in rows:
        c = entry["canonical_location"]
        canonical.add(c)
        for a in entry.get("aliases") or []:
            alias_to_canonical[a] = c
    return canonical, alias_to_canonical


def normalize_location_value(
    loc: str | None,
    canonical: set[str],
    alias_to_canonical: dict[str, str],
) -> str | None:
    if loc is None:
        return None
    if not isinstance(loc, str):
        return loc  # type: ignore[return-value]
    trimmed = loc.strip()
    if not trimmed:
        return loc
    if trimmed in canonical:
        return trimmed
    if trimmed in alias_to_canonical:
        return alias_to_canonical[trimmed]
    return loc


def process_file(
    path: Path,
    canonical: set[str],
    alias_to_canonical: dict[str, str],
) -> bool:
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    changed = False
    events = data.get("events")
    if not isinstance(events, list):
        return False
    for ev in events:
        if "location" not in ev:
            continue
        old = ev.get("location")
        new = normalize_location_value(old, canonical, alias_to_canonical)
        if new != old:
            changed = True
            ev["location"] = new
    if changed:
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return changed


def main() -> None:
    canonical, alias_to_canonical = load_kb_maps(KB_PATH)
    total_files = 0
    modified = 0
    for root in DIRS:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.json")):
            total_files += 1
            if process_file(path, canonical, alias_to_canonical):
                modified += 1
    print(f"扫描 {total_files} 个 JSON，改写 {modified} 个文件。")


if __name__ == "__main__":
    main()
