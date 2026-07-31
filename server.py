import os
import json
import shutil
import tempfile
from typing import Optional, List, Dict

from fastapi import FastAPI, Request, HTTPException, File, UploadFile
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from reader3 import (
    Book, TOCEntry, ChapterContent, BookMetadata,
    process_epub_to_sqlite,
    build_heading_based_toc, inject_heading_ids
)
from schema import get_db

app = FastAPI()
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))
templates.env.auto_reload = True  # reload templates on each request during dev

BOOKS_DIR = os.path.join(os.path.dirname(__file__), "books")
_heading_toc_cache: Dict[str, List[TOCEntry]] = {}
_book_cache: Dict[str, dict] = {}  # book_id → {Book object, db_path}
_unified_html_cache: Dict[str, str] = {}  # book_id → 拼接全书的 HTML（已注入锚点）


# ── Helpers ──

# ── 统一 HTML 构建 ──

def _get_unified_html(book: Book) -> str:
    """【统一HTML】将所有 spine 文件拼接为一个 HTML 文档并注入标题锚点。"""
    unified = ''
    for ch in book.spine:
        html_with_ids = inject_heading_ids(ch, book.metadata.title)
        unified += html_with_ids
    return unified


# ── 统一 HTML 缓存 ──

def _get_unified_html_cached(book_id: str, book: Book) -> str:
    """【统一HTML缓存】获取带缓存的统一 HTML"""
    if book_id not in _unified_html_cache:
        _unified_html_cache[book_id] = _get_unified_html(book)
    return _unified_html_cache[book_id]


# ── Spine 文件字节偏移 ──

def _get_spine_offsets(book: Book) -> List[int]:
    """【文件偏移】返回每个 spine 文件在统一 HTML 中的起始字节偏移（按 spine_order 索引）。"""
    offsets = []
    pos = 0
    for ch in book.spine:
        offsets.append(pos)
        html_with_ids = inject_heading_ids(ch, book.metadata.title)
        pos += len(html_with_ids)
    return offsets


# ── 标题目录缓存 ──

def _get_heading_toc(book_id: str, book: Book) -> List[TOCEntry]:
    """【标题目录缓存】获取带缓存的标题式目录"""
    if book_id not in _heading_toc_cache:
        _heading_toc_cache[book_id] = build_heading_based_toc(book)
    return _heading_toc_cache[book_id]


# ── 分页构建（标题树 → 页面列表）──

def _build_toc_pages(book: Book, heading_toc: List[TOCEntry]) -> List[dict]:
    """【分页构建】将标题树展平为页面列表，每标题一页。
    
    全书 spine 文件已拼接为统一 HTML，所有标题在同一文档中切片。
    depth==0 的标题标记为 _chapter_start（章边界）。
    """
    raw_pages = []

    def _flatten(entries, depth=0):
        for e in entries:
            spine_order = None
            for ch in book.spine:
                if ch.href == e.file_href:
                    spine_order = ch.order
                    break
            raw_pages.append({
                'title': e.title,
                'anchor': e.anchor,
                'spine_order': spine_order,
                'depth': depth,
                'has_children': len(e.children) > 0,
                '_chapter_start': (depth == 0),
            })
            if e.children:
                _flatten(e.children, depth + 1)

    _flatten(heading_toc)
    return raw_pages


# ── 分页缓存 ──

def _get_toc_pages(book_id: str, book: Book) -> List[dict]:
    """【分页缓存】获取带缓存的分页列表"""
    cache_key = f"{book_id}_pages"
    if not hasattr(_get_toc_pages, '_cache'):
        _get_toc_pages._cache = {}
    if cache_key not in _get_toc_pages._cache:
        heading_toc = _get_heading_toc(book_id, book)
        _get_toc_pages._cache[cache_key] = _build_toc_pages(book, heading_toc)
    return _get_toc_pages._cache[cache_key]


# ── 章构建（页面 → 章分组）──

def _build_chapters(toc_pages: List[dict]) -> List[dict]:
    """【章构建】将页面按 _chapter_start 分组为章列表。
    
    每章包含：起始页索引、标题、子节列表、有效锚点（用于切片）。
    若章标题无锚点（NCX 条目），则用章内第一个子节的锚点作为切片起点。
    """
    chapters = []
    current = None
    for pi, p in enumerate(toc_pages):
        if p.get('_chapter_start') or current is None:
            if current:
                chapters.append(current)
            current = {
                'title': p['title'],
                'start_page': pi,
                'anchor': p['anchor'],
                'sections': [],
            }
        if not p.get('_chapter_start'):
            current['sections'].append({
                'title': p['title'],
                'anchor': p['anchor'],
                'page': pi,
                'depth': p['depth'],
            })
    if current:
        chapters.append(current)
    return chapters


# ── 章切片锚点计算 ──

def _chapter_slice_anchors(chapters: List[dict], toc_pages: List[dict],
                           book: Book, chapter_idx: int):
    """返回第 idx 章的切片 (start_anchor, end_anchor)。

    优先用章标题锚点；若为空（NCX 条目），用 spine 文件边界字节偏移做精确切片。
    第 0 章始终从文档头开始。
    """
    ch = chapters[chapter_idx]
    start = '' if chapter_idx == 0 else ch.get('anchor', '')

    # 如果 start 锚点为空，用 spine 文件边界做精确切片
    if start == '' and chapter_idx > 0:
        # 找到本章第一个标题所在的 spine 文件
        start_page = toc_pages[ch['start_page']]
        spine_idx = start_page.get('spine_order', 0)
        if spine_idx is not None:
            offsets = _get_spine_offsets(book)
            if spine_idx < len(offsets):
                start = '__byte__{}'.format(offsets[spine_idx])

    # 终点：下一章锚点，或下一章文件边界
    end = None
    if chapter_idx + 1 < len(chapters):
        next_ch = chapters[chapter_idx + 1]
        end = next_ch.get('anchor', '')
        if not end:
            next_start_page = toc_pages[next_ch['start_page']]
            next_spine_idx = next_start_page.get('spine_order', 0)
            if next_spine_idx is not None:
                offsets = _get_spine_offsets(book)
                if next_spine_idx < len(offsets):
                    end = '__byte__{}'.format(offsets[next_spine_idx])

    return start, end


# ── HTML 标签起始位置查找 ──

def _find_tag_start(html: str, id_pos: int) -> int:
    """【标签定位】从 id 属性位置反查所在 HTML 标签的开头 < 位置"""
    tag_start = html.rfind('<', 0, id_pos)
    if tag_start < 0:
        return id_pos
    # Verify this '<' opens a tag whose '>' is after id_pos
    tag_end = html.find('>', tag_start)
    if tag_end < 0 or tag_end < id_pos:
        return id_pos
    return tag_start


# ── 内容切片（锚点间 HTML 片段提取）──

def _slice_content(full_html: str, anchor: str, next_anchor: Optional[str]) -> str:
    """【内容切片】从完整 HTML 中切出两个锚点之间的内容片段。
    
    anchor/next_anchor 可以是标准 HTML id，也可以是 '__byte__N' 格式的字节偏移。
    """
    # ── 处理字节偏移 ──
    if anchor and anchor.startswith('__byte__'):
        byte_pos = int(anchor[8:])
        start_tag = byte_pos
    elif not anchor:
        start_tag = 0
    else:
        start_pattern = f'id="{anchor}"'
        start_id_pos = full_html.find(start_pattern)
        if start_id_pos < 0:
            return full_html
        start_tag = _find_tag_start(full_html, start_id_pos)

    if next_anchor and next_anchor.startswith('__byte__'):
        end_tag = int(next_anchor[8:])
        return full_html[start_tag:end_tag]

    result = full_html[start_tag:]

    if next_anchor:
        end_pattern = f'id="{next_anchor}"'
        end_id_pos = full_html.find(end_pattern, start_tag + 1)
        if end_id_pos >= 0:
            end_tag = _find_tag_start(full_html, end_id_pos)
            if end_tag > start_tag:
                result = full_html[start_tag:end_tag]

    return result


# ── 从 SQLite 重建 Book 对象 ──

def _load_book_from_sqlite(folder_name: str) -> Optional[Book]:
    """【SQLite加载】从 SQLite 数据库重建 Book 对象（含缓存）"""
    # Check cache first
    if folder_name in _book_cache:
        return _book_cache[folder_name]['book']

    db_path = os.path.join(BOOKS_DIR, folder_name, "book.db")
    if not os.path.exists(db_path):
        return None

    db = get_db(db_path)
    row = db.execute("SELECT * FROM books LIMIT 1").fetchone()
    if not row:
        return None

    # Build BookMetadata
    authors = json.loads(row['authors'] or '[]')
    metadata = BookMetadata(
        title=row['title'],
        language=row['language'] or 'zh',
        authors=authors,
    )

    # Build spine (ChapterContent list)
    chapters = db.execute(
        "SELECT * FROM chapters WHERE book_id = ? ORDER BY spine_order", (row['id'],)
    ).fetchall()

    spine = []
    for ch in chapters:
        spine.append(ChapterContent(
            id=str(ch['id']),
            href=ch['href'],
            title=ch['title'],
            content=ch['content_html'],
            text=ch['content_text'],
            order=ch['spine_order'],
        ))

    # Build TOC (flat from headings cache — will be rebuilt later)
    # For now create a minimal TOC from chapters
    toc = []
    for ch in chapters:
        toc.append(TOCEntry(
            title=ch['title'],
            href=ch['href'],
            file_href=ch['href'],
            anchor="",
            children=[],
        ))

    book = Book(
        metadata=metadata,
        spine=spine,
        toc=toc,
        images={},  # Images are served directly from disk, map not needed here
        source_file=row['source_file'] or '',
        processed_at=row['processed_at'],
    )
    _book_cache[folder_name] = {'book': book, 'db_path': db_path}
    return book


# ── 书籍加载公开接口 ──

def load_book_cached(folder_name: str) -> Optional[Book]:
    """【书籍加载】从 SQLite 数据库加载一本书"""
    return _load_book_from_sqlite(folder_name)

# ═══════════════════════════════════════════
# HTTP 路由
# ═══════════════════════════════════════════

# ── 书库首页 GET / ──
@app.get("/", response_class=HTMLResponse)
async def library_view(request: Request):
    """【书库页面】列出所有已处理书籍的首页"""
    books = []

    if os.path.exists(BOOKS_DIR):
        for item in os.listdir(BOOKS_DIR):
            if item.endswith("_data") and os.path.isdir(os.path.join(BOOKS_DIR, item)):
                book = load_book_cached(item)
                if book:
                    # 从 SQLite 读取更丰富的统计信息
                    db_path = os.path.join(BOOKS_DIR, item, "book.db")
                    total_paras = 0
                    total_chaps = len(book.spine)
                    if os.path.exists(db_path):
                        try:
                            from schema import get_db
                            db = get_db(db_path)
                            row = db.execute("SELECT total_chaps, total_paras FROM books LIMIT 1").fetchone()
                            if row:
                                total_chaps = row['total_chaps'] or total_chaps
                                total_paras = row['total_paras'] or 0
                        except Exception:
                            pass

                    # 计算 TOC 页数（标题目录中的条目数）
                    try:
                        heading_toc = _get_heading_toc(item, book)
                        toc_pages = _get_toc_pages(item, book)
                        page_count = len(toc_pages)
                    except Exception:
                        page_count = total_chaps

                    books.append({
                        "id": item,
                        "title": book.metadata.title,
                        "author": ", ".join(book.metadata.authors),
                        "chapters": total_chaps,
                        "paras": total_paras,
                        "pages": page_count,
                    })

    return templates.TemplateResponse(request, "library.html", {"books": books})

# ── 上传处理 POST /upload ──
@app.post("/upload")
async def upload_epub(file: UploadFile = File(...)):
    """【上传处理】接收 EPUB/TXT 文件，处理后加入书库"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="未指定文件名")

    ext = os.path.splitext(file.filename)[1].lower()

    if ext == '.epub':
        suffix = '.epub'
        file_type = "EPUB"
    elif ext == '.txt':
        suffix = '.txt'
        file_type = "TXT"
    else:
        raise HTTPException(status_code=400, detail="只支持 EPUB 和 TXT 格式的文件")

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        if ext == '.epub':
            out_dir = process_epub_to_sqlite(tmp_path, BOOKS_DIR)
        elif ext == '.txt':
            raise HTTPException(status_code=400, detail="TXT 支持尚未迁移到 SQLite")

        # Get book info from the new DB
        folder = os.path.basename(out_dir)
        book = load_book_cached(folder)
        _heading_toc_cache.pop(folder, None)  # clear stale TOC
        _heading_toc_cache.clear()
        _unified_html_cache.pop(folder, None)
        _unified_html_cache.clear()
        if hasattr(_get_toc_pages, '_cache'):
            _get_toc_pages._cache.clear()

        return JSONResponse({
            "success": True,
            "title": book.metadata.title if book else folder,
            "author": ", ".join(book.metadata.authors) if book else "",
            "folder": folder,
            "chapters": len(book.spine) if book else 0,
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"处理 {file_type} 失败: {str(e)}")
    finally:
        os.unlink(tmp_path)

# ── 首页跳转 GET /read/{book_id} → 第 0 章 ──
@app.get("/read/{book_id}", response_class=HTMLResponse)
async def redirect_to_first_chapter(request: Request, book_id: str):
    """【首页跳转】重定向到书籍第 0 章"""
    return await read_chapter(request=request, book_id=book_id, chapter_idx=0)

# ── 阅读页面 GET /read/{book_id}/{chapter_idx} ──
@app.get("/read/{book_id}/{chapter_idx}", response_class=HTMLResponse)
async def read_chapter(request: Request, book_id: str, chapter_idx: int):
    """【阅读页面】chapter_idx = 章索引（0-based），每章为连续滚动页"""
    book = load_book_cached(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    heading_toc = _get_heading_toc(book_id, book)
    toc_pages = _get_toc_pages(book_id, book)
    chapters = _build_chapters(toc_pages)

    if chapter_idx < 0 or chapter_idx >= len(chapters):
        raise HTTPException(status_code=404, detail="Chapter not found")

    ch = chapters[chapter_idx]

    # 使用有效锚点切片（处理 NCX 空锚点章标题）
    unified = _get_unified_html_cached(book_id, book)
    start_anchor, end_anchor = _chapter_slice_anchors(chapters, toc_pages, book, chapter_idx)
    chapter_content = _slice_content(unified, start_anchor, end_anchor)

    return templates.TemplateResponse(request, "reader.html", {
        "book": book,
        "book_id": book_id,
        "heading_toc": heading_toc,
        "chapter_idx": chapter_idx,
        "chapter_title": ch['title'],
        "chapter_content": chapter_content,
        "total_chapters": len(chapters),
    })

# ── 整章 AJAX API GET /api/full_chapter/{book_id}/{chapter_idx} ──
@app.get("/api/full_chapter/{book_id}/{chapter_idx}")
async def api_full_chapter(book_id: str, chapter_idx: int):
    """【整章API】返回一整章的 HTML + 节列表"""
    book = load_book_cached(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    toc_pages = _get_toc_pages(book_id, book)
    chapters = _build_chapters(toc_pages)

    if chapter_idx < 0 or chapter_idx >= len(chapters):
        raise HTTPException(status_code=404, detail="Chapter not found")

    ch = chapters[chapter_idx]

    unified = _get_unified_html_cached(book_id, book)
    start_anchor, end_anchor = _chapter_slice_anchors(chapters, toc_pages, book, chapter_idx)
    html = _slice_content(unified, start_anchor, end_anchor)

    return JSONResponse({
        "chapter_idx": chapter_idx,
        "title": ch['title'],
        "html": html,
        "sections": ch['sections'],
        "total_chapters": len(chapters),
    })

# ── 图片服务 GET /read/{book_id}/images/{image_name} ──
@app.get("/read/{book_id}/images/{image_name}")
async def serve_image(book_id: str, image_name: str):
    """【图片服务】返回书籍内的图片文件"""
    safe_book_id = os.path.basename(book_id)
    safe_image_name = os.path.basename(image_name)
    img_path = os.path.join(BOOKS_DIR, safe_book_id, "images", safe_image_name)
    if not os.path.exists(img_path):
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(img_path)

# ── 服务器入口 ──
if __name__ == "__main__":
    import uvicorn
    print("Starting server at http://127.0.0.1:8123")
    uvicorn.run(app, host="127.0.0.1", port=8123)
