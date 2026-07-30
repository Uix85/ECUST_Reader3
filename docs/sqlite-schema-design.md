# 四层认知辅助阅读 — 数据存储结构设计

## 设计原则

1. **每层数据通过外键锚定到文本的精确位置**（书→章→段→字符偏移）
2. **各层独立存储**，可增量生成，互不阻塞
3. **段落是物理锚定最小单位**，语义层和概念层都挂在段落上
4. **Agent 输出字段预定义**，后续填写即可，不频繁改 Schema

---

## 总览

```
books ──→ chapters ──→ paragraphs ──→ semantic_annotations
  │            │                           │
  │            │                           │
  │            └──→ chapter_analyses       │
  │                                        │
  ├──→ book_overviews                      │
  │                                        │
  └──→ concepts ──→ concept_occurrences ──→ paragraphs
```

---

## 建表 SQL

### 1. books — 书

```sql
CREATE TABLE books (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT    NOT NULL,
    language      TEXT    DEFAULT 'zh',
    authors       TEXT,              -- JSON array: ["费孝通"]
    source_file   TEXT,              -- 原始 EPUB 文件名
    processed_at  TEXT    NOT NULL,  -- ISO timestamp
    total_chaps   INTEGER NOT NULL,
    total_paras   INTEGER DEFAULT 0
);
```

### 2. chapters — 章（对应原 spine）

```sql
CREATE TABLE chapters (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id       INTEGER NOT NULL REFERENCES books(id),
    spine_order   INTEGER NOT NULL,  -- 阅读顺序 0..N
    href          TEXT    NOT NULL,  -- 文件名 chunk_2.html
    title         TEXT    NOT NULL,  -- 章节标题（来自 TOC）
    content_html  TEXT    NOT NULL,  -- 完整 HTML（清洗后，图片路径已重写）
    content_text  TEXT    NOT NULL,  -- 纯文本（搜索/Agent 分析用）
    heading_json  TEXT,              -- 本章的子标题树 JSON（来自 heading_toc）
    para_count    INTEGER DEFAULT 0,

    UNIQUE(book_id, spine_order)
);
```

### 3. paragraphs — 段（物理锚定最小单位）

```sql
CREATE TABLE paragraphs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_id    INTEGER NOT NULL REFERENCES chapters(id),
    book_id       INTEGER NOT NULL REFERENCES books(id),  -- 冗余加速查询
    seq           INTEGER NOT NULL,  -- 段序号（0 开始）
    text          TEXT    NOT NULL,  -- 纯文本（对应用户视口内容）
    html          TEXT    NOT NULL,  -- HTML 片段（前端直接渲染）
    offset_start  INTEGER NOT NULL,  -- 在 chapter.content_html 中的起始字符位置
    offset_end    INTEGER NOT NULL,  -- 结束字符位置
    char_count    INTEGER NOT NULL,  -- text 的字符数

    UNIQUE(chapter_id, seq)
);
CREATE INDEX idx_paragraphs_chapter ON paragraphs(chapter_id, seq);
CREATE INDEX idx_paragraphs_book    ON paragraphs(book_id);
```

**段落拆分策略**：优先 `<p>` → 回退 `<br>` → 回退 `\u3000\u3000`。
BeautifulSoup 遍历 HTML，每个叶子块或分隔符断点生成一行。

---

## 四层辅助信息表

### 4. book_overviews — 全书层（1书→1条）

> 对应：全书概览Agent。思想地图，宏观框架。

```sql
CREATE TABLE book_overviews (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id        INTEGER NOT NULL UNIQUE REFERENCES books(id),
    core_question  TEXT,        -- 全书核心问题
    theme_framework TEXT,       -- 主题脉络（JSON 树）
    argument_logic TEXT,        -- 整体论证逻辑
    generated_at   TEXT,        -- Agent 生成时间
    model_version  TEXT,        -- 使用的模型标识
    is_verified    INTEGER DEFAULT 0  -- 0=未校验 1=人工已核
);
```

### 5. chapter_analyses — 章节层（1章→1条）

> 对应：篇章论证Agent。论证脚手架。

```sql
CREATE TABLE chapter_analyses (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_id       INTEGER NOT NULL UNIQUE REFERENCES chapters(id),
    book_id          INTEGER NOT NULL REFERENCES books(id),
    position_in_book TEXT,      -- 在全书中承上启下的位置
    argument_steps   TEXT,      -- 论证步骤（JSON数组，每步含标题+说明）
    key_turnings     TEXT,      -- 关键论证转折点（JSON数组）
    generated_at     TEXT,
    model_version    TEXT,
    is_verified      INTEGER DEFAULT 0
);
CREATE INDEX idx_chapter_analyses_book ON chapter_analyses(book_id);
```

### 6. semantic_annotations — 语义层（1段→1条）

> 对应：语义解析Agent。要点+释义+关系三要素。

```sql
CREATE TABLE semantic_annotations (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    paragraph_id       INTEGER NOT NULL UNIQUE REFERENCES paragraphs(id),
    chapter_id         INTEGER NOT NULL REFERENCES chapters(id),   -- 冗余加速
    book_id            INTEGER NOT NULL REFERENCES books(id),      -- 冗余加速
    key_points         TEXT,     -- 要点提炼
    paraphrase         TEXT,     -- 通俗释义
    sentence_relations TEXT,     -- 句段关系标注（JSON: [{"type":"转折","from":"...","to":"..."}]）
    generated_at       TEXT,
    model_version      TEXT,
    is_verified        INTEGER DEFAULT 0
);
CREATE INDEX idx_semantic_chapter ON semantic_annotations(chapter_id);
CREATE INDEX idx_semantic_book    ON semantic_annotations(book_id);
```

### 7. concepts — 概念层（跨段/跨章，全书共享）

> 对应：概念辨析Agent。定义+辨析+网络三维结构。

```sql
CREATE TABLE concepts (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id              INTEGER NOT NULL REFERENCES books(id),
    name                 TEXT    NOT NULL,  -- 概念名（如"模范与系列"）
    academic_definition  TEXT,              -- 学术定义
    common_vs_academic   TEXT,              -- 日常理解 vs 学术概念辨析
    relations_json       TEXT,              -- 概念关系网络（JSON: [{"target":"系列","rel":"对立依存"},...]）
    generated_at         TEXT,
    model_version        TEXT,
    is_verified          INTEGER DEFAULT 0,

    UNIQUE(book_id, name)
);
CREATE INDEX idx_concepts_book ON concepts(book_id);
```

### 8. concept_occurrences — 概念→段落出现位置（反向索引）

> 将概念与原文位置绑定，支持"这个概念在哪些段出现过"的查询。

```sql
CREATE TABLE concept_occurrences (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_id    INTEGER NOT NULL REFERENCES concepts(id),
    paragraph_id  INTEGER NOT NULL REFERENCES paragraphs(id),
    span_text     TEXT,       -- 原文中的出现文本片段
    span_start    INTEGER,    -- 在 paragraph.text 中的起始字符位置
    span_end      INTEGER     -- 结束位置

    -- 不设 UNIQUE，同一概念可在同一段出现多次
);
CREATE INDEX idx_concept_occurrences_concept   ON concept_occurrences(concept_id);
CREATE INDEX idx_concept_occurrences_paragraph ON concept_occurrences(paragraph_id);
```

---

## 查询示例（验证设计）

### Q1: 用户滚动到第 3 章第 5 段 → 取对应辅助信息

```sql
-- 语义层
SELECT * FROM semantic_annotations sa
JOIN paragraphs p ON sa.paragraph_id = p.id
JOIN chapters c ON p.chapter_id = c.id
WHERE c.book_id = 1 AND c.spine_order = 3 AND p.seq = 5;

-- 该段涉及的概念
SELECT co.span_text, c.name, c.academic_definition
FROM concept_occurrences co
JOIN concepts c ON co.concept_id = c.id
JOIN paragraphs p ON co.paragraph_id = p.id
JOIN chapters ch ON p.chapter_id = ch.id
WHERE ch.book_id = 1 AND ch.spine_order = 3 AND p.seq = 5;
```

### Q2: 查"模范与系列"这个概念在全书哪些段出现

```sql
SELECT ch.title, ch.spine_order, p.seq, co.span_text
FROM concept_occurrences co
JOIN concepts c  ON co.concept_id = c.id
JOIN paragraphs p ON co.paragraph_id = p.id
JOIN chapters ch  ON p.chapter_id = ch.id
WHERE c.book_id = 1 AND c.name = '模范与系列'
ORDER BY ch.spine_order, p.seq;
```

### Q3: 取全书层概览

```sql
SELECT * FROM book_overviews WHERE book_id = 1;
```

### Q4: 取某章论证分析 + 该章所有段语义标注

```sql
-- 章节层
SELECT * FROM chapter_analyses WHERE chapter_id = 3;

-- 该章所有段的语义层
SELECT p.seq, p.text, sa.key_points, sa.paraphrase, sa.sentence_relations
FROM paragraphs p
LEFT JOIN semantic_annotations sa ON sa.paragraph_id = p.id
WHERE p.chapter_id = 3
ORDER BY p.seq;
```

---

## 四层 → 文本的锚定关系

```
Level 1  全书层              book_overviews.book_id → books.id
                             1 本书 → 1 条记录

Level 2  章节层              chapter_analyses.chapter_id → chapters.id
                             1 章 → 1 条记录

Level 3  语义层              semantic_annotations.paragraph_id → paragraphs.id
                             1 段 → 1 条记录

Level 4  概念层              concepts.book_id → books.id（概念定义属于全书）
                             concept_occurrences.paragraph_id → paragraphs.id（出现位置属于段落）
                             1 概念 → N 个出现位置（跨段/跨章）
```

### 前端定位链路

```
用户视口可见区域内 → 找到 data-para-seq 标记
  → GET /api/annotations/{book_id}/{ch_order}/{para_seq}
  → server 查 paragraphs WHERE book_id=? AND spine_order=? AND seq=?
  → JOIN 到 semantic_annotations + concept_occurrences
  → 返回该段的语义层 + 涉及的概念
  → 前端右侧面板刷新
```
