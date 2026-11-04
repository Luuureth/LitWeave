from __future__ import annotations

from pathlib import Path


CHAPTERS = [3, 6, 8, 9, 18, 19, 20, 26, 29, 34, 37, 52, 54, 55, 60, 62, 64, 71, 72]

BASE_DIR = Path(__file__).resolve().parent
SRC_DIR = BASE_DIR / "hongloumeng_txt"
OUT_DIR = SRC_DIR / "split_parts"


def normalize_paragraphs(lines: list[str]) -> list[str]:
    paragraphs: list[str] = []
    buf: list[str] = []
    for line in lines:
        if line.strip() == "":
            if buf:
                paragraphs.append("\n".join(buf).strip())
                buf = []
            continue
        buf.append(line.rstrip())
    if buf:
        paragraphs.append("\n".join(buf).strip())
    return [p for p in paragraphs if p]


def boundary_quality(prev_para: str, next_para: str) -> int:
    score = 0

    if prev_para.endswith(("。", "！", "？", "”", "』", "」")):
        score += 6
    elif prev_para.endswith(("；", "：")):
        score += 3
    else:
        score -= 2

    good_starts = (
        "且说",
        "话说",
        "却说",
        "次日",
        "至次日",
        "一时",
        "不一时",
        "少时",
        "再说",
        "又说",
    )
    if next_para.startswith(good_starts):
        score += 8

    # 尽量不要在非常短的小段前后切
    if len(prev_para) < 40:
        score -= 3
    if len(next_para) < 40:
        score -= 3

    return score


def choose_split_index(paragraphs: list[str]) -> int:
    if len(paragraphs) < 2:
        return 1

    lengths = [len(p) for p in paragraphs]
    total = sum(lengths)
    target = total / 2

    cum = 0
    best_idx = 1
    best_score = None

    for i in range(1, len(paragraphs)):
        cum += lengths[i - 1]
        left = cum
        right = total - cum
        # 两侧至少占 30%，避免一边太短
        if left < total * 0.30 or right < total * 0.30:
            continue

        distance_penalty = abs(cum - target) / max(total, 1) * 100
        quality_bonus = boundary_quality(paragraphs[i - 1], paragraphs[i])
        score = distance_penalty - quality_bonus

        if best_score is None or score < best_score:
            best_score = score
            best_idx = i

    return best_idx


def build_text(title: str, paras: list[str]) -> str:
    if not paras:
        return f"{title}\n"
    return f"{title}\n\n" + "\n\n".join(paras).rstrip() + "\n"


def process_one(chapter_no: int) -> tuple[str, int, int]:
    name = f"第{chapter_no:03d}回.txt"
    path = SRC_DIR / name
    if not path.is_file():
        raise FileNotFoundError(f"未找到文件：{path}")

    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines()
    title = lines[0].strip() if lines else f"第{chapter_no:03d}回"
    body_lines = lines[1:] if len(lines) > 1 else []
    paragraphs = normalize_paragraphs(body_lines)

    if len(paragraphs) < 2:
        split_idx = 1
    else:
        split_idx = choose_split_index(paragraphs)

    part1 = build_text(title, paragraphs[:split_idx])
    part2 = build_text(title, paragraphs[split_idx:])

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    p1 = OUT_DIR / f"第{chapter_no:03d}_1回.txt"
    p2 = OUT_DIR / f"第{chapter_no:03d}_2回.txt"
    p1.write_text(part1, encoding="utf-8")
    p2.write_text(part2, encoding="utf-8")

    return name, split_idx, len(paragraphs)


def main() -> None:
    print(f"输出目录：{OUT_DIR}")
    for c in CHAPTERS:
        name, idx, total = process_one(c)
        print(f"已分割 {name}: 段落切分点 {idx}/{total}")


if __name__ == "__main__":
    main()

