import csv
import json
import re
from pathlib import Path


BASE = Path(__file__).resolve().parent.parent
KB = BASE / "知识库" / "人物知识库" / "character_kb.json"
TABLE = BASE / "知识库" / "人物知识库" / "红楼梦人物表.csv"
DIRS = [
    BASE / "剧版红楼梦" / "hongloumeng_json",
    BASE / "红楼梦文本" / "hongloumeng_txt_json",
]


def build_known_names() -> set[str]:
    known: set[str] = set()
    kb_data = json.loads(KB.read_text(encoding="utf-8"))
    for row in kb_data:
        c = (row.get("canonical_name") or "").strip()
        if c:
            known.add(c)
        for a in (row.get("aliases") or []):
            if isinstance(a, str) and a.strip():
                known.add(a.strip())

    with TABLE.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            n = (row.get("姓名") or "").strip()
            if n:
                known.add(n)
    return known


def collect_unknown_counts(known: set[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for root in DIRS:
        for path in root.rglob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            events = data.get("events") if isinstance(data, dict) else None
            if not isinstance(events, list):
                continue
            for ev in events:
                if not isinstance(ev, dict):
                    continue
                chars = ev.get("characters")
                if not isinstance(chars, list):
                    continue
                for name in chars:
                    if isinstance(name, str):
                        s = name.strip()
                        if s and s not in known:
                            counts[s] = counts.get(s, 0) + 1
    return counts


PATTERNS = [
    r"母亲$",
    r"之母$",
    r"母$",
    r"家属$",
    r"娘子$",
    r"夫人$",
    r"二夫人$",
    r"奶妈$",
    r"姨奶奶$",
    r"舅母$",
    r"大舅母$",
    r"二舅母$",
    r"老爷$",
    r"大爷$",
    r"二爷$",
    r"太太$",
    r"奶奶$",
    r"媳妇$",
]

EXTRA_INCLUDE = {
    "邢王二夫人",
    "贾芸母",
    "贾芸之母",
    "袭人母亲",
    "袭人之母",
    "甄家娘子",
    "甄府管家娘子",
    "金钏儿母亲",
    "赖升媳妇",
    "赖大母亲",
    "郑好时媳妇",
    "金文翔的媳妇",
    "吴大娘",
    "周奶妈",
}

SUGGESTIONS = {
    "袭人母亲": "可能对应“袭人之母”（建议并入同一规范项）",
    "袭人之母": "可能对应“袭人母亲”（建议并入同一规范项）",
    "贾芸母": "可能对应“贾芸之母”（建议二者归并）",
    "贾芸之母": "可能对应“贾芸母”（建议二者归并）",
    "邢王二夫人": "复合指代，建议拆分为“邢夫人、王夫人”",
    "甄家娘子": "可能对应“封氏”（需你确认）",
}


def main() -> None:
    known = build_known_names()
    unknown_counts = collect_unknown_counts(known)

    b_list: list[tuple[str, int, str]] = []
    for name, freq in unknown_counts.items():
        is_b = any(re.search(p, name) for p in PATTERNS) or name in EXTRA_INCLUDE
        if is_b:
            b_list.append((name, freq, SUGGESTIONS.get(name, "")))

    b_list.sort(key=lambda x: (-x[1], x[0]))
    print(f"B_TOTAL\t{len(b_list)}")
    for i, (name, freq, hint) in enumerate(b_list, start=1):
        print(f"{i}\t{name}\t{freq}\t{hint}")


if __name__ == "__main__":
    main()
