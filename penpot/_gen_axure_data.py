# -*- coding: utf-8 -*-
"""生成 Axure 原型素材数据包（Phase 0 辅助工具）。

从本地阅读器 API 抓取《精神现象学》第一章/第二章的完整正文与目录树，
输出为 markdown 数据包，供 reforeAI 爬取素材时对照 / Figma 文字层直接使用。

用法: python penpot/_gen_axure_data.py
输出: docs/axure-material-data.md
"""
import json
import re
import sys
import urllib.parse
import urllib.request

BOOK_ID = "精神现象学 黑格尔着 (精神现象学 黑格尔着.txt) (z-library.sk, 1lib.sk, z-lib.sk)_data"
BASE = "http://127.0.0.1:8123"
OUT = "docs/axure-material-data.md"


def fetch(path: str) -> dict:
    url = BASE + path
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def html_to_text(html: str) -> str:
    """HTML → 纯文本（保留段落结构，标题用 [方括号] 标记）。"""
    # 提取标题锚点 span（txt-hdr-*）
    text = html
    # 标题 span 转标记
    text = re.sub(r'<span id="([^"]+)"></span>', r'[ANCHOR:\1]', text)
    # 段落/换行
    text = re.sub(r'<p>', '\n', text)
    text = re.sub(r'</p>', '\n', text)
    text = re.sub(r'<br\s*/?>', '\n', text)
    # 去其余标签
    text = re.sub(r'<[^>]+>', '', text)
    # 去多余空白
    lines = [ln.strip() for ln in text.split('\n')]
    lines = [ln for ln in lines if ln]
    return '\n'.join(lines)


def main():
    print(f"抓取 {BOOK_ID} ...")
    ch1 = fetch(f"/api/full_chapter/{urllib.parse.quote(BOOK_ID)}/1")
    ch2 = fetch(f"/api/full_chapter/{urllib.parse.quote(BOOK_ID)}/2")
    total = ch1.get("total_chapters", 9)

    t1 = html_to_text(ch1["html"])
    t2 = html_to_text(ch2["html"])

    # 目录树（从阅读页 DOM 获取，这里用已知结构）
    toc = [
        ("序言：论科学认识", 8, ["一、当代的科学任务", "二、从意识到科学的发展过程"]),
        ("第一章　感性确定性；这一个和意谓", 0, []),
        ("第二章　知觉；事物和幻觉", 3, ["一、事物的简单概念", "二、事物的矛盾概念", "三、朝向无条件的普遍性和知性领域的发展运动"]),
        ("第三章　力和知性；现象和超感官世界", 12, ["一、力与力的交互作用", "二、力的内在本质", "三、无限性"]),
        ("第四章　意识自身确定性的真理性", 17, ["Ⅰ．自我意识自身", "Ⅱ．生命", "Ⅲ．自我与欲望", "一、自我意识的独立与依赖；主人与奴隶", "二、自我意识的自由；斯多葛主义、怀疑主义和苦恼的意识"]),
        ("第五章　理性的确定性与真理性", 49, ["Ⅰ．唯心主义", "Ⅱ．范畴", "Ⅲ．空虚的主观唯心主义的知识", "一、观察的理性", "二、理性的自我意识通过其自身的活动而实现", "三、自在自为地实在的个体性"]),
        ("第六章　精神", 67, ["一、真实的精神；伦理", "二、自身异化了的精神；教化", "三、对其自身具有确定性的精神、道德"]),
        ("第七章　宗教", 31, ["一、自然宗教", "二、艺术宗教", "三、天启宗教"]),
        ("第八章　绝对知识", 3, ["一、确知自己是存在的“自我”的简单内容", "二、科学即对自我自身的概念式的理解", "三、达到概念式理解的精神向着特定存在的直接性的返回"]),
    ]

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("# Axure 原型素材数据包 — 《精神现象学》（黑格尔著 贺麟等译）\n\n")
        f.write(f"> 生成时间：2026-08-23 ｜ 数据源：本地阅读器 API（book_id=`{BOOK_ID}`）\n")
        f.write(f"> 全书共 **{total}** 个顶层章。演示范围：**第一章（感性确定性）** + **第二章（知觉）**。\n\n")

        f.write("## 一、目录树结构（9 个顶层项）\n\n")
        f.write("| # | 顶层章 | 子节数 | 子节标题 |\n|---|---|---|---|\n")
        for i, (title, n, secs) in enumerate(toc):
            sec_str = "；".join(secs) if secs else "—（无子节）"
            f.write(f"| {i} | {title} | {n} | {sec_str} |\n")
        f.write("\n> 注意：**第一章无子节**（txt 版未检测到子标题），目录折叠演示以第二章的 3 个子节为主。\n")
        f.write("> 第二章子节均为 d1 层级（一级缩进），无更深层。\n\n")

        f.write("## 二、第一章正文（完整，纯文本）\n\n")
        f.write(f"### 第一章　感性确定性；这一个和意谓（{len(t1)} 字符）\n\n")
        f.write("```text\n")
        f.write(t1)
        f.write("\n```\n\n")

        f.write("## 三、第二章正文（完整，纯文本）\n\n")
        f.write(f"### 第二章　知觉；事物和幻觉（{len(t2)} 字符）\n\n")
        f.write("```text\n")
        f.write(t2)
        f.write("\n```\n\n")

        f.write("## 四、正文锚点（滚动高亮阈值用）\n\n")
        f.write("| 章 | 锚点 | 对应标题 |\n|---|---|---|\n")
        f.write("| 第一章 | txt-hdr-unk3html-0 | 第一章　感性确定性；这一个和意谓（章首） |\n")
        f.write("| 第二章 | txt-hdr-unk4html-4 | 一、事物的简单概念 |\n")
        f.write("| 第二章 | txt-hdr-unk4html-9 | 二、事物的矛盾概念 |\n")
        f.write("| 第二章 | txt-hdr-unk4html-20 | 三、朝向无条件的普遍性和知性领域的发展运动 |\n\n")

        f.write("## 五、几何基线（真实阅读器实测）\n\n")
        f.write("| 元素 | 值 |\n|---|---|\n")
        f.write("| 浏览器栏 | 52px 宽 |\n")
        f.write("| 目录侧栏 | 280px 宽（可收起 76px） |\n")
        f.write("| 正文列 | x≈574..1274（max-width 700px，左 1/4 偏移） |\n")
        f.write("| 章标题 | 24px 粗体，吸顶 sticky |\n")
        f.write("| 正文 | 15.5px / 行高 28px |\n")
        f.write("| 目录章行 | 14.4px / 行高 19.44px |\n")
        f.write("| 目录节行 d1 | 13.6px / 缩进 8px |\n")
        f.write("| 底部翻章条 | 固定 bottom:20px 居中，◀ 2/9 ▶ |\n")

    print(f"written {OUT} ({len(open(OUT, encoding='utf-8').read())} bytes)")


if __name__ == "__main__":
    main()