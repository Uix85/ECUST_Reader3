# -*- coding: utf-8 -*-
"""重新生成整页版「02 阅读页 · 目录展开态」（1920×1080）。

- side-wrap：真实目录数据渲染（复用 _gen_toc 逻辑，整页里 x 偏移 +52）
- browser-bar / main / ch-nav：整页其余组件（从既有设计内嵌）
"""
import os
import sys

sys.path.insert(0, r"d:/Programs/reader3")
sys.path.insert(0, os.path.dirname(__file__))

import _gen_toc  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "02-reader-toc.svg")

BROWSER_BAR = """  <g id="browser-bar">
    <title>浏览器外壳侧边栏（52px）</title>
    <rect x="0" y="0" width="52" height="1080" fill="#eceff1"/>
    <line x1="51.5" y1="0" x2="51.5" y2="1080" stroke="#d5d9dd"/>
    <g id="bb-home">
      <title>主页 Library</title>
      <rect x="10" y="10" width="32" height="32" rx="6" fill="#fff" stroke="#d5d9dd"/>
      <text x="26" y="31" text-anchor="middle" font-size="14" font-weight="bold" fill="#4a5560">L</text>
    </g>
    <line x1="10" y1="54" x2="42" y2="54" stroke="#d5d9dd"/>
    <g id="bb-toc">
      <title>目录（激活 · 点击折叠/展开侧栏）</title>
      <rect x="10" y="64" width="32" height="32" rx="6" fill="#5b9bd5"/>
      <path d="M3 6h18v2H3V6zm0 5h18v2H3v-2zm0 5h18v2H3v-2z" transform="translate(18 72) scale(0.6667)" fill="#fff"/>
    </g>
    <g id="bb-aux">
      <title>辅助键（跳转笔记页）</title>
      <rect x="10" y="102" width="32" height="32" rx="6" fill="#fff" stroke="#d5d9dd"/>
      <path d="M19 9l1.25-2.75L23 5l-2.75-1.25L19 1l-1.25 2.75L15 5l2.75 1.25L19 9zm-7.5.5L9 4 6.5 9.5 1 12l5.5 2.5L9 20l2.5-5.5L17 12l-5.5-2.5zM19 15l-1.25 2.75L15 19l2.75 1.25L19 23l1.25-2.75L23 19l-2.75-1.25L19 15z" transform="translate(18 110) scale(0.6667)" fill="#4a5560"/>
    </g>
    <g id="bb-concept">
      <title>解释笔（开关划词）</title>
      <rect x="10" y="140" width="32" height="32" rx="6" fill="#fff" stroke="#d5d9dd"/>
      <path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.39-.39-1.02-.39-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z" transform="translate(18 148) scale(0.6667)" fill="#4a5560"/>
    </g>
  </g>"""

MAIN_BLOCK = """  <g id="main">
    <title>正文区（#main）</title>
    <g id="chapter-view">
      <title>章视图（max-width 700 + padding 40）</title>
      <g id="ch-title-bar">
        <title>章标题栏（position:sticky 吸顶）</title>
        <rect x="574" y="0" width="700" height="56" fill="#fff"/>
        <line x1="574" y1="56" x2="1274" y2="56" stroke="#3498db" stroke-width="2"/>
        <text x="574" y="36" font-size="24" font-weight="bold" fill="#1a1a2e">导言：作为科学体系第一部分的《精神现象学》的任务</text>
      </g>
      <g id="ch-content">
        <title>正文内容（15.5px / 行高 28px）</title>
        <g id="h1-chapter">
          <title>章标题（h1）</title>
          <text x="574" y="92" font-size="24" font-weight="bold" fill="#1a1a2e">导言：作为科学体系第一部分的《精神现象学》的任务</text>
        </g>
        <g id="p-1">
          <title>第 1 段</title>
          <text x="574" y="128">下面的讲座是对黑格尔著作的解释，我们都很熟知这部被冠以《</text>
          <text x="574" y="154">精神现象学》标题的著作。通过对标题及其各种不同文稿措辞的</text>
          <text x="574" y="180">讲解，我们力求先对这部著作做一个无法回避的临时性说明，以</text>
          <text x="574" y="206">便随即着手进行解释，更确切地说，绕过长篇的序言和导言，从</text>
          <text x="574" y="232">事实本身开始的地方进行解释。</text>
        </g>
        <g id="p-2">
          <title>第 2 段</title>
          <text x="574" y="268">这部著作通行的标题“精神现象学”当然不是原初的标题；自从</text>
          <text x="574" y="294">这个标题在1832年之后被黑格尔的朋友们采纳以来，的确对著</text>
          <text x="574" y="320">作产生了明显的字面影响。</text>
        </g>
        <g id="p-3">
          <title>第 3 段</title>
          <text x="574" y="356">《精神现象学》首次出版于1807年，完整标题是“科学的体系，</text>
          <text x="574" y="382">第一部分，精神现象学”；著作的内容只能从它的这种内在任务</text>
          <text x="574" y="408">出发才能得到把握。</text>
        </g>
        <g id="h2-1">
          <title>节标题：第一节 现象学体系和哲学全书体系</title>
          <text x="574" y="456" font-size="20" font-weight="bold" fill="#333">第一节 现象学体系和哲学全书体系</text>
        </g>
        <g id="p-4">
          <title>第 4 段</title>
          <text x="574" y="492">科学的体系在何种程度上要求《精神现象学》作为第一部分？这个</text>
          <text x="574" y="518">副标题意味着什么？在我们回答这些问题之前必须提醒，尽管这个</text>
          <text x="574" y="544">副标题后来变成唯一的标题，但它并不是完整的。</text>
        </g>
        <g id="h2-2">
          <title>节标题：第二节 黑格尔对科学体系的理解</title>
          <text x="574" y="592" font-size="20" font-weight="bold" fill="#333">第二节 黑格尔对科学体系的理解</text>
        </g>
        <g id="p-5">
          <title>第 5 段</title>
          <text x="574" y="628">“意识经验的科学”这个表述，此后以“精神现象学的科学”的形式</text>
          <text x="574" y="654">流传，并最终简化成了流行的“精神现象学”。</text>
        </g>
        <g id="h2-3">
          <title>节标题：第三节 标明体系第一部分特征的两个标题的意义</title>
          <text x="574" y="702" font-size="20" font-weight="bold" fill="#333">第三节 标明体系第一部分特征的两个标题的意义</text>
        </g>
        <g id="p-6">
          <title>第 6 段</title>
          <text x="574" y="738">作为“意识经验的科学”，著作展示意识从最直接的感性确定出发、</text>
          <text x="574" y="764">逐级上升到绝对知识的内在必然过程。</text>
        </g>
        <g id="h2-4">
          <title>节标题：第四节 《精神现象学》作为体系之第一部分的内在任务</title>
          <text x="574" y="812" font-size="20" font-weight="bold" fill="#333">第四节 《精神现象学》作为体系之第一部分的内在任务</text>
        </g>
        <g id="p-7">
          <title>第 7 段</title>
          <text x="574" y="848">其内在任务，在于把“实体即主体”的原则落实到意识的全部形态之</text>
          <text x="574" y="874">中，使其成为体系的第一部分。</text>
        </g>
      </g>
    </g>
  </g>"""

CH_NAV = """  <g id="ch-nav">
    <title>底部浮动翻章条</title>
    <rect x="926" y="1018" width="400" height="42" rx="21" fill="#fff" stroke="#dee2e6"/>
    <circle cx="952" cy="1039" r="15" fill="#3498db"/>
    <text x="952" y="1045" text-anchor="middle" font-size="15" fill="#fff">◀</text>
    <text x="1118" y="1044" text-anchor="middle" font-size="14" fill="#495057">3 / 11</text>
    <circle cx="1284" cy="1039" r="15" fill="#3498db"/>
    <text x="1284" y="1045" text-anchor="middle" font-size="15" fill="#fff">▶</text>
  </g>"""

NOTES = """  <text x="52" y="1050" font-size="12" fill="#adb5bd">素材 02 · 阅读页 · 目录展开态（真实数据）｜用途：折叠演示基准板，章/小节全展开</text>
  <text x="52" y="1068" font-size="12" fill="#adb5bd">接线：章折叠钮→02b · 小节三角→02d · 侧栏→02c · 标注→03 · 滚动→06</text>"""

# ── 生成真实 side-wrap（导言展开 + 第二节展开 = 全展开基准板）──
side_svg = _gen_toc.gen_svg("page-side-wrap", "整页 side-wrap", ["导言"], ["第二节"])
import xml.dom.minidom as minidom  # noqa: E402
side_doc = minidom.parseString(side_svg)
side_inner = None
for el in side_doc.getElementsByTagName("g"):
    if el.getAttribute("id") == "side-wrap":
        side_inner = el.toxml()
        break
if side_inner is None:
    raise SystemExit("side-wrap not found")
side_wrap = (f'  <g transform="translate(52 0)">\n'
             f'    <title>目录侧栏（真实数据 · 290px 展开态）</title>\n'
             f'    {side_inner}\n'
             f'  </g>')

svg = []
svg.append('<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" '
           'viewBox="0 0 1920 1080" font-family="\'PingFang SC\',\'Microsoft YaHei\',\'Noto Sans CJK SC\',sans-serif">')
svg.append('  <title>02 阅读页 · 目录展开态（真实数据）</title>')
svg.append('  <rect width="1920" height="1080" fill="#fff"/>')
svg.append('  <g id="page">')
svg.append('    <title>白色背景页（整页容器 · 对应 body）</title>')
svg.append(BROWSER_BAR)
svg.append(side_wrap)
svg.append(MAIN_BLOCK)
svg.append(CH_NAV)
svg.append('  </g>')
svg.append(NOTES)
svg.append('</svg>')

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(svg))
print("written", OUT, len("\n".join(svg)), "bytes")
