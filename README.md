# 惯导智衡 · Data Agent

> MinerU 2026大赛 · 赛道二 · 惯性产品检测实验室

[![Python](https://img.shields.io/badge/Python-3.12-blue)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110-green)](https://fastapi.tiangolo.com)
[![MinerU](https://img.shields.io/badge/MinerU-API_v4-orange)](https://mineru.net)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

**惯导智衡**是面向惯性产品检测领域的智能 Data Agent 系统，基于 MinerU 云端 API 构建，实现从原始 PDF 检测报告到结构化知识图谱、智能问答、多步任务自动执行的完整闭环。

## 🌐 在线演示

**服务地址**：http://49.232.174.229:7883

## ✨ 核心功能

| 功能 | 描述 |
|------|------|
| 📄 PDF 智能解析 | MinerU 云端 API VLM 模型解析检测报告 |
| 🔗 知识图谱构建 | 自动抽取实体关系，701节点/704关系 |
| 💬 RAG 智能问答 | 基于知识库的检索增强问答 |
| 🤖 Data Agent | 两阶段规划-执行，支持复杂多步任务 |
| 📊 可视化界面 | 知识图谱力导向可视化，支持拖拽缩放 |

## 🚀 快速开始

### 环境要求

- Python 3.10+
- 网络访问 MinerU API 和 MiniMax API

### 安装依赖

```bash
pip install fastapi uvicorn requests python-multipart starlette
```

### 启动服务

```bash
# 配置 API Key（可选，已内置默认值）
export MINIMAX_API_KEY="your_key"
export MINERU_TOKEN="your_token"

# 启动
python3 app.py
```

访问 http://localhost:7883

## 📡 API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/stats` | GET | 系统统计 |
| `/api/parse/batch` | POST | 批量 PDF 解析 |
| `/api/jobs/{id}` | GET | 任务状态查询 |
| `/api/qa` | POST | 智能问答 |
| `/api/agent/plan` | POST | Agent 任务规划 |
| `/api/agent/execute` | POST | Agent 任务执行 |
| `/api/kg` | GET | 知识图谱数据 |
| `/api/docs/list` | GET | 文档列表 |
| `/api/docs/{id}` | GET | 文档详情 |
| `/api/qa/history` | GET | 问答历史 |

## 🏗️ 系统架构

```
前端 Web UI (index.html)
       ↓ HTTP REST
FastAPI 后端 (app.py, port 7883)
  ├── PDF解析模块 → MinerU 云端 API v4
  ├── KG构建模块 → MiniMax LLM (实体抽取)
  ├── Agent模块  → MiniMax LLM (规划+执行)
  └── QA模块    → MiniMax LLM (RAG问答)
       ↓
SQLite 知识库 (knowledge.db)
```

## 📊 当前知识库规模

- 知识文档：56 篇
- 实体节点：701 个
- 关系连接：704 条
- 实体类型：参数、测试方法、误差、国军标、器件、算法等

## 📁 项目结构

```
MinerU_Track2_Agent/
├── app.py              # 主程序（FastAPI + 所有业务逻辑）
├── src/
│   └── index.html      # 前端单页应用
├── data/
│   └── knowledge.db    # SQLite 知识库
├── logs/
│   └── app.log         # 运行日志
└── docs/
    ├── 技术报告.md
    ├── 部署运行说明.md
    └── 运行日志与测试结果.md
```

## 📄 提交材料

- [技术报告](docs/技术报告.md)
- [部署运行说明](docs/部署运行说明.md)
- [运行日志与测试结果](docs/运行日志与测试结果.md)

## 🔑 技术亮点

1. **MinerU VLM 模型**：使用最新 VLM 模型解析复杂惯性检测报告，支持表格、公式提取
2. **领域专用 Prompt**：针对惯性检测领域设计实体抽取 Prompt，识别参数、器件、标准等专业实体
3. **两阶段 Agent**：规划与执行分离，计划内容作为上下文传入执行阶段，保证逻辑一致性
4. **零依赖前端**：纯原生 HTML/CSS/JS，无框架依赖，部署简单
5. **持久化 QA 历史**：问答记录持久化存储，支持历史回溯

## 📜 License

MIT License

---

*惯性产品检测实验室 · MinerU 2026大赛赛道二*
