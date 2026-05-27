# 惯导智衡 INSRuler AI — MinerU 2026 赛道二参赛作品

> 惯性产品检测领域智能 Data Agent · v5.0

**在线演示**：http://49.232.174.229:7883  
**API 文档**：http://49.232.174.229:7883/api/docs  
**健康检查**：http://49.232.174.229:7883/api/health

---

## 快速复现（5分钟）

### 环境要求

- Python 3.10+
- 2GB+ 内存
- MiniMax API Key（用于 LLM 推理）
- MinerU Cloud API Key（用于 PDF 解析，可选）

### 一键部署

```bash
# 1. 克隆仓库
git clone https://github.com/YOUR_USERNAME/insruler-ai.git
cd insruler-ai

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量
export MINIMAX_API_KEY="your_minimax_key"
export MINIMAX_GROUP_ID="your_group_id"
export MINERU_API_KEY="your_mineru_key"   # 可选

# 4. 启动服务
python3 app.py
# 服务启动于 http://localhost:7883
```

### Docker 部署（推荐）

```bash
docker build -t insruler-ai .
docker run -d -p 7883:7883 \
  -e MINIMAX_API_KEY=your_key \
  -e MINIMAX_GROUP_ID=your_group_id \
  --name insruler insruler-ai
```

### systemd 守护进程（生产环境）

```bash
sudo cp deploy/insruler.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now insruler
sudo systemctl status insruler
```

---

## 系统架构

```
用户请求
    │
    ▼
FastAPI 接口层（Pydantic校验 + Correlation-ID追踪）
    │
    ├── ReAct Agent（Reason-Act-Observe循环）
    │       ├── CoT 思维链规划
    │       ├── 工具调度（7种工具）
    │       └── 任务控制（取消/暂停/恢复）
    │
    ├── RAG 问答引擎
    │       ├── TF-IDF 语义索引（322篇文档）
    │       ├── 滑动窗口分块（600字符/块）
    │       └── BM25 重排序 + 引用溯源
    │
    ├── 知识图谱（2314实体 · 2245关系）
    │       └── D3.js 力导向可视化
    │
    └── MinerU 云端 PDF 解析
            └── 文档类型感知结构化提取
```

---

## 五维评分覆盖

| 维度 | 分值 | 核心实现 |
|------|------|----------|
| 文档理解 | 20分 | RAG滑动窗口分块 + TF-IDF语义检索 + 引用溯源 |
| 技术创新 | 15分 | ReAct + CoT + 知识图谱 + 文档类型感知Schema |
| Agent执行 | 30分 | ReAct循环 + 工具模糊匹配 + 任务控制 + 异步执行 |
| 系统稳定性 | 20分 | systemd守护 + Correlation-ID + Pydantic校验 + 日志轮转 |
| 开源价值 | 15分 | 完整代码 + README + 技术报告 + PPT + 演示视频 |

---

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/health | 系统健康检查 |
| GET | /api/readiness | 就绪检查（DB/TF-IDF/API） |
| POST | /api/agent/plan | CoT 任务规划 |
| POST | /api/agent/execute | ReAct 执行 |
| POST | /api/agent/run | 一键异步 ReAct |
| GET | /api/agent/result | 轮询异步执行结果 |
| POST | /api/agent/control | 任务控制（取消/暂停/恢复） |
| POST | /api/qa | RAG 智能问答 |
| POST | /api/parse/batch | 批量 PDF 解析 |
| GET | /api/kg | 知识图谱数据 |
| GET | /api/docs | Swagger API 文档 |

---

## 技术栈

- **后端**：Python 3.10 · FastAPI · SQLite · TF-IDF
- **AI**：MiniMax LLM · MinerU Cloud API · ReAct Agent
- **前端**：原生 JS · D3.js · 响应式设计
- **运维**：systemd · RotatingFileHandler · Pydantic v2

---

## 目录结构

```
insruler-ai/
├── app.py              # 主程序（FastAPI + Agent + RAG）
├── src/
│   └── index.html      # 前端界面
├── data/
│   └── knowledge.db    # SQLite 知识库
├── docs/
│   └── 技术报告.md     # 技术方案报告
├── deploy/
│   └── insruler.service # systemd 服务配置
├── logs/               # 日志目录（自动轮转）
├── requirements.txt
└── README.md
```

---

## 许可证

MIT License · 惯性产品检测实验室 · 2026
