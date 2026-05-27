#!/usr/bin/env python3
"""
快速重解析：只做 MinerU PDF→文本提取，跳过实体抽取
实体抽取后续单独批量处理
"""
import sqlite3, os, time, json, requests, zipfile, io, logging, sys

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('/root/MinerU_Track2_Agent/logs/reparse_fast.log', mode='w')
    ]
)
logger = logging.getLogger('reparse')

DB_PATH   = '/root/MinerU_Track2_Agent/data/knowledge.db'
PDF_DIR   = '/root/MinerU_Track2_Agent/data/pdfs'
MINERU_TOKEN = os.environ.get("MINERU_TOKEN", "eyJ0eXBlIjoiSldUIiwiYWxnIjoiSFM1MTIifQ.eyJqdGkiOiIyODkwMDY0NiIsInJvbCI6IlJPTEVfUkVHSVNURVIiLCJpc3MiOiJPcGVuWExhYiIsImlhdCI6MTc3NDI1NjQ0MywiY2xpZW50SWQiOiJsa3pkeDU3bnZ5MjJqa3BxOXgydyIsInBob25lIjoiMTMyNjAxNjk4ODUiLCJvcGVuSWQiOm51bGwsInV1aWQiOiJmNTg5ZjE5NC1jYmFkLTQ5ZTUtYWQ4Zi04MmU0M2UyZWRhZDQiLCJlbWFpbCI6IiIsImV4cCI6MTc4MjAzMjQ0M30.DTzzcfCKsyadfeNy3mwoJ93V11mkPiOXE3sKlq8NYvfl2EWmngcmJbw5OGni0LegfNz7oETK30blEQt3nuupMg")

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn

def mineru_parse_pdf(pdf_path: str, retry: int = 2) -> tuple:
    fname = os.path.basename(pdf_path)
    last_err = ""
    for attempt in range(retry + 1):
        if attempt > 0:
            logger.info(f"  重试 attempt={attempt}")
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
                last_err = f"API错误: {result.get('msg', '未知')}"
                continue
            batch_id = result["data"]["batch_id"]
            upload_url = result["data"]["file_urls"][0]
            with open(pdf_path, "rb") as f:
                put = requests.put(upload_url, data=f, timeout=180)
            if put.status_code not in (200, 201):
                last_err = f"上传失败 {put.status_code}"
                continue
            check_url = f"https://mineru.net/api/v4/extract-results/batch/{batch_id}"
            for i in range(72):  # 最多等6分钟
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
                            mds = [fn for fn in zf.namelist() if fn.endswith('.md')]
                            if mds:
                                content = zf.read(mds[0]).decode('utf-8', errors='ignore')
                                return content, None
                        last_err = "ZIP中无MD文件"
                        break
                    elif state == "failed":
                        last_err = f"解析失败: {items[0].get('error', 'unknown')}"
                        break
                except:
                    continue
            else:
                last_err = "轮询超时(6分钟)"
        except Exception as e:
            last_err = f"异常: {str(e)[:100]}"
    return None, last_err

def main():
    db = get_db()
    failed = db.execute(
        "SELECT job_id, filename FROM parse_history WHERE status='failed'"
    ).fetchall()
    db.close()

    total = len(failed)
    logger.info(f"待重新解析: {total} 个文件")
    if total == 0:
        logger.info("无需处理")
        return

    success = 0
    fail = 0

    for idx, row in enumerate(failed):
        job_id = row["job_id"]
        fname  = row["filename"]
        pdf_path = os.path.join(PDF_DIR, fname)

        if not os.path.exists(pdf_path):
            logger.error(f"[{idx+1}/{total}] 文件不存在: {fname}")
            fail += 1
            continue

        logger.info(f"[{idx+1}/{total}] 解析: {fname}")

        # MinerU 解析
        content, err = mineru_parse_pdf(pdf_path, retry=2)
        if err:
            logger.error(f"  失败: {err}")
            db = get_db()
            db.execute(
                "UPDATE parse_history SET status='failed', error=?, retry_count=retry_count+1, updated_at=CURRENT_TIMESTAMP WHERE job_id=?",
                (err, job_id)
            )
            db.commit()
            db.close()
            fail += 1
            time.sleep(2)
            continue

        # 写入数据库（只存内容，不做实体抽取）
        db = get_db()
        title = fname.replace('.pdf', '').replace('_', ' ')

        # 更新 parse_history
        db.execute(
            "UPDATE parse_history SET status='done', progress=100, content=?, chars=?, error=NULL, updated_at=CURRENT_TIMESTAMP WHERE job_id=?",
            (content[:200000], len(content), job_id)
        )

        # 更新或插入 documents
        existing = db.execute("SELECT id FROM documents WHERE title=?", (title,)).fetchone()
        if existing:
            db.execute(
                "UPDATE documents SET content=?, metadata=? WHERE id=?",
                (content[:200000],
                 json.dumps({"file": fname, "parsed_by": "MinerU_VLM_reparse", "chars": len(content)}, ensure_ascii=False),
                 existing["id"])
            )
        else:
            doc_id = f"doc_{int(time.time()*1000)}_{job_id}"
            db.execute(
                "INSERT INTO documents (doc_id, title, doc_type, source_type, content, metadata, created_at) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
                (doc_id, title, "检测报告", "MinerU解析",
                 content[:200000],
                 json.dumps({"file": fname, "parsed_by": "MinerU_VLM_reparse", "chars": len(content)}, ensure_ascii=False))
            )

        db.commit()
        db.close()

        success += 1
        logger.info(f"  完成: {len(content)}字符")

        if (idx + 1) % 10 == 0:
            logger.info(f"===== 进度: {idx+1}/{total} 成功={success} 失败={fail} =====")

        time.sleep(1)

    logger.info(f"===== 全部完成: 总={total} 成功={success} 失败={fail} =====")

    db = get_db()
    docs = db.execute("SELECT COUNT(*) as c FROM documents").fetchone()["c"]
    done = db.execute("SELECT COUNT(*) as c FROM parse_history WHERE status='done'").fetchone()["c"]
    logger.info(f"最终状态: 文档={docs} 已解析={done}")
    db.close()

if __name__ == "__main__":
    main()
