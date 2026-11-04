import csv
import json
import time
from pathlib import Path
from urllib.parse import urljoin

import requests


BASE = "https://honglou.mayuniverse.com"
OUT = Path(__file__).resolve().parent / "honglou_dataset"
OUT.mkdir(parents=True, exist_ok=True)

# 输出文件
RAW_JSON = OUT / "raw.json"
CHAR_CSV = OUT / "characters.csv"
REL_CSV = OUT / "relations.csv"
STATE_JSON = OUT / "state.json"
DETAILS_JSONL = OUT / "details.jsonl"

# 限速与重试
REQUEST_INTERVAL_SEC = 0.6
MAX_RETRIES = 4
TIMEOUT_SEC = 25

# 从截图推测 + 常见命名候选；脚本会自动探测可用接口
GRAPH_CANDIDATE_PATHS = [
    "PKD-DXST-C.json",
    "EncodeSwitch.json",
    "api/graph",
    "api/roles",
    "data/PKD-DXST-C.json",
]

# 可选详情接口模板（不保证站点一定存在）
DETAIL_CANDIDATE_TEMPLATES = [
    "api/role/{id}",
    "api/roles/{id}",
    "api/character/{id}",
]

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; honglou-research-bot/1.0)"})


def load_state() -> dict:
    if STATE_JSON.exists():
        try:
            return json.loads(STATE_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"done_detail_ids": [], "source_url": None}


def save_state(state: dict) -> None:
    STATE_JSON.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def get_json_with_retry(url: str, params=None):
    last_err = None
    for i in range(MAX_RETRIES):
        try:
            r = session.get(url, params=params, timeout=TIMEOUT_SEC)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            wait = 1.2 * (2**i)
            print(f"[retry {i+1}/{MAX_RETRIES}] {url} -> {e} ; wait={wait:.1f}s")
            time.sleep(wait)
    raise RuntimeError(f"请求失败: {url} ; last_error={last_err}")


def pick_source_json() -> tuple[str, object]:
    for rel in GRAPH_CANDIDATE_PATHS:
        url = urljoin(BASE + "/", rel)
        try:
            data = get_json_with_retry(url, params={"t": int(time.time() * 1000)})
            print(f"[ok] source: {url}")
            return url, data
        except Exception:
            continue
    raise RuntimeError("未探测到可用 JSON 接口，请在浏览器 Network 中确认接口后补充到 GRAPH_CANDIDATE_PATHS。")


def normalize_graph(raw: object) -> tuple[list[dict], list[dict]]:
    """
    尽量从不同 JSON 形态中提取 nodes/links。
    返回:
      - characters: [{id,name,group,intro,raw}]
      - relations:  [{source,target,relation,weight,raw}]
    """
    nodes = []
    links = []

    if isinstance(raw, dict):
        # 常见图结构
        if isinstance(raw.get("nodes"), list):
            nodes = raw.get("nodes", [])
        if isinstance(raw.get("links"), list):
            links = raw.get("links", [])
        if isinstance(raw.get("edges"), list):
            links = raw.get("edges", [])

        # 另一种: data.nodes / data.links
        data = raw.get("data")
        if isinstance(data, dict):
            if isinstance(data.get("nodes"), list):
                nodes = data.get("nodes", [])
            if isinstance(data.get("links"), list):
                links = data.get("links", [])

        # 如果没有 nodes，但本体是“角色列表”
        if not nodes and isinstance(raw.get("roles"), list):
            nodes = raw["roles"]

    elif isinstance(raw, list):
        # 有些接口直接返回角色数组
        nodes = raw

    characters = []
    for idx, n in enumerate(nodes):
        if not isinstance(n, dict):
            continue
        nid = n.get("id", n.get("uid", n.get("name", f"row_{idx}")))
        name = n.get("name", n.get("title", n.get("label", str(nid))))
        group = n.get("group", n.get("family", n.get("category", "")))
        intro = n.get("intro", n.get("desc", n.get("description", "")))
        characters.append(
            {
                "id": str(nid),
                "name": str(name),
                "group": group if isinstance(group, str) else json.dumps(group, ensure_ascii=False),
                "intro": intro if isinstance(intro, str) else json.dumps(intro, ensure_ascii=False),
                "raw": n,
            }
        )

    relations = []
    for e in links:
        if not isinstance(e, dict):
            continue
        src = e.get("source", e.get("from", e.get("start")))
        tgt = e.get("target", e.get("to", e.get("end")))
        rel = e.get("relation", e.get("type", e.get("label", "")))
        w = e.get("weight", e.get("value", ""))
        if src is None or tgt is None:
            continue
        relations.append(
            {
                "source": str(src),
                "target": str(tgt),
                "relation": rel if isinstance(rel, str) else json.dumps(rel, ensure_ascii=False),
                "weight": w,
                "raw": e,
            }
        )

    return characters, relations


def write_characters_csv(characters: list[dict]) -> None:
    with CHAR_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "name", "group", "intro"])
        for c in characters:
            w.writerow([c["id"], c["name"], c["group"], c["intro"]])


def write_relations_csv(relations: list[dict]) -> None:
    with REL_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["source", "target", "relation", "weight"])
        for r in relations:
            w.writerow([r["source"], r["target"], r["relation"], r["weight"]])


def crawl_optional_details(characters: list[dict], state: dict) -> None:
    """
    断点续跑：仅抓未完成 id。
    如果站点没有详情接口，会自动跳过。
    """
    done = set(state.get("done_detail_ids", []))
    if not DETAILS_JSONL.exists():
        DETAILS_JSONL.write_text("", encoding="utf-8")

    for c in characters:
        cid = c["id"]
        if cid in done:
            continue

        detail = None
        for tpl in DETAIL_CANDIDATE_TEMPLATES:
            url = urljoin(BASE + "/", tpl.format(id=cid))
            try:
                detail = get_json_with_retry(url)
                break
            except Exception:
                detail = None

        if detail is None:
            # 没有详情接口不算致命错误，标记已尝试，避免每次重复请求
            done.add(cid)
            state["done_detail_ids"] = sorted(done)
            save_state(state)
            continue

        with DETAILS_JSONL.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"id": cid, "detail": detail}, ensure_ascii=False) + "\n")

        done.add(cid)
        state["done_detail_ids"] = sorted(done)
        save_state(state)
        time.sleep(REQUEST_INTERVAL_SEC)


def main():
    state = load_state()

    # 1) 自动探测并读取图谱源接口
    source_url, raw = pick_source_json()
    state["source_url"] = source_url
    RAW_JSON.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    save_state(state)

    # 2) 规范化并导出 CSV
    characters, relations = normalize_graph(raw)
    write_characters_csv(characters)
    write_relations_csv(relations)

    # 3) 可选详情抓取（带断点续跑）
    crawl_optional_details(characters, state)

    print(f"完成: source={source_url}")
    print(f"characters={len(characters)} -> {CHAR_CSV}")
    print(f"relations={len(relations)} -> {REL_CSV}")
    print(f"raw -> {RAW_JSON}")
    print(f"state -> {STATE_JSON}")


if __name__ == "__main__":
    main()