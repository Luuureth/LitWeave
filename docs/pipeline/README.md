# 功能2：跨模态事件对齐与事件时间线构建（离线模块）

本目录提供一套**离线算法流水线**，用于在《红楼梦》多模态知识图谱构建中完成：

- 阶段A：**Event-to-Timeline Grounding**（事件→参考时间线锚定）
- 阶段B：**Cross-modal Event Alignment**（时间窗口约束下的文本-视频事件对齐）
- 阶段C：**Event Cluster Construction**（仅用高置信 aligned 边构建统一事件簇）
- 阶段D：**Global Event Timeline Construction**（在 cluster 层构建全局事件时间线）

它不是“输入一个事件在线检索”的系统，而是**全量离线构建**跨模态对齐图谱、事件簇与全局时间线，供前端图谱展示使用。

## 输入

- `../unified_events/unified_events.csv`
- `../知识库/红楼梦时间线.csv`

## 一键运行

在**项目根目录**执行：

```bash
python "跨模态事件对齐与事件时间线构建/run_feature2_pipeline.py" --output-dir "跨模态事件对齐与事件时间线构建/outputs"
```

如需强制使用 TF-IDF（不启用 sentence-transformers）：

```bash
set FORCE_TFIDF=1
python "跨模态事件对齐与事件时间线构建/run_feature2_pipeline.py"
```

## 主要输出（你论文/前端要的三件事）

输出目录默认 `跨模态事件对齐与事件时间线构建/outputs/`：

1. `cross_modal_event_alignment.csv`：全量文本-视频事件对齐关系表（可解释拆分分数）
2. `event_clusters.json`：全量统一事件簇（cluster 为前端点击单位）
3. `global_event_timeline.json`：簇级全局事件时间线（按 timeline_order 排序）

## 中间可审查产物

- `timeline_nodes.csv`
- `unified_events_repr.csv`
- `timeline_candidate_recall.csv`
- `timeline_grounding_results.json`
- `unified_events_grounded.csv`
- `event_cluster_members.csv`

