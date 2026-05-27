# 惯导智衡 - MinerU 2026大赛赛道二参赛作品

> **Data Agent数据智能体系统 v6.0**  
> 惯性产品检测实验室 · 北京航天控制仪器研究所

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com)
[![MinerU](https://img.shields.io/badge/MinerU-Cloud%20API-orange.svg)](https://mineru.net)

## 🏆 系统概览

**惯导智衡**是面向惯性产品检测领域的智能数据Agent系统，基于MinerU云端API实现高精度PDF解析，结合ReAct模式Agent、真正RAG检索增强、知识图谱构建，为惯性检测报告的智能分析提供完整解决方案。

### 核心数据指标
| 指标 | 数值 |
|------|------|
| 已解析文档 | 356 篇 |
| 知识图谱实体 | 2,314 个 |
| 知识图谱关系 | 2,245 条 |
| RAG分块总数 | 28,741 块 |
| 接口测试通过率 | 10/10 (100%) |

## 🚀 快速部署

### 环境要求
- Python 3.10+
- 4GB+ RAM
- MinerU API Key（[申请地址](https://mineru.net)）
- MiniMax API Key（[申请地址](https://api.minimax.chat)）

### 一键部署

```bash
# 克隆仓库
git clone https://github.com/insruler/MinerU-Track2-Agent.git
cd MinerU-Track2-Agent

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
export MINIMAX_API_KEY="your_minimax_key"
export MINERU_TOKEN="your_mineru_token"

# 启动服务
python app.py
```

服务启动后访问：`http://localhost:7883`

### systemd 守护进程部署（生产环境）

```bash
# 复制服务文件
sudo cp deploy/insruler.service /etc/systemd/system/

# 启用并启动
sudo systemctl daemon-reload
sudo systemctl enable insruler
sudo systemctl start insruler

# 查看状态
sudo systemctl status insruler
```

## 📡 API 接口文档

### 基础接口
| 接口 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/ready` | GET | 就绪检查 |
| `/api/stats` | GET | 系统统计（文档/实体/分块数） |

### 文档管理
| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/documents` | GET | 文档列表（分页，`?page=1&page_size=20`） |
| `/api/docs/list` | GET | 文档列表（`?limit=50&offset=0`） |
| `/api/docs/{id}` | GET | 文档详情 |
| `/api/parse/batch` | POST | 批量PDF解析（MinerU云端） |
| `/api/jobs` | GET | 解析任务列表（分页） |
| `/api/jobs/list/summary` | GET | 任务统计摘要 |

### 知识库与问答
| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/qa` | POST | RAG增强问答（支持`query`或`question`字段） |
| `/api/qa/history` | GET | 问答历史 |
| `/api/knowledge/search` | POST | 知识库搜索 |
| `/api/docs/search` | POST | 文档全文搜索 |
| `/api/kg` | GET | 知识图谱数据（D3.js格式） |

### Agent 执行
| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/agent/plan` | POST | ReAct任务规划（支持`task`或`query`字段） |
| `/api/agent/execute` | POST | 异步ReAct执行（支持`task`或`query`字段） |
| `/api/agent/result` | GET | 查询执行结果（`?trace_id=xxx`） |
| `/api/agent/logs` | GET | 执行日志 |
| `/api/agent/traces` | GET | 执行轨迹列表 |
| `/api/agent/control` | POST | 任务控制（取消/暂停/恢复） |
| `/api/tools` | GET | 已注册工具列表 |

### 接口调用示例

**RAG问答**
```bash
curl -X POST http://localhost:7883/api/qa \
  -H "Content-Type: application/json" \
  -d '{"query": "陀螺仪标度因数的测试方法是什么？", "top_k": 5}'
```

**Agent任务规划**
```bash
curl -X POST http://localhost:7883/api/agent/plan \
  -H "Content-Type: application/json" \
  -d '{"task": "分析所有陀螺仪检测报告中的标度因数数据"}'
```

**Agent异步执行**
```bash
# 提交任务
curl -X POST http://localhost:7883/api/agent/execute \
  -H "Content-Type: application/json" \
  -d '{"task": "提取IMU零偏稳定性数据并生成分析报告", "mode": "react"}'

# 查询结果（使用返回的trace_id）
curl "http://localhost:7883/api/agent/result?trace_id=<trace_id>"
```

## 🏗️ 系统架构

```
┌─────────────────────────────────────────────────────────┐
│                    惯导智衡 v6.0                          │
├─────────────────────────────────────────────────────────┤
│  前端 Dashboard (src/index.html)                         │
│  ├── 实时监控面板    ├── Agent执行可视化                   │
│  ├── 知识图谱D3.js  └── RAG问答界面                       │
├─────────────────────────────────────────────────────────┤
│  FastAPI 后端 (app.py)                                   │
│  ├── ReAct Agent Engine    ← Reason-Act-Observe循环      │
│  ├── RAG Engine            ← TF-IDF + BM25重排序         │
│  ├── Knowledge Graph       ← 实体/关系抽取                │
│  ├── MinerU Cloud Parser   ← PDF高精度解析                │
│  └── Correlation Tracking  ← 全链路追踪                   │
├─────────────────────────────────────────────────────────┤
│  数据层 (SQLite)                                          │
│  ├── documents (356篇)     ├── kg_entities (2314个)      │
│  ├── document_chunks       └── kg_relations (2245条)     │
│      (28741块)                                           │
└─────────────────────────────────────────────────────────┘
```

## 🔬 技术亮点

### 1. ReAct Agent（赛道核心）
- **Reason-Act-Observe** 循环，最多5步推理
- **Chain-of-Thought** 完整思维链输出
- 异步执行，消除HTTP超时风险
- 支持任务取消/暂停/恢复控制

### 2. 真正RAG检索增强
- **TF-IDF分块检索**：512字符块，128字符重叠
- **BM25重排序**：提升检索精度
- **引用溯源**：回答中标注文档来源[1][2]
- 28,741个分块覆盖356篇惯性检测报告

### 3. 惯性检测领域知识图谱
- 2,314个专业实体（陀螺仪/加速度计/IMU/惯导系统等）
- 2,245条关系（测试方法/技术参数/标准规范等）
- D3.js力导向图可视化

### 4. MinerU云端高精度解析
- 支持PDF/DOCX/PPTX/XLSX多格式
- 表格/图表专用解析
- 结构化字段抽取（编号/客户/样品/参数）

### 5. 生产级稳定性
- systemd守护进程，崩溃自动重启
- Correlation-ID全链路追踪
- Pydantic参数校验
- 就绪检查端点（`/ready`）

## 📊 评分维度对应

| 评分维度 | 满分 | 对应功能 |
|---------|------|---------|
| 文档理解 | 20 | MinerU解析 + RAG分块检索 + 引用溯源 |
| 技术创新 | 15 | ReAct Agent + CoT推理链 + 知识图谱 |
| Agent执行 | 30 | 异步ReAct + 任务控制 + 工具链 |
| 系统稳定性 | 20 | systemd + 全链路追踪 + 参数校验 |
| 开源价值 | 15 | 本仓库（MIT License） |

## 🌐 在线演示

- **系统地址**：http://49.232.174.229:7883
- **API文档**：http://49.232.174.229:7883/api/docs
- **健康检查**：http://49.232.174.229:7883/health

## 📄 许可证

MIT License - 详见 [LICENSE](LICENSE)

## 👥 团队

惯性产品检测实验室 · 北京航天控制仪器研究所惯性技术产品检测中心
