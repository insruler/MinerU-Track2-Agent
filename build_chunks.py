#!/usr/bin/env python3
"""
重建 document_chunks 表
将 documents.content 按滑动窗口切分，写入 document_chunks
"""
import sqlite3
import re
import time

DB_PATH = "data/knowledge.db"
CHUNK_SIZE = 512       # 每块字符数
CHUNK_OVERLAP = 128    # 重叠字符数
MIN_CHUNK_LEN = 50     # 最小有效块长度

def split_chunks(text: str, doc_id: int, doc_title: str):
    """滑动窗口分块"""
    text = re.sub(r'\n{3,}', '\n\n', text.strip())
    chunks = []
    pos = 0
    chunk_idx = 0
    while pos < len(text):
        end = pos + CHUNK_SIZE
        chunk_text = text[pos:end].strip()
        if len(chunk_text) >= MIN_CHUNK_LEN:
            chunks.append({
                "doc_id": doc_id,
                "chunk_index": chunk_idx,
                "content": chunk_text,
                "char_start": pos,
                "char_end": min(end, len(text)),
            })
            chunk_idx += 1
        pos += CHUNK_SIZE - CHUNK_OVERLAP
    return chunks

def main():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 表已存在，字段为: doc_id, chunk_id, chunk_content, metadata, created_at

    # 清空旧数据
    c.execute("DELETE FROM document_chunks")
    conn.commit()
    print("已清空旧 document_chunks 数据")

    # 读取所有文档
    rows = c.execute("SELECT id, doc_id, title, content FROM documents WHERE content IS NOT NULL AND content != ''").fetchall()
    print(f"共 {len(rows)} 篇文档需要分块")

    total_chunks = 0
    batch = []
    BATCH_SIZE = 500

    for i, (db_id, doc_id, title, content) in enumerate(rows):
        chunks = split_chunks(content, doc_id or str(db_id), title or "")
        import json
        for ch in chunks:
            meta = json.dumps({"char_start": ch["char_start"], "char_end": ch["char_end"], "title": title or ""}, ensure_ascii=False)
            batch.append((
                ch["doc_id"],
                ch["chunk_index"],
                ch["content"],
                meta,
            ))
        total_chunks += len(chunks)

        if len(batch) >= BATCH_SIZE:
            c.executemany(
                "INSERT INTO document_chunks (doc_id, chunk_id, chunk_content, metadata) VALUES (?,?,?,?)",
                batch
            )
            conn.commit()
            batch = []
            print(f"  已处理 {i+1}/{len(rows)} 篇，累计 {total_chunks} 个 chunks")

    if batch:
        c.executemany(
            "INSERT INTO document_chunks (doc_id, chunk_id, chunk_content, metadata) VALUES (?,?,?,?)",
            batch
        )
        conn.commit()

    # 验证
    final_count = c.execute("SELECT COUNT(*) FROM document_chunks").fetchone()[0]
    print(f"\n✅ 分块完成！document_chunks 共 {final_count} 条")
    print(f"   平均每篇文档 {final_count/len(rows):.1f} 个 chunks")

    # 统计分布
    c.execute("SELECT MIN(LENGTH(chunk_content)), MAX(LENGTH(chunk_content)), AVG(LENGTH(chunk_content)) FROM document_chunks")
    mn, mx, avg = c.fetchone()
    print(f"   chunk 长度: min={mn} max={mx} avg={avg:.0f}")

    conn.close()

if __name__ == "__main__":
    t0 = time.time()
    main()
    print(f"耗时: {time.time()-t0:.1f}s")
