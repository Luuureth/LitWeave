# LitWeave 本地运行与部署步骤

## 1. 安装依赖
在 `litweave/` 目录下执行：

```bash
npm install
```

## 2. 配置环境变量
在 `litweave/` 下复制环境变量模板并根据本机 MySQL 配置修改：

```bash
cp .env.example .env
cp server/.env.example server/.env
```

需要修改的主要项：

- `DB_HOST=127.0.0.1`
- `DB_PORT=3306`
- `DB_USER=root`
- `DB_PASSWORD=`
- `DB_NAME=litweave`
- `VITE_API_BASE_URL=http://localhost:4000`

## 3. 初始化数据库
执行 `server/schema.sql`，创建数据库与表结构。

可在 MySQL 客户端中执行，或使用你熟悉的 SQL 工具导入。

## 4. 导入实验数据
在 `litweave/` 目录下执行：

```bash
npm run import:data
```

该脚本会读取：
- `跨模态事件对齐与事件时间线构建/timeline_outputs/matched_events_with_timeline.json`

并写入 MySQL。

## 5. 启动后端
在 `litweave/` 目录下执行：

```bash
npm run server
```

默认监听：`http://localhost:4000`

## 6. 启动前端
在另一个终端中执行：

```bash
npm run dev
```

默认监听：`http://localhost:5173`

## 7. 开发联调说明
- 前端 `Vite` 已配置 `/api` 代理到 `http://localhost:4000`
- 前端页面通过 `src/app/lib/api.ts` 请求真实后端数据
- 若需要切换后端地址，可修改 `.env` 中的 `VITE_API_BASE_URL`

## 8. 运行顺序建议
1. MySQL 启动并可连接
2. 导入 SQL 表结构
3. 执行数据导入脚本
4. 启动后端
5. 启动前端

## 9. 当前已接通的数据源
- 统一事件主数据：`matched_events_with_timeline.json`
- 人物索引：`person_event_timeline_index.json`
- 地点索引：`location_event_timeline_index.json`

## 10. 占位方案说明
如果某些事件的 `text` 或 `video` 字段缺失，后端会优雅降级使用 `timeline_event_name` 作为摘要补位；视频预览区域前端可先显示占位区域，待接入真实视频文件后再替换为实际播放组件。
