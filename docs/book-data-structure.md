# Book 数据结构文档

## 数据存储

处理后的书目数据保存在 `{书名_data}/book.pkl`，使用 `pickle.dump()` 序列化。

**写**：`reader3.py:952` — `save_to_pickle(book, output_dir)`

```python
def save_to_pickle(book: Book, output_dir: str):
    p_path = os.path.join(output_dir, 'book.pkl')
    with open(p_path, 'wb') as f:
        pickle.dump(book, f)
```

**读**：`server.py:47` — `load_book_cached(folder_name)`

```python
@lru_cache(maxsize=10)
def load_book_cached(folder_name: str) -> Optional[Book]:
    file_path = os.path.join(BOOKS_DIR, folder_name, "book.pkl")
    ...
    with open(file_path, "rb") as f:
        book = pickle.load(f)
    return book
```

---

## 数据类定义（`reader3.py:19-87`）

### `Book` — 最外层

```
Book
├── metadata: BookMetadata    书名/作者/语言等
├── spine: List[ChapterContent]  各章节HTML内容（阅读顺序）
├── toc: List[TOCEntry]      目录树（导航用）
├── images: Dict[str,str]    图片路径映射（原路径→本地路径）
├── source_file: str         来源EPUB文件名
├── processed_at: str        处理时间戳
└── version: str             数据格式版本（默认"3.0"）
```

### `BookMetadata`

```
BookMetadata
├── title: str              书名
├── language: str           语言代码（"zh"/"en"...）
├── authors: List[str]      作者列表
├── description: str|None   描述
├── publisher: str|None     出版社
├── date: str|None          出版日期
├── identifiers: List[str]  标识符（ISBN等）
└── subjects: List[str]     主题分类
```

### `ChapterContent` — 单个章节（一个 HTML 文件）

```
ChapterContent
├── id: str         EPUB内部ID（如"item_1"）
├── href: str       文件名（如"chunk_2.html"）
├── title: str      章节标题（回退名）
├── content: str    清洗后的完整HTML（图片路径已重写）
├── text: str       纯文本版本（供搜索/LLM使用）
└── order: int      线性阅读顺序
```

### `TOCEntry` — 目录条目

```
TOCEntry
├── title: str              显示标题
├── href: str               原始链接（如"part01.html#c1"）
├── file_href: str          文件名部分（如"part01.html"）
├── anchor: str             锚点部分（如"c1"），无则为空
└── children: List[TOCEntry]  子条目（递归结构）
```

---

## 逻辑关系

```
toc（逻辑目录）                spine（实际内容）
┌─────────────────┐          ┌─────────────────┐
│ 第二章：调查区域   │          │ chunk_2.html     │
│  ├─ 1．调查区域的界定│          │   <p>...          │
│  ├─ 2．地理状况     │          │   江村经济1．...   │
│  └─ ...           │          │   ...             │
└────────┬─────────┘          └────────┬─────────┘
         │                             │
         └──────── file_href ──────────┘
                  （关联键）
```

- **`toc`**：EPUB 原始目录条目，通过 `file_href` 关联到 `spine` 中的文件
- **`spine`**：实际 HTML 内容数组，`order` 决定阅读顺序
- **process_epub() 组装**（`reader3.py:940`）：

```python
final_book = Book(
    metadata=extract_metadata_robust(book),
    spine=spine_chapters,
    toc=parse_toc_recursive(book.toc),
    images=image_map,
    source_file=os.path.basename(epub_path),
    processed_at=datetime.now().isoformat()
)
```

---

## 实例（江村经济）

```
Book
├── metadata
│   ├── title: "江村经济"
│   ├── language: "zh"
│   └── authors: ["费孝通"]
│
├── spine: [17个ChapterContent]
│   ├── [0] chunk_0.html          （封面/目录页）
│   ├── [1] chunk_1.html          （第一章：前 言）
│   ├── [2] chunk_2.html          （第二章：调查区域）
│   │   └── content: "<p>...江村经济1．调查区域的界定...</p>"
│   ├── [3] chunk_3.html          （第三章：家）
│   │   └── content: "<p>...江村经济1．家，扩大的家庭...</p>"
│   ├── [4] chunk_4.html          （第四章：财产与继承）
│   ├── [5] ... 至
│   └── [16] chunk_16.html        （第十六章：中国的土地问题）
│
├── toc: [17个TOCEntry]（平坦一级，无子项）
│   ├── 江村经济 - 开头
│   ├── 第一章：前 言
│   ├── 第二章：调查区域
│   │   ├── 1．调查区域的界定
│   │   ├── 2．地理状况
│   │   └── ... （共6子项）
│   ├── 第三章：家
│   └── ... 至 第十六章
│
├── images
│   └── "OEBPS/Images/cover.jpg" → "images/cover.jpg"
│
├── source_file: "江村经济.epub"
├── processed_at: "2026-07-26T..."
└── version: "3.0"
```
