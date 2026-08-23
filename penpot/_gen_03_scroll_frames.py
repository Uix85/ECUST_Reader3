# -*- coding: utf-8 -*-
"""生成 03 的多帧滚动模拟素材（Penpot 无「滚动时保持固定」时的替代方案）。

原理：把重组后的 03 克隆成 N 帧，每帧 = 完整 1920×1080 页面，
固定层（browser-bar / 标题栏 / 蓝线以上 / 翻章条）坐标全部不变，
只有 #scroll-content（正文文字层）整体上移 N 像素。

Penpot 用法：每帧一个画板，放在同一个 flow；用一个「滚动/下滚」按钮
依次 Navigate 到下一帧 —— 看起来就是正文文字滚动、其他一概不动。
"""
import os
import xml.dom.minidom as m

SRC = os.path.join(os.path.dirname(__file__), "import", "03-scroll.svg")
OUT_DIR = os.path.join(os.path.dirname(__file__), "import")

# 滚动帧：offset = 正文上移像素（模拟小距离滚动到底）
# 正文从 y≈92 到 y≈1250，视口底 1080 → 最大滚动 ≈ 170
FRAMES = [
    ("03-scroll-frame-1", 0,   "帧1 · 顶部（起始）"),
    ("03-scroll-frame-2", 55,  "帧2 · 正文上移 55px"),
    ("03-scroll-frame-3", 110, "帧3 · 正文上移 110px"),
    ("03-scroll-frame-4", 165, "帧4 · 正文上移 165px（到底）"),
]


def build_frame(base_doc, offset, title_text):
    doc = m.parseString(base_doc.toxml())
    root = doc.documentElement

    # 找 #scroll-content，给它加 transform 整体上移
    sc = None
    for g in root.getElementsByTagName("g"):
        if g.getAttribute("id") == "scroll-content":
            sc = g
            break
    if sc is None:
        raise SystemExit("缺少 #scroll-content")

    if offset:
        sc.setAttribute("transform", f"translate(0 -{offset})")

    # 更新 <title>
    for t in root.getElementsByTagName("title"):
        if t.firstChild and "03" in (t.firstChild.nodeValue or ""):
            t.firstChild.nodeValue = f"03 滚动帧 · {title_text}"
            break
    # 更新底部注释第一行
    for t in root.getElementsByTagName("text"):
        if t.getAttribute("y") == "1050" and t.firstChild:
            t.firstChild.nodeValue = f"03 滚动帧 {title_text}｜固定层全在原位，仅正文上移 {offset}px"
            break
    return doc


base = m.parse(SRC)
for fname, off, desc in FRAMES:
    doc = build_frame(base, off, desc)
    path = os.path.join(OUT_DIR, fname + ".svg")
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc.toprettyxml(indent="  "))
    print("written", path, os.path.getsize(path), "bytes")
print("done")
