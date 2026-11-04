# LitWeave

面向经典文学（《红楼梦》）的**多模态事件级语义对齐、知识重构与可视化展示**系统。

本仓库开源的是**算法流水线与 Web 系统代码**。  
**数据版权声明：**《红楼梦》原文文本与剧版音视频等材料的版权归原作者及相应权利方所有；本仓库仅开源算法与系统代码，附带结构化数据仅供学术研究与复现参考，不构成数据版权转让或授权。

## 项目结构

```
.
├── litweave/                         # Web 前端 (React/Vite) + Express/MySQL 后端
├── 跨模态事件对齐与事件时间线构建/      # 跨模态对齐与全局时间线离线流水线
├── 知识库/                           # 人物 / 地点 / 事件知识库
├── 红楼梦文本/                        # 原文分章与文本事件 JSON
├── 剧版红楼梦/                        # 剧集场景 JSON（视频本地保留，默认不入库）
├── unified_events/                   # 统一事件表示
├── scripts/                          # 根级工具脚本（UEO、归一化等）
├── docs/                             # 文档、部署说明、论文材料
├── examples/                         # 示例说明
├── assets/                           # 静态资源
├── requirements.txt                  # Python 依赖
└── LICENSE                           # MIT + 数据版权说明
```

## 环境依赖

| 组件 | 要求 |
|------|------|
| Python | 3.10+（推荐 3.12） |
| Node.js | 18+（前端 / 后端） |
| MySQL | 8.x（LitWeave 展示端） |
| （可选）DashScope API | 人物/地点 LLM 归一、闭集 grounding |

## 安装

### 1. Python 流水线

```bash
pip install -r requirements.txt
# 若不需要句向量模型，可跳过 sentence-transformers，并用 FORCE_TFIDF=1 跑对齐
```

### 2. LitWeave Web

```bash
cd litweave
npm install
cp .env.example .env
cp server/.env.example server/.env
# 按本机 MySQL 修改 DB_* 与 VITE_API_BASE_URL
```

在 MySQL 中执行 `litweave/server/schema.sql` 创建库表。

## 运行

### 离线流水线（功能 2）

在**项目根目录**执行：

```bash
python "跨模态事件对齐与事件时间线构建/run_feature2_pipeline.py" --output-dir "跨模态事件对齐与事件时间线构建/outputs"
```

强制 TF-IDF（不加载 sentence-transformers）：

```bash
# Windows PowerShell
$env:FORCE_TFIDF=1
python "跨模态事件对齐与事件时间线构建/run_feature2_pipeline.py"
```

主要输出（默认在 `跨模态事件对齐与事件时间线构建/outputs/`）：

- `cross_modal_event_alignment.csv`
- `event_clusters.json`
- `global_event_timeline.json`

更多说明见 [docs/pipeline/README.md](docs/pipeline/README.md)。

### 统一事件表示

```bash
python scripts/unified_event_representation.py
```

### LitWeave 前端 + 后端

```bash
cd litweave

# 导入实验数据（读取跨模态 timeline_outputs）
npm run import:data

# 终端 1：后端 API（默认 http://localhost:4000）
npm run server

# 终端 2：前端开发服务（默认 http://localhost:5173）
npm run dev
```

详细部署步骤见 [docs/deployment.md](docs/deployment.md)。

## 使用示例

```bash
# 抽取人物 / 地点表
python scripts/extract_characters_to_csv.py
python scripts/extract_locations_to_csv.py

# 按回拆分原文
python scripts/split_hongloumeng_chapters.py
```

知识库构建流程见 `docs/kb/`。

## 数据与大文件说明（上传 GitHub 前必读）

| 内容 | 仓库策略 |
|------|----------|
| 代码、文档、知识库、pipeline `outputs/` | **入库**（D2） |
| `剧版红楼梦/**/*.mp4` 等视频 | **本地保留**，已写入 `.gitignore` |
| `event_timeline_chains.json`（约 115MB） | **本地保留**，超 GitHub 单文件限制 |
| `.env` | **不入库**，请使用 `.env.example` |

克隆后请自行准备剧版切分视频目录（若需复现视频侧实验），路径保持为 `剧版红楼梦/hongloumeng_segments/`。

## 文档索引

- [部署说明](docs/deployment.md)
- [跨模态流水线](docs/pipeline/README.md)
- [人物归一化](docs/kb/人物归一化全流程说明.md)
- [地点归一化](docs/kb/地点归一化全流程说明.md)
- [方法与实验](docs/kb/多模态知识内容理解_方法与实验文档.md)

## License

代码采用 [MIT](LICENSE) 许可。文本与音视频等数据版权归原作者及权利方所有；本仓库仅开源算法与系统代码。
