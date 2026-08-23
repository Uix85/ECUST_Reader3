# -*- coding: utf-8 -*-
"""重组 03-scroll.svg，满足 Penpot「仅文字滚动、其他固定」的层级结构。

目标 z 序（SVG 文档顺序 = 渲染顺序，后者在上）：
  1. 背景（整页白底）                    —— 最底
  2. scroll-content（正文文字层，超高）   —— 中间，滚动
  3. fixed-layer（固定层：browser-bar / 章标题栏(蓝线以上) / 视口虚线 / 滚动条提示 / 翻章条）—— 最顶

导入 Penpot 后：scroll-content 不勾固定（滚动），fixed-layer 勾「滚动时保持固定」（钉住）。
02 系列目录素材不动。
"""
import os
import xml.dom.minidom as m

SRC = os.path.join(os.path.dirname(__file__), "import", "03-scroll.svg")
OUT = SRC


def find_g(root, gid):
    for g in root.getElementsByTagName("g"):
        if g.getAttribute("id") == gid:
            return g
    return None


doc = m.parse(SRC)
root = doc.documentElement

page = find_g(root, "page")
browser_bar = find_g(page, "browser-bar")
main = find_g(page, "main")
ch_title_bar = find_g(main, "ch-title-bar")
msf = find_g(main, "main-scroll-frame")
ch_content = find_g(msf, "ch-content")
scrollbar_hint = find_g(msf, "scrollbar-hint")
ch_nav = find_g(page, "ch-nav")

# 视口虚线 rect（main-scroll-frame 的直接 rect 子元素）
viewport_rect = None
for el in msf.childNodes:
    if el.nodeType == 1 and el.tagName == "rect":
        viewport_rect = el
        break

# 背景（根下第一个整页白底 rect）
bg = None
for el in root.childNodes:
    if el.nodeType == 1 and el.tagName == "rect" and el.getAttribute("fill") == "#fff":
        bg = el
        break

# 底部说明注释
notes = [el.cloneNode(True) for el in root.childNodes
         if el.nodeType == 1 and el.tagName == "text" and el.getAttribute("x") == "52"]

for name, el in [("page", page), ("browser-bar", browser_bar), ("ch-title-bar", ch_title_bar),
                 ("main-scroll-frame", msf), ("ch-content", ch_content),
                 ("scrollbar-hint", scrollbar_hint), ("ch-nav", ch_nav), ("bg", bg)]:
    if el is None:
        raise SystemExit(f"缺少节点: {name}")
if viewport_rect is None:
    raise SystemExit("缺少视口虚线 rect")

# ── 重建 ──
imp = doc.implementation.createDocument(None, "svg", None)
svg = imp.documentElement
svg.setAttribute("xmlns", "http://www.w3.org/2000/svg")
svg.setAttribute("width", root.getAttribute("width"))
svg.setAttribute("height", root.getAttribute("height"))
svg.setAttribute("viewBox", root.getAttribute("viewBox"))
svg.setAttribute("font-family", root.getAttribute("font-family"))

t = imp.createElement("title")
t.appendChild(imp.createTextNode("03 阅读页 · 无目录内容板（重组：背景 < 文字层 < 固定层）"))
svg.appendChild(t)

# 1) 背景
svg.appendChild(bg.cloneNode(True))

# 2) page 容器（z：scroll-content < fixed-layer）
page_g = imp.createElement("g")
page_g.setAttribute("id", "page")

sc = imp.createElement("g")
sc.setAttribute("id", "scroll-content")
sc_title = imp.createElement("title")
sc_title.appendChild(imp.createTextNode("文字层 · 超高内容 · 滚动（勿勾固定）"))
sc.appendChild(sc_title)
sc.appendChild(ch_content.cloneNode(True))

fl = imp.createElement("g")
fl.setAttribute("id", "fixed-layer")
fl_title = imp.createElement("title")
fl_title.appendChild(imp.createTextNode("固定层 · 不滚动（导入后勾「滚动时保持固定」）"))
fl.appendChild(fl_title)
for part in (browser_bar, ch_title_bar, viewport_rect, scrollbar_hint, ch_nav):
    fl.appendChild(part.cloneNode(True))

page_g.appendChild(sc)
page_g.appendChild(fl)
svg.appendChild(page_g)

# 3) 底部说明（更新）
new_note = (
    "素材 03 · 重组后层级：背景 < #scroll-content(文字·滚动) < #fixed-layer(固定·勾「滚动时保持固定」)｜"
    "02 系列目录素材不动"
)
nt = imp.createElement("text")
nt.setAttribute("x", "52")
nt.setAttribute("y", "1050")
nt.setAttribute("font-size", "12")
nt.setAttribute("fill", "#adb5bd")
nt.appendChild(imp.createTextNode(new_note))
svg.appendChild(nt)
nt2 = nt.cloneNode(True)
nt2.setAttribute("y", "1068")
nt2.appendChild(imp.createTextNode(
    "固定层 = browser-bar + 章标题栏(蓝线以上) + 视口虚线 + 滚动条 + 翻章条；文字层 = #scroll-content 内正文"
))
svg.appendChild(nt2)

with open(OUT, "w", encoding="utf-8") as f:
    f.write(svg.toprettyxml(indent="  "))
print("written", OUT, os.path.getsize(OUT), "bytes")
