# scripts/

项目根目录下的通用工具脚本（统一事件表示、人物/地点归一、功能 2 归档等）。

多数脚本以**项目根目录**为数据根路径（`Path(__file__).resolve().parent.parent`）。

## 常用入口

```bash
# 构建统一事件表示 → unified_events/
python scripts/unified_event_representation.py

# 按回拆分原文
python scripts/split_hongloumeng_chapters.py

# 从多模态 JSON 抽取人物/地点表
python scripts/extract_characters_to_csv.py
python scripts/extract_locations_to_csv.py
```

跨模态主流水线请使用目录 `跨模态事件对齐与事件时间线构建/`，见 `docs/pipeline/`。
