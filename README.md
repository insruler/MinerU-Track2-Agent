# 惯导智衡 · MinerU 赛道二 Data Agent

> 面向惯性产品检测领域的智能 Data Agent 系统，基于 MinerU 云端 API 实现从 PDF 检测报告到结构化知识的全链路自动化。

**🏆 参赛赛道**：MinerU 2026 大赛 · 赛道二 · Data Agent 数据智能体评测  
**📂 仓库**：[github.com/insruler/MinerU-Track2-Agent](https://github.com/insruler/MinerU-Track2-Agent)  
**🌐 在线演示**：[http://49.232.174.229:7883](http://49.232.174.229:7883)  
**📖 API文档**：[http://49.232.174.229:7883/api/docs](http://49.232.174.229:7883/api/docs)  
**🔖 版本**：v6.0 · 2026-05-27

---

## 一、项目成果

### 知识库规模（截至 2026-05-27）

| 指标 | 数值 |
|------|------|
| 已解析文档 | **356 篇** |
| RAG 分块总数 | **28,741 块** |
| 知识图谱实体 | **2,314 个** |
| 知识图谱关系 | **2,245 条** |
| 接口测试通过率 | **10/10 (100%)** |
| 系统运行时长 | **7天+** |

### 五维评分覆盖

| 维度 | 满分 | 核心实现 |
|------|------|----------|
| 文档理解 | 20分 | TF-IDF+BM25 双路检索，28,741 chunks，引用溯源 |
| 技术创新 | 15分 | ReAct+CoT 思维链，知识图谱，文档类型感知 |
| Agent执行 | 30分 | 异步 ReAct，6 个注册工具，任务控制 |
| 系统稳定性 | 20分 | systemd 守护，Correlation-ID 全链路追踪 |
| 开源价值 | 15分 | 完整代码 + 详细文档 + PPT + 演示视频 |

---

## 二、技术架构

```
┌──────────────────────────────────────────────────────────────┐
│                     前端 Web UI (index.html)                    │
│         总览 · PDF解析 · Agent交互 · 知识图谱 · RAG问答        │
└──────────────────────────┬───────────────────────────────────┘
                           │  HTTP REST API (28个接口)
┌──────────────────────────▼───────────────────────────────────┐
│                   FastAPI 后端 (app.py)                        │
│                                                              │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌──────────┐ │
│  │ MinerU     │ │  知识图谱   │ │  ReAct     │ │   RAG    │ │
│  │ 云端解析   │ │  构建模块   │ │  Agent     │ │   问答   │ │
│  └────────────┘ └────────────┘ └────────────┘ └──────────┘ │
└───────────────────────────┬──────────────────────────────────┘
                            │
          ┌─────────────────┼─────────────────┐
          ▼                 ▼                 ▼
   ┌─────────────┐  ┌───────────┐  ┌──────────────────┐
   │ MinerU 云端  │  │  SQLite   │  │  MiniMax LLM API  │
   │ API (PDF)    │  │  知识库    │  │  (MiniMax-M2.7)   │
   └─────────────┘  └───────────┘  └─────────────────────┘
```

### 核心模块

#### 1. ReAct Agent（赛道核心）
采用 **Reason-Act-Observe** 循环架构，支持复杂多步骤任务自动执行：
- **Reason**：Chain-of-Thought 推理，明确当前状态和目标
- **Act**：选择并调用6个注册工具之一
- **Observe**：观察工具返回结果，决定下一步或输出最终答案

已注册工具：
| 工具名 | 功能 |
|--------|------|
| `search_knowledge_base` | RAG 分块检索（BM25+TF-IDF） |
| `get_kg_entities` | 知识图谱实体查询 |
| `get_kg_relations` | 实体关系查询 |
| `extract_structured_fields` | 结构化字段抽取 |
| `call_llm` | LLM 通用推理调用 |
| `get_stats` | 系统统计查询 |

#### 2. RAG 检索增强问答
- **分块策略**：512 字符/块，128 字符重叠，最小 50 字符过滤
- **检索流程**：TF-IDF 向量化 → 候选块召回 → BM25 重排序 → Top-K → LLM 生成
- **引用溯源**：每个回答标注文档来源，可追溯到具体检测报告

#### 3. 惯性检测领域知识图谱
覆盖六类惯性产品核心实体与关系：
- 惯性器件：陀螺仪、加速度计、IMU、惯性导航系统
- 测试参数：标度因数、零偏稳定性、随机游走、Allan方差
- 测试方法：角振动试验、温度循环、冲击振动
- 标准规范：GJB系列、QJ系列、YT系列

#### 4. MinerU 云端高精度解析
- **API端点**：`https://mineru.net/api/v4`
- **支持格式**：PDF / DOCX / PPTX / XLSX
- **已处理**：300+ PDF 检测报告 → 356篇结构化文档

---

## 三、快速部署（5分钟可复现）

### 环境要求
- Python 3.10+
- 2GB+ 内存
- MiniMax API Key
- MinerU Cloud API Key（PDF解析用，可选）

### 步骤

```bash
# 1. 克隆仓库
git clone https://github.com/insruler/MinerU-Track2-Agent.git
cd MinerU-Track2-Agent

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量
export MINIMAX_API_KEY="your_key"
export MINIMAX_GROUP_ID="your_group_id"
export MINERU_API_KEY="your_mineru_key"   # 可选

# 4. 启动服务
python3 app.py
# 访问 http://localhost:7883
```

### systemd 生产部署

```bash
sudo cp deploy/insruler.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now insruler
sudo systemctl status insruler
```

### Docker 部署

```bash
docker build -t mineru-track2-agent .
docker run -d -p 7883:7883 \
  -e MINIMAX_API_KEY=your_key \
  -e MINIMAX_GROUP_ID=your_group_id \
  --name mineru-agent mineru-track2-agent
```

---

## 四、API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/ready` | 就绪检查（依赖项验证） |
| GET | `/api/stats` | 知识库统计（文档/实体/chunks数） |
| GET | `/api/documents` | 文档列表（分页） |
| GET | `/api/documents/{id}` | 单篇文档详情 |
| POST | `/api/parse/batch` | 批量 PDF 解析 |
| POST | `/api/qa` | RAG 智能问答 |
| GET | `/api/knowledge/search` | 知识库搜索 |
| POST | `/api/agent/plan` | CoT 任务规划 |
| POST | `/api/agent/execute` | ReAct 同步执行 |
| POST | `/api/agent/run` | ReAct 异步执行 |
| GET | `/api/agent/result` | 异步结果查询 |
| POST | `/api/agent/control` | 任务控制（取消/暂停/恢复） |
| GET | `/api/kg` | 知识图谱数据 |
| GET | `/api/jobs` | 解析任务列表 |

完整文档：http://49.232.174.229:7883/api/docs

---

## 五、系统稳定性

### 守护进程
systemd 托管，崩溃后5秒自动重启，已稳定运行7天+。

### 全链路追踪
每个请求携带 `Correlation-ID`，贯穿：
```
Request → Middleware → Handler → Tool → LLM → Response
```

### 参数校验
Pydantic v2 模型，支持字段别名兼容：
- `query` / `question` 均可用
- `query` / `task` 均可用

### 异步执行
```
POST /api/agent/execute → 立即返回 trace_id
GET  /api/agent/result?trace_id=xxx → 轮询结果
```

---

## 六、技术栈

| 层次 | 技术 |
|------|------|
| 后端 | Python 3.10 · FastAPI · Pydantic v2 · SQLite |
| AI | MiniMax LLM (M2.7) · MinerU Cloud API |
| 前端 | 原生 JS · D3.js · 响应式设计 |
| 运维 | systemd · RotatingFileHandler |

---

## 七、目录结构

```
MinerU-Track2-Agent/
├── app.py                   # 主程序（FastAPI + Agent + RAG）
├── src/
│   └── index.html           # 前端界面
├── data/
│   └── knowledge.db         # SQLite 知识库
├── docs/
│   ├── 技术报告.md          # 详细技术方案
│   ├── 部署运行说明.md      # 部署指南
│   └── 运行日志与测试结果.md # 测试记录
├── deploy/
│   └── insruler.service     # systemd 配置
├── logs/                    # 日志目录（自动轮转）
├── requirements.txt
└── README.md
```

---

## 八、版本历史

| 版本 | 日期 | 主要变更 |
|------|------|---------|
| v3.2 | 2026-05-18 | 初始版本，基础 Agent + 知识图谱 |
| v4.0 | 2026-05-21 | 对标评分标准全面升级 |
| v5.0 | 2026-05-22 | ReAct Agent + 真正 RAG + systemd |
| v5.1 | 2026-05-22 | asyncio 修复，14项缺陷修复 |
| v6.0 | 2026-05-27 | 接口兼容性修复，chunks统计，路由别名 |

---

## 九、许可证

MIT License · 惯性产品检测实验室 · 2026

**联系方式**：insruler @ GitHub