#!/usr/bin/env python3
"""
惯导智衡 - 惯性检测实验室智能Agent (专业版 v3.2)
MinerU 2026大赛赛道二 · Data Agent
"""

import sys, os, time, json, re, sqlite3, zipfile, io, threading
from pathlib import Path
from typing import Dict, List
from datetime import datetime
import uvicorn
from fastapi import FastAPI, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware
import requests

# ==================== 配置 ====================
# 敏感凭证优先从环境变量读取，回退到内置值（生产环境请设置环境变量）
MINIMAX_API_KEY = os.environ.get("MINIMAX_API_KEY", "sk-cp-ypfEn_bc2iumGQhRTyJjhRU1oSK6XMCLvv0Ow3ehAuP1K6rmetK_UO5vQPFSptVeWwTTftP77EyNA7FPMyXTgkTD2qjVwj-7ifRZz4pA5iksyAGpFEMYGfc")
MINIMAX_MODEL = "MiniMax-M2.7"
MINERU_TOKEN = os.environ.get("MINERU_TOKEN", "eyJ0eXBlIjoiSldUIiwiYWxnIjoiSFM1MTIifQ.eyJqdGkiOiIyODkwMDY0NiIsInJvbCI6IlJPTEVfUkVHSVNURVIiLCJpc3MiOiJPcGVuWExhYiIsImlhdCI6MTc3NDI1NjQ0MywiY2xpZW50SWQiOiJsa3pkeDU3bnZ5MjJqa3BxOXgydyIsInBob25lIjoiMTMyNjAxNjk4ODUiLCJvcGVuSWQiOm51bGwsInV1aWQiOiJmNTg5ZjE5NC1jYmFkLTQ5ZTUtYWQ4Zi04MmU0M2UyZWRhZDQiLCJlbWFpbCI6IiIsImV4cCI6MTc4MjAzMjQ0M30.DTzzcfCKsyadfeNy3mwoJ93V11mkPiOXE3sKlq8NYvfl2EWmngcmJbw5OGni0LegfNz7oETK30blEQt3nuupMg")
APP_VERSION = "3.2"
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
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS qa_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        query TEXT NOT NULL,
        answer TEXT,
        sources TEXT,
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
    """)
    db.commit()
    db.close()

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
        print(f"get_kg_for_d3 error: {ex}")
        return {"nodes": [], "links": []}

def search_docs(query: str = "", limit: int = 20) -> List:
    try:
        db = get_db()
        cur = db.execute(
            "SELECT id, title, doc_type, source_type, content FROM documents WHERE title LIKE ? OR content LIKE ? LIMIT ?",
            (f"%{query}%", f"%{query}%", limit)
        )
        rows = cur.fetchall()
        db.close()
        return [[r[0], r[1] or "", r[2] or "", r[3] or "", r[4] or ""] for r in rows]
    except Exception as ex:
        print(f"search_docs error: {ex}")
        return []

# ==================== MinerU解析 ====================
def mineru_parse_pdf(pdf_path: str) -> tuple:
    fname = os.path.basename(pdf_path)
    try:
        resp = requests.post(
            "https://mineru.net/api/v4/file-urls/batch",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {MINERU_TOKEN}"},
            json={"files": [{"name": fname}], "model_version": "vlm"},
            timeout=30
        )
        result = resp.json()
        if result.get("code") != 0:
            return None, f"MinerU错误: {result.get('msg', '未知')}"
        batch_id = result["data"]["batch_id"]
        upload_url = result["data"]["file_urls"][0]
        with open(pdf_path, "rb") as f:
            put = requests.put(upload_url, data=f, timeout=120)
        if put.status_code not in (200, 201):
            return None, f"上传失败 {put.status_code}"
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
                        return None, "成功但无下载URL"
                    z = requests.get(d_url, timeout=120)
                    if z.status_code != 200:
                        return None, f"下载失败 {z.status_code}"
                    with zipfile.ZipFile(io.BytesIO(z.content)) as zf:
                        mds = [f for f in zf.namelist() if f.endswith('.md')]
                        if mds:
                            content = zf.read(mds[0]).decode('utf-8', errors='ignore')
                            return content, None
                    return None, "ZIP中无MD文件"
                elif state == "failed":
                    return None, f"MinerU解析失败: {items[0].get('error', 'unknown')}"
            except Exception as e:
                continue
        return None, "轮询超时"
    except Exception as e:
        return None, f"异常: {str(e)[:80]}"

def mineru_extract_entities(content: str) -> tuple:
    prompt = f"""你是一个惯性技术领域的知识图谱抽取专家。从以下文档内容中提取实体和关系。

要求：
1. 实体（entity）：惯性器件、技术参数、测试方法、设备型号、人名、机构名等
2. 关系（relation）：实体之间的关系

输出严格的JSON格式（不要任何其他内容）：
{{
  "entities": [
    {{"name": "实体名称", "type": "实体类型"}}
  ],
  "relations": [
    {{"from": "实体A", "to": "实体B", "relation": "关系描述"}}
  ]
}}

文档内容：
{content[:3000]}"""
    try:
        resp = requests.post(
            "https://api.minimax.chat/v1/text/chatcompletion_v2",
            headers={"Authorization": f"Bearer {MINIMAX_API_KEY}", "Content-Type": "application/json"},
            json={"model": MINIMAX_MODEL, "messages": [{"role": "user", "content": prompt}], "max_tokens": 1500, "temperature": 0.1},
            timeout=60
        )
        result = resp.json()
        content_text = result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        if content_text.startswith("```"):
            content_text = re.sub(r"^```(?:json)?\s*", "", content_text, flags=re.IGNORECASE).strip()
            content_text = re.sub(r"\s*```$", "", content_text).strip()
        data = json.loads(content_text)
        return data.get("entities", []), data.get("relations", [])
    except Exception as e:
        return [], []

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
        return inserted
    except Exception as e:
        db.rollback()
        print(f"batch_insert_kg error: {e}")
        return 0
    finally:
        db.close()

def process_single_pdf(job_id: str, pdf_path: str):
    fname = os.path.basename(pdf_path)
    db = get_db()
    try:
        db.execute("UPDATE parse_history SET status='parsing', progress=10, updated_at=CURRENT_TIMESTAMP WHERE job_id=?", (job_id,))
        db.commit()
        content, err = mineru_parse_pdf(pdf_path)
        if err:
            db.execute("UPDATE parse_history SET status='failed', error=?, progress=100, updated_at=CURRENT_TIMESTAMP WHERE job_id=?", (err, job_id))
            db.commit()
            return
        db.execute("UPDATE parse_history SET status='extracting', progress=50, content=?, chars=?, updated_at=CURRENT_TIMESTAMP WHERE job_id=?",
                   (content[:200000], len(content), job_id))
        db.commit()
        entities, relations = mineru_extract_entities(content)
        title = fname.replace('.pdf', '').replace('_', ' ')
        doc_id = f"doc_{int(time.time()*1000)}_{job_id}"
        db.execute(
            "INSERT INTO documents (doc_id, title, doc_type, source_type, content, metadata) VALUES (?, ?, ?, ?, ?, ?)",
            (doc_id, title, "检测报告", "MinerU解析", content[:200000],
             json.dumps({"file": fname, "parsed_by": "MinerU", "chars": len(content)}, ensure_ascii=False))
        )
        db.commit()
        doc_row = db.execute("SELECT id FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
        doc_pk = doc_row[0] if doc_row else 0
        batch_insert_kg(entities, relations, doc_pk)
        db.execute("UPDATE parse_history SET status='done', progress=100, entities_count=?, relations_count=?, updated_at=CURRENT_TIMESTAMP WHERE job_id=?",
                   (len(entities), len(relations), job_id))
        db.execute("UPDATE batch_jobs SET completed=completed+1 WHERE job_id=(SELECT batch_id FROM parse_history WHERE job_id=?)", (job_id,))
        db.commit()
    except Exception as e:
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
        task_job_id = task[0]
        fname = task[1]
        pdf_path = DATA_DIR / "pdfs" / fname
        if pdf_path.exists():
            process_single_pdf(task_job_id, str(pdf_path))
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

# ==================== FastAPI ====================
app = FastAPI(title="惯导智衡", version=APP_VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=str(SRC_DIR)), name="static")

# ==================== HTML页面 ====================
HTML_PAGE = open(str(BASE_DIR / "src" / "index.html"), encoding="utf-8").read()

# ==================== 路由 ====================
@app.get("/", response_class=HTMLResponse)
async def root():
    return HTML_PAGE

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
    t = threading.Thread(target=_batch_process, args=(job_id,), daemon=True)
    t.start()
    return JSONResponse({"job_id": job_id, "total": len(files), "message": "已提交批量解析任务"})

@app.post("/api/qa")
async def api_qa(req: Request):
    body = await req.json()
    query = body.get("query", "")
    docs = search_docs(query)
    context = "\n".join([f"【{d[1]}】{d[4][:500]}" for d in docs[:3]])
    prompt = f"""你是一个惯性检测实验室的智能Agent助手，请根据以下知识库内容回答问题。

问题: {query}

知识库内容:
{context if context else '暂无相关文档'}

请给出专业、准确的回答。"""
    answer = call_minimax(prompt, "你是专业的惯性检测实验室Agent助手。")
    sources = [{"title": d[1], "type": d[2]} for d in docs[:3]]
    # 持久化QA历史（兼容旧表字段 question/query）
    try:
        db = get_db()
        cols = [c[1] for c in db.execute('PRAGMA table_info(qa_history)').fetchall()]
        if 'query' in cols:
            db.execute(
                "INSERT INTO qa_history (query, answer, sources) VALUES (?, ?, ?)",
                (query, answer, json.dumps(sources, ensure_ascii=False))
            )
        else:
            db.execute(
                "INSERT INTO qa_history (question, answer, sources) VALUES (?, ?, ?)",
                (query, answer, json.dumps(sources, ensure_ascii=False))
            )
        db.commit()
        db.close()
    except Exception:
        pass
    return JSONResponse({"answer": answer, "sources": sources})

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

@app.post("/api/agent/plan")
async def api_agent_plan(req: Request):
    body = await req.json()
    query = body.get("query", "")
    docs = search_docs(query)
    context = "\n".join([f"【{d[1]}】" for d in docs[:5]])
    prompt = f"""你是一个惯性检测实验室的智能Agent助手。请为以下任务制定执行计划:

任务: {query}

已上传的相关文档: {context if context else '暂无'}

请按以下格式输出计划（用中文）:
1. 任务理解：...
2. 步骤规划：...（列出具体步骤）
3. 预期结果：...

请给出详细可行的执行计划。"""
    plan = call_minimax(prompt, "你是专业的惯性检测实验室Agent助手。")
    return JSONResponse({"plan": plan})

@app.post("/api/agent/execute")
async def api_agent_execute(req: Request):
    body = await req.json()
    query = body.get("query", "")
    plan = body.get("plan", "")  # 接收前端传入的计划
    docs = search_docs(query)
    context = "\n".join([f"【{d[1]}】{d[4][:500]}" for d in docs[:3]])
    plan_section = f"\n\n执行计划:\n{plan}" if plan else ""
    prompt = f"""你是一个惯性检测实验室的智能Agent。请严格按照以下计划执行任务并给出结果:

任务: {query}{plan_section}

参考文档:
{context if context else '无'}

请直接给出执行结果，包含：分析结论、数据摘要、建议。如果需要生成报告格式请用Markdown输出。"""
    result = call_minimax(prompt, "你是专业的惯性检测实验室Agent助手。")
    return JSONResponse({"result": result})

@app.get("/api/docs/list")
async def api_docs_list(limit: int = 50, offset: int = 0):
    db = get_db()
    try:
        rows = db.execute(
            "SELECT id, doc_id, title, doc_type, LENGTH(content) as chars, created_at FROM documents ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset)
        ).fetchall()
        db.close()
        return JSONResponse({"docs": [{"id": r[0], "doc_id": r[1], "title": r[2], "doc_type": r[3], "chars": r[4], "created_at": r[5]} for r in rows]})
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
    init_db()
    print("=" * 60)
    print("🧭 惯导智衡 - 惯性检测实验室智能Agent v3.2")
    print("=" * 60)
    print(f"📍 服务地址: http://49.232.174.229:7883")
    print("💡 按 Ctrl+C 停止服务")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=7883, log_level="info")
