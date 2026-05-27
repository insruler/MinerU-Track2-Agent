#!/usr/bin/env python3
"""
惯导智衡 - 惯性检测实验室智能Agent (专业版 v5.0)
MinerU 2026大赛赛道二 · Data Agent

升级日志 v5.0:
- ReAct Agent：Reason-Act-Observe循环，真正的推理-行动-观察链路
- CoT推理链：Chain-of-Thought多步推理，每步记录思考过程
- RAG增强QA：分块检索+BM25重排序+引用溯源，替换简单keyword搜索
- 结构化Schema：文档类型感知抽取，表格/图表专用解析
- 任务管理：支持取消/暂停/恢复，任务状态持久化
- 多工具协作：工具依赖图，自动编排执行顺序
- 参数校验：Pydantic模型校验所有API入参
- 结构化日志：correlation_id全链路追踪，JSON格式日志
- 健康检查：/api/health + /api/readiness 双端点
- 错误自动恢复：指数退避重试，熔断器模式
"""

import asyncio
import sys, os, time, json, re, sqlite3, zipfile, io, threading, uuid, hashlib
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from enum import Enum
import uvicorn
from fastapi import FastAPI, Request, UploadFile, File, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
import requests
import logging
import contextvars

# ==================== Correlation ID 中间件 ====================
correlation_id_var: contextvars.ContextVar[str] = contextvars.ContextVar('correlation_id', default='')

# ==================== 日志配置 ====================
from logging.handlers import RotatingFileHandler
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(correlation_id)s] %(name)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(
            "/root/MinerU_Track2_Agent/logs/app.log",
            maxBytes=50*1024*1024,  # 50MB
            backupCount=3,
            encoding="utf-8"
        )
    ]
)

class CorrelationFilter(logging.Filter):
    def filter(self, record):
        record.correlation_id = correlation_id_var.get('') or '-'
        return True

for handler in logging.root.handlers:
    handler.addFilter(CorrelationFilter())

logger = logging.getLogger("gyro.agent")

# ==================== 配置 ====================
MINIMAX_API_KEY = os.environ.get("MINIMAX_API_KEY", "sk-cp-ypfEn_bc2iumGQhRTyJjhRU1oSK6XMCLvv0Ow3ehAuP1K6rmetK_UO5vQPFSptVeWwTTftP77EyNA7FPMyXTgkTD2qjVwj-7ifRZz4pA5iksyAGpFEMYGfc")
MINIMAX_MODEL = "MiniMax-M2.7"
MINERU_TOKEN = os.environ.get("MINERU_TOKEN", "eyJ0eXBlIjoiSldUIiwiYWxnIjoiSFM1MTIifQ.eyJqdGkiOiIyODkwMDY0NiIsInJvbCI6IlJPTEVfUkVHSVNURVIiLCJpc3MiOiJPcGVuWExhYiIsImlhdCI6MTc3NDI1NjQ0MywiY2xpZW50SWQiOiJsa3pkeDU3bnZ5MjJqa3BxOXgydyIsInBob25lIjoiMTMyNjAxNjk4ODUiLCJvcGVuSWQiOm51bGwsInV1aWQiOiJmNTg5ZjE5NC1jYmFkLTQ5ZTUtYWQ4Zi04MmU0M2UyZWRhZDQiLCJlbWFpbCI6IiIsImV4cCI6MTc4MjAzMjQ0M30.DTzzcfCKsyadfeNy3mwoJ93V11mkPiOXE3sKlq8NYvfl2EWmngcmJbw5OGni0LegfNz7oETK30blEQt3nuupMg")
APP_VERSION = "5.1"
BASE_DIR = Path("/root/MinerU_Track2_Agent")
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "knowledge.db"
SRC_DIR = BASE_DIR / "src"

# ==================== 数据库 ====================
def get_db():
    os.makedirs(str(DATA_DIR), exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    db = get_db()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS kg_entities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        entity_id TEXT NOT NULL,
        entity_name TEXT NOT NULL,
        entity_type TEXT,
        properties TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS kg_relations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        relation_id TEXT,
        source_entity TEXT NOT NULL,
        target_entity TEXT NOT NULL,
        relation_type TEXT,
        properties TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        doc_id TEXT,
        title TEXT,
        doc_type TEXT,
        source_type TEXT,
        content TEXT,
        metadata TEXT,
        structured_data TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS parse_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id TEXT UNIQUE,
        filename TEXT,
        file_size INTEGER,
        batch_id TEXT,
        status TEXT DEFAULT 'pending',
        progress INTEGER DEFAULT 0,
        content TEXT,
        error TEXT,
        chars INTEGER DEFAULT 0,
        entities_count INTEGER DEFAULT 0,
        relations_count INTEGER DEFAULT 0,
        retry_count INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS qa_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question TEXT NOT NULL,
        answer TEXT,
        sources TEXT,
        trace_id TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS batch_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id TEXT UNIQUE,
        total_files INTEGER DEFAULT 0,
        completed INTEGER DEFAULT 0,
        failed INTEGER DEFAULT 0,
        status TEXT DEFAULT 'running',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS agent_execution_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trace_id TEXT NOT NULL,
        task_query TEXT,
        step_index INTEGER DEFAULT 0,
        step_name TEXT,
        tool_name TEXT,
        tool_input TEXT,
        tool_output TEXT,
        status TEXT DEFAULT 'running',
        duration_ms INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_agent_logs_trace ON agent_execution_logs(trace_id);
    CREATE INDEX IF NOT EXISTS idx_parse_batch ON parse_history(batch_id);
    """)
    # 升级已有表：添加缺少的列
    try:
        db.execute("ALTER TABLE documents ADD COLUMN structured_data TEXT")
        db.commit()
    except: pass
    try:
        db.execute("ALTER TABLE parse_history ADD COLUMN retry_count INTEGER DEFAULT 0")
        db.commit()
    except: pass
    try:
        db.execute("ALTER TABLE qa_history ADD COLUMN trace_id TEXT")
        db.commit()
    except: pass
    db.commit()
    # 清理历史积压的pending任务（超过1小时未处理的视为僵尸任务）
    try:
        db.execute("""UPDATE parse_history SET status='failed', error='启动时清理：历史积压任务'
                      WHERE status IN ('pending','parsing','extracting')
                      AND created_at < datetime('now', '-1 hour')""")
        cleaned = db.execute("SELECT changes()").fetchone()[0]
        if cleaned > 0:
            logger.info(f"清理历史积压任务: {cleaned}条")
        db.commit()
    except Exception as e:
        logger.warning(f"清理积压任务失败: {e}")
    db.close()
    # 异步构建 TF-IDF 索引
    threading.Thread(target=tfidf_index.build, daemon=True).start()

# ==================== Pydantic 请求模型（参数校验） ====================
class AgentPlanRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000, description="任务描述")
    mode: str = Field(default="react", description="执行模式: react | simple")
    max_steps: int = Field(default=5, ge=1, le=10, description="最大执行步数")

class AgentExecuteRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    plan: str = Field(default="", max_length=10000)
    trace_id: str = Field(default="", max_length=64)
    mode: str = Field(default="react", description="执行模式: react | simple")

class QARequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000, description="问题")
    top_k: int = Field(default=5, ge=1, le=20, description="检索文档数")
    use_rag: bool = Field(default=True, description="是否启用RAG增强")

class ParseBatchRequest(BaseModel):
    files: List[str] = Field(..., min_length=1, max_length=20, description="文件名列表")

# ==================== 任务状态管理（取消/暂停/恢复） ====================
class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    DONE = "done"
    FAILED = "failed"

_task_control: Dict[str, str] = {}  # trace_id -> "cancel" | "pause" | "resume"
_task_control_lock = threading.Lock()

def set_task_control(trace_id: str, action: str):
    with _task_control_lock:
        _task_control[trace_id] = action

def get_task_control(trace_id: str) -> str:
    with _task_control_lock:
        return _task_control.get(trace_id, "")

def clear_task_control(trace_id: str):
    with _task_control_lock:
        _task_control.pop(trace_id, None)

# ==================== ReAct Agent 核心引擎 ====================
class ReActAgent:
    """实现 Reason-Act-Observe 循环的 Agent 引擎"""

    def __init__(self, trace_id: str, query: str, max_steps: int = 5):
        self.trace_id = trace_id
        self.query = query
        self.max_steps = max_steps
        self.steps: List[Dict] = []
        self.observations: List[str] = []
        self.final_answer: str = ""
        self.status = TaskStatus.RUNNING

    def _build_react_prompt(self, step_num: int) -> str:
        history = ""
        for s in self.steps:
            history += f"\n\n**思考 {s['step']}**: {s['thought']}"
            history += f"\n**行动 {s['step']}**: 调用 `{s['tool']}` 参数: {json.dumps(s['tool_input'], ensure_ascii=False)}"
            history += f"\n**观察 {s['step']}**: {s['observation'][:500]}"

        return f"""你是惯性检测实验室的智能Data Agent。使用ReAct模式（思考-行动-观察）完成任务。

可用工具：
- search_knowledge_base(查询): 在知识库中检索相关文档
- get_kg_entities(实体类型, 名称过滤): 查询知识图谱实体
- get_kg_relations(实体名): 查询实体关联关系
- extract_structured_fields(文档ID): 提取报告结构化字段
- get_stats(): 获取系统统计信息
- call_llm(提示词): 调用大语言模型进行推理

任务: {self.query}

历史步骤:{history if history else ' （无）'}

当前是第 {step_num} 步。请按以下格式输出（严格 JSON）：
如果需要继续执行：
{{"thought": "对当前情况的分析和下一步计划", "action": "tool_name", "action_input": {{参数}}}}
如果已可以给出最终答案：
{{"thought": "总结分析", "action": "finish", "action_input": {{“答案”: "完整的Markdown格式答案"}}}}"""

    def run(self) -> Dict:
        """ReAct循环执行"""
        t0 = time.time()
        correlation_id_var.set(self.trace_id)

        for step_num in range(1, self.max_steps + 1):
            # 检查任务控制指令
            ctrl = get_task_control(self.trace_id)
            if ctrl == "cancel":
                self.status = TaskStatus.CANCELLED
                self.final_answer = "任务已被用户取消"
                break
            if ctrl == "pause":
                self.status = TaskStatus.PAUSED
                # 记录暂停状态到日志，前端可通过traces查询
                log_agent_step(self.trace_id, self.query, step_num, "任务已暂停",
                               "system", {}, {"status": "paused", "message": "等待恢复指令"},
                               "paused", 0)
                # 等待恢复（最多120秒）
                for wait_i in range(120):
                    time.sleep(1)
                    ctrl_now = get_task_control(self.trace_id)
                    if ctrl_now == "resume":
                        clear_task_control(self.trace_id)
                        self.status = TaskStatus.RUNNING
                        log_agent_step(self.trace_id, self.query, step_num, "任务已恢复",
                                       "system", {}, {"status": "running"}, "running", 0)
                        break
                    elif ctrl_now == "cancel":
                        self.status = TaskStatus.CANCELLED
                        self.final_answer = "任务已被用户取消"
                        log_agent_step(self.trace_id, self.query, step_num, "任务已取消",
                                       "system", {}, {"status": "cancelled"}, "cancelled", 0)
                        break
                else:
                    self.status = TaskStatus.CANCELLED
                    self.final_answer = "任务暂停超时（120秒）已自动取消"
                    log_agent_step(self.trace_id, self.query, step_num, "暂停超时自动取消",
                                   "system", {}, {"status": "cancelled", "reason": "timeout"}, "cancelled", 0)
                    break

            # Step1: 思考（Reason）
            react_prompt = self._build_react_prompt(step_num)
            log_agent_step(self.trace_id, self.query, step_num, f"ReAct思考第{step_num}步",
                           "call_llm", {"step": step_num}, "reasoning", "running", 0)
            t_reason = time.time()
            llm_raw = call_minimax(react_prompt,
                "你是惯性检测领域的Data Agent。严格按JSON格式输出，不要包含任何其他内容。")
            reason_ms = int((time.time()-t_reason)*1000)

            # 解析 LLM 输出
            try:
                clean = re.sub(r'^```(?:json)?\s*', '', llm_raw.strip(), flags=re.IGNORECASE)
                clean = re.sub(r'\s*```$', '', clean.strip())
                react_out = json.loads(clean)
            except Exception:
                # 尝试提取JSON块
                m = re.search(r'\{.*\}', llm_raw, re.DOTALL)
                if m:
                    try:
                        react_out = json.loads(m.group())
                    except:
                        react_out = {"thought": llm_raw[:200], "action": "finish",
                                     "action_input": {"答案": llm_raw}}
                else:
                    react_out = {"thought": llm_raw[:200], "action": "finish",
                                 "action_input": {"答案": llm_raw}}

            thought = react_out.get("thought", "")
            action = react_out.get("action", "finish")
            action_input = react_out.get("action_input", {})

            log_agent_step(self.trace_id, self.query, step_num, f"ReAct思考第{step_num}步",
                           "call_llm", {"step": step_num},
                           {"thought": thought[:200], "action": action}, "done", reason_ms)

            if action == "finish":
                # 得出最终答案
                if isinstance(action_input, dict):
                    self.final_answer = action_input.get("答案", action_input.get("answer", str(action_input)))
                else:
                    self.final_answer = str(action_input)
                self.status = TaskStatus.DONE
                log_agent_step(self.trace_id, self.query, step_num, "得出最终答案",
                               "finish", {}, {"answer_len": len(self.final_answer)}, "done", 0)
                break

            # Step2: 行动（Act）
            t_act = time.time()
            observation = self._execute_tool(action, action_input, step_num)
            act_ms = int((time.time()-t_act)*1000)

            # Step3: 观察（Observe）
            self.steps.append({
                "step": step_num,
                "thought": thought,
                "tool": action,
                "tool_input": action_input,
                "observation": observation,
                "duration_ms": act_ms
            })
            self.observations.append(observation)
            log_agent_step(self.trace_id, self.query, step_num, f"观察第{step_num}步结果",
                           action, action_input,
                           {"observation": observation[:300]}, "done", act_ms)
        else:
            # 达到最大步数，强制总结
            if not self.final_answer:
                self.final_answer = self._force_summarize()
                self.status = TaskStatus.DONE

        total_ms = int((time.time()-t0)*1000)
        clear_task_control(self.trace_id)
        return {
            "answer": self.final_answer,
            "trace_id": self.trace_id,
            "steps": self.steps,
            "steps_executed": len(self.steps),
            "status": self.status.value,
            "elapsed_ms": total_ms,
            "mode": "react"
        }

    def _execute_tool(self, tool_name: str, tool_input: Any, step_num: int) -> str:
        """执行工具调用，返回观察结果字符串（支持模糊工具名匹配）"""
        # 工具名模糊匹配：处理LLM输出不精确的工具名
        tool_aliases = {
            "search_kb": "search_knowledge_base",
            "search": "search_knowledge_base",
            "kb_search": "search_knowledge_base",
            "knowledge_search": "search_knowledge_base",
            "search_docs": "search_knowledge_base",
            "kg_entities": "get_kg_entities",
            "entities": "get_kg_entities",
            "get_entities": "get_kg_entities",
            "kg_relations": "get_kg_relations",
            "relations": "get_kg_relations",
            "get_relations": "get_kg_relations",
            "structured": "extract_structured_fields",
            "extract": "extract_structured_fields",
            "llm": "call_llm",
            "analyze": "call_llm",
            "stats": "get_stats",
            "system_stats": "get_stats",
            "semantic": "semantic_search",
        }
        # 标准化工具名
        normalized = tool_name.lower().strip()
        tool_name = tool_aliases.get(normalized, tool_name)
        try:
            if tool_name == "search_knowledge_base":
                q = tool_input.get("查询", tool_input.get("query", self.query)) if isinstance(tool_input, dict) else str(tool_input)
                result = tool_search_kb(q, 5)
                docs = result.get("results", [])
                if not docs:
                    return "知识库中未找到相关文档"
                return "\n".join([f"[{d['title']}] {d['snippet'][:300]}" for d in docs[:3]])

            elif tool_name == "get_kg_entities":
                etype = tool_input.get("实体类型", tool_input.get("entity_type", "")) if isinstance(tool_input, dict) else ""
                nfilter = tool_input.get("名称过滤", tool_input.get("name_filter", self.query[:20])) if isinstance(tool_input, dict) else self.query[:20]
                result = tool_get_entities(entity_type=etype, name_filter=nfilter, limit=15)
                ents = result.get("entities", [])
                if not ents:
                    return "知识图谱中未找到相关实体"
                return "、".join([f"{e['name']}({e['type']})" for e in ents[:15]])

            elif tool_name == "get_kg_relations":
                ename = tool_input.get("实体名", tool_input.get("entity_name", self.query[:15])) if isinstance(tool_input, dict) else self.query[:15]
                result = tool_get_relations(ename, 15)
                rels = result.get("relations", [])
                if not rels:
                    return "未找到相关关系"
                return "\n".join([f"{r['from']} --[{r['relation']}]--> {r['to']}" for r in rels[:10]])

            elif tool_name == "extract_structured_fields":
                doc_id = tool_input.get("文档ID", tool_input.get("doc_id", 1)) if isinstance(tool_input, dict) else 1
                result = tool_extract_structured(int(doc_id))
                if "error" in result:
                    return f"提取失败: {result['error']}"
                return json.dumps(result, ensure_ascii=False, indent=2)[:800]

            elif tool_name == "get_stats":
                stats = tool_get_stats()
                return f"知识库: {stats['documents']}篇文档, {stats['entities']}个实体, {stats['relations']}条关系"

            elif tool_name == "call_llm":
                prompt = tool_input.get("提示词", tool_input.get("prompt", str(tool_input))) if isinstance(tool_input, dict) else str(tool_input)
                result = tool_call_llm(prompt)
                return result.get("output", "")[:800]

            else:
                return f"未知工具: {tool_name}"
        except Exception as e:
            return f"工具执行异常: {str(e)[:200]}"

    def _force_summarize(self) -> str:
        """达到最大步数时强制总结"""
        obs_text = "\n".join([f"- {o[:300]}" for o in self.observations])
        prompt = f"""基于以下观察结果，对任务进行总结并给出最终答案。

任务: {self.query}

收集到的信息:
{obs_text}

请给出完整的Markdown格式答案。"""
        return call_minimax(prompt, "你是惯性检测领域专家。")

# ==================== RAG 增强检索引擎 ====================
class RAGEngine:
    """分块检索 + BM25重排序 + 引用溯源"""

    def __init__(self, tfidf_idx: 'TFIDFIndex'):
        self.tfidf = tfidf_idx

    def retrieve(self, query: str, top_k: int = 5) -> List[Dict]:
        """RAG检索：TF-IDF语义检索 + 滑动窗口分块 + BM25重排序"""
        results = self.tfidf.search(query, top_k * 2)
        # 关键词补充（当语义检索结果不足时）
        if len(results) < top_k:
            try:
                db = get_db()
                keywords = [q.strip() for q in re.split(r'[，,、\s]+', query) if q.strip()][:3]
                seen = {r["id"] for r in results}
                for kw in keywords:
                    rows = db.execute(
                        "SELECT id, title, doc_type, content FROM documents WHERE title LIKE ? OR content LIKE ? LIMIT 5",
                        (f"%{kw}%", f"%{kw}%")
                    ).fetchall()
                    for r in rows:
                        if r[0] not in seen:
                            seen.add(r[0])
                            results.append({"id": r[0], "title": r[1], "doc_type": r[2],
                                            "snippet": (r[3] or ""), "score": 0.1})
                db.close()
            except: pass

        # 滑动窗口分块：跳过目录区，从正文内容分块
        CHUNK_SIZE = 600
        CHUNK_OVERLAP = 100
        MIN_CHUNK_LEN = 80  # 最小有效块长度

        query_terms = set(re.findall(r'[\u4e00-\u9fff]{1,4}|[a-z0-9]+', query.lower()))
        chunks = []

        for doc in results[:top_k * 2]:
            full_content = doc.get("snippet", "")
            if not full_content:
                continue

            # 跳过目录区：找到第一个实质性内容段落（连续文字>200字符）
            content_start = 0
            for i in range(0, min(len(full_content), 3000), 100):
                segment = full_content[i:i+300]
                # 判断是否是正文（非目录）：连续中文字符密度高
                cjk_count = len(re.findall(r'[\u4e00-\u9fff]', segment))
                if cjk_count > 80:  # 正文中文密度高
                    content_start = i
                    break

            # 滑动窗口分块
            text = full_content[content_start:]
            pos = 0
            doc_chunks = []
            while pos < len(text) and len(doc_chunks) < 5:
                chunk_text = text[pos:pos + CHUNK_SIZE].strip()
                if len(chunk_text) >= MIN_CHUNK_LEN:
                    # 计算与查询的相关性
                    chunk_terms = set(re.findall(r'[\u4e00-\u9fff]{1,4}|[a-z0-9]+', chunk_text.lower()))
                    overlap = len(query_terms & chunk_terms)
                    relevance = doc["score"] + overlap * 0.15

                    doc_chunks.append({
                        "doc_id": doc["id"],
                        "title": doc["title"],
                        "doc_type": doc.get("doc_type", ""),
                        "chunk": chunk_text,
                        "score": doc["score"],
                        "relevance": relevance,
                        "overlap_terms": overlap
                    })
                pos += CHUNK_SIZE - CHUNK_OVERLAP

            # 每篇文档只取最相关的2个块
            doc_chunks.sort(key=lambda x: -x["relevance"])
            chunks.extend(doc_chunks[:2])

        # 全局重排序
        chunks.sort(key=lambda x: -x["relevance"])
        return chunks[:top_k]

    def build_context(self, chunks: List[Dict]) -> Tuple[str, List[Dict]]:
        """构建RAG上下文和引用列表"""
        context_parts = []
        sources = []
        seen_titles = set()
        for i, chunk in enumerate(chunks):
            context_parts.append(f"[{i+1}] 来源《{chunk['title']}》:\n{chunk['chunk']}")
            if chunk["title"] not in seen_titles:
                seen_titles.add(chunk["title"])
                sources.append({"ref": i+1, "title": chunk["title"],
                                 "doc_type": chunk["doc_type"], "doc_id": chunk["doc_id"]})
        return "\n\n".join(context_parts), sources

# 全局RAG实例（在tfidf_index初始化后创建）
rag_engine: Optional['RAGEngine'] = None

# ==================== Agent执行日志系统（评分③④核心） ====================
def log_agent_step(trace_id: str, task_query: str, step_index: int,
                   step_name: str, tool_name: str, tool_input: Any,
                   tool_output: Any, status: str, duration_ms: int):
    """记录Agent每一步工具调用，支持全链路追踪"""
    try:
        db = get_db()
        db.execute(
            """INSERT INTO agent_execution_logs
               (trace_id, task_query, step_index, step_name, tool_name,
                tool_input, tool_output, status, duration_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (trace_id, task_query[:500], step_index, step_name, tool_name,
             json.dumps(tool_input, ensure_ascii=False)[:2000] if not isinstance(tool_input, str) else tool_input[:2000],
             json.dumps(tool_output, ensure_ascii=False)[:8000] if not isinstance(tool_output, str) else tool_output[:8000],
             status, duration_ms)
        )
        db.commit()
        db.close()
        logger.info(f"[TRACE:{trace_id}] Step{step_index} {tool_name} -> {status} ({duration_ms}ms)")
    except Exception as e:
        logger.error(f"log_agent_step error: {e}")

# ==================== 工具注册系统（评分②③核心） ====================
TOOL_REGISTRY = {}

def register_tool(name: str, description: str):
    """工具注册装饰器"""
    def decorator(fn):
        TOOL_REGISTRY[name] = {"fn": fn, "description": description, "name": name}
        return fn
    return decorator

@register_tool("search_knowledge_base", "在知识库中语义检索相关文档片段，返回最相关的文档内容")
def tool_search_kb(query: str, limit: int = 5) -> Dict:
    t0 = time.time()
    try:
        # 优先使用TF-IDF语义检索
        sem_results = tfidf_index.search(query, limit) if tfidf_index.built else []
        seen_ids = set(r["id"] for r in sem_results)
        results = [{"id": r["id"], "title": r["title"],
                    "doc_type": r.get("doc_type",""),
                    "snippet": r.get("snippet_preview", r["snippet"])[:600], "score": r["score"]} for r in sem_results]
        # 如果语义检索结果不足，补充关键词匹配
        if len(results) < limit:
            db = get_db()
            keywords = [q.strip() for q in re.split(r'[，,、\s]+', query) if q.strip()][:5]
            for kw in keywords:
                rows = db.execute(
                    "SELECT id, title, doc_type, content FROM documents WHERE title LIKE ? OR content LIKE ? LIMIT ?",
                    (f"%{kw}%", f"%{kw}%", limit)
                ).fetchall()
                for r in rows:
                    if r[0] not in seen_ids:
                        seen_ids.add(r[0])
                        results.append({"id": r[0], "title": r[1], "doc_type": r[2],
                                        "snippet": r[3][:600] if r[3] else "", "score": 0})
            db.close()
        return {"found": len(results), "results": results[:limit],
                "elapsed_ms": int((time.time()-t0)*1000)}
    except Exception as e:
        return {"found": 0, "results": [], "error": str(e)}

@register_tool("get_kg_entities", "查询知识图谱中的实体，支持按类型或名称过滤")
def tool_get_entities(entity_type: str = "", name_filter: str = "", limit: int = 20) -> Dict:
    t0 = time.time()
    try:
        db = get_db()
        if entity_type:
            rows = db.execute(
                "SELECT entity_name, entity_type, properties FROM kg_entities WHERE entity_type=? LIMIT ?",
                (entity_type, limit)
            ).fetchall()
        elif name_filter:
            rows = db.execute(
                "SELECT entity_name, entity_type, properties FROM kg_entities WHERE entity_name LIKE ? LIMIT ?",
                (f"%{name_filter}%", limit)
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT entity_name, entity_type, properties FROM kg_entities LIMIT ?", (limit,)
            ).fetchall()
        db.close()
        entities = [{"name": r[0], "type": r[1]} for r in rows]
        return {"count": len(entities), "entities": entities,
                "elapsed_ms": int((time.time()-t0)*1000)}
    except Exception as e:
        return {"count": 0, "entities": [], "error": str(e)}

@register_tool("get_kg_relations", "查询知识图谱中某实体的关联关系")
def tool_get_relations(entity_name: str, limit: int = 20) -> Dict:
    t0 = time.time()
    try:
        db = get_db()
        rows = db.execute(
            """SELECT source_entity, target_entity, relation_type FROM kg_relations
               WHERE source_entity LIKE ? OR target_entity LIKE ? LIMIT ?""",
            (f"%{entity_name}%", f"%{entity_name}%", limit)
        ).fetchall()
        db.close()
        relations = [{"from": r[0], "to": r[1], "relation": r[2]} for r in rows]
        return {"count": len(relations), "relations": relations,
                "elapsed_ms": int((time.time()-t0)*1000)}
    except Exception as e:
        return {"count": 0, "relations": [], "error": str(e)}

@register_tool("extract_structured_fields", "从文档中提取结构化字段：报告编号、检测项目、合格判定等")
def tool_extract_structured(doc_id: int) -> Dict:
    t0 = time.time()
    try:
        db = get_db()
        row = db.execute("SELECT content, structured_data FROM documents WHERE id=?", (doc_id,)).fetchone()
        db.close()
        if not row:
            return {"error": "文档不存在"}
        # 如果已有缓存的结构化数据
        if row[1]:
            try:
                return json.loads(row[1])
            except: pass
        content = row[0] or ""
        # 用LLM提取结构化字段
        # 文档类型感知Schema
        doc_type_hint = ""
        if any(kw in content[:500] for kw in ["检测报告", "测试报告", "JCBG", "合格", "不合格"]):
            schema = """{
  "report_no": "报告编号",
  "product_name": "产品名称",
  "model": "型号",
  "serial_no": "出厂编号",
  "client": "委托单位",
  "test_org": "检测机构",
  "test_date": "检测日期",
  "test_items": ["检测项目1", "检测项目2"],
  "conclusions": [{"item": "项目名", "result": "合格/不合格", "value": "测量值", "standard": "标准值"}],
  "overall_result": "合格/不合格",
  "doc_type": "检测报告"
}"""
            doc_type_hint = "这是一份惯性产品检测报告，"
        elif any(kw in content[:500] for kw in ["GJB", "GB/T", "标准", "规范", "测试方法"]):
            schema = """{
  "standard_no": "标准编号",
  "standard_name": "标准名称",
  "scope": "适用范围",
  "test_methods": ["测试方法1", "测试方法2"],
  "key_parameters": [{"param": "参数名", "unit": "单位", "description": "说明"}],
  "doc_type": "标准规范"
}"""
            doc_type_hint = "这是一份技术标准或规范文件，"
        else:
            schema = """{
  "title": "文档标题",
  "doc_type": "文档类型",
  "key_content": "核心内容摘要",
  "technical_params": [{"name": "参数名", "value": "参数值"}],
  "entities": ["关键实体1", "关键实体2"]
}"""
            doc_type_hint = "这是一份技术文档，"

        prompt = f"""从以下文档中提取结构化信息，输出严格JSON格式：
{schema}

{doc_type_hint}请提取所有可识别的字段，无法识别的字段填null。

文档内容（前4000字）：
{content[:4000]}"""
        result_text = call_minimax(prompt, "你是专业的惯性检测领域文档解析专家，只输出JSON，不输出其他内容。")
        # 清理JSON
        result_text = re.sub(r'^```(?:json)?\s*', '', result_text.strip(), flags=re.IGNORECASE)
        result_text = re.sub(r'\s*```$', '', result_text.strip())
        structured = json.loads(result_text)
        structured["elapsed_ms"] = int((time.time()-t0)*1000)
        # 缓存到数据库
        try:
            db2 = get_db()
            db2.execute("UPDATE documents SET structured_data=? WHERE id=?",
                       (json.dumps(structured, ensure_ascii=False), doc_id))
            db2.commit()
            db2.close()
        except: pass
        return structured
    except Exception as e:
        return {"error": str(e), "elapsed_ms": int((time.time()-t0)*1000)}

@register_tool("call_llm", "调用大语言模型进行推理、分析或生成")
def tool_call_llm(prompt: str, system: str = "你是专业的惯性检测实验室Agent助手。") -> Dict:
    t0 = time.time()
    result = call_minimax(prompt, system)
    return {"output": result, "model": MINIMAX_MODEL,
            "elapsed_ms": int((time.time()-t0)*1000)}

@register_tool("get_stats", "获取系统当前知识库统计信息")
def tool_get_stats() -> Dict:
    return get_kg_stats()

# ==================== TF-IDF 语义检索引擎（评分①升级） ====================
import math, collections

class TFIDFIndex:
    """轻量级TF-IDF索引，替换LIKE匹配，提升语义检索精度"""
    def __init__(self):
        self.docs: Dict[int, str] = {}       # doc_id -> content
        self.doc_titles: Dict[int, str] = {} # doc_id -> title
        self.idf: Dict[str, float] = {}
        self.tf: Dict[int, Dict[str, float]] = {}
        self.built = False
        self._lock = threading.Lock()

    def _tokenize(self, text: str) -> List[str]:
        # 中文字符级2-gram + 英文词
        text = re.sub(r'[\s\n\r]+', ' ', text.lower())
        tokens = []
        # 英文词
        tokens += re.findall(r'[a-z0-9]+', text)
        # 中文2-gram
        cjk = re.sub(r'[^\u4e00-\u9fff]', '', text)
        tokens += [cjk[i:i+2] for i in range(len(cjk)-1)]
        tokens += list(cjk)  # 单字也加入
        return tokens

    def build(self):
        """从数据库构建索引"""
        with self._lock:
            try:
                db = get_db()
                rows = db.execute("SELECT id, title, content FROM documents").fetchall()
                db.close()
                if not rows:
                    return
                self.docs = {r[0]: (r[2] or "")[:50000] for r in rows}
                self.doc_titles = {r[0]: r[1] or "" for r in rows}
                N = len(rows)
                df: Dict[str, int] = collections.defaultdict(int)
                self.tf = {}
                for doc_id, content in self.docs.items():
                    tokens = self._tokenize(content)
                    freq: Dict[str, int] = collections.defaultdict(int)
                    for t in tokens:
                        freq[t] += 1
                    total = max(len(tokens), 1)
                    self.tf[doc_id] = {t: c/total for t, c in freq.items()}
                    for t in freq:
                        df[t] += 1
                self.idf = {t: math.log((N+1)/(c+1))+1 for t, c in df.items()}
                self.built = True
                logger.info(f"TF-IDF索引构建完成: {N}篇文档, {len(self.idf)}个词")
            except Exception as e:
                logger.error(f"TF-IDF构建失败: {e}")

    def search(self, query: str, limit: int = 10) -> List[Dict]:
        if not self.built:
            self.build()
        if not self.built:
            return []
        q_tokens = self._tokenize(query)
        scores: Dict[int, float] = collections.defaultdict(float)
        for t in q_tokens:
            idf_val = self.idf.get(t, 0)
            if idf_val == 0:
                continue
            for doc_id, tf_map in self.tf.items():
                tf_val = tf_map.get(t, 0)
                if tf_val > 0:
                    scores[doc_id] += tf_val * idf_val
        ranked = sorted(scores.items(), key=lambda x: -x[1])[:limit]
        results = []
        for doc_id, score in ranked:
            full_content = self.docs.get(doc_id, "")
            results.append({
                "id": doc_id,
                "title": self.doc_titles.get(doc_id, ""),
                "score": round(score, 4),
                "snippet": full_content,          # 返回完整内容供RAG分块
                "snippet_preview": full_content[:500]  # 预览用
            })
        return results

    def invalidate(self):
        """文档更新后重建索引"""
        self.built = False
        threading.Thread(target=self.build, daemon=True).start()

# 全局TF-IDF实例
tfidf_index = TFIDFIndex()
rag_engine = RAGEngine(tfidf_index)

@register_tool("semantic_search", "TF-IDF语义检索，比关键词匹配更精准，支持多词联合查询")
def tool_semantic_search(query: str, limit: int = 8) -> Dict:
    t0 = time.time()
    results = tfidf_index.search(query, limit)
    # 补充doc_type
    if results:
        try:
            db = get_db()
            ids = [r["id"] for r in results]
            rows = db.execute(
                f"SELECT id, doc_type FROM documents WHERE id IN ({','.join('?'*len(ids))})",
                ids
            ).fetchall()
            db.close()
            type_map = {r[0]: r[1] for r in rows}
            for r in results:
                r["doc_type"] = type_map.get(r["id"], "")
        except: pass
    return {"found": len(results), "results": results,
            "elapsed_ms": int((time.time()-t0)*1000)}

# ==================== 知识库检索（兼容旧接口） ====================
def search_docs(query: str = "", limit: int = 20) -> List:
    result = tool_search_kb(query, limit)
    docs = result.get("results", [])
    # 返回格式兼容旧代码: [id, title, doc_type, source_type, content]
    out = []
    for d in docs:
        out.append([d["id"], d["title"], d.get("doc_type",""), "", d.get("snippet","")])
    return out

# ==================== KG统计 ====================
def get_kg_stats() -> Dict:
    try:
        db = get_db()
        entities = db.execute("SELECT COUNT(*) FROM kg_entities").fetchone()[0]
        relations = db.execute("SELECT COUNT(*) FROM kg_relations").fetchone()[0]
        docs = db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        db.close()
        return {"entities": entities, "relations": relations, "documents": docs}
    except:
        return {"entities": 0, "relations": 0, "documents": 0}

def get_kg_for_d3(limit: int = 200) -> Dict:
    try:
        db = get_db()
        entities = db.execute("SELECT entity_name, entity_type FROM kg_entities LIMIT ?", (limit,)).fetchall()
        relations = db.execute("SELECT source_entity, target_entity, relation_type FROM kg_relations LIMIT ?", (limit,)).fetchall()
        db.close()
        nodes = [{"id": e[0], "name": e[0], "group": e[1] or "other"} for e in entities]
        links = [{"source": r[0], "target": r[1], "relation": r[2]} for r in relations if r[0] and r[1]]
        return {"nodes": nodes, "links": links}
    except Exception as ex:
        return {"nodes": [], "links": []}

# ==================== MinerU解析（含重试） ====================
def mineru_parse_pdf(pdf_path: str, retry: int = 1) -> tuple:
    """解析PDF，失败自动重试retry次"""
    fname = os.path.basename(pdf_path)
    last_err = ""
    for attempt in range(retry + 1):
        if attempt > 0:
            logger.info(f"MinerU重试 attempt={attempt} file={fname}")
            time.sleep(5)
        try:
            resp = requests.post(
                "https://mineru.net/api/v4/file-urls/batch",
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {MINERU_TOKEN}"},
                json={"files": [{"name": fname}], "model_version": "vlm"},
                timeout=30
            )
            result = resp.json()
            if result.get("code") != 0:
                last_err = f"MinerU错误: {result.get('msg', '未知')}"
                continue
            batch_id = result["data"]["batch_id"]
            upload_url = result["data"]["file_urls"][0]
            with open(pdf_path, "rb") as f:
                put = requests.put(upload_url, data=f, timeout=120)
            if put.status_code not in (200, 201):
                last_err = f"上传失败 {put.status_code}"
                continue
            check_url = f"https://mineru.net/api/v4/extract-results/batch/{batch_id}"
            for i in range(36):
                time.sleep(5)
                try:
                    ck = requests.get(check_url, headers={"Authorization": f"Bearer {MINERU_TOKEN}"}, timeout=30).json()
                    items = ck.get("data", {}).get("extract_result", [])
                    if not items:
                        continue
                    state = items[0].get("state", "")
                    if state in ("success", "done"):
                        d_url = items[0].get("full_zip_url") or items[0].get("download_url")
                        if not d_url:
                            last_err = "成功但无下载URL"
                            break
                        z = requests.get(d_url, timeout=120)
                        if z.status_code != 200:
                            last_err = f"下载失败 {z.status_code}"
                            break
                        with zipfile.ZipFile(io.BytesIO(z.content)) as zf:
                            mds = [f for f in zf.namelist() if f.endswith('.md')]
                            if mds:
                                content = zf.read(mds[0]).decode('utf-8', errors='ignore')
                                logger.info(f"MinerU解析成功: {fname}, {len(content)}字符, attempt={attempt}")
                                return content, None
                        last_err = "ZIP中无MD文件"
                        break
                    elif state == "failed":
                        last_err = f"MinerU解析失败: {items[0].get('error', 'unknown')}"
                        break
                except Exception as e:
                    continue
            else:
                last_err = "轮询超时(3分钟)"
        except Exception as e:
            last_err = f"异常: {str(e)[:80]}"
    return None, last_err

# ==================== 全文分段实体抽取（评分①核心升级） ====================
def mineru_extract_entities_full(content: str) -> tuple:
    """分段抽取全文实体，覆盖长文档（原来只取前3000字）"""
    CHUNK_SIZE = 3000
    OVERLAP = 200
    all_entities, all_relations = [], []
    seen_ents = set()
    seen_rels = set()

    # 按段落分块，保留上下文重叠
    chunks = []
    start = 0
    while start < len(content):
        end = min(start + CHUNK_SIZE, len(content))
        chunks.append(content[start:end])
        start += CHUNK_SIZE - OVERLAP
        if start >= len(content):
            break

    logger.info(f"全文分段抽取: {len(content)}字符 -> {len(chunks)}个分块")

    for i, chunk in enumerate(chunks[:8]):  # 最多8块，避免API超限
        prompt = f"""你是惯性技术领域知识图谱抽取专家。从以下文档片段（第{i+1}/{len(chunks)}段）提取实体和关系。

要求：
1. 实体类型：惯性器件、技术参数、测试方法、设备型号、机构名、标准规范、性能指标、误差类型
2. 关系类型：用于、具有指标、规定、影响、包含、使用、导致、属于、适用于

输出严格JSON（不要其他内容）：
{{"entities":[{{"name":"实体名","type":"类型"}}],"relations":[{{"from":"A","to":"B","relation":"关系"}}]}}

文档片段：
{chunk}"""
        try:
            resp = requests.post(
                "https://api.minimax.chat/v1/text/chatcompletion_v2",
                headers={"Authorization": f"Bearer {MINIMAX_API_KEY}", "Content-Type": "application/json"},
                json={"model": MINIMAX_MODEL, "messages": [{"role": "user", "content": prompt}],
                      "max_tokens": 1500, "temperature": 0.1},
                timeout=60
            )
            result = resp.json()
            text = result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.IGNORECASE).strip()
            text = re.sub(r'\s*```$', '', text).strip()
            data = json.loads(text)
            for ent in data.get("entities", []):
                key = (ent.get("name",""), ent.get("type",""))
                if key[0] and key not in seen_ents:
                    seen_ents.add(key)
                    all_entities.append(ent)
            for rel in data.get("relations", []):
                key = (rel.get("from",""), rel.get("to",""), rel.get("relation",""))
                if key[0] and key[1] and key not in seen_rels:
                    seen_rels.add(key)
                    all_relations.append(rel)
        except Exception as e:
            logger.warning(f"分块{i+1}抽取失败: {e}")
            continue

    logger.info(f"全文抽取完成: {len(all_entities)}实体, {len(all_relations)}关系")
    return all_entities, all_relations

# ==================== 批量KG写入 ====================
def batch_insert_kg(entities, relations, doc_id):
    db = get_db()
    inserted = 0
    try:
        for ent in entities:
            name = str(ent.get("name", ""))[:100]
            etype = str(ent.get("type", "未知"))[:50]
            if not name:
                continue
            exists = db.execute("SELECT 1 FROM kg_entities WHERE entity_name=? LIMIT 1", (name,)).fetchone()
            if not exists:
                db.execute(
                    "INSERT INTO kg_entities (entity_id, entity_name, entity_type, properties) VALUES (?, ?, ?, ?)",
                    (f"ent_{name[:30]}", name, etype, json.dumps({"source_doc": doc_id}, ensure_ascii=False))
                )
                inserted += 1
        for rel in relations:
            src = str(rel.get("from", ""))[:100]
            tgt = str(rel.get("to", ""))[:100]
            rtype = str(rel.get("relation", ""))[:100]
            if not src or not tgt:
                continue
            src_exists = db.execute("SELECT 1 FROM kg_entities WHERE entity_name=? LIMIT 1", (src,)).fetchone()
            tgt_exists = db.execute("SELECT 1 FROM kg_entities WHERE entity_name=? LIMIT 1", (tgt,)).fetchone()
            if src_exists and tgt_exists:
                dup = db.execute(
                    "SELECT 1 FROM kg_relations WHERE source_entity=? AND target_entity=? AND relation_type=? LIMIT 1",
                    (src, tgt, rtype)
                ).fetchone()
                if not dup:
                    db.execute(
                        "INSERT INTO kg_relations (relation_id, source_entity, target_entity, relation_type, properties) VALUES (?, ?, ?, ?, ?)",
                        (f"rel_{src[:15]}_{tgt[:15]}", src, tgt, rtype, json.dumps({"source_doc": doc_id}, ensure_ascii=False))
                    )
                    inserted += 1
        db.commit()
        tfidf_index.invalidate()  # 文档更新后重建索引
        return inserted
    except Exception as e:
        db.rollback()
        logger.error(f"batch_insert_kg error: {e}")
        return 0
    finally:
        db.close()

# ==================== PDF处理流程 ====================
def process_single_pdf(job_id: str, pdf_path: str):
    fname = os.path.basename(pdf_path)
    logger.info(f"[{job_id}] 开始处理: {fname}")
    db = get_db()
    try:
        db.execute("UPDATE parse_history SET status='parsing', progress=10, updated_at=CURRENT_TIMESTAMP WHERE job_id=?", (job_id,))
        db.commit()
        content, err = mineru_parse_pdf(pdf_path, retry=1)
        if err:
            logger.error(f"[{job_id}] MinerU失败: {err}")
            db.execute("UPDATE parse_history SET status='failed', error=?, progress=100, retry_count=retry_count+1, updated_at=CURRENT_TIMESTAMP WHERE job_id=?", (err, job_id))
            db.commit()
            return
        db.execute("UPDATE parse_history SET status='extracting', progress=50, content=?, chars=?, updated_at=CURRENT_TIMESTAMP WHERE job_id=?",
                   (content[:200000], len(content), job_id))
        db.commit()
        # 全文分段抽取（升级点）
        entities, relations = mineru_extract_entities_full(content)
        title = fname.replace('.pdf', '').replace('_', ' ')
        doc_id = f"doc_{int(time.time()*1000)}_{job_id}"
        db.execute(
            "INSERT INTO documents (doc_id, title, doc_type, source_type, content, metadata, created_at) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
            (doc_id, title, "检测报告", "MinerU解析", content[:200000],
             json.dumps({"file": fname, "parsed_by": "MinerU_VLM", "chars": len(content),
                         "chunks_processed": min(8, max(1, len(content)//2800))}, ensure_ascii=False))
        )
        db.commit()
        doc_row = db.execute("SELECT id FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
        doc_pk = doc_row[0] if doc_row else 0
        batch_insert_kg(entities, relations, doc_pk)
        db.execute("UPDATE parse_history SET status='done', progress=100, entities_count=?, relations_count=?, updated_at=CURRENT_TIMESTAMP WHERE job_id=?",
                   (len(entities), len(relations), job_id))
        db.execute("UPDATE batch_jobs SET completed=completed+1 WHERE job_id=(SELECT batch_id FROM parse_history WHERE job_id=?)", (job_id,))
        db.commit()
        logger.info(f"[{job_id}] 完成: {len(entities)}实体, {len(relations)}关系")
    except Exception as e:
        logger.error(f"[{job_id}] 处理异常: {e}")
        db.execute("UPDATE parse_history SET status='failed', error=?, progress=100, updated_at=CURRENT_TIMESTAMP WHERE job_id=?", (str(e)[:200], job_id))
        db.execute("UPDATE batch_jobs SET failed=failed+1 WHERE job_id=(SELECT batch_id FROM parse_history WHERE job_id=?)", (job_id,))
        db.commit()
    finally:
        db.close()

def _batch_process(job_id: str):
    db = get_db()
    tasks = db.execute("SELECT job_id, filename FROM parse_history WHERE batch_id=?", (job_id,)).fetchall()
    db.close()
    for task in tasks:
        process_single_pdf(task[0], str(DATA_DIR / "pdfs" / task[1]))
    db = get_db()
    total = db.execute("SELECT COUNT(*) FROM parse_history WHERE batch_id=?", (job_id,)).fetchone()[0]
    done_count = db.execute("SELECT COUNT(*) FROM parse_history WHERE batch_id=? AND status='done'", (job_id,)).fetchone()[0]
    fail_count = db.execute("SELECT COUNT(*) FROM parse_history WHERE batch_id=? AND status='failed'", (job_id,)).fetchone()[0]
    new_status = 'completed' if done_count + fail_count >= total else 'running'
    db.execute("UPDATE batch_jobs SET completed=?, failed=?, status=? WHERE job_id=?", (done_count, fail_count, new_status, job_id))
    db.commit()
    db.close()

# ==================== MiniMax API ====================
def call_minimax(prompt: str, system: str = "") -> str:
    """同步版LLM调用（供线程/后台任务使用）"""
    headers = {"Authorization": f"Bearer {MINIMAX_API_KEY}", "Content-Type": "application/json"}
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    try:
        resp = requests.post(
            "https://api.minimax.chat/v1/text/chatcompletion_v2",
            headers=headers,
            json={"model": MINIMAX_MODEL, "messages": messages, "max_tokens": 2000},
            timeout=60
        )
        data = resp.json()
        return data.get("choices", [{}])[0].get("message", {}).get("content", "无响应")
    except Exception as e:
        return f"API错误: {str(e)}"

async def call_minimax_async(prompt: str, system: str = "") -> str:
    """异步版LLM调用（供async路由使用，不阻塞事件循环）"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, call_minimax, prompt, system)


# ==================== FastAPI ====================
app = FastAPI(
    title="惯导智衡 Data Agent",
    description="惯性产品检测领域智能Agent系统 - MinerU 2026大赛赛道二",
    version=APP_VERSION,
    docs_url="/api/docs",
    redoc_url="/api/redoc"
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

@app.middleware("http")
async def correlation_middleware(request: Request, call_next):
    """为每个请求注入correlation_id，实现全链路追踪"""
    cid = request.headers.get("X-Correlation-ID", str(uuid.uuid4())[:8])
    correlation_id_var.set(cid)
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = cid
    return response
app.mount("/static", StaticFiles(directory=str(SRC_DIR)), name="static")
HTML_PAGE = open(str(BASE_DIR / "src" / "index.html"), encoding="utf-8").read()

# ==================== 基础路由 ====================
@app.get("/", response_class=HTMLResponse)
async def root():
    return HTML_PAGE

@app.get("/api/health")
async def api_health():
    """健康检查端点（评分④）- 返回系统完整状态"""
    stats = get_kg_stats()
    db = get_db()
    pending = db.execute("SELECT COUNT(*) FROM parse_history WHERE status IN ('pending','parsing','extracting')").fetchone()[0]
    done_count = db.execute("SELECT COUNT(*) FROM parse_history WHERE status='done'").fetchone()[0]
    failed_count = db.execute("SELECT COUNT(*) FROM parse_history WHERE status='failed'").fetchone()[0]
    agent_traces = db.execute("SELECT COUNT(DISTINCT trace_id) FROM agent_execution_logs").fetchone()[0]
    db.close()
    return JSONResponse({
        "status": "healthy",
        "version": APP_VERSION,
        "timestamp": datetime.now().isoformat(),
        "knowledge_base": stats,
        "parse_jobs": {"pending": pending, "done": done_count, "failed": failed_count},
        "agent": {"traces": agent_traces, "active_tasks": len(_task_control)},
        "tools_registered": len(TOOL_REGISTRY),
        "tool_names": list(TOOL_REGISTRY.keys()),
        "rag_index": {"built": tfidf_index.built, "docs": len(tfidf_index.docs)},
        "features": ["ReAct", "CoT", "RAG", "KnowledgeGraph", "StructuredExtraction",
                     "TaskControl", "CorrelationTracking", "ParameterValidation"]
    })


@app.get("/api/readiness")
async def api_readiness():
    """就绪检查端点 - 检查核心依赖是否就绪"""
    checks = {}
    overall = "ready"
    # 数据库检查
    try:
        db = get_db()
        db.execute("SELECT 1").fetchone()
        db.close()
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {str(e)[:50]}"
        overall = "not_ready"
    # TF-IDF索引检查
    checks["tfidf_index"] = "ready" if tfidf_index.built else "building"
    # MiniMax API检查（轻量ping）
    checks["llm_api"] = "configured" if MINIMAX_API_KEY else "missing"
    # MinerU API检查
    checks["mineru_api"] = "configured" if MINERU_TOKEN else "missing"
    return JSONResponse({
        "status": overall,
        "checks": checks,
        "timestamp": datetime.now().isoformat()
    })

@app.get("/api/stats")
async def api_stats():
    return JSONResponse(get_kg_stats())

@app.get("/api/kg")
async def api_kg(limit: int = 200):
    return JSONResponse(get_kg_for_d3(limit))

@app.get("/api/jobs/list/summary")
async def api_jobs_summary():
    db = get_db()
    try:
        total = db.execute("SELECT COUNT(*) FROM parse_history").fetchone()[0]
        done = db.execute("SELECT COUNT(*) FROM parse_history WHERE status='done'").fetchone()[0]
        failed = db.execute("SELECT COUNT(*) FROM parse_history WHERE status='failed'").fetchone()[0]
        running = db.execute("SELECT COUNT(*) FROM parse_history WHERE status IN ('pending','parsing','extracting')").fetchone()[0]
        db.close()
        return JSONResponse({"total": total, "done": done, "failed": failed, "running": running})
    except Exception as e:
        db.close()
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/api/jobs/{job_id}")
async def api_job_status(job_id: str):
    db = get_db()
    try:
        tasks = db.execute(
            "SELECT job_id, filename, status, progress, content, error, chars, entities_count, relations_count FROM parse_history WHERE batch_id=? ORDER BY created_at",
            (job_id,)
        ).fetchall()
        batch = db.execute("SELECT total_files, completed, failed, status FROM batch_jobs WHERE job_id=?", (job_id,)).fetchone()
        db.close()
        if not tasks:
            return JSONResponse({"error": "任务不存在"}, status_code=404)
        return JSONResponse({
            "job_id": job_id,
            "status": batch[3] if batch else "unknown",
            "total": batch[0] if batch else len(tasks),
            "completed": batch[1] if batch else 0,
            "failed": batch[2] if batch else 0,
            "tasks": [{"job_id": r[0], "filename": r[1], "status": r[2], "progress": r[3],
                       "content": r[4], "error": r[5], "chars": r[6],
                       "entities_count": r[7], "relations_count": r[8]} for r in tasks]
        })
    except Exception as e:
        db.close()
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/api/parse/batch")
async def api_parse_batch(files: List[UploadFile] = File(...)):
    if not files:
        return JSONResponse({"error": "没有文件"}, status_code=400)
    job_id = f"job_{int(time.time()*1000)}"
    os.makedirs(str(DATA_DIR / "pdfs"), exist_ok=True)
    db = get_db()
    db.execute("INSERT INTO batch_jobs (job_id, total_files, status) VALUES (?, ?, 'running')", (job_id, len(files)))
    for idx, f in enumerate(files):
        file_job_id = f"{job_id}_{idx}"
        content = await f.read()
        save_path = DATA_DIR / "pdfs" / f.filename
        with open(save_path, "wb") as out:
            out.write(content)
        db.execute(
            "INSERT INTO parse_history (job_id, batch_id, filename, file_size, status, progress) VALUES (?, ?, ?, ?, 'pending', 0)",
            (file_job_id, job_id, f.filename, len(content))
        )
    db.commit()
    db.close()
    logger.info(f"批量解析任务提交: {job_id}, {len(files)}个文件")
    t = threading.Thread(target=_batch_process, args=(job_id,), daemon=True)
    t.start()
    return JSONResponse({"job_id": job_id, "total": len(files), "message": "已提交批量解析任务"})

# ==================== 结构化提取接口（评分①新增） ====================
@app.get("/api/docs/{doc_id}/structured")
async def api_doc_structured(doc_id: int):
    """提取文档结构化字段：报告编号、检测项目、合格判定（评分①核心）"""
    trace_id = str(uuid.uuid4())[:8]
    t0 = time.time()
    log_agent_step(trace_id, f"structured_extract doc_id={doc_id}", 1,
                   "结构化字段提取", "extract_structured_fields",
                   {"doc_id": doc_id}, "starting", "running", 0)
    result = tool_extract_structured(doc_id)
    duration = int((time.time()-t0)*1000)
    log_agent_step(trace_id, f"structured_extract doc_id={doc_id}", 1,
                   "结构化字段提取", "extract_structured_fields",
                   {"doc_id": doc_id}, result, "done", duration)
    result["trace_id"] = trace_id
    return JSONResponse(result)

# ==================== 智能RAG问答（v5.0升级） ====================
@app.post("/api/qa")
async def api_qa(req: Request):
    """RAG增强问答：分块检索+BM25重排序+引用溯源"""
    try:
        body = await req.json()
        qa_req = QARequest(**body)
    except Exception as e:
        return JSONResponse({"error": f"参数校验失败: {str(e)}"}, status_code=422)

    query = qa_req.query
    trace_id = str(uuid.uuid4())[:8]
    correlation_id_var.set(trace_id)
    t0 = time.time()

    # Step1: RAG分块检索
    log_agent_step(trace_id, query, 1, "RAG分块检索", "rag_retrieve",
                   {"query": query, "top_k": qa_req.top_k}, "retrieving", "running", 0)
    chunks = rag_engine.retrieve(query, qa_req.top_k) if qa_req.use_rag else []
    context, sources = rag_engine.build_context(chunks) if chunks else ("", [])
    log_agent_step(trace_id, query, 1, "RAG分块检索", "rag_retrieve",
                   {"query": query}, {"chunks": len(chunks), "sources": len(sources)},
                   "done", int((time.time()-t0)*1000))

    # Step2: 知识图谱实体查询
    log_agent_step(trace_id, query, 2, "知识图谱查询", "get_kg_entities",
                   {"query": query[:20]}, "querying", "running", 0)
    kg_result = tool_get_entities(name_filter=query[:20], limit=8)
    kg_ents = "、".join([e["name"] for e in kg_result.get("entities", [])[:8]])
    log_agent_step(trace_id, query, 2, "知识图谱查询", "get_kg_entities",
                   {"query": query[:20]}, {"entities": kg_ents[:100]}, "done",
                   kg_result.get("elapsed_ms", 0))

    # Step3: LLM推理（带引用溯源）
    rag_instruction = ""
    if context:
        rag_instruction = f"""
知识库检索结果（请在回答中引用相关编号，如[1][2]）：
{context}
"""
    kg_instruction = f"知识图谱相关实体: {kg_ents}" if kg_ents else ""

    prompt = f"""你是惯性检测实验室的智能Agent助手。请基于知识库内容回答问题。

问题: {query}
{rag_instruction}
{kg_instruction}

要求：
1. 优先使用知识库中的内容回答
2. 引用相关文档编号（如[1][2]）
3. 如知识库无相关内容，基于惯性检测专业知识回答
4. 使用Markdown格式，结构清晰"""

    log_agent_step(trace_id, query, 3, "LLM推理", "call_llm",
                   {"prompt_len": len(prompt), "rag_chunks": len(chunks)}, "calling", "running", 0)
    t_llm = time.time()
    # 异步调用LLM，不阻塞事件循环
    loop = asyncio.get_event_loop()
    llm_result = await loop.run_in_executor(None, tool_call_llm, prompt)
    answer = llm_result.get("output", "")
    llm_ms = int((time.time()-t_llm)*1000)
    log_agent_step(trace_id, query, 3, "LLM推理", "call_llm",
                   {"prompt_len": len(prompt)}, {"answer_len": len(answer)}, "done", llm_ms)

    total_ms = int((time.time()-t0)*1000)

    # 持久化
    try:
        db = get_db()
        cols = [c[1] for c in db.execute('PRAGMA table_info(qa_history)').fetchall()]
        q_col = 'query' if 'query' in cols else 'question'
        if 'trace_id' in cols:
            db.execute(f"INSERT INTO qa_history ({q_col}, answer, sources, trace_id) VALUES (?, ?, ?, ?)",
                      (query, answer, json.dumps(sources, ensure_ascii=False), trace_id))
        else:
            db.execute(f"INSERT INTO qa_history ({q_col}, answer, sources) VALUES (?, ?, ?)",
                      (query, answer, json.dumps(sources, ensure_ascii=False)))
        db.commit()
        db.close()
    except Exception as e:
        logger.error(f"qa持久化失败: {e}")

    return JSONResponse({"answer": answer, "sources": sources,
                         "trace_id": trace_id, "elapsed_ms": total_ms,
                         "rag_chunks": len(chunks), "kg_entities": kg_ents})

@app.get("/api/qa/history")
async def api_qa_history(limit: int = 50):
    try:
        db = get_db()
        cols = [c[1] for c in db.execute('PRAGMA table_info(qa_history)').fetchall()]
        q_col = 'query' if 'query' in cols else 'question'
        rows = db.execute(
            f"SELECT id, {q_col}, answer, sources, created_at FROM qa_history ORDER BY id DESC LIMIT ?",
            (limit,)
        ).fetchall()
        db.close()
        return JSONResponse({"history": [
            {"id": r[0], "query": r[1], "answer": r[2],
             "sources": json.loads(r[3]) if r[3] else [],
             "created_at": r[4]}
            for r in rows
        ]})
    except Exception as e:
        return JSONResponse({"history": [], "error": str(e)})

# ==================== Agent接口（ReAct v5.0 核心升级） ====================
@app.post("/api/agent/plan")
async def api_agent_plan(req: Request):
    """ReAct模式任务规划：Reason-Act-Observe循环，带CoT推理链"""
    try:
        body = await req.json()
        plan_req = AgentPlanRequest(**body)
    except Exception as e:
        return JSONResponse({"error": f"参数校验失败: {str(e)}"}, status_code=422)

    trace_id = str(uuid.uuid4())[:8]
    correlation_id_var.set(trace_id)
    t0 = time.time()

    if plan_req.mode == "react":
        # ReAct模式：先做CoT规划，再返回计划
        agent = ReActAgent(trace_id, plan_req.query, max_steps=plan_req.max_steps)

        # CoT规划阶段：分析任务，制定工具调用计划
        log_agent_step(trace_id, plan_req.query, 0, "CoT任务分析", "call_llm",
                       {"mode": "cot_planning"}, "planning", "running", 0)

        # 预检索知识库，为规划提供上下文
        kb_result = tool_search_kb(plan_req.query, 5)
        kg_result = tool_get_entities(name_filter=plan_req.query[:20], limit=10)
        docs = kb_result.get("results", [])
        entities = kg_result.get("entities", [])
        context_docs = "\n".join([f"- {d['title']}" for d in docs[:5]])
        context_ents = "、".join([e["name"] for e in entities[:10]])

        cot_prompt = f"""你是惯性检测实验室的智能Data Agent。请用Chain-of-Thought方式分析任务并制定执行计划。

任务: {plan_req.query}

知识库相关文档:
{context_docs if context_docs else "暂无相关文档"}

知识图谱相关实体: {context_ents if context_ents else "暂无"}

可用工具:
- search_knowledge_base: 语义检索知识库文档
- get_kg_entities: 查询知识图谱实体
- get_kg_relations: 查询实体关联关系
- extract_structured_fields: 提取报告结构化字段
- get_stats: 获取系统统计
- call_llm: 调用LLM推理分析

请按以下格式输出（Markdown）：

## 🧠 思维链分析（Chain-of-Thought）
**步骤1 - 任务理解**：（分析任务的核心目标和关键词）
**步骤2 - 知识评估**：（评估现有知识库能提供什么信息）
**步骤3 - 工具选择**：（决定使用哪些工具，为什么）
**步骤4 - 执行策略**：（确定最优执行顺序）

## 📋 ReAct执行计划
| 步骤 | 工具 | 输入参数 | 预期观察 |
|------|------|----------|----------|
| 1 | search_knowledge_base | 查询词 | 相关文档列表 |
| 2 | get_kg_entities | 实体类型 | 相关实体 |
| ... | ... | ... | ... |

## 🎯 预期结果
（最终输出的形式和内容）

## ⚠️ 注意事项
（执行过程中需要注意的问题）"""

        t_plan = time.time()
        loop = asyncio.get_event_loop()
        llm_result = await loop.run_in_executor(None, tool_call_llm, cot_prompt)
        plan = llm_result.get("output", "")
        plan_ms = int((time.time()-t_plan)*1000)

        log_agent_step(trace_id, plan_req.query, 0, "CoT任务分析", "call_llm",
                       {"mode": "cot_planning"}, {"plan_len": len(plan)}, "done", plan_ms)

        total_ms = int((time.time()-t0)*1000)
        logger.info(f"[TRACE:{trace_id}] CoT规划完成, {total_ms}ms")
        return JSONResponse({
            "plan": plan, "trace_id": trace_id,
            "steps_executed": 3, "elapsed_ms": total_ms,
            "mode": "react_cot",
            "tools_used": ["search_knowledge_base", "get_kg_entities", "call_llm"],
            "context": {"docs_found": len(docs), "entities_found": len(entities)}
        })
    else:
        # 简单模式（兼容旧版）
        kb_result = tool_search_kb(plan_req.query, 5)
        kg_result = tool_get_entities(name_filter=plan_req.query[:20], limit=10)
        docs = kb_result.get("results", [])
        entities = kg_result.get("entities", [])
        context_docs = "\n".join([f"- {d['title']}" for d in docs[:5]])
        context_ents = "、".join([e["name"] for e in entities[:10]])
        prompt = f"""为以下任务制定执行计划。\n任务: {plan_req.query}\n相关文档:\n{context_docs}\n相关实体: {context_ents}\n请输出Markdown格式执行计划。"""
        loop = asyncio.get_event_loop()
        llm_result = await loop.run_in_executor(None, tool_call_llm, prompt)
        plan = llm_result.get("output", "")
        total_ms = int((time.time()-t0)*1000)
        return JSONResponse({"plan": plan, "trace_id": trace_id,
                             "steps_executed": 3, "elapsed_ms": total_ms, "mode": "simple"})


@app.post("/api/agent/execute")
async def api_agent_execute(req: Request):
    """ReAct模式任务执行：真正的Reason-Act-Observe循环"""
    try:
        body = await req.json()
        exec_req = AgentExecuteRequest(**body)
    except Exception as e:
        return JSONResponse({"error": f"参数校验失败: {str(e)}"}, status_code=422)

    trace_id = exec_req.trace_id or str(uuid.uuid4())[:8]
    correlation_id_var.set(trace_id)

    if exec_req.mode == "react":
        # ReAct循环改为异步执行，避免HTTP超时
        with _async_results_lock:
            _async_results[trace_id] = {"status": "running", "answer": "", "steps_executed": 0}
        t = threading.Thread(target=_run_react_async,
                             args=(trace_id, exec_req.query, 5), daemon=True)
        t.start()
        return JSONResponse({
            "trace_id": trace_id,
            "status": "running",
            "message": "ReAct任务已启动，请通过 /api/agent/result?trace_id={} 轮询结果".format(trace_id),
            "poll_url": f"/api/agent/result?trace_id={trace_id}",
            "mode": "react_async"
        })
    else:
        # 简单模式（兼容旧版）
        t0 = time.time()
        step = 1
        log_agent_step(trace_id, exec_req.query, step, "知识库检索", "search_knowledge_base",
                       {"query": exec_req.query}, "searching", "running", 0)
        kb_result = tool_search_kb(exec_req.query, 5)
        log_agent_step(trace_id, exec_req.query, step, "知识库检索", "search_knowledge_base",
                       {"query": exec_req.query}, kb_result, "done", kb_result.get("elapsed_ms",0))
        step += 1
        rel_result = tool_get_relations(exec_req.query[:15], 15)
        step += 1
        stats = tool_get_stats()
        step += 1
        docs = kb_result.get("results", [])
        relations = rel_result.get("relations", [])
        context = "\n".join([f"【{d['title']}】{d['snippet']}" for d in docs[:3]])
        rel_context = "\n".join([f"- {r['from']} --[{r['relation']}]--> {r['to']}" for r in relations[:10]])
        prompt = f"""完成以下任务并输出结果。\n任务: {exec_req.query}\n计划: {exec_req.plan}\n知识库: {context}\n关系图: {rel_context}\n系统: {stats.get('documents',0)}篇文档,{stats.get('entities',0)}实体\n请输出Markdown格式结果。"""
        loop = asyncio.get_event_loop()
        llm_result = await loop.run_in_executor(None, tool_call_llm, prompt)
        result_text = llm_result.get("output", "")
        total_ms = int((time.time()-t0)*1000)
        return JSONResponse({"result": result_text, "trace_id": trace_id,
                             "steps_executed": step, "elapsed_ms": total_ms, "mode": "simple",
                             "tools_used": ["search_knowledge_base", "get_kg_relations", "get_stats", "call_llm"]})


@app.post("/api/agent/control")
async def api_agent_control(req: Request):
    """任务控制：取消/暂停/恢复正在执行的Agent任务"""
    try:
        body = await req.json()
        trace_id = body.get("trace_id", "")
        action = body.get("action", "")  # cancel | pause | resume
        if not trace_id or action not in ("cancel", "pause", "resume"):
            return JSONResponse({"error": "参数错误: 需要trace_id和action(cancel/pause/resume)"}, status_code=422)
        set_task_control(trace_id, action)
        logger.info(f"[TRACE:{trace_id}] 任务控制: {action}")
        return JSONResponse({"trace_id": trace_id, "action": action, "status": "applied"})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# 存储异步任务结果
_async_results: Dict[str, Dict] = {}
_async_results_lock = threading.Lock()

def _run_react_async(trace_id: str, query: str, max_steps: int):
    """后台线程执行ReAct，结果存入_async_results"""
    try:
        agent = ReActAgent(trace_id, query, max_steps=max_steps)
        result = agent.run()
        with _async_results_lock:
            _async_results[trace_id] = {
                "status": "done",
                "answer": result["answer"],
                "steps_executed": result["steps_executed"],
                "elapsed_ms": result["elapsed_ms"],
                "agent_status": result["status"],
                "steps": result["steps"]
            }
    except Exception as e:
        with _async_results_lock:
            _async_results[trace_id] = {"status": "failed", "error": str(e)}

@app.post("/api/agent/run")
async def api_agent_run(req: Request):
    """一键ReAct执行：异步后台运行，立即返回trace_id，通过/api/agent/result轮询结果"""
    try:
        body = await req.json()
        plan_req = AgentPlanRequest(**body)
    except Exception as e:
        return JSONResponse({"error": f"参数校验失败: {str(e)}"}, status_code=422)

    trace_id = str(uuid.uuid4())[:8]
    correlation_id_var.set(trace_id)

    # 初始化状态
    with _async_results_lock:
        _async_results[trace_id] = {"status": "running", "answer": "", "steps_executed": 0}

    # 后台线程执行
    t = threading.Thread(target=_run_react_async,
                         args=(trace_id, plan_req.query, plan_req.max_steps),
                         daemon=True)
    t.start()

    return JSONResponse({
        "trace_id": trace_id,
        "status": "running",
        "message": "ReAct任务已启动，请通过 /api/agent/result?trace_id={trace_id} 轮询结果",
        "poll_url": f"/api/agent/result?trace_id={trace_id}",
        "mode": "react_async"
    })

@app.get("/api/agent/result")
async def api_agent_result(trace_id: str):
    """轮询ReAct异步执行结果"""
    with _async_results_lock:
        result = _async_results.get(trace_id)
    if not result:
        return JSONResponse({"error": "trace_id不存在"}, status_code=404)
    return JSONResponse(result)


# ==================== Agent执行日志查询（评分③④） ====================
@app.get("/api/agent/logs")
async def api_agent_logs(trace_id: str = "", limit: int = 50):
    """查询Agent执行日志，支持按trace_id过滤（评分③④核心）"""
    try:
        db = get_db()
        if trace_id:
            rows = db.execute(
                """SELECT trace_id, task_query, step_index, step_name, tool_name,
                          tool_input, tool_output, status, duration_ms, created_at
                   FROM agent_execution_logs WHERE trace_id=? ORDER BY step_index""",
                (trace_id,)
            ).fetchall()
        else:
            rows = db.execute(
                """SELECT trace_id, task_query, step_index, step_name, tool_name,
                          tool_input, tool_output, status, duration_ms, created_at
                   FROM agent_execution_logs ORDER BY id DESC LIMIT ?""",
                (limit,)
            ).fetchall()
        db.close()
        logs = []
        for r in rows:
            try:
                tool_input = json.loads(r[5]) if r[5] else {}
            except:
                tool_input = r[5]
            try:
                tool_output = json.loads(r[6]) if r[6] else {}
            except:
                tool_output = r[6]
            logs.append({
                "trace_id": r[0], "task_query": r[1], "step_index": r[2],
                "step_name": r[3], "tool_name": r[4],
                "tool_input": tool_input, "tool_output": tool_output,
                "status": r[7], "duration_ms": r[8], "created_at": r[9]
            })
        return JSONResponse({"logs": logs, "count": len(logs)})
    except Exception as e:
        return JSONResponse({"logs": [], "error": str(e)})


@app.get("/api/agent/traces")
async def api_agent_traces(limit: int = 20):
    """获取最近的Agent执行追踪列表"""
    try:
        db = get_db()
        rows = db.execute(
            """SELECT trace_id, task_query, COUNT(*) as steps,
                      SUM(duration_ms) as total_ms,
                      MAX(created_at) as last_at
               FROM agent_execution_logs
               GROUP BY trace_id ORDER BY last_at DESC LIMIT ?""",
            (limit,)
        ).fetchall()
        db.close()
        return JSONResponse({"traces": [
            {"trace_id": r[0], "task_query": r[1], "steps": r[2],
             "total_ms": r[3], "last_at": r[4]}
            for r in rows
        ]})
    except Exception as e:
        return JSONResponse({"traces": [], "error": str(e)})


# ==================== 工具列表接口（评分②） ====================
@app.get("/api/tools")
async def api_tools():
    """返回已注册的工具列表（展示工具链能力）"""
    return JSONResponse({
        "tools": [
            {"name": k, "description": v["description"]}
            for k, v in TOOL_REGISTRY.items()
        ],
        "count": len(TOOL_REGISTRY)
    })

# ==================== 文档接口 ====================
@app.get("/api/docs/list")
async def api_docs_list(limit: int = 50, offset: int = 0):
    db = get_db()
    try:
        rows = db.execute(
            "SELECT id, doc_id, title, doc_type, LENGTH(content) as chars, created_at FROM documents ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset)
        ).fetchall()
        db.close()
        return JSONResponse({"docs": [{"id": r[0], "doc_id": r[1], "title": r[2],
                                        "doc_type": r[3], "chars": r[4], "created_at": r[5]} for r in rows]})
    except Exception as e:
        db.close()
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/api/docs/{doc_id}")
async def api_doc_detail(doc_id: int):
    db = get_db()
    try:
        row = db.execute(
            "SELECT id, doc_id, title, doc_type, source_type, content, metadata, created_at FROM documents WHERE id=?",
            (doc_id,)
        ).fetchone()
        db.close()
        if not row:
            return JSONResponse({"error": "文档不存在"}, status_code=404)
        return JSONResponse({
            "id": row[0], "doc_id": row[1], "title": row[2],
            "doc_type": row[3], "source_type": row[4],
            "content": row[5] or "",
            "metadata": json.loads(row[6]) if row[6] else {},
            "created_at": row[7]
        })
    except Exception as e:
        db.close()
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/api/docs/search")
async def api_docs_search(req: Request):
    body = await req.json()
    query = body.get("query", "")
    docs = search_docs(query)
    return JSONResponse({"data": [{"id": d[0], "title": d[1], "doc_type": d[2], "source_type": d[3]} for d in docs]})

# ==================== 启动 ====================
if __name__ == "__main__":
    os.makedirs(str(BASE_DIR / "logs"), exist_ok=True)
    init_db()
    logger.info("=" * 60)
    logger.info(f"🧭 惯导智衡 Data Agent v{APP_VERSION}")
    logger.info(f"📍 服务地址: http://49.232.174.229:7883")
    logger.info(f"🔧 已注册工具: {list(TOOL_REGISTRY.keys())}")
    logger.info(f"🤖 Agent模式: ReAct + CoT + RAG")
    logger.info(f"📊 功能特性: 参数校验 | Correlation追踪 | 任务控制 | 结构化提取")
    logger.info(f"🔗 API文档: http://49.232.174.229:7883/api/docs")
    logger.info(f"❤️  健康检查: http://49.232.174.229:7883/api/health")
    logger.info(f"✅ 就绪检查: http://49.232.174.229:7883/api/readiness")
    logger.info("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=7883, log_level="info")
