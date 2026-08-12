"""
辅助阅读（auxiliary_reading）—— 四层级 AI 辅助功能专用模块。

独立于基础阅读器（book_service.py）与路由层（server.py），
承载概念层/语义层/全书层/章节层等"项目专用功能"的读取与后续生成逻辑。
目前：L1 全书 / L2 章节 / L3 语义 / L4 概念 读取。
"""

import os
import re
import hashlib
import unicodedata
from datetime import datetime

from fastapi import APIRouter, Body, HTTPException

from schema import get_db
from book_service import BOOKS_DIR


router = APIRouter(prefix="/api/layer", tags=["layer"])


def _normalize_text(text: str) -> str:
    """【文本规范化】NFKC 统一全半角 + 去全部空白 + 小写（用于 L3 语义层键）"""
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text)).lower()


def _text_hash(text: str) -> str:
    """【文本哈希】L3 语义层键 = MD5(规范化文本)"""
    return hashlib.md5(_normalize_text(text).encode('utf-8')).hexdigest()


def _book_db(book_id: str):
    db_path = os.path.join(BOOKS_DIR, book_id, "book.db")
    if not os.path.exists(db_path):
        raise HTTPException(status_code=404, detail="Book not found")
    return get_db(db_path)


@router.get("/book/{book_id}")
async def get_book_layer(book_id: str):
    """【全书层API】L1：查询 book_layer 全书层内容；无则返回空"""
    db = _book_db(book_id)
    row = db.execute(
        "SELECT content, model_version, updated_at FROM book_layer LIMIT 1"
    ).fetchone()
    if not row:
        return {"content": "", "model_version": "", "updated_at": "", "matched": False}
    return {"content": row["content"], "model_version": row["model_version"],
            "updated_at": row["updated_at"], "matched": True}


@router.get("/chapter/{book_id}/{chapter_idx}")
async def get_chapter_layer(book_id: str, chapter_idx: int):
    """【章节层API】L2：按章节索引（spine_order）查询 chapter_layer 内容；无则返回空"""
    db = _book_db(book_id)
    # 先解析书籍主键（book_id 路由参数是文件夹名，chapters.book_id 是整数外键）
    bk = db.execute("SELECT id FROM books LIMIT 1").fetchone()
    if not bk:
        raise HTTPException(status_code=404, detail="Book not found")
    row = db.execute(
        "SELECT cl.content, cl.model_version, cl.updated_at, ch.title "
        "FROM chapters ch LEFT JOIN chapter_layer cl ON cl.chapter_id = ch.id "
        "WHERE ch.book_id = ? AND ch.spine_order = ?",
        (bk["id"], chapter_idx),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Chapter not found")
    if not row["content"]:
        return {"chapter_idx": chapter_idx, "title": row["title"], "content": "",
                "model_version": "", "updated_at": "", "matched": False}
    return {"chapter_idx": chapter_idx, "title": row["title"], "content": row["content"],
            "model_version": row["model_version"], "updated_at": row["updated_at"],
            "matched": True}


@router.get("/concept/{book_id}")
async def get_concept(book_id: str, term: str = ""):
    """【概念层API】按词条查询概念层内容；未匹配则返回该书第一条作为填充物"""
    db = _book_db(book_id)
    if term:
        row = db.execute("SELECT term, content FROM concept_layer WHERE term = ? LIMIT 1", (term,)).fetchone()
        if row:
            return {"term": row["term"], "content": row["content"], "matched": True}
    row = db.execute("SELECT term, content FROM concept_layer LIMIT 1").fetchone()
    if not row:
        return {"term": "", "content": "", "matched": False}
    return {"term": row["term"], "content": row["content"], "matched": False}


@router.get("/semantic/{book_id}")
async def get_semantic(book_id: str, text: str = ""):
    """【语义层API】按选中文本 MD5 查询语义层内容；未匹配则返回该书第一条作为填充物"""
    db = _book_db(book_id)
    if text:
        h = _text_hash(text)
        row = db.execute("SELECT content FROM semantic_layer WHERE text_hash = ? LIMIT 1", (h,)).fetchone()
        if row:
            return {"text_hash": h, "content": row["content"], "matched": True}
    row = db.execute("SELECT content FROM semantic_layer LIMIT 1").fetchone()
    if not row:
        return {"text_hash": "", "content": "", "matched": False}
    return {"text_hash": "", "content": row["content"], "matched": False}


# ═══════════════════════════════════════════════════════════
# 记忆写入 / 删除（选中即缓存 → layer 表，后续再选直接命中）
# 内容当前为固定填充物；接入 AI 后只需替换生成逻辑，接口不变。
# 旧骨架库（缺 text_hash/term 列）在写入时自动 ALTER 补齐。
# ═══════════════════════════════════════════════════════════

def _book_int_id(db):
    """books 主键（表内 book_id 是整数外键）"""
    row = db.execute("SELECT id FROM books LIMIT 1").fetchone()
    return row["id"] if row else None


def _ensure_columns(db, table: str, cols: dict):
    """层表缺目标列（旧骨架库）时 ALTER 补齐，保证可写入"""
    existing = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
    for name, ddl in cols.items():
        if name not in existing:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def _now():
    return datetime.now().isoformat(timespec="seconds")


@router.post("/semantic/{book_id}")
async def save_semantic(book_id: str, text: str = Body(...), content: str = Body("")):
    """【语义层写入】按 MD5(规范化文本) upsert 记忆；旧库缺列自动补齐"""
    db = _book_db(book_id)
    _ensure_columns(db, "semantic_layer", {
        "text_hash": "TEXT", "model_version": "TEXT", "updated_at": "TEXT",
    })
    bid = _book_int_id(db)
    h = _text_hash(text)
    row = db.execute("SELECT id FROM semantic_layer WHERE text_hash = ?", (h,)).fetchone()
    if row:
        db.execute("UPDATE semantic_layer SET content=?, model_version=?, updated_at=? WHERE id=?",
                   (content, "manual-v1", _now(), row["id"]))
    else:
        db.execute("INSERT INTO semantic_layer (book_id, text_hash, content, model_version, updated_at) VALUES (?,?,?,?,?)",
                   (bid, h, content, "manual-v1", _now()))
    db.commit()
    return {"ok": True, "text_hash": h}


@router.delete("/semantic/{book_id}")
async def delete_semantic(book_id: str, text: str = ""):
    """【语义层删除】删除指定文本的记忆（前端书签 × 号触发）"""
    db = _book_db(book_id)
    _ensure_columns(db, "semantic_layer", {"text_hash": "TEXT"})
    if text:
        h = _text_hash(text)
        db.execute("DELETE FROM semantic_layer WHERE text_hash = ?", (h,))
        db.commit()
        return {"ok": True, "deleted": True, "text_hash": h}
    return {"ok": False, "deleted": False}


@router.post("/concept/{book_id}")
async def save_concept(book_id: str, term: str = Body(...), content: str = Body("")):
    """【概念层写入】按词条名 upsert 记忆（键与 get_concept 查询一致，保证命中）；旧库缺列自动补齐"""
    db = _book_db(book_id)
    _ensure_columns(db, "concept_layer", {
        "term": "TEXT", "model_version": "TEXT", "updated_at": "TEXT",
    })
    bid = _book_int_id(db)
    t = (term or "").strip()
    row = db.execute("SELECT id FROM concept_layer WHERE term = ?", (t,)).fetchone()
    if row:
        db.execute("UPDATE concept_layer SET content=?, model_version=?, updated_at=? WHERE id=?",
                   (content, "manual-v1", _now(), row["id"]))
    else:
        db.execute("INSERT INTO concept_layer (book_id, term, content, model_version, updated_at) VALUES (?,?,?,?,?)",
                   (bid, t, content, "manual-v1", _now()))
    db.commit()
    return {"ok": True, "term": t}


@router.delete("/concept/{book_id}")
async def delete_concept(book_id: str, term: str = ""):
    """【概念层删除】删除指定词条的记忆"""
    db = _book_db(book_id)
    _ensure_columns(db, "concept_layer", {"term": "TEXT"})
    if term:
        t = (term or "").strip()
        db.execute("DELETE FROM concept_layer WHERE term = ?", (t,))
        db.commit()
        return {"ok": True, "deleted": True, "term": t}
    return {"ok": False, "deleted": False}
