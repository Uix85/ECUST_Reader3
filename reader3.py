"""
Parses an EPUB file into a structured object that can be used to serve the book via a web interface.
"""

import os
import shutil
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from datetime import datetime
from urllib.parse import unquote
import re

import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup, Comment

# --- Data structures ---

@dataclass
class ChapterContent:
    """
    Represents a physical file in the EPUB (Spine Item).
    A single file might contain multiple logical chapters (TOC entries).
    """
    id: str           # Internal ID (e.g., 'item_1')
    href: str         # Filename (e.g., 'part01.html')
    title: str        # Best guess title from file
    content: str      # Cleaned HTML with rewritten image paths
    text: str         # Plain text for search/LLM context
    order: int        # Linear reading order


@dataclass
class TOCEntry:
    """Represents a logical entry in the navigation sidebar."""
    title: str
    href: str         # original href (e.g., 'part01.html#chapter1')
    file_href: str    # just the filename (e.g., 'part01.html')
    anchor: str       # just the anchor (e.g., 'chapter1'), empty if none
    children: List['TOCEntry'] = field(default_factory=list)


@dataclass
class BookMetadata:
    """Metadata"""
    title: str
    language: str
    authors: List[str] = field(default_factory=list)
    description: Optional[str] = None
    publisher: Optional[str] = None
    date: Optional[str] = None
    identifiers: List[str] = field(default_factory=list)
    subjects: List[str] = field(default_factory=list)


@dataclass
class Book:
    """The Master Object to be pickled."""
    metadata: BookMetadata
    spine: List[ChapterContent]  # The actual content (linear files)
    toc: List[TOCEntry]          # The navigation tree
    images: Dict[str, str]       # Map: original_path -> local_path

    # Meta info
    source_file: str
    processed_at: str
    version: str = "3.0"


# --- Utilities ---

def clean_html_content(soup: BeautifulSoup) -> BeautifulSoup:
    """【HTML清理】移除 script/style/iframe/nav/form 等无关标签"""

    # Remove dangerous/useless tags
    for tag in soup(['script', 'style', 'iframe', 'video', 'nav', 'form', 'button']):
        tag.decompose()

    # Remove HTML comments
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    # Remove input tags
    for tag in soup.find_all('input'):
        tag.decompose()

    return soup


def extract_plain_text(soup: BeautifulSoup) -> str:
    """【纯文本提取】从 BeautifulSoup 对象提取纯文本"""
    text = soup.get_text(separator=' ')
    # Collapse whitespace
    return ' '.join(text.split())


def parse_toc_recursive(toc_list, depth=0) -> List[TOCEntry]:
    """【NCX目录解析】递归解析 EPUB 原始 NCX 目录为 TOCEntry 树"""
    result = []

    for item in toc_list:
        # ebooklib TOC items are either `Link` objects or tuples (Section, [Children])
        if isinstance(item, tuple):
            section, children = item
            entry = TOCEntry(
                title=section.title,
                href=section.href,
                file_href=section.href.split('#')[0],
                anchor=section.href.split('#')[1] if '#' in section.href else "",
                children=parse_toc_recursive(children, depth + 1)
            )
            result.append(entry)
        elif isinstance(item, epub.Link):
            entry = TOCEntry(
                title=item.title,
                href=item.href,
                file_href=item.href.split('#')[0],
                anchor=item.href.split('#')[1] if '#' in item.href else ""
            )
            result.append(entry)
        # Note: ebooklib sometimes returns direct Section objects without children
        elif isinstance(item, epub.Section):
             entry = TOCEntry(
                title=item.title,
                href=item.href,
                file_href=item.href.split('#')[0],
                anchor=item.href.split('#')[1] if '#' in item.href else ""
            )
             result.append(entry)

    return result


def get_fallback_toc(book_obj) -> List[TOCEntry]:
    """【兜底目录】当 NCX 为空时，从 Spine 构建平坦目录"""
    toc = []
    for item in book_obj.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            name = item.get_name()
            # Try to guess a title from the content or ID
            title = item.get_name().replace('.html', '').replace('.xhtml', '').replace('_', ' ').title()
            toc.append(TOCEntry(title=title, href=name, file_href=name, anchor=""))
    return toc


def extract_metadata_robust(book_obj) -> BookMetadata:
    """【元数据提取】健壮地提取 EPUB 元数据（标题、作者、语言等）"""
    def get_list(key):
        data = book_obj.get_metadata('DC', key)
        return [x[0] for x in data] if data else []

    def get_one(key):
        data = book_obj.get_metadata('DC', key)
        return data[0][0] if data else None

    return BookMetadata(
        title=get_one('title') or "Untitled",
        language=get_one('language') or "en",
        authors=get_list('creator'),
        description=get_one('description'),
        publisher=get_one('publisher'),
        date=get_one('date'),
        identifiers=get_list('identifier'),
        subjects=get_list('subject')
    )


# --- Heading-based TOC extraction ---


# Comprehensive regex patterns for heading detection (multi-language)
_HEADING_PATTERNS = [
    # Chinese chapter/section markers
    re.compile(r'^第[一二三四五六七八九十百千〇零\d]+[章节篇回部集卷][：:　\s]?'),
    re.compile(r'^[序前引导绪]言[：:　]?'),
    re.compile(r'^[跋后]记[：:　]?'),
    re.compile(r'^附录[：:　]?'),
    re.compile(r'^译者序[：:　]?'),
    re.compile(r'^出版说明[：:　]?'),
    re.compile(r'^内容提要[：:　]?'),
    # Parenthetical Chinese markers: （一）, 一、, 1. 等
    re.compile(r'^[（(][一二三四五六七八九十\d][）)]'),
    re.compile(r'^[一二三四五六七八九十\d]+[、．.]'),
    # Parenthetical letters: (a), (b), (c), （a）（b）（c）
    re.compile(r'^[（(][a-zA-Z][）)]'),
    # English chapter/section markers
    re.compile(r'^(Chapter|Part|Section|§)\s*[\dIVXLCDM]+[\.\s]?', re.IGNORECASE),
    re.compile(r'^(Preface|Introduction|Appendix|Foreword|Afterword)[\s:]', re.IGNORECASE),
    # Roman numeral headings: I., II., III., IV., IX. etc.
    re.compile(r'^[IVXLCDM]{1,4}\.\s+\S'),
    # Letter headings: A., B., C., a., b., c.
    re.compile(r'^[A-Za-z]\.\s+\S'),
    # Unicode Roman numerals: Ⅰ．, Ⅱ．, Ⅲ．, Ⅳ．etc.
    re.compile(r'^[\u2160-\u2169]+[．\.]'),
    # Square-bracket headings: [一、...], [1．...], [三、哲学的认识], [Ⅰ．...] etc.
    re.compile(r'^\[[一二三四五六七八九十\d\u2160-\u2169]+[、．\.]\s*\S'),
    # Book metadata in square brackets (精神现象学 风格)
    re.compile(r'^【.*?】'),
]


def _determine_level(text: str) -> int:
    """【层级判定】根据标题文本模式判断层级（1=章,2=节,5=数字子节等）"""
    # Strip enclosing brackets before pattern matching
    detect = re.sub(r'^\[([^\]]+)\]$', r'\1', text.strip())

    if re.match(r'^第[一二三四五六七八九十百千〇零\d]+[章节篇回部集卷]', detect):
        return 1
    if re.match(r'^(Section|Chapter|Part)', detect, re.IGNORECASE):
        return 1
    if re.match(r'^[（(][一二三四五六七八九十\d][）)]', detect):
        return 2
    if re.match(r'^[一二三四五六七八九十]+[、．.]', detect):
        return 2
    if re.match(r'^[A-Z]\.\s', detect):
        return 2
    if re.match(r'^[（(][a-zA-Z][）)]', detect):
        return 3
    if re.match(r'^[a-z]\.\s', detect):
        return 3
    if re.match(r'^【', detect):
        return 4
    if re.match(r'^[IVXLCDM]{1,4}\.\s', detect):
        return 4
    if re.match(r'^[\u2160-\u2169]+[．\.]', detect):
        return 4
    if re.match(r'^\d+[．\.、]', detect):
        return 5
    if re.match(r'^[（(][\d][）)]', detect):
        return 6
    return 2


def _score_heading_candidate(text: str) -> int:
    """【标题评分】评估一段文本是否为标题（0=非标题，越高越像）"""
    if len(text) < 2 or len(text) > 80:
        return 0
    
    # Reject outright: Chinese headings never contain sentence terminators
    if '。' in text or text.rstrip()[-1] in '！？':
        return 0
    
    score = 0
    
    # Check against known heading patterns
    for i, pat in enumerate(_HEADING_PATTERNS):
        if pat.match(text):
            # Metadata patterns (【...】) get lower score
            if i == len(_HEADING_PATTERNS) - 1:  # last pattern = metadata
                score = max(score, 10)
            else:
                score = max(score, 80)
    
    # Bonus for being short
    if len(text) <= 30:
        score += 10
    elif len(text) <= 50:
        score += 5
    
    # Bonus: does NOT end with period
    if not text.endswith('.') :
        score += 10
    
    # Bonus: only contains Chinese/English/numbers/punctuation, no long content
    if len(text) <= 30:
        score += 5
    
    # Penalty: contains obvious body-text markers
    if '的' in text and len(text) > 30:
        score -= 5
    
    # Reject table-of-contents / index entries (…digits, like page references)
    if re.search(r'…+\s*\d', text):
        return 0
    
    # Reject glued headings: chapter-title + sub-heading stuck together
    # e.g., "第二章：调查区域江村经济1．调查区域的界定"
    # The chapter-pattern part and sub-heading part are both detected separately
    if re.match(r'^第[一二三四五六七八九十百千〇零\d]+[章节篇回部集卷]', text):
        if re.search(r'\d+[．\.、]', text[len(text)//2:]):
            return 0
    
    # Downgrade digit-based parentheticals like (1), (2) vs legitimate （一）, （二）
    # These are often body-text enumerations, not real headings
    if re.match(r'^[(（]\d+[)）]', text) and not re.match(r'^[（(][一二三四五六七八九十]+[）)]', text):
        score = min(score, 25)
    
    return score


def _detect_headings_from_text(soup, chapter_href: str, book_title: str = '') -> list:
    """【文本标题检测】从纯文本 EPUB 中检测标题（方法A/B/C/D四轮）"""
    headings = []
    
    # Method A: Split by <br> (typical for TXT-converted content)
    html_str = str(soup)
    br_segments = []
    for seg in html_str.replace('<br/>', '<br>').split('<br>'):
        seg_soup = BeautifulSoup(seg, 'html.parser')
        text = seg_soup.get_text(strip=True)
        if text:
            br_segments.append(text)
    
    seen_texts = set()
    for idx, text in enumerate(br_segments):
        score = _score_heading_candidate(text)
        if score >= 30 and text not in seen_texts:
            seen_texts.add(text)
            # Determine level based on patterns
            level = _determine_level(text)
            
            hid = f"txt-hdr-{re.sub(r'[^a-zA-Z0-9]', '', chapter_href)[-8:]}-{idx}"
            headings.append({
                'level': level,
                'title': text,
                'anchor': hid,
                'score': score,
                'chapter_order': 0,
                'chapter_href': chapter_href,
            })
    
    # Method B: For each chapter, also try to extract a clean heading from the start
    full_text = soup.get_text()
    # Take first non-empty line / segment
    for line in full_text.replace('<br>', '\n').replace('<br/>', '\n').split('\n'):
        line = line.strip()
        if line and len(line) >= 2:
            # Try _clean_title on it (truncates at \u3000\u3000 etc.)
            cleaned = _clean_title(line, max_len=60)
            if cleaned and len(cleaned) >= 2 and len(cleaned) <= 60 and cleaned not in seen_texts:
                # Only add if it actually got truncated (meaning it had body text)
                if cleaned != line or len(line) <= 30:
                    score = _score_heading_candidate(cleaned)
                    if score >= 20:
                        seen_texts.add(cleaned)
                        hid = f"txt-hdr-start-{re.sub(r'[^a-zA-Z0-9]', '', chapter_href)[-8:]}"
                        headings.append({
                            'level': 1,
                            'title': cleaned,
                            'anchor': hid,
                            'score': score,
                            'chapter_order': 0,
                            'chapter_href': chapter_href,
                        })
            break
    
    # Method C: Scan full continuous text for numbered sub-heading patterns
    # Catches patterns like "1．调查区域的界定" embedded in body text (江村经济 style)
    full_text = soup.get_text()
    # Normalize separators to find sentence boundaries
    normalized = full_text
    for sep in ['\u3000\u3000', '  ', '\n', '；']:
        normalized = normalized.replace(sep, '\n')
    lines = [ln.strip() for ln in normalized.split('\n') if ln.strip()]
    
    for idx, line in enumerate(lines):
        if len(line) < 3 or len(line) > 60:
            continue
        if line in seen_texts:
            continue
        # Match various sub-heading patterns within continuous text
        is_sub = False
        sub_lvl = 2
        if re.match(r'^[一二三四五六七八九十]+[、．.]', line):
            is_sub = True
            sub_lvl = 2
        elif re.match(r'^\d+[．\.、](?!\d)', line):
            is_sub = True
            sub_lvl = 5
        elif re.match(r'^[（(][a-zA-Z][）)]', line):
            is_sub = True
            sub_lvl = 3
        elif re.match(r'^[（(][一二三四五六七八九十\d][）)]', line):
            is_sub = True
            sub_lvl = 2
        elif re.match(r'^[IVXLCDM]{1,4}\.', line):
            is_sub = True
            sub_lvl = 4
        elif re.match(r'^[\u2160-\u2169]+[．\.]', line):
            is_sub = True
            sub_lvl = 4
        elif re.match(r'^[A-Z]\.\s', line):
            is_sub = True
            sub_lvl = 2
        elif re.match(r'^[a-z]\.\s', line):
            is_sub = True
            sub_lvl = 3
        
        if is_sub:
            # Must end without body-terminating punctuation (period only, not ；)
            if line.rstrip()[-1] in '。！？':
                continue
            score = _score_heading_candidate(line)
            if score >= 30:
                seen_texts.add(line)
                hid = f"txt-hdr-full-{re.sub(r'[^a-zA-Z0-9]', '', chapter_href)[-8:]}-{idx}"
                headings.append({
                    'level': sub_lvl,
                    'title': line,
                    'anchor': hid,
                    'score': score,
                    'chapter_order': 0,
                    'chapter_href': chapter_href,
                })
    
    # Method D: Scan segments for inline sub-heading patterns
    # (e.g. "江村经济1．调查区域的界定" embedded at end of body text)
    # This handles TXT-converted EPUBs where sub-headings are inline
    # rather than on separate lines. The book title consistently appears
    # before actual sub-headings in this format.
    # Use a reproducible anchor so inject_heading_ids can match them.
    if book_title:
        escaped_title = re.escape(book_title)
        _INLINE_SUB_PAT = re.compile(
            rf'{escaped_title}(\d+)\s*[．\.]\s*([^。；、！？\n\u3000]{{1,40}})'
        )
        for idx, line in enumerate(lines):
            for m in _INLINE_SUB_PAT.finditer(line):
                num = m.group(1)
                title_part = m.group(2).strip()
                if re.match(r'^\d', title_part) or re.search(r'[\d．\.]+\s*(亩|岁|％|元|蒲式耳|英里|小时)', title_part):
                    continue
                full_title = '%s．%s' % (num, title_part)
                if len(full_title) < 3 or len(full_title) > 50:
                    continue
                if full_title in seen_texts:
                    continue
                score = _score_heading_candidate(full_title)
                if score >= 30:
                    seen_texts.add(full_title)
                    # Reproducible anchor from title text (not position-based)
                    hid = 'hdr-inline-' + re.sub(r'[^a-zA-Z0-9\u4e00-\u9fff]', '', full_title)[:30]
                    headings.append({
                        'level': 5,
                        'title': full_title,
                        'anchor': hid,
                        'score': score,
                        'chapter_order': 0,
                        'chapter_href': chapter_href,
                    })
    
    # Sort by original position (not score) to preserve document order
    for i, h in enumerate(headings):
        h['_orig_idx'] = i
    headings.sort(key=lambda h: h['_orig_idx'])
    
    return headings


def _clean_title(title: str, max_len: int = 100) -> str:
    """【标题清洗】截断正文后缀、去除括号噪音、限制长度"""
    title = title.strip()
    if not title:
        return title
    
    # Strip matching square brackets (精神现象学: [一、...] → 一、...)
    if title.startswith('[') and title.endswith(']'):
        inner = title[1:-1].strip()
        if inner and len(inner) >= 2:
            title = inner
    
    # Split trailing "导言"/"引言" from chapter titles when preceded by space
    # e.g. "第五章　理性的确定性与真理性　导言" → split into two parts
    # Only splits when "导言" is in the latter half of the title
    for sep_suffix in [('\u3000导言', 3), ('\u3000引言', 3), (' 导言', 3), (' 引言', 3)]:
        sep, word_len = sep_suffix
        idx = title.rfind(sep)
        if idx > len(title) // 2 and idx > 3:
            before = title[:idx].strip()
            if len(before) >= 4 and _score_heading_candidate(before) >= 30:
                title = before
                break
    
    # Truncate at double Chinese space (wide space) — common in Chinese EPUBs
    idx = title.find('\u3000\u3000')
    if idx > 0:
        title = title[:idx]
    # Truncate at double regular space
    idx = title.find('  ')
    if idx is not None and 10 < idx < len(title) - 10:
        title = title[:idx]
    # Truncate at Chinese period + space (sentence boundary with body text)
    for punct in '。！？':
        idx = title.find(punct)
        if 5 < idx < max_len and idx < len(title) - 5:
            title = title[:idx + 1]
            break
    # Enforce max length at a sentence boundary
    if len(title) > max_len:
        for punct in '。！？.!?':
            idx = title.rfind(punct, 0, max_len)
            if idx > 10:
                title = title[:idx + 1]
                break
        else:
            title = title[:max_len].rstrip() + '…'
    return title.strip()


def _clean_toc_entries(entries: list, depth: int = 0, filter_depth0: bool = True) -> list:
    """【目录清洗】递归清洗 TOC 条目，过滤非标题条目"""
    cleaned = []
    for entry in entries:
        new_title = _clean_title(entry.title)
        # Skip entries that don't look like headings after cleaning:
        # - Very long strings that aren't proper titles
        # - Strings that are just filenames
        if depth == 0 and filter_depth0:
            if _score_heading_candidate(new_title) < 20:
                # Check if it has children to keep
                if entry.children:
                    new_children = _clean_toc_entries(entry.children, depth + 1, filter_depth0)
                    cleaned.extend(new_children)
                continue
        new_children = _clean_toc_entries(entry.children, depth + 1, filter_depth0) if entry.children else []
        cleaned.append(TOCEntry(
            title=new_title,
            href=entry.href,
            file_href=entry.file_href,
            anchor=entry.anchor,
            children=new_children,
        ))
    return cleaned


def inject_heading_ids(chapter: ChapterContent, book_title: str = '') -> str:
    """【锚点注入】为章节内的标题标签注入 id 属性（方法1:HTML标签 方法2:文本检测 方法3:内联）"""
    soup = BeautifulSoup(chapter.content, 'html.parser')
    modified = False

    # Method 1: Inject IDs for <h1>-<h6> tags
    heading_tags = soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
    for idx, tag in enumerate(heading_tags):
        # 总是重写 ID，确保统一 HTML 中锚点全局唯一（calibre 的 calibre_pb_N 会跨文件重复）
        tag['id'] = f"hdr-{chapter.order}-{idx}"
        modified = True

    # Method 2: If no heading tags, inject anchors for text-detected headings
    if not heading_tags:
        html_str = str(soup)
        br_tag = '<br/>'
        parts = html_str.split(br_tag)
        new_parts = []
        for p_idx, part in enumerate(parts):
            part_text = BeautifulSoup(part, 'html.parser').get_text(strip=True)
            if part_text and _score_heading_candidate(part_text) >= 30:
                # Deterministic anchor from chapter href
                hkey = re.sub(r'[^a-zA-Z0-9]', '', chapter.href)[-8:]
                anchor_id = f"txt-hdr-{hkey}-{p_idx}"
                # Avoid double-injection
                if anchor_id not in part:
                    part = f'<span id="{anchor_id}"></span>' + part
                    modified = True
            new_parts.append(part)
        if modified:
            html_str = br_tag.join(new_parts)

        # Method 3: Inject anchors for inline sub-headings
        # (e.g., "江村经济<br><br>1．调查区域的界定" — detected by Method D)
        # Uses the book title to locate patterns and generates matching
        # reproducible anchor IDs. Accounts for HTML tags between elements.
        if book_title:
            escaped = re.escape(book_title)
            _inj_pat = re.compile(
                rf'({escaped})(?:<[^>]+>|\s)*?(\d+)\s*[．\.]\s*([^。；、！？\n\u3000]{{1,40}})'
            )
            def _inject_inline_anchor(m):
                """【内联锚点注入】为内联子标题注入 <span> 锚点"""
                num = m.group(2)
                title_part = m.group(3).strip()
                if re.match(r'^\d', title_part):
                    return m.group(0)
                full = '%s．%s' % (num, title_part)
                if len(full) < 3:
                    return m.group(0)
                anchor_id = 'hdr-inline-' + re.sub(r'[^a-zA-Z0-9\u4e00-\u9fff]', '', full)[:30]
                return '<span id="%s"></span>%s' % (anchor_id, m.group(0))
            new_html = _inj_pat.sub(_inject_inline_anchor, html_str)
            if new_html != html_str:
                return new_html

        if modified:
            return html_str

    return str(soup) if modified else chapter.content


def _attach_sub_headings(toc_entries: List[TOCEntry], book: Book) -> List[TOCEntry]:
    """【子标题挂载】检测章节内的子标题并挂载到父级 TOC 条目下"""
    def _titles_are_similar(a: str, b: str) -> bool:
        """【标题相似判断】检查两个标题是否近似重复"""
        if a == b:
            return True
        # One is a prefix/suffix of the other (after cleaning)
        a_clean = re.sub(r'[\[\]（）()\s]', '', a)
        b_clean = re.sub(r'[\[\]（）()\s]', '', b)
        if len(a_clean) >= 3 and len(b_clean) >= 3:
            if a_clean in b_clean or b_clean in a_clean:
                return True
        return False

    def _clean_sub_title(title: str, parent_title: str) -> str:
        """【子标题清洗】剥离父标题前缀和括号噪音"""
        t = _clean_title(title)
        if not t or t == parent_title:
            return ''
        # Strip parent title prefix
        if parent_title and t.startswith(parent_title):
            remainder = t[len(parent_title):].strip()
            if remainder and _score_heading_candidate(remainder) >= 30:
                t = remainder
        # Find sub-heading pattern in remaining text
        m = re.search(r'([一二三四五六七八九十]+[．\.、][^。\n]{2,40})$', t)
        if m:
            cand = m.group(1).strip()
            if _score_heading_candidate(cand) >= 30:
                t = cand
        # Also try digit pattern
        m2 = re.search(r'(\d+[．\.、][^。\n]{2,40})$', t)
        if m2 and not m:
            cand = m2.group(1).strip()
            if _score_heading_candidate(cand) >= 30:
                t = cand
        return t

    # Build map: file_href → TOC entries
    toc_by_file: Dict[str, List[TOCEntry]] = {}
    for entry in toc_entries:
        toc_by_file.setdefault(entry.file_href, []).append(entry)

    def _recompute_level(title: str) -> int:
        """【层级重算】从清洗后的标题重新计算层级"""
        return _determine_level(title)

    for ch in book.spine:
        if ch.href not in toc_by_file:
            continue

        soup = BeautifulSoup(ch.content, 'html.parser')
        detected = _detect_headings_from_text(soup, ch.href, book.metadata.title)
        good = [h for h in detected if h['score'] >= 25]

        if not good:
            continue

        parent = toc_by_file[ch.href][-1]

        # Clean and deduplicate titles
        seen_clean = set()
        cleaned_heads = []
        for h in good:
            t = _clean_sub_title(h['title'], parent.title)
            if not t or t in seen_clean:
                continue
            # Check similarity with already-added titles
            is_dup = False
            for existing in seen_clean:
                if _titles_are_similar(t, existing):
                    is_dup = True
                    break
            if is_dup:
                continue
            seen_clean.add(t)
            # Recompute level from cleaned title (fixes glued heading bug)
            new_level = _recompute_level(t)
            cleaned_heads.append({
                'level': new_level,
                'title': t,
                'anchor': h['anchor'],
                '_orig_idx': h.get('_orig_idx', 0),
                'chapter_order': 0,
                'chapter_href': ch.href,
            })

        if not cleaned_heads:
            continue

        # Sort by original position (not score) for correct tree building
        cleaned_heads.sort(key=lambda h: h.get('_orig_idx', 0))

        # Build hierarchy among sub-headings and attach
        sub_tree = _headings_to_tree(cleaned_heads, use_levels=True)
        parent.children = sub_tree

    return toc_entries


def build_heading_based_toc(book: Book) -> List[TOCEntry]:
    """【标题目录构建】构建完整层级目录——优先 HTML 标签，回退到文本检测+NCX"""
    all_headings: List[dict] = []
    has_any_html_headings = False

    for ch in book.spine:
        soup = BeautifulSoup(ch.content, 'html.parser')
        html_headings = soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])

        if html_headings:
            has_any_html_headings = True
            for idx, tag in enumerate(html_headings):
                level = int(tag.name[1])
                text = tag.get_text(strip=True)
                if not text:
                    continue
                hid = f"hdr-{ch.order}-{idx}"
                all_headings.append({
                    'level': level,
                    'title': text,
                    'anchor': hid,
                    'chapter_order': ch.order,
                    'chapter_href': ch.href,
                })

    if has_any_html_headings:
        # Clean up titles from real heading tags
        for h in all_headings:
            h['title'] = _clean_title(h['title'])
        
        # Fix hierarchy for books where all headings share the same HTML level
        # (e.g. all-<h1> books like 富爸爸穷爸爸).  Within each spine file,
        # if subsequent headings have the same level as the first, demote them
        # by one level so they become children rather than siblings.
        by_file: Dict[str, List[dict]] = {}
        for h in all_headings:
            by_file.setdefault(h['chapter_href'], []).append(h)
        for fh, headings in by_file.items():
            if len(headings) <= 1:
                continue
            first_level = headings[0]['level']
            for i, h in enumerate(headings):
                if i > 0 and h['level'] <= first_level:
                    h['level'] = first_level + 1
        
        return _headings_to_tree(all_headings, use_levels=True)

    # No <h1>-<h6> tags found.
    # Strategy: use cleaned original TOC as base, supplemented by
    # high-confidence text-detected headings.

    cleaned_original = _clean_toc_entries(book.toc)

    # Collect high-confidence text headings (score >= 60, i.e. strong heading matches)
    text_headings: List[dict] = []
    for ch in book.spine:
        soup = BeautifulSoup(ch.content, 'html.parser')
        detected = _detect_headings_from_text(soup, ch.href)
        for h in detected:
            if h['score'] >= 60:
                h['chapter_order'] = ch.order
                h['title'] = _clean_title(h['title'])
                text_headings.append(h)

    # If original TOC is decent (>=3 entries), use it with sub-headings attached.
    if len(cleaned_original) >= 3:
        # Check if content has enough structural separation to support sub-heading detection.
        # Some EPUBs use <br> to separate headings from body (精神现象学, 资本论),
        # others use double wide spaces \u3000\u3000 (江村经济).
        sample_spine = book.spine[:min(3, len(book.spine))]
        br_count = sum(
            len(BeautifulSoup(ch.content, 'html.parser').find_all('br'))
            for ch in sample_spine
        )
        ws_count = sum(
            BeautifulSoup(ch.content, 'html.parser').get_text().count('\u3000\u3000')
            for ch in sample_spine
        )
        has_structure = br_count >= 50 or ws_count >= 20
        if has_structure:
            return _attach_sub_headings(cleaned_original, book)
        return cleaned_original

    # Use text-detected headings if we have enough
    if len(text_headings) >= 3:
        return _headings_to_tree(text_headings, use_levels=False)

    # Last resort: return whatever we have (cleaned original or text)
    return cleaned_original if cleaned_original else _headings_to_tree(text_headings, use_levels=False)


def _match_ncx_to_html(ncx_entries: List[TOCEntry], html_by_file: Dict[str, List[dict]]):
    """【NCX-HTML锚点匹配】将 HTML 标题的锚点 id 复制到匹配的 NCX 条目上"""
    def _normalize(s: str) -> str:
        """【文本标准化】去除标点和空格用于模糊匹配"""
        return re.sub(r'[\s\u3000·•\-—―,，.。;；:：!！?？"\'\"\'「」『』【】《》（）()\[\]]+', '', s.lower())
    
    def _walk(entries):
        for e in entries:
            if e.file_href in html_by_file:
                candidates = html_by_file[e.file_href]
                e_norm = _normalize(e.title)
                best = None
                best_score = 0
                for h in candidates:
                    h_norm = _normalize(h['title'])
                    # Exact match after normalization
                    if e_norm == h_norm:
                        best = h
                        break
                    # Partial match: one contains the other
                    if len(e_norm) >= 3 and len(h_norm) >= 3:
                        if e_norm in h_norm or h_norm in e_norm:
                            score = min(len(e_norm), len(h_norm)) / max(len(e_norm), len(h_norm))
                            if score > best_score:
                                best_score = score
                                best = h
                if best:
                    e.anchor = best['anchor']
            if e.children:
                _walk(e.children)
    
    _walk(ncx_entries)


def _headings_to_tree(headings: List[dict], use_levels: bool = True) -> List[TOCEntry]:
    """【标题树构建】将扁平的标题 dict 列表转换为嵌套的 TOCEntry 树"""
    if not use_levels:
        return [
            TOCEntry(
                title=h['title'],
                href=f"{h['chapter_href']}#{h['anchor']}",
                file_href=h['chapter_href'],
                anchor=h['anchor'],
                children=[],
            )
            for h in headings
        ]

    root: List[TOCEntry] = []
    stack: List[tuple] = []

    for h in headings:
        entry = TOCEntry(
            title=h['title'],
            href=f"{h['chapter_href']}#{h['anchor']}",
            file_href=h['chapter_href'],
            anchor=h['anchor'],
            children=[],
        )
        level = h['level']
        while stack and stack[-1][0] >= level:
            stack.pop()
        if stack:
            stack[-1][1].append(entry)
        else:
            root.append(entry)
        stack.append((level, entry.children))

    return root


# --- SQLite processing ---

def _split_paragraphs(html: str) -> list:
    """【段落拆分】将章节 HTML 拆分为段落列表（策略: <p> → <br> → \u3000\u3000）"""
    soup = BeautifulSoup(html, 'html.parser')
    p_tags = soup.find_all('p')
    
    if p_tags:
        # Strategy A: <p> tags, but split <br>-heavy <p>s into sub-paras
        result = []
        for tag in p_tags:
            tag_html = str(tag)
            tag_text = tag.get_text().strip()
            if not tag_text or len(tag_text) < 2:
                continue
            
            # If this <p> has many <br> tags, split into sub-paragraphs
            br_count = tag_html.lower().count('<br')
            if br_count >= 5:
                sub_segments = tag_html.replace('<br/>', '<br>').split('<br>')
                running = 0
                for sub in sub_segments:
                    sub_soup = BeautifulSoup(sub, 'html.parser')
                    sub_text = sub_soup.get_text().strip()
                    sub_html = str(sub_soup)
                    if sub_text and len(sub_text) >= 2:
                        result.append({
                            'html': sub_html,
                            'text': sub_text,
                            'offset_start': running,
                            'offset_end': running + len(sub_html),
                        })
                    running += len(sub) + 4  # +4 for <br>
            else:
                offset_start = html.find(tag_html)
                offset_end = offset_start + len(tag_html) if offset_start != -1 else 0
                result.append({
                    'html': tag_html,
                    'text': tag_text,
                    'offset_start': offset_start,
                    'offset_end': offset_end,
                })
        if result:
            return result

    # Strategy B+C: No <p> tags found — split by <br>, then \u3000\u3000 for long segments
    normalized = html.replace('<br/>', '<br>')
    segments = normalized.split('<br>')
    result = []
    running_offset = 0
    
    for seg in segments:
        seg_soup = BeautifulSoup(seg, 'html.parser')
        seg_text = seg_soup.get_text().strip()
        seg_html = str(seg_soup)
        
        if not seg_text or len(seg_text) < 2:
            running_offset += len(seg) + 4
            continue
        
        if len(seg_text) > 300 and '\u3000\u3000' in seg_text:
            sub_segs = seg_text.split('\u3000\u3000')
            for sub in sub_segs:
                sub = sub.strip()
                if sub and len(sub) >= 2:
                    result.append({
                        'html': f'<p>{sub}</p>',
                        'text': sub,
                        'offset_start': running_offset,
                        'offset_end': running_offset + len(sub),
                    })
        else:
            result.append({
                'html': seg_html,
                'text': seg_text,
                'offset_start': running_offset,
                'offset_end': running_offset + len(seg_html),
            })
        running_offset += len(seg) + 4
    
    return result


def process_epub_to_sqlite(epub_path: str, books_dir: str = "books") -> str:
    """【EPUB处理入库】将 EPUB 解析后写入 SQLite 数据库，返回输出目录路径"""
    from schema import get_db
    
    # 1. Load & extract
    print(f"Loading {epub_path}...")
    book_obj = epub.read_epub(epub_path)
    metadata = extract_metadata_robust(book_obj)
    
    # 2. Prepare directories
    base_name = os.path.splitext(os.path.basename(epub_path))[0]
    out_dir = os.path.join(books_dir, base_name + "_data")
    images_dir = os.path.join(out_dir, 'images')
    
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(images_dir, exist_ok=True)
    
    # 3. Extract images
    print("Extracting images...")
    image_map = {}
    for item in book_obj.get_items():
        if item.get_type() == ebooklib.ITEM_IMAGE:
            original_fname = os.path.basename(item.get_name())
            safe_fname = "".join(c for c in original_fname if c.isalnum() or c in '._-').strip()
            local_path = os.path.join(images_dir, safe_fname)
            with open(local_path, 'wb') as f:
                f.write(item.get_content())
            rel_path = f"images/{safe_fname}"
            image_map[item.get_name()] = rel_path
            image_map[original_fname] = rel_path
    
    # 4. Parse TOC
    print("Parsing Table of Contents...")
    toc_structure = parse_toc_recursive(book_obj.toc)
    if not toc_structure:
        print("Warning: Empty TOC, building fallback from Spine...")
        toc_structure = get_fallback_toc(book_obj)
    
    import json as _json
    toc_json = _json.dumps([{
        'title': e.title, 'href': e.href, 'file_href': e.file_href,
        'anchor': e.anchor, 'children': _json.loads(toc_json) if False else []
    } for e in toc_structure], ensure_ascii=False)
    # (simplified - full TOC stored as JSON string)
    
    # 5. Open DB
    db_path = os.path.join(out_dir, 'book.db')
    db = get_db(db_path)
    
    # 6. Insert book row
    now = datetime.now().isoformat()
    db.execute(
        "INSERT INTO books (title, language, authors, source_file, processed_at, total_chaps, toc_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (metadata.title, metadata.language, _json.dumps(metadata.authors, ensure_ascii=False),
         os.path.basename(epub_path), now, 0, '[]')
    )
    book_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    
    # 7. Process chapters & paragraphs
    print("Processing chapters and paragraphs...")
    total_paras = 0
    
    for i, spine_item in enumerate(book_obj.spine):
        item_id, linear = spine_item
        item = book_obj.get_item_with_id(item_id)
        if not item or item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        
        raw_content = item.get_content().decode('utf-8', errors='ignore')
        soup = BeautifulSoup(raw_content, 'html.parser')
        
        # Fix images
        for img in soup.find_all('img'):
            src = img.get('src', '')
            if not src:
                continue
            src_decoded = unquote(src)
            filename = os.path.basename(src_decoded)
            if src_decoded in image_map:
                img['src'] = image_map[src_decoded]
            elif filename in image_map:
                img['src'] = image_map[filename]
        
        # Clean HTML
        soup = clean_html_content(soup)
        
        # Extract body
        body = soup.find('body')
        if body:
            final_html = "".join(str(x) for x in body.contents)
        else:
            final_html = str(soup)
        
        full_text = soup.get_text()
        full_text_clean = ' '.join(full_text.split())
        
        # Chapter title: try TOC lookup first
        ch_title = f"Section {i+1}"
        for t in toc_structure:
            if t.file_href == item.get_name():
                ch_title = t.title
                break
        
        # Heading tree for this chapter
        heading_json = '[]'
        try:
            soup_h = BeautifulSoup(final_html, 'html.parser')
            h_tags = soup_h.find_all(['h1','h2','h3','h4','h5','h6'])
            if h_tags:
                htree = [{'level': int(h.name[1]), 'text': h.get_text(strip=True)} for h in h_tags]
                heading_json = _json.dumps(htree, ensure_ascii=False)
        except:
            pass
        
        # Insert chapter
        db.execute(
            "INSERT INTO chapters (book_id, spine_order, href, title, content_html, content_text, heading_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (book_id, i, item.get_name(), ch_title, final_html, full_text_clean, heading_json)
        )
        chapter_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        
        # Split and insert paragraphs
        paragraphs = _split_paragraphs(final_html)
        for seq, para in enumerate(paragraphs):
            db.execute(
                "INSERT INTO paragraphs (chapter_id, book_id, seq, text, html, offset_start, offset_end, char_count) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (chapter_id, book_id, seq, para['text'], para['html'],
                 para['offset_start'], para['offset_end'], len(para['text']))
            )
        
        db.execute("UPDATE chapters SET para_count = ? WHERE id = ?", (len(paragraphs), chapter_id))
        total_paras += len(paragraphs)
    
    # 8. Update book totals
    db.execute(
        "UPDATE books SET total_chaps = (SELECT COUNT(*) FROM chapters WHERE book_id = ?), total_paras = ? WHERE id = ?",
        (book_id, total_paras, book_id)
    )
    db.commit()
    
    print(f"Saved to {db_path}")
    print(f"  Chapters: {db.execute('SELECT COUNT(*) FROM chapters WHERE book_id=?',(book_id,)).fetchone()[0]}")
    print(f"  Paragraphs: {total_paras}")
    
    return out_dir

# --- CLI ---

if __name__ == "__main__":

    import sys
    if len(sys.argv) < 2:
        print("Usage: python reader3.py <file.epub>")
        sys.exit(1)

    epub_file = sys.argv[1]
    assert os.path.exists(epub_file), "File not found."
    
    out_dir = process_epub_to_sqlite(epub_file)
    print(f"\nDone → {out_dir}")