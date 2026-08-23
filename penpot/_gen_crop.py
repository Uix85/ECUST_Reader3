# -*- coding: utf-8 -*-
"""生成 02f-toc-collapsed.svg（目录收起态 · 覆盖层）

按用户要求自行构造，与 03 号素材视觉一致：
- 背景色 = 03 的整页背景（白色 #fff）
- 03 里在 y=56 处有蓝色虚线（main-scroll-frame 视口标记框的顶边），
  02F 在同高度（y=56）画一条同样式的蓝色虚线（stroke #3498db，dasharray 8 6，opacity .35）
"""
import os

OUT = os.path.join(os.path.dirname(__file__), "import", "02f-toc-collapsed.svg")
W, H = 290, 1080          # 目录面板大小
DASH_Y = 56               # 与 03 蓝色虚线（视口标记）等高
FONT = "'PingFang SC','Microsoft YaHei','Noto Sans CJK SC',sans-serif"

svg = []
svg.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
           f'viewBox="0 0 {W} {H}" font-family="{FONT}">')
svg.append('  <title>02f-toc-collapsed · 目录收起态（覆盖层 · 白底 + 等高蓝色虚线）</title>')
svg.append('  <g id="side-wrap">')
svg.append(f'    <rect x="0" y="0" width="{W}" height="{H}" fill="#fff"/>')
# 与 03 视口标记虚线等高（y=56）的蓝色虚线，样式与 03 一致
svg.append(f'    <line x1="0" y1="{DASH_Y}" x2="{W}" y2="{DASH_Y}" stroke="#3498db" '
           f'stroke-width="1.5" stroke-dasharray="8 6" opacity="0.35"/>')
svg.append('  </g>')
svg.append('</svg>')

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(svg))
print("written", OUT, len("\n".join(svg)), "bytes")
