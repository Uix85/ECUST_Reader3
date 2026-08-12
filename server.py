"""
ECUST_Reader3 —— FastAPI 阅读服务器（路由层）。

只保留 HTTP 路由与必要装配；业务逻辑见：
- book_service.py       基础阅读器（标题检测 + 渲染管线 + Book 加载 + 缓存）
- auxiliary_reading.py  辅助阅读（四层级 AI 功能：概念层/语义层等，独立模块）
- reader3.py            EPUB 解析与 SQLite 入库
- schema.py             SQLite schema 与连接池
"""

import os
import shutil
import tempfile

from fastapi import FastAPI, Request, HTTPException, File, UploadFile
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from models import Book
from reader3 import process_epub_to_sqlite
from schema import get_db
from book_service import (
    BOOKS_DIR,
    load_book_cached,
    clear_book_caches,
    _get_heading_toc,
    _get_toc_pages,
    _build_chapters,
    _get_unified_html_cached,
    _chapter_slice_anchors,
    _slice_content,
    _get_anchor_chapter_map,
)
from auxiliary_reading import router as layer_router

app = FastAPI()
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))
templates.env.auto_reload = True  # reload templates on each request during dev

# 辅助阅读（四层级 AI 功能）独立挂载，与基础阅读路由隔离
app.include_router(layer_router)

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
                            db = get_db(db_path)
                            row = db.execute("SELECT total_chaps, total_paras FROM books LIMIT 1").fetchone()
                            if row:
                                total_chaps = row['total_chaps'] or total_chaps
                                total_paras = row['total_paras'] or 0
                        except Exception:
                            pass

                    # 计算 TOC 页数（标题目录中的条目数）
                    try:
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
        # 只清理该书缓存（不影响其他书的缓存命中）
        clear_book_caches(folder)

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

# ── 章节切片共用（页面路由与 API 共用，避免重复逻辑）──
def _get_chapter_slice(book_id: str, book: Book, chapter_idx: int):
    """【章节切片】返回 (chapters, ch, html)；章越界时抛 404"""
    toc_pages = _get_toc_pages(book_id, book)
    chapters = _build_chapters(toc_pages)
    if chapter_idx < 0 or chapter_idx >= len(chapters):
        raise HTTPException(status_code=404, detail="Chapter not found")
    ch = chapters[chapter_idx]
    unified = _get_unified_html_cached(book_id, book)
    start_anchor, end_anchor = _chapter_slice_anchors(chapters, toc_pages, book, book_id, chapter_idx)
    html = _slice_content(unified, start_anchor, end_anchor)
    return chapters, ch, html

# ── 阅读页面 GET /read/{book_id}/{chapter_idx} ──
@app.get("/read/{book_id}/{chapter_idx}", response_class=HTMLResponse)
async def read_chapter(request: Request, book_id: str, chapter_idx: int):
    """【阅读页面】chapter_idx = 章索引（0-based），每章为连续滚动页"""
    book = load_book_cached(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    heading_toc = _get_heading_toc(book_id, book)
    chapters, ch, chapter_content = _get_chapter_slice(book_id, book, chapter_idx)

    return templates.TemplateResponse(request, "reader.html", {
        "book": book,
        "book_id": book_id,
        "heading_toc": heading_toc,
        "chapter_idx": chapter_idx,
        "chapter_title": ch['title'],
        "chapter_content": chapter_content,
        "total_chapters": len(chapters),
        "anchor_map": _get_anchor_chapter_map(book_id, book),
    })

# ── 整章 AJAX API GET /api/full_chapter/{book_id}/{chapter_idx} ──
@app.get("/api/full_chapter/{book_id}/{chapter_idx}")
async def api_full_chapter(book_id: str, chapter_idx: int):
    """【整章API】返回一整章的 HTML + 节列表"""
    book = load_book_cached(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    chapters, ch, html = _get_chapter_slice(book_id, book, chapter_idx)

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
