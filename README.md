# 惯导智衡 · MinerU 赛道二 Data Agent 参赛材料

**队伍**：惯性产品检测实验室  
**赛道**：MinerU 2026 · 赛道二 · Data Agent 数据智能体评测  
**仓库**：https://github.com/insruler/MinerU-Track2-Agent  
**演示**：http://49.232.174.229:7883  
**版本**：v6.0 · 2026-05-27

---

## 提交材料清单

| 文件 | 说明 |
|------|------|
| `README.md` | 本文件，完整项目说明 |
| `技术报告.md` | 系统设计方案、核心技术、架构图 |
| `部署运行说明.md` | 部署指南、环境要求、API文档 |
| `运行日志与测试结果.md` | 接口测试、日志样例、任务示例 |
| `惯导智衡_风格A_靛蓝瓷.pptx` | 参赛PPT（风格A：电子杂志风） |
| `惯导智衡_风格B_瑞士IKB.pptx` | 参赛PPT（风格B：国际主义风） |
| `惯导智衡_演示视频_v60_字幕版.mp4` | 演示视频（字幕版） |
| `惯导智衡_演示视频_v60_配音版.mp4` | 演示视频（配音版） |

---

## 一、成果总览

### 知识库规模

| 指标 | 数值 |
|------|------|
| 已解析文档 | **356 篇** |
| RAG 分块总数 | **28,741 块**（512字符/块，128字符重叠）|
| 知识图谱实体 | **2,314 个** |
| 知识图谱关系 | **2,245 条** |
| 系统运行时长 | **7天+** |
| 接口测试通过率 | **10/10 (100%)** |

### 五维评分对照

| 评分维度 | 满分 | 核心实现 |
|----------|------|----------|
| 文档理解 | 20分 | 真正RAG（28,741 chunks），TF-IDF+BM25双路检索，引用溯源 |
| 技术创新 | 15分 | ReAct+CoT思维链，知识图谱（2,314实体），文档类型感知 |
| Agent执行 | 30分 | 异步ReAct循环，6个注册工具，任务取消/暂停/恢复控制 |
| 系统稳定性 | 20分 | systemd守护（自动重启），Correlation-ID全链路追踪，Pydantic校验 |
| 开源价值 | 15分 | 完整开源代码，详细文档，PPT，演示视频，可直接验证 |

**总分目标：95分+**

---

## 二、系统架构

```
用户请求
    │
    ▼
FastAPI 接口层（Pydantic校验 + Correlation-ID追踪）
    │
    ├─── ReAct Agent（Reason-Act-Observe循环）
    │       ├── CoT 思维链规划
    │       ├── 6个注册工具（搜索/图谱/抽取/LLM/统计）
    │       └── 异步执行 + 任务控制
    │
    ├─── RAG 问答引擎
    │       ├── TF-IDF 向量化（28,741 chunks）
    │       ├── BM25 重排序
    │       └── 引用溯源回答
    │
    ├─── 知识图谱（2,314实体 · 2,245关系）
    │       └── D3.js 力导向可视化
    │
    └─── MinerU 云端 PDF 解析
            ├── API端点：https://mineru.net/api/v4
            └── 支持：PDF/DOCX/PPTX/XLSX
```

---

## 三、核心功能演示

### 3.1 RAG 智能问答

**示例问题**：什么是标度因数？

**系统回答**（带引用溯源）：
> **标度因数（Scale Factor）**是惯性器件（陀螺仪、加速度计）输出与输入之间的比例系数，反映了传感器的灵敏度特性。
> - 陀螺仪：输入角速率与输出脉冲率的比例系数
> - 加速度计：输入加速度与输出电信号的比例系数
> **来源**：[检测报告 JCBG01 系列]

### 3.2 ReAct Agent 多步任务

**示例任务**：分析 JCBG01-20260318-001 报告中的标度因数试验结果

**Agent 执行过程**：
```
Step 1 → Reason：需要先搜索相关检测报告
Step 1 → Act：search_knowledge_base（标度因数试验）
Step 1 → Observe：找到3篇相关文档
Step 2 → Reason：需要获取知识图谱中的实体关系
Step 2 → Act：get_kg_entities（标度因数）
Step 2 → Observe：陀螺仪→标度因数→精度等级
Step 3 → Reason：综合信息，生成分析报告
Step 3 → Act：call_llm（综合回答）
Step 3 → Final Answer：输出完整分析结果
```

### 3.3 知识图谱可视化

- 2,314 个实体节点，涵盖陀螺仪、加速度计、IMU、测试参数等
- D3.js 力导向图，支持拖拽、缩放、节点检索
- 实体类型：惯性器件、测试参数、测试方法、标准规范

---

## 四、接口测试结果

### 测试时间：2026-05-27 | 服务：http://49.232.174.229:7883

| # | 接口 | 方法 | 状态 | 关键指标 |
|---|------|------|------|----------|
| 1 | `/api/health` | GET | ✅ PASS | status=healthy |
| 2 | `/api/ready` | GET | ✅ PASS | status=ready |
| 3 | `/api/stats` | GET | ✅ PASS | chunks=28741 |
| 4 | `/api/documents` | GET | ✅ PASS | total=356 |
| 5 | `/api/knowledge/search` | POST | ✅ PASS | results≥3 |
| 6 | `/api/qa`（query字段）| POST | ✅ PASS | answer有效 |
| 7 | `/api/qa`（question字段）| POST | ✅ PASS | 兼容性验证 |
| 8 | `/api/agent/plan` | POST | ✅ PASS | CoT规划有效 |
| 9 | `/api/agent/execute` | POST | ✅ PASS | 异步执行启动 |
| 10 | `/api/kg` | GET | ✅ PASS | 2,314实体 |

**通过率：10/10 (100%)**

---

## 五、部署与运行

### 快速启动

```bash
# 1. 克隆仓库
git clone https://github.com/insruler/MinerU-Track2-Agent.git
cd MinerU-Track2-Agent

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量
export MINIMAX_API_KEY="your_key"
export MINIMAX_GROUP_ID="your_group_id"

# 4. 启动服务
python3 app.py
# 访问 http://localhost:7883
```

### systemd 生产部署

```bash
sudo cp deploy/insruler.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now insruler
```

### 在线验证

直接访问 http://49.232.174.229:7883 使用完整功能，无需本地部署。

---

## 六、技术栈

| 层次 | 技术选型 |
|------|----------|
| 后端框架 | Python 3.10 · FastAPI · Pydantic v2 |
| 数据库 | SQLite（知识库 + 图谱） |
| AI 能力 | MiniMax LLM (M2.7) · MinerU Cloud API |
| 前端 | 原生 JavaScript · D3.js |
| 运维 | systemd · RotatingFileHandler（日志轮转）|

---

## 七、版本历史

| 版本 | 日期 | 重大变更 |
|------|------|----------|
| v3.2 | 2026-05-18 | 初始版本，基础Agent+知识图谱 |
| v4.0 | 2026-05-21 | 对标评分标准全面重构 |
| v5.0 | 2026-05-22 | ReAct Agent + 真正RAG + systemd守护 |
| v5.1 | 2026-05-22 | asyncio修复，14项缺陷修复 |
| v6.0 | 2026-05-27 | 接口兼容性，chunks统计，路由别名优化 |

---

## 八、评分维度详细说明

### 文档理解（20分）
- ✅ 28,741 chunks 真实RAG检索
- ✅ TF-IDF + BM25 双路检索
- ✅ 引用溯源，每个答案可追溯
- ✅ 356篇文档全覆盖

### 技术创新（15分）
- ✅ ReAct + CoT 思维链
- ✅ 领域知识图谱（2,314实体）
- ✅ 文档类型感知Schema抽取
- ✅ 异步任务执行架构

### Agent执行（30分）
- ✅ 完整ReAct循环（Reason-Act-Observe）
- ✅ 6个注册工具，工具模糊匹配
- ✅ 任务取消/暂停/恢复控制
- ✅ 异步非阻塞执行

### 系统稳定性（20分）
- ✅ systemd守护，崩溃自动重启
- ✅ Correlation-ID全链路追踪
- ✅ Pydantic v2参数校验
- ✅ 日志轮转，磁盘空间管理

### 开源价值（15分）
- ✅ GitHub公开仓库
- ✅ 完整代码+文档+PPT+视频
- ✅ 服务可直接访问验证
- ✅ README+部署指南+技术报告全套材料

---

## 九、参赛PPT说明

提供两种风格PPT，均为12页：

**风格A · 靛蓝瓷（电子杂志风）**
- 配色：深靛蓝（#0a1f3d）+ 暖白（#f8f6f0）+ 中国红（#c0362c）
- 特点：衬线字体大标题，数据大字报，章节幕封，装饰色块

**风格B · 瑞士IKB（国际主义风）**
- 配色：白底（#fafaf8）+ IKB深蓝（#002FA7）+ 灰阶
- 特点：无衬线字体，几何网格，简洁图表，信息密度高

两套PPT均完整覆盖：核心指标、技术架构、流水线、RAG、RAG问答、评分体系、技术演进、知识图谱、核心价值、开源部署。

---

## 十、联系与验证

- **GitHub**：https://github.com/insruler/MinerU-Track2-Agent
- **在线演示**：http://49.232.174.229:7883
- **API文档**：http://49.232.174.229:7883/api/docs
- **健康检查**：http://49.232.174.229:7883/api/health

评委会员可直接访问上述地址验证系统能力，或克隆仓库本地复现。

---

*惯导智衡 · MinerU 赛道二 · 2026*
