# -*- coding: utf-8 -*-
"""重新生成完整的目录叠加层面板素材（02a~02e）。

数据：真实书籍数据库（books/tmpuke_eepn_data/book.db = 黑格尔的精神现象学），
通过 book_service.build_heading_based_toc + _get_heading_toc 构建真实目录树，
与阅读页 /read/tmpuke_eepn_data/0 侧栏渲染 100% 一致。

与旧版（省略号截断、手写假数据）的差异：
  - 标题完整显示，超长标题按面板宽度自动换行（多行），不再截断加省略号；
  - 层级缩进严格对照真实 CSS（.sec-row.d1/d2/d3 + .sec-link.d1/d2/d3）；
  - 行高/字号/颜色/折叠钮/锁图标全部来自真实应用实测。
"""
import os
import sys

sys.path.insert(0, r"d:/Programs/reader3")
import book_service  # noqa: E402

BOOK_ID = "tmpuke_eepn_data"

# ════════════════════════════════════════════════════════════════
# 几何常量（面板内坐标，全部来自真实应用 getBoundingClientRect 实测）
# ════════════════════════════════════════════════════════════════
PANEL_W = 290          # #side-wrap 实测 290（sidebar 含滚动条）
PANEL_H = 1080

HEADER_Y = 12          # panel-header 顶
HEADER_BASE = 26       # 「目 录」文字 baseline
HEADER_LINE = 32       # 分隔线 y
TOC_TOP = 44           # 第一个 .ch-row 顶

# ── 章行 ──
CH_X = 12              # .ch-row 左（sidebar padding-left 12）
CH_TEXT_X = 51         # 章文字 x（.ch-link padding-box 41 + padding-left 10）
CH_TOGGLE_X = 12       # .ch-toggle 左
CH_TOGGLE_W = 27       # toggle 组件宽（padding 8+8 + 方块 4+4 + gap 3）
CH_TOGGLE_H = 23       # toggle 组件高（padding 6+6 + 方块 4+4 + gap 3）
CH_PAD_T = 5           # .ch-link padding-top
CH_FS = 14.4           # .ch-link font-size (.9em)
CH_LH = 19.44          # line-height 1.35
CH_BASE = 18           # 第一行 baseline 偏移（padT + fs*0.9）
CH_MARGIN = 6          # .ch-item margin-bottom
LOCK_X = 259           # .lock-icon 左（面板内，实测 311-52）
LOCK_W = 18            # lock 18x18
RIGHT_NO_LOCK = 270    # 无锁时文字右缘

# ── 节框 ──
BOX_X = 12             # .section-box 左（sidebar padding 内）
BOX_W = 265            # 290 - 12*2 - 1(border-right)
BOX_B = 1              # border
BOX_PAD_T = 4          # padding 上下
BOX_PAD_S = 6          # padding 左右
BOX_MT = 4             # margin-top
BOX_MB = 8             # margin-bottom

# ── 节行 ──
SEC_ROW_X = 19         # box 内容起点（12 + border 1 + padding 6）
SEC_TOGGLE_W = 20      # .sec-toggle width
SEC_TOGGLE_H = 28      # .sec-toggle height
SEC_TOGGLE_MR = 2      # margin-right
D_INDENT = {1: 8, 2: 20, 3: 32}   # .sec-row.dN padding-left
D_FS = {1: 13.6, 2: 13.12, 3: 12.64}
D_PADL = {1: 2, 2: 4, 3: 6}       # .sec-link.dN padding-left
D_LH = {1: 18.36, 2: 17.71, 3: 17.06}
D_BASE = {1: 16, 2: 15.5, 3: 15}  # 第一行 baseline 偏移
D_MINH = 28            # 节行最小高（sec-toggle 高）

FONT = "'PingFang SC','Microsoft YaHei','Noto Sans CJK SC',sans-serif"

# 锁图标（Edge 风格图钉）
LOCK_PATH = ('M12 2a5 5 0 0 0-5 5v3H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8'
             'a2 2 0 0 0-2-2h-1V7a5 5 0 0 0-5-5zm0 2a3 3 0 0 1 3 3v3H9V7a3 3 0 0 1 3-3z')


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


def cw(ch, fs):
    """单字符像素宽：中文全角 ≈ fs，半角 ≈ 0.55*fs"""
    o = ord(ch)
    if o > 0x2E80 or ch in '（）“”：；，。…—《》·':
        return fs
    return fs * 0.55


def wrap(text, max_w, fs):
    """按像素宽度将长标题拆成多行（不截断、不加省略号）"""
    lines = []
    cur, cur_w = '', 0.0
    for ch in text:
        w = cw(ch, fs)
        if cur and cur_w + w > max_w:
            lines.append(cur)
            cur, cur_w = ch, w
        else:
            cur += ch
            cur_w += w
    if cur:
        lines.append(cur)
    return lines


def ch_h(n):
    return CH_PAD_T * 2 + n * CH_LH


def sec_h(d, n):
    return max(4 * 2 + n * D_LH[d], D_MINH)


def max_w(depth, has_lock):
    right = LOCK_X if has_lock else RIGHT_NO_LOCK
    if depth == 0:
        left = CH_TEXT_X
    else:
        left = SEC_ROW_X + D_INDENT[depth] + SEC_TOGGLE_W + SEC_TOGGLE_MR + D_PADL[depth]
    return right - left


def render_ch_toggle(L, row_y, open_):
    """章折叠钮：2x2 小方块。收起=灰 .5；展开=蓝"""
    ty = row_y + (ch_h(1) - CH_TOGGLE_H) / 2  # 单行近似垂直居中
    color = "#3498db" if open_ else "#495057"
    op = "1" if open_ else "0.5"
    for dx, dy in ((8, 6), (15, 6), (8, 13), (15, 13)):
        L.append(f'      <rect x="{CH_TOGGLE_X + dx}" y="{ty + dy}" width="4" height="4" '
                 f'fill="{color}" opacity="{op}" rx="1"/>')


def render_sec_toggle(L, x, y, open_):
    """节折叠三角 ▸（open 时旋转为 ▾）。真实：.sec-toggle font-size 18 opacity .35"""
    cx, cy = x + SEC_TOGGLE_W / 2, y + SEC_TOGGLE_H / 2
    if open_:
        # 向下三角
        L.append(f'      <path d="M4 0 L12 0 L8 8 Z" transform="translate({cx - 6} {cy - 3})" '
                 f'fill="#6c757d" opacity="0.55"/>')
    else:
        L.append(f'      <path d="M0 4 L8 4 L4 12 Z" transform="translate({cx - 3} {cy - 6})" '
                 f'fill="#6c757d" opacity="0.35"/>')


def render_lock(L, y, color="#6c757d", opacity="0.3"):
    L.append(f'      <path d="{LOCK_PATH}" transform="translate({LOCK_X} {y}) '
             f'scale(0.72)" fill="{color}" opacity="{opacity}"/>')


def render_text_lines(L, x, y0, lines, fs, lh, base, color, bold=False):
    """多行标题。x=文字左缘，y0=行顶，返回末行底"""
    y = y0 + base
    for ln in lines:
        attrs = f' x="{x}" y="{round(y, 1)}" font-size="{fs}"'
        if bold:
            attrs += ' font-weight="bold"'
        L.append(f'      <text{attrs} fill="{color}">{esc(ln)}</text>')
        y += lh
    return y - lh


# ════════════════════════════════════════════════════════════════
# 真实目录树
# ════════════════════════════════════════════════════════════════
book = book_service.load_book_cached(BOOK_ID)
TOC = book_service._get_heading_toc(BOOK_ID, book)

ACTIVE_CH = "导言"   # 当前章（蓝色高亮），其标题以"导言"开头


def tree_summary(entries, depth=0):
    out = []
    for e in entries:
        out.append((e.title, [t[0] for t in tree_summary(e.children, depth + 1)]))
    return out


for i, (t, kids) in enumerate(tree_summary(TOC)):
    print(i, t, f"({len(kids)} 子级)")

# 变体：展开的章（按标题匹配）+ 展开的节（标题前缀匹配）
VARIANTS = {
    "02a-toc-v0-collapsed":    {"ch_open": [], "sec_open": []},
    "02b-toc-v1-ch-open":      {"ch_open": ["导言"], "sec_open": []},
    "02c-toc-v2-sec-open":     {"ch_open": ["导言"], "sec_open": ["第二节"]},
    "02d-toc-v3-secs-open":    {"ch_open": ["导言"], "sec_open": ["第二节", "第三节"]},
    "02e-toc-v4-sec2-only":    {"ch_open": ["导言"], "sec_open": ["第三节"]},
}

TITLES = {
    "02a-toc-v0-collapsed": "变体 V0（全折叠 · 默认）",
    "02b-toc-v1-ch-open": "变体 V1（章展开 · 节收起）",
    "02c-toc-v2-sec-open": "变体 V2（章展开 · 第二节展开）",
    "02d-toc-v3-secs-open": "变体 V3（第二节+第三节展开）",
    "02e-toc-v4-sec2-only": "变体 V4（第三节展开 · 其余收起）",
}


def is_active_ch(title):
    return title.startswith(ACTIVE_CH)


def match(prefixes, title):
    return any(title.startswith(p) for p in prefixes)


def render(ch_entries, ch_open, sec_open):
    """渲染一棵（顶层=章）目录树，返回 SVG 行列表与结束 y"""
    L = []
    y = TOC_TOP
    for ch in ch_entries:
        has_kids = bool(ch.children)
        active = is_active_ch(ch.title)
        open_ = match(ch_open, ch.title)
        lines = wrap(ch.title, max_w(0, has_kids), CH_FS)
        h = ch_h(len(lines))
        # ── 章行 ──
        L.append(f'    <g id="ch" data-title="{esc(ch.title[:12])}">')
        if active:
            L.append(f'      <rect x="{CH_X + 29}" y="{y}" width="{max_w(0, has_kids) + 10}" '
                     f'height="{round(h, 1)}" fill="#3498db" rx="4"/>')
        render_ch_toggle(L, y, open_)
        render_text_lines(L, CH_TEXT_X, y, lines, CH_FS, CH_LH, CH_BASE,
                          "#fff" if active else "#495057", bold=active)
        if has_kids:
            render_lock(L, y + (h - 18) / 2, color="#fff" if active else "#6c757d",
                        opacity="0.85" if active else "0.3")
        L.append('    </g>')
        y += h
        # ── 节框（展开时）──
        if open_ and has_kids:
            box_top = y + BOX_MT
            rows = []          # (row_y, depth, entry, sec_open)
            ry = box_top + BOX_B + BOX_PAD_T
            for sec in ch.children:
                depth = 1
                rows.append((ry, depth, sec, match(sec_open, sec.title)))
                ry += sec_h(depth, len(wrap(sec.title, max_w(depth, bool(sec.children)), D_FS[depth])))
                if match(sec_open, sec.title) and sec.children:
                    for kid in sec.children:
                        d2 = depth + 1
                        rows.append((ry, d2, kid, False))
                        ry += sec_h(d2, len(wrap(kid.title, max_w(d2, bool(kid.children)), D_FS[d2])))
            box_h = (ry - box_top) + BOX_PAD_T + BOX_B
            L.append(f'    <rect x="{BOX_X}" y="{box_top}" width="{BOX_W}" height="{round(box_h, 1)}" '
                     f'fill="#fbfcfd" stroke="#e9ecef" rx="6"/>')
            for (ry, depth, sec, s_open) in rows:
                has_skids = bool(sec.children)
                slines = wrap(sec.title, max_w(depth, has_skids), D_FS[depth])
                rh = sec_h(depth, len(slines))
                tx = SEC_ROW_X + D_INDENT[depth]
                if has_skids:
                    render_sec_toggle(L, tx, ry + (rh - SEC_TOGGLE_H) / 2, s_open)
                render_text_lines(L, tx + SEC_TOGGLE_W + SEC_TOGGLE_MR + D_PADL[depth], ry,
                                  slines, D_FS[depth], D_LH[depth], D_BASE[depth], "#4a5568")
                if has_skids:
                    render_lock(L, ry + (rh - 18) / 2)
            y = box_top + box_h + BOX_MB
        else:
            y += CH_MARGIN
    return L


def gen_svg(name, desc, ch_open, sec_open):
    L = []
    L.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{PANEL_W}" height="{PANEL_H}" '
             f'viewBox="0 0 {PANEL_W} {PANEL_H}" font-family="{FONT}">')
    L.append(f'  <title>{name} · {desc}</title>')
    L.append('  <g id="side-wrap">')
    L.append(f'    <rect x="0" y="0" width="{PANEL_W}" height="{PANEL_H}" fill="#f8f9fa"/>')
    L.append(f'    <line x1="{PANEL_W - 0.5}" y1="0" x2="{PANEL_W - 0.5}" y2="{PANEL_H}" stroke="#e9ecef"/>')
    # 面板头
    L.append('    <g id="panel-header">')
    L.append(f'      <text x="{HEADER_Y}" y="{HEADER_BASE}" font-size="12.8" font-weight="bold" '
             f'fill="#868e96" letter-spacing="0.5">目 录</text>')
    L.append(f'      <line x1="{HEADER_Y}" y1="{HEADER_LINE}" x2="{PANEL_W - 12}" y2="{HEADER_LINE}" stroke="#dee2e6"/>')
    L.append('    </g>')
    L.append('    <g id="toc-tree">')
    L.extend(render(TOC, ch_open, sec_open))
    L.append('    </g>')
    L.append('  </g>')
    L.append('</svg>')
    return "\n".join(L)


OUT = os.path.join(os.path.dirname(__file__), "import")
for fname, st in VARIANTS.items():
    svg = gen_svg(fname, TITLES[fname], st["ch_open"], st["sec_open"])
    path = os.path.join(OUT, fname + ".svg")
    with open(path, "w", encoding="utf-8") as f:
        f.write(svg)
    print("written", path, len(svg), "bytes")
print("done")
# 02F 目录收起态覆盖层由 _gen_crop.py 从 03 号素材裁剪生成（勿在此重复生成）
