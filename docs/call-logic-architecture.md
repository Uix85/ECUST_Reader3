# 四层级调用逻辑架构：存储位置与调用路径

> 项目：ECUST_Reader3
> 日期：2026-08-05
> 状态：设计定稿（不含 AI 包接入，AI 调用为唯一可插拔点）
> 前置：四层级处理形式见 `docs/four-level-data-structure.md`；交互逻辑见 `docs/interaction-design.md`

---

## 〇、结论先行

- **本设计不依赖任何 AI 包**。AI 调用在整条链路中是唯一一个待实现的函数：`ai_layer.stream_chat()`。
- 其余一切（存储、路由、模块划分、缓存、落库）现在即可定死，等 openai 包接入时**只写 `stream_chat` 一个函数**。
- 若 openai 包未接入，模块以 `AI_PROVIDER=mock` 离线模式运行（用于本地验证调用逻辑），真实模式 `AI_PROVIDER=openai` 时才需要 openai 包。

---

## 一、存储位置（数据放在哪）

全部四层数据都存放在**每本书自己的 SQLite 文件**：

```
books/{book_id}/book.db
├── books / chapters / paragraphs   ← 既有基础表（不动）
├── book_layer                      ← L1 全书层
├── chapter_layer                   ← L2 章节层
├── semantic_layer                  ← L3 语义层
├── concept_layer                   ← L4 概念层
└── concept_occurrences             ← 概念→段落关联
```

> 与书籍正文同一文件：外键完整、备份方便。连接统一走 `schema.get_db(db_path)`（thread-local 连接池，WAL 模式）。

### 层表目标结构（schema.py 后期据此更新）

```sql
-- L1 全书层：键=book_id（books 表主键）
CREATE TABLE book_layer (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id       INTEGER NOT NULL UNIQUE REFERENCES books(id),
    content       TEXT,             -- 分析结果（Markdown）
    model_version TEXT,             -- 生成所用模型版本
    updated_at    TEXT
);

-- L2 章节层：键=chapter_id（chapters 表主键）
CREATE TABLE chapter_layer (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_id    INTEGER NOT NULL UNIQUE REFERENCES chapters(id),
    book_id       INTEGER NOT NULL REFERENCES books(id),
    content       TEXT,
    model_version TEXT,
    updated_at    TEXT
);

-- L3 语义层：键=MD5(规范化选中文本)（任意选区可用）
CREATE TABLE semantic_layer (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id       INTEGER NOT NULL REFERENCES books(id),
    text_hash     TEXT    NOT NULL,
    content       TEXT,
    model_version TEXT,
    updated_at    TEXT,
    UNIQUE(book_id, text_hash)
);

-- L4 概念层：键=规范化词条名
CREATE TABLE concept_layer (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id       INTEGER NOT NULL REFERENCES books(id),
    term          TEXT    NOT NULL,
    content       TEXT,
    model_version TEXT,
    updated_at    TEXT,
    UNIQUE(book_id, term)
);

-- 概念→出现段落（回跳定位）
CREATE TABLE concept_occurrences (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_id   INTEGER NOT NULL REFERENCES concept_layer(id),
    paragraph_id INTEGER NOT NULL REFERENCES paragraphs(id)
);
```

> 旧骨架（`semantic_layer` 用 `paragraph_id`、`concept_layer.name`）为预留空表，实施时迁移：检测缺 `text_hash` 列 → 删空表重建即可，无数据损失。

---

## 二、调用路径（可调用文件位置）

### 模块划分

| 文件 | 职责 | 是否依赖 AI 包 |
|---|---|---|
| `schema.py` | DDL（含层表）+ 连接池 | 否 |
| `ai_layer.py` **（新建，预留）** | 四层调用逻辑 + `/api/layer/*` 路由 | **仅 `stream_chat` 一个函数** |
| `server.py` | 挂载路由：`app.include_router(ai_layer.router)` | 否 |
| `.env`（后期） | AI 配置（PROVIDER/BASE_URL/KEY/MODEL/VERSION） | — |

### 调用链（前端 → 路由 → 函数 → 表）

```
前端请求
  → GET/POST /api/layer/...        （ai_layer.py 内 APIRouter）
  → ai_layer 层函数                 （读/生成/缓存判断）
  → schema.get_db("books/{book_id}/book.db")
  → 对应层表
```

### 每层的"可调用位置"映射表（核心）

| 层 | 路由 | ai_layer 函数（入口） | 读表 | 写入表 | 键 |
|---|---|---|---|---|---|
| L1 全书 | `GET /api/layer/book/{book_id}`<br>`POST /api/layer/book/{book_id}/generate` | `get_book(db, book_pk)`<br>`generate_book(...)` | `book_layer` | `book_layer` | `book_id` |
| L2 章节 | `GET /api/layer/chapter/{book_id}/{chapter_idx}`<br>`POST /api/layer/chapter/{book_id}/{chapter_idx}/generate` | `get_chapter(...)`<br>`generate_chapter(...)` | `chapter_layer` | `chapter_layer` | `chapter_id`（由 spine_order 查出） |
| L3 语义 | `POST /api/layer/semantic` | `get_semantic(db, book_pk, text)` | `semantic_layer` | `semantic_layer` | `MD5(规范化text)` |
| L4 概念 | `POST /api/layer/concept`<br>`GET /api/layer/concepts/{book_id}` | `get_concept(db, book_pk, term)`<br>`list_concepts(db, book_pk)` | `concept_layer` | `concept_layer` + `concept_occurrences` | 规范化词条名 |
| 状态 | `GET /api/layer/stats/{book_id}` | `layer_stats(db, book_pk)` | 四表 | — | — |
| 清缓存 | `DELETE /api/layer/cache/{book_id}?model=...` | `clear_cache(db, book_pk, model)` | — | 四表（按 model_version） | — |

> 生成类接口一律 **SSE 流式**：`data: {"delta": "..."}` / `data: {"done": true}` / `data: {"error": "..."}`；`finally` 中把已生成内容落库。

---

## 三、AI 包接入点（唯一依赖处）

```python
# ai_layer.py 内 —— 全模块唯一需要 AI 包的地方
# openai 包接入时只实现这个函数，其余全部不动
async def stream_chat(messages) -> AsyncIterator[str]:
    """返回文本增量（逐块 yield）。"""
    ...
```

- **真实模式**（`AI_PROVIDER=openai`）：用 `openai.AsyncOpenAI(base_url=..., api_key=...)` 的 `chat.completions.create(stream=True)`，yield `delta.content`。
- **离线模式**（`AI_PROVIDER=mock`，默认）：本地模板分块流出，用于无 key 验证调用逻辑全链路。

`ai_layer.py` 内部结构（函数名即"可调用位置"，实施时按此落位）：

```
ai_layer.py
├── _load_dotenv() / 配置读取
├── get_provider()                    # 按 AI_PROVIDER 选 mock / openai
├── stream_chat()                     # ⭐ 唯一 AI 包接入点
├── _normalize_text() / _text_hash()  # L3 键：规范化+MD5
├── 层函数：get_*/generate_*          # 读/生成/落库（每层一套）
├── _sse(gen)                         # 包成 SSE 事件
└── router = APIRouter(prefix="/api/layer")
```

---

## 四、配置（后期 .env）

```
AI_PROVIDER=mock|openai      # 默认 mock（离线验证）
AI_BASE_URL=...              # openai 兼容接口地址（DeepSeek 等）
AI_API_KEY=...
AI_MODEL=deepseek-chat
AI_MODEL_VERSION=deepseek-chat   # 缓存版本标记，升级模型后可一键清缓存
AI_MAX_CONTEXT_CHARS=20000
```

---

## 五、实施顺序（全部无需 AI 包，除第 4 步）

1. `schema.py` 更新层表结构 + 旧骨架迁移
2. 新建 `ai_layer.py`：配置、mock provider、层函数、路由、SSE（真实 `stream_chat` 先留占位）
3. `server.py` 挂载路由，`/api/layer/*` 全部可用（mock 模式全链路验证）
4. **接入 openai 包**：实现 `stream_chat` 一个函数 → 设 `AI_PROVIDER=openai` + `.env` → 完成
