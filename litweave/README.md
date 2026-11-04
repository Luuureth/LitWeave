# LitWeave Web

LitWeave 桌面 Web 界面：人物 / 地点 / 事件浏览、时间线与证据面板。

技术栈：React + Vite + Express + MySQL。

## 快速开始

```bash
npm install
cp .env.example .env
cp server/.env.example server/.env
# 编辑数据库配置后：
npm run import:data   # 可选，导入实验数据
npm run server        # http://localhost:4000
npm run dev           # http://localhost:5173
```

完整步骤见仓库根目录 [docs/deployment.md](../docs/deployment.md)。

## 目录

- `src/` — 前端源码
- `server/` — Express API 与数据导入脚本
- `guidelines/` — UI 指南
