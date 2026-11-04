from datetime import datetime
from pathlib import Path
import shutil


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def copy_if_exists(src: Path, dst: Path) -> bool:
    if src.exists():
        shutil.copy2(src, dst)
        return True
    return False


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    scripts_dir = Path(__file__).resolve().parent
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    archive = root / f"功能2_事件整理归档_{ts}"

    input_dir = archive / "00_输入"
    process_dir = archive / "01_过程文件"
    output_dir = archive / "02_结果文件"
    log_dir = archive / "03_日志与原始响应"
    script_dir = archive / "04_脚本"

    for d in [input_dir, process_dir, output_dir, log_dir, script_dir]:
        ensure_dir(d)

    copied = []
    missing = []

    # 输入层
    input_files = [
        root / "unified_events" / "unified_events.csv",
        root / "知识库" / "红楼梦时间线.csv",
    ]
    for f in input_files:
        ok = copy_if_exists(f, input_dir / f.name)
        (copied if ok else missing).append(str(f))

    # 过程层
    process_files = [
        root / "timeline_nodes.csv",
        root / "unified_events_repr.csv",
        root / "timeline_candidate_recall.csv",
        root / "timeline_grounding_input.json",
        root / "timeline_grounding_results.json",
        root / "timeline_grounding_llm_output.json",
        root / "unified_events_grounded.csv",
    ]
    for f in process_files:
        ok = copy_if_exists(f, process_dir / f.name)
        (copied if ok else missing).append(str(f))

    # 输出层
    output_files = [
        root / "cross_modal_event_alignment.csv",
        root / "event_timeline_chains.json",
    ]
    for f in output_files:
        ok = copy_if_exists(f, output_dir / f.name)
        (copied if ok else missing).append(str(f))

    # 日志层
    log_files = [
        root / "timeline_grounding_llm_progress.json",
        root / "timeline_grounding_llm_errors.json",
        root / "timeline_grounding_llm_raw.json",
    ]
    for f in log_files:
        ok = copy_if_exists(f, log_dir / f.name)
        (copied if ok else missing).append(str(f))

    # 脚本层
    scripts = [
        scripts_dir / "feature2_timeline_alignment.py",
        scripts_dir / "batch_llm_closed_set_grounding.py",
        scripts_dir / "organize_feature2_outputs.py",
    ]
    for f in scripts:
        ok = copy_if_exists(f, script_dir / f.name)
        (copied if ok else missing).append(str(f))

    readme = archive / "README_说明.txt"
    readme.write_text(
        "\n".join(
            [
                "功能2 归档说明",
                f"归档目录: {archive}",
                "",
                "目录结构：",
                "00_输入：原始输入文件",
                "01_过程文件：中间产物与锚定结果",
                "02_结果文件：最终对齐与事件链",
                "03_日志与原始响应：LLM调用过程文件",
                "04_脚本：功能2相关脚本",
                "",
                "说明：本次为复制归档，不会删除原目录中的文件。",
            ]
        ),
        encoding="utf-8",
    )

    print(f"归档完成: {archive}")


if __name__ == "__main__":
    main()
