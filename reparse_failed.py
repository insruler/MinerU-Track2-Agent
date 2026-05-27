#!/usr/bin/env python3
"""
重新解析所有 failed 状态的 PDF 文件
- 将 failed 记录重置为 pending
- 创建新的 batch_job
- 逐个调用 MinerU 解析（串行，避免并发超限）
"""
import sqlite3, os, time, json, requests, zipfile, io, logging, sys

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('/root/MinerU_Track2_Agent/logs/reparse.log', mode='w')
    ]
)
logger = logging.getLogger('reparse')

DB_PATH   = '/root/MinerU_Track2_Agent/data/knowledge.db'
PDF_DIR   = '/root/MinerU_Track2_Agent/data/pdfs'
MINERU_TOKEN = "eyJ0eXBlIjoiSldUIiwiYWxnIjoiSFM1MTIifQ.eyJqdGkiOiIyODkwMDY0NiIsInJvbCI6IlJPTEVfUkVHSVNURVIiLCJpc3MiOiJPcGVuWExhYiIsImlhdCI6MTc3NDI1NjQ0MywiY2xpZW50SWQiOiJsa3pkeDU3bnZ5MjJqa3BxOXgydyIsInBob25lIjoiMTMyNjAxNjk4ODUiLCJvcGVuSWQiOm51bGwsInV1aWQiOiJmNTg5ZjE5NC1jYmFkLTQ5ZTUtYWQ4Zi04MmU0M2UyZWRhZDQiLCJlbWFpbCI6IiIsImV4cCI6MTc4MjAzMjQ0M30.DTzzcfCKsyadfeNy3mwoJ93V11mkPiOXE3sKlq8NYvfl2EWmngcmJbw5OGni0LegfNz7oETK30blEQt3nuupMg"
MINIMAX_API_KEY = "sk-cp-ypfEn_bc2iumGQhRTyJjhRU1oSK6XMCLvv0Ow3ehAuP1K6rmetK_UO5vQPFSptVeWwTTftP77EyNA7FPMyXTgkTD2qjVwj-7ifRZz4pA5iksyAGpFEMYGfc"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ── MinerU 解析 ──────────────────────────────────────────────────────────────
def mineru_parse_pdf(pdf_path: str, retry: int = 2) -> tuple:
    fname = os.path.basename(pdf_path)
    last_err = ""
    for attempt in range(retry + 1):
        if attempt > 0:
            logger.info(f"MinerU重试 attempt={attempt} file={fname}")
            time.sleep(10)
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
                logger.warning(f"{fname}: {last_err}")
                continue
            batch_id = result["data"]["batch_id"]
            upload_url = result["data"]["file_urls"][0]
            with open(pdf_path, "rb") as f:
                put = requests.put(upload_url, data=f, timeout=180)
            if put.status_code not in (200, 201):
                last_err = f"上传失败 {put.status_code}"
                continue
            check_url = f"https://mineru.net/api/v4/extract-results/batch/{batch_id}"
            for i in range(60):   # 最多等5分钟
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
                        z = requests.get(d_url, timeout=180)
                        if z.status_code != 200:
                            last_err = f"下载失败 {z.status_code}"
                            break
                        with zipfile.ZipFile(io.BytesIO(z.content)) as zf:
                            mds = [f for f in zf.namelist() if f.endswith('.md')]
                            if mds:
                                content = zf.read(mds[0]).decode('utf-8', errors='ignore')
                                logger.info(f"MinerU解析成功: {fname}, {len(content)}字符")
                                return content, None
                        last_err = "ZIP中无MD文件"
                        break
                    elif state == "failed":
                        last_err = f"MinerU解析失败: {items[0].get('error', 'unknown')}"
                        break
                except Exception as e:
                    continue
            else:
                last_err = "轮询超时(5分钟)"
        except Exception as e:
            last_err = f"异常: {str(e)[:100]}"
    return None, last_err

# ── LLM 实体抽取（简化版，与 app.py 保持一致） ───────────────────────────────
def call_minimax(prompt: str, system: str = "") -> str:
    headers = {"Authorization": f"Bearer {MINIMAX_API_KEY}", "Content-Type": "application/json"}
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload = {
        "model": "MiniMax-M2.7",
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 8192
    }
    resp = requests.post(
        "https://api.minimax.chat/v1/text/chatcompletion_v2",
        headers=headers, json=payload, timeout=120
    )
    data = resp.json()
    choices = data.get("choices")
    if not choices:
        raise ValueError(f"LLM无响应: {data.get('base_resp', {})}.get('status_msg', str(data)[:100])")
    msg = choices[0]["message"]
    # MiniMax-M2.7 是思考模型，正文在 content，思考在 reasoning_content
    content = msg.get("content", "").strip()
    if not content:
        # 有时正文为空但 reasoning_content 有内容，尝试从中提取JSON
        content = msg.get("reasoning_content", "").strip()
    return content

def extract_entities(content: str) -> tuple:
    chunk_size = 2800
    chunks = [content[i:i+chunk_size] for i in range(0, min(len(content), 22400), chunk_size)]
    all_entities, all_relations = [], []
    seen_e, seen_r = set(), set()
    for idx, chunk in enumerate(chunks):
        try:
            prompt = f"""从以下惯性器件检测文档片段中抽取实体和关系，以JSON格式返回。
实体类型：产品型号、检测项目、技术指标、标准规范、检测机构、客户单位
关系类型：检测项目-技术指标、产品型号-检测项目、标准规范-检测项目

文档片段：
{chunk}

返回格式：
{{"entities":[{{"name":"实体名","type":"实体类型","value":"具体值或描述"}}],"relations":[{{"source":"实体1","relation":"关系类型","target":"实体2"}}]}}

只返回JSON，不要其他内容。"""
            raw = call_minimax(prompt)
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            data = json.loads(raw)
            for e in data.get("entities", []):
                key = (e.get("name",""), e.get("type",""))
                if key not in seen_e and e.get("name"):
                    seen_e.add(key)
                    all_entities.append(e)
            for r in data.get("relations", []):
                key = (r.get("source",""), r.get("relation",""), r.get("target",""))
                if key not in seen_r and r.get("source") and r.get("target"):
                    seen_r.add(key)
                    all_relations.append(r)
        except Exception as ex:
            logger.warning(f"实体抽取chunk{idx}失败: {ex}")
    return all_entities, all_relations

# ── 主流程 ────────────────────────────────────────────────────────────────────
def main():
    db = get_db()
    failed = db.execute(
        "SELECT job_id, filename FROM parse_history WHERE status='failed'"
    ).fetchall()
    db.close()

    total = len(failed)
    logger.info(f"待重新解析文件数: {total}")

    success_count = 0
    fail_count = 0

    for idx, row in enumerate(failed):
        job_id  = row["job_id"]
        fname   = row["filename"]
        pdf_path = os.path.join(PDF_DIR, fname)

        logger.info(f"[{idx+1}/{total}] 开始: {fname}")

        if not os.path.exists(pdf_path):
            logger.error(f"文件不存在: {pdf_path}")
            fail_count += 1
            continue

        # 重置状态
        db = get_db()
        db.execute(
            "UPDATE parse_history SET status='parsing', progress=10, error=NULL, updated_at=CURRENT_TIMESTAMP WHERE job_id=?",
            (job_id,)
        )
        db.commit()
        db.close()

        # MinerU 解析
        content, err = mineru_parse_pdf(pdf_path, retry=2)
        if err:
            logger.error(f"[{idx+1}/{total}] 失败: {fname} -> {err}")
            db = get_db()
            db.execute(
                "UPDATE parse_history SET status='failed', error=?, progress=100, retry_count=retry_count+1, updated_at=CURRENT_TIMESTAMP WHERE job_id=?",
                (err, job_id)
            )
            db.commit()
            db.close()
            fail_count += 1
            time.sleep(2)
            continue

        # 实体抽取
        db = get_db()
        db.execute(
            "UPDATE parse_history SET status='extracting', progress=50, content=?, chars=?, updated_at=CURRENT_TIMESTAMP WHERE job_id=?",
            (content[:200000], len(content), job_id)
        )
        db.commit()
        db.close()

        entities, relations = extract_entities(content)

        # 写入 documents 表（先检查是否已存在）
        db = get_db()
        title = fname.replace('.pdf', '').replace('_', ' ')
        existing = db.execute("SELECT id FROM documents WHERE title=?", (title,)).fetchone()
        if existing:
            # 更新已有文档内容
            db.execute(
                "UPDATE documents SET content=?, metadata=? WHERE title=?",
                (content[:200000],
                 json.dumps({"file": fname, "parsed_by": "MinerU_VLM_reparse", "chars": len(content)}, ensure_ascii=False),
                 title)
            )
            doc_pk = existing[0]
            logger.info(f"更新已有文档: {title}")
        else:
            doc_id = f"doc_{int(time.time()*1000)}_{job_id}"
            db.execute(
                "INSERT INTO documents (doc_id, title, doc_type, source_type, content, metadata, created_at) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
                (doc_id, title, "检测报告", "MinerU解析",
                 content[:200000],
                 json.dumps({"file": fname, "parsed_by": "MinerU_VLM_reparse", "chars": len(content)}, ensure_ascii=False))
            )
            db.commit()
            doc_row = db.execute("SELECT id FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
            doc_pk = doc_row[0] if doc_row else 0

        # 写入知识图谱
        for e in entities:
            try:
                db.execute(
                    "INSERT OR IGNORE INTO kg_entities (name, entity_type, description, doc_id) VALUES (?, ?, ?, ?)",
                    (e.get("name","")[:200], e.get("type","")[:100], e.get("value","")[:500], doc_pk)
                )
            except Exception:
                pass
        for r in relations:
            try:
                src = db.execute("SELECT id FROM kg_entities WHERE name=?", (r.get("source",""),)).fetchone()
                tgt = db.execute("SELECT id FROM kg_entities WHERE name=?", (r.get("target",""),)).fetchone()
                if src and tgt:
                    db.execute(
                        "INSERT OR IGNORE INTO kg_relations (source_id, relation_type, target_id, doc_id) VALUES (?, ?, ?, ?)",
                        (src[0], r.get("relation","")[:100], tgt[0], doc_pk)
                    )
            except Exception:
                pass

        db.execute(
            "UPDATE parse_history SET status='done', progress=100, entities_count=?, relations_count=?, updated_at=CURRENT_TIMESTAMP WHERE job_id=?",
            (len(entities), len(relations), job_id)
        )
        db.commit()
        db.close()

        success_count += 1
        logger.info(f"[{idx+1}/{total}] 完成: {fname} | 实体={len(entities)} 关系={len(relations)} 内容={len(content)}字符")

        # 每10个打印一次进度
        if (idx + 1) % 10 == 0:
            logger.info(f"===== 进度: {idx+1}/{total} 成功={success_count} 失败={fail_count} =====")

        time.sleep(1)  # 避免API过快

    logger.info(f"===== 全部完成: 总={total} 成功={success_count} 失败={fail_count} =====")

    # 最终统计
    db = get_db()
    docs = db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    entities = db.execute("SELECT COUNT(*) FROM kg_entities").fetchone()[0]
    db.close()
    logger.info(f"知识库最终状态: 文档={docs} 实体={entities}")

if __name__ == "__main__":
    main()
