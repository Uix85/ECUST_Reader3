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
    _ensure_columns(db, "concept_layer", {"source_text": "TEXT", "anchor_text": "TEXT"})
    if term:
        row = db.execute("SELECT term, content, source_text, anchor_text FROM concept_layer WHERE term = ? LIMIT 1", (term,)).fetchone()
        if row:
            return {"term": row["term"], "content": row["content"], "matched": True,
                    "source_text": row["source_text"] or "", "anchor_text": row["anchor_text"] or ""}
    row = _first_row(db, "concept_layer", "term, content")
    if not row:
        return {"term": "", "content": "", "matched": False}
    return {"term": row["term"], "content": row["content"], "matched": False}


@router.get("/semantic/{book_id}")
async def get_semantic(book_id: str, text: str = ""):
    """【语义层API】按选中文本 MD5 查询语义层内容；未匹配则返回该书第一条作为填充物"""
    db = _book_db(book_id)
    _ensure_columns(db, "semantic_layer", {"source_text": "TEXT", "anchor_text": "TEXT"})
    if text:
        h = _text_hash(text)
        row = db.execute("SELECT content, source_text, anchor_text FROM semantic_layer WHERE text_hash = ? LIMIT 1", (h,)).fetchone()
        if row:
            return {"text_hash": h, "content": row["content"], "matched": True,
                    "source_text": row["source_text"] or "", "anchor_text": row["anchor_text"] or ""}
    row = _first_row(db, "semantic_layer", "content")
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


def _first_row(db, table, cols):
    """返回层表第一条（未匹配查询时的填充物）"""
    return db.execute(f"SELECT {cols} FROM {table} LIMIT 1").fetchone()


@router.post("/semantic/{book_id}")
async def save_semantic(book_id: str, text: str = Body(...), content: str = Body(""),
                        source_text: str = Body(""), anchor_text: str = Body("")):
    """【语义层写入】按 MD5(规范化文本) upsert 记忆；旧库缺列自动补齐。
    source_text=选中原文（恢复高亮用），anchor_text=所在段落前缀（精确定位用）。"""
    db = _book_db(book_id)
    _ensure_columns(db, "semantic_layer", {
        "text_hash": "TEXT", "model_version": "TEXT", "updated_at": "TEXT",
        "source_text": "TEXT", "anchor_text": "TEXT",
    })
    bid = _book_int_id(db)
    # 记忆功能：content 缺省时统一填充全书层文本（占位，后续 AI 生成替换）
    if not content:
        _brow = db.execute("SELECT content FROM book_layer WHERE book_id = ?", (bid,)).fetchone()
        content = (_brow["content"] if _brow else None) or ""
    h = _text_hash(text)
    src = source_text or text
    anc = anchor_text or ""
    row = db.execute("SELECT id FROM semantic_layer WHERE text_hash = ?", (h,)).fetchone()
    if row:
        db.execute("UPDATE semantic_layer SET content=?, model_version=?, updated_at=?, source_text=?, anchor_text=? WHERE id=?",
                   (content, "manual-v1", _now(), src, anc, row["id"]))
    else:
        db.execute("INSERT INTO semantic_layer (book_id, text_hash, content, model_version, updated_at, source_text, anchor_text) VALUES (?,?,?,?,?,?,?)",
                   (bid, h, content, "manual-v1", _now(), src, anc))
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
async def save_concept(book_id: str, term: str = Body(...), content: str = Body(""),
                      source_text: str = Body(""), anchor_text: str = Body("")):
    """【概念层写入】按词条名 upsert 记忆（键与 get_concept 查询一致，保证命中）；旧库缺列自动补齐。
    source_text=词条原文，anchor_text=所在段落前缀（恢复高亮用）。"""
    db = _book_db(book_id)
    _ensure_columns(db, "concept_layer", {
        "term": "TEXT", "model_version": "TEXT", "updated_at": "TEXT",
        "source_text": "TEXT", "anchor_text": "TEXT",
    })
    bid = _book_int_id(db)
    # 记忆功能：content 缺省时统一填充全书层文本（占位，后续 AI 生成替换）
    if not content:
        _brow = db.execute("SELECT content FROM book_layer WHERE book_id = ?", (bid,)).fetchone()
        content = (_brow["content"] if _brow else None) or ""
    t = (term or "").strip()
    src = source_text or t
    anc = anchor_text or ""
    row = db.execute("SELECT id FROM concept_layer WHERE term = ?", (t,)).fetchone()
    if row:
        db.execute("UPDATE concept_layer SET content=?, model_version=?, updated_at=?, source_text=?, anchor_text=? WHERE id=?",
                   (content, "manual-v1", _now(), src, anc, row["id"]))
    else:
        db.execute("INSERT INTO concept_layer (book_id, term, content, model_version, updated_at, source_text, anchor_text) VALUES (?,?,?,?,?,?,?)",
                   (bid, t, content, "manual-v1", _now(), src, anc))
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


# ═══════════════════════════════════════════════════════
# 全书层 / 章节层 写入（笔记界面保存用）
# 与读取接口同键（book_id / spine_order），保证命中；接口签名兼容后续 AI 生成
# （AI 生成只需替换调用方，把 content 换成模型输出即可，路由不变）。
# ═══════════════════════════════════════════════════════

@router.post("/book/{book_id}")
async def save_book_layer(book_id: str, content: str = Body(default="", embed=True)):
    """【全书层写入】upsert book_layer（L1，键=book_id）"""
    db = _book_db(book_id)
    bid = _book_int_id(db)
    now = _now()
    row = db.execute("SELECT id FROM book_layer WHERE book_id = ?", (bid,)).fetchone()
    if row:
        db.execute("UPDATE book_layer SET content=?, model_version=?, updated_at=? WHERE id=?",
                   (content, "manual-v1", now, row["id"]))
    else:
        db.execute("INSERT INTO book_layer (book_id, content, model_version, updated_at) VALUES (?,?,?,?)",
                   (bid, content, "manual-v1", now))
    db.commit()
    return {"ok": True, "updated_at": now}


@router.post("/chapter/{book_id}/{chapter_idx}")
async def save_chapter_layer(book_id: str, chapter_idx: int, content: str = Body(default="", embed=True)):
    """【章节层写入】upsert chapter_layer（L2，chapter_idx=spine_order，键=chapter_id）"""
    db = _book_db(book_id)
    bid = _book_int_id(db)
    if not bid:
        raise HTTPException(status_code=404, detail="Book not found")
    ch = db.execute(
        "SELECT id FROM chapters WHERE book_id = ? AND spine_order = ?",
        (bid, chapter_idx),
    ).fetchone()
    if not ch:
        raise HTTPException(status_code=404, detail="Chapter not found")
    now = _now()
    row = db.execute("SELECT id FROM chapter_layer WHERE chapter_id = ?", (ch["id"],)).fetchone()
    if row:
        db.execute("UPDATE chapter_layer SET content=?, model_version=?, updated_at=? WHERE id=?",
                   (content, "manual-v1", now, row["id"]))
    else:
        db.execute("INSERT INTO chapter_layer (chapter_id, book_id, content, model_version, updated_at) VALUES (?,?,?,?,?)",
                   (ch["id"], bid, content, "manual-v1", now))
    db.commit()
    return {"ok": True, "chapter_idx": chapter_idx, "updated_at": now}


# ═══════════════════════════════════════════════════════
# 语义层 / 概念层 列表（笔记界面 L3/L4 展示用）
# 阅读页仍用单条查询（semantic/{id}?text= / concept/{id}?term=）
# ═══════════════════════════════════════════════════════

@router.get("/semantic_list/{book_id}")
async def list_semantic(book_id: str):
    """【语义层列表】返回该书全部语义层条目（笔记界面 L3 展示 / 阅读页恢复高亮）"""
    db = _book_db(book_id)
    _ensure_columns(db, "semantic_layer", {"source_text": "TEXT", "anchor_text": "TEXT"})
    rows = db.execute(
        "SELECT text_hash, content, source_text, anchor_text FROM semantic_layer ORDER BY id"
    ).fetchall()
    return {"items": [
        {"text_hash": r["text_hash"], "content": r["content"] or "",
         "source_text": r["source_text"] or "", "anchor_text": r["anchor_text"] or ""}
        for r in rows
    ]}


@router.get("/concept_list/{book_id}")
async def list_concept(book_id: str):
    """【概念层列表】返回该书全部概念层条目（笔记界面 L4 展示 / 阅读页恢复高亮）"""
    db = _book_db(book_id)
    _ensure_columns(db, "concept_layer", {"source_text": "TEXT", "anchor_text": "TEXT"})
    rows = db.execute(
        "SELECT term, content, source_text, anchor_text FROM concept_layer ORDER BY id"
    ).fetchall()
    return {"items": [
        {"term": r["term"], "content": r["content"] or "",
         "source_text": r["source_text"] or "", "anchor_text": r["anchor_text"] or ""}
        for r in rows
    ]}
