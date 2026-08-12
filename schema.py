"""
SQLite schema and connection management for the reader.

Database file: books/{book_folder}/book.db
基础数据表：books / chapters / paragraphs（正文 + 段落）
预留层级表：book_layer / chapter_layer / semantic_layer / concept_layer（仅骨架，字段待定）
"""

import sqlite3
import os
import threading

# ── DDL ──────────────────────────────────────────────

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- 1. books
CREATE TABLE IF NOT EXISTS books (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT    NOT NULL,
    language      TEXT    DEFAULT 'zh',
    authors       TEXT,              -- JSON array
    source_file   TEXT,
    processed_at  TEXT    NOT NULL,
    total_chaps   INTEGER NOT NULL,
    total_paras   INTEGER DEFAULT 0,
    toc_json      TEXT               -- 原始 TOC 结构 JSON
);

-- 2. chapters
CREATE TABLE IF NOT EXISTS chapters (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id       INTEGER NOT NULL REFERENCES books(id),
    spine_order   INTEGER NOT NULL,
    href          TEXT    NOT NULL,
    title         TEXT    NOT NULL,
    content_html  TEXT    NOT NULL,
    content_text  TEXT    NOT NULL,
    heading_json  TEXT,              -- 子标题树 JSON
    para_count    INTEGER DEFAULT 0,
    UNIQUE(book_id, spine_order)
);
CREATE INDEX IF NOT EXISTS idx_chapters_book ON chapters(book_id, spine_order);

-- 3. paragraphs
CREATE TABLE IF NOT EXISTS paragraphs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_id    INTEGER NOT NULL REFERENCES chapters(id),
    book_id       INTEGER NOT NULL REFERENCES books(id),
    seq           INTEGER NOT NULL,
    text          TEXT    NOT NULL,
    html          TEXT    NOT NULL,
    offset_start  INTEGER NOT NULL,
    offset_end    INTEGER NOT NULL,
    char_count    INTEGER NOT NULL,
    UNIQUE(chapter_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_paras_chapter ON paragraphs(chapter_id, seq);
CREATE INDEX IF NOT EXISTS idx_paras_book    ON paragraphs(book_id);

-- 4. book_layer (L1 全书层·键=book_id)
CREATE TABLE IF NOT EXISTS book_layer (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id       INTEGER NOT NULL UNIQUE REFERENCES books(id),
    content       TEXT,             -- 分析结果（Markdown）
    model_version TEXT,             -- 生成所用模型版本
    updated_at    TEXT
);

-- 5. chapter_layer (L2 章节层·键=chapter_id)
CREATE TABLE IF NOT EXISTS chapter_layer (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_id    INTEGER NOT NULL UNIQUE REFERENCES chapters(id),
    book_id       INTEGER NOT NULL REFERENCES books(id),
    content       TEXT,
    model_version TEXT,
    updated_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_ch_layer_book ON chapter_layer(book_id);

-- 6. semantic_layer (L3 语义层·键=MD5(规范化选中文本))
CREATE TABLE IF NOT EXISTS semantic_layer (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id       INTEGER NOT NULL REFERENCES books(id),
    text_hash     TEXT    NOT NULL,
    content       TEXT,
    model_version TEXT,
    updated_at    TEXT,
    UNIQUE(book_id, text_hash)
);
CREATE INDEX IF NOT EXISTS idx_semantic_layer_book ON semantic_layer(book_id);

-- 7. concept_layer (L4 概念层·键=规范化词条名)
CREATE TABLE IF NOT EXISTS concept_layer (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id       INTEGER NOT NULL REFERENCES books(id),
    term          TEXT    NOT NULL,
    content       TEXT,
    model_version TEXT,
    updated_at    TEXT,
    UNIQUE(book_id, term)
);
CREATE INDEX IF NOT EXISTS idx_concept_layer_book ON concept_layer(book_id);

-- 8. concept_occurrences (概念→段落·预留)
CREATE TABLE IF NOT EXISTS concept_occurrences (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_id   INTEGER NOT NULL REFERENCES concept_layer(id),
    paragraph_id INTEGER NOT NULL REFERENCES paragraphs(id)
);
CREATE INDEX IF NOT EXISTS idx_co_concept   ON concept_occurrences(concept_id);
CREATE INDEX IF NOT EXISTS idx_co_paragraph ON concept_occurrences(paragraph_id);
"""

# ── Connection pool (thread-local) ───────────────────

_connections: dict = {}
_lock = threading.Lock()

def get_db(db_path: str) -> sqlite3.Connection:
    """Get or create a thread-local connection to a book database."""
    key = os.path.abspath(db_path)
    with _lock:
        if key not in _connections:
            os.makedirs(os.path.dirname(key), exist_ok=True)
            conn = sqlite3.connect(key, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.executescript(SCHEMA_SQL)
            conn.commit()
            _connections[key] = conn
        return _connections[key]

def close_db(db_path: str):
    """Close and remove a connection from the pool."""
    key = os.path.abspath(db_path)
    with _lock:
        conn = _connections.pop(key, None)
        if conn:
            conn.close()

def close_all():
    """Close all connections in the pool."""
    with _lock:
        for conn in _connections.values():
            conn.close()
        _connections.clear()
