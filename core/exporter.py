"""
core/exporter.py — Markdown / PDF 导出模块

职责：
1. 拼装完整 Markdown 文件（YAML Front Matter + 核验摘要 + 8节笔记）
2. 按规则生成文件名：{year}_{LastName}_{KeywordSlug}.md / .pdf
3. 调用 PowerShell 弹出 Windows 原生文件夹选择对话框
4. 自动创建 YYYY-MM/ 月份子文件夹
5. 重名文件追加 _2、_3 后缀，不覆盖
6. export_pdf()：将笔记导出为带中文字体的 PDF 文件
"""

import re
import io
import json
import subprocess
from datetime import datetime
from pathlib import Path


# ══════════════════════════════════════════════════════════════════════════════
# Windows 文件夹选择
# ══════════════════════════════════════════════════════════════════════════════

def pick_folder_windows() -> str | None:
    """
    弹出 Windows 原生文件夹选择对话框（PowerShell + System.Windows.Forms）。
    避免 tkinter 与 Gradio 事件循环冲突。
    返回用户选择路径，取消则返回 None。
    """
    ps_script = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$d = New-Object System.Windows.Forms.FolderBrowserDialog;"
        "$d.Description = '选择笔记保存根目录';"
        "$d.ShowNewFolderButton = $true;"
        "$r = $d.ShowDialog();"
        "if ($r -eq [System.Windows.Forms.DialogResult]::OK) { $d.SelectedPath } else { '' }"
    )
    try:
        result = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", ps_script],
            text=True,
            encoding="utf-8",
            timeout=60,
        ).strip()
        return result if result else None
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════════
# 文件命名
# ══════════════════════════════════════════════════════════════════════════════

def _slugify(title: str, max_words: int = 3) -> str:
    """
    从标题提取 2~3 个核心词，下划线连接，首字母大写。
    过滤常见冠词、介词、连词。
    """
    stop = {
        'a', 'an', 'the', 'of', 'for', 'in', 'on', 'to', 'and',
        'with', 'is', 'are', 'via', 'using', 'from', 'by', 'as',
        'at', 'or', 'be', 'its', 'this', 'that',
    }
    words = re.findall(r'[A-Za-z0-9]+', title)
    keywords = [w for w in words if w.lower() not in stop][:max_words]
    return '_'.join(w.capitalize() for w in keywords) or 'Paper'


def build_filename(metadata: dict) -> str:
    """
    生成文件名：{year}_{FirstAuthorLastName}_{KeywordSlug}.md

    metadata 需含：year, authors(list[str]), title
    """
    year = str(metadata.get("year") or "未知年份")

    authors = metadata.get("authors") or []
    if authors and authors[0].strip():
        # 取第一作者姓（Last Name = 最后一个空格分隔词）
        last_name = authors[0].strip().split()[-1]
    else:
        last_name = "未知作者"

    slug = _slugify(metadata.get("title") or "论文")
    return f"{year}_{last_name}_{slug}.md"


def _unique_path(folder: Path, filename: str) -> Path:
    """处理重名：在文件名末尾追加 _2、_3…，不覆盖已有文件。"""
    stem   = Path(filename).stem
    suffix = Path(filename).suffix
    path   = folder / filename
    counter = 2
    while path.exists():
        path = folder / f"{stem}_{counter}{suffix}"
        counter += 1
    return path


# ══════════════════════════════════════════════════════════════════════════════
# Markdown 内容组装
# ══════════════════════════════════════════════════════════════════════════════

def build_markdown(
    metadata: dict,
    sections: dict,
    crossref_msg: str,
    validate_summary: str,
    tags: list = None,
) -> str:
    """
    拼装完整 Markdown 文件字符串。

    metadata 字段：title, authors, year, venue, doi, crossref_verified
    sections：{1: str, 2: str, ..., 8: str}
    """
    tags = tags or []
    read_date = datetime.now().strftime("%Y-%m-%d")
    authors_yaml = json.dumps(metadata.get("authors") or [], ensure_ascii=False)
    tags_yaml    = json.dumps(tags, ensure_ascii=False)

    front_matter = f"""---
title: "{metadata.get('title', '')}"
authors: {authors_yaml}
year: {metadata.get('year', '')}
venue: "{metadata.get('venue', '')}"
doi: "{metadata.get('doi', '')}"
tags: {tags_yaml}
read_date: "{read_date}"
crossref_verified: {str(bool(metadata.get('crossref_verified', False))).lower()}
---

{crossref_msg}
{validate_summary}

"""
    body = "\n\n".join(sections.get(i, "") for i in range(1, 9))
    return front_matter + body


# ══════════════════════════════════════════════════════════════════════════════
# 文件保存
# ══════════════════════════════════════════════════════════════════════════════

def save_note(root_dir: str, filename: str, content: str) -> str:
    """
    将笔记保存到 root_dir/YYYY-MM/filename。
    返回实际写入的完整路径字符串。
    """
    month_folder = Path(root_dir) / datetime.now().strftime("%Y-%m")
    month_folder.mkdir(parents=True, exist_ok=True)
    save_path = _unique_path(month_folder, filename)
    save_path.write_text(content, encoding="utf-8")
    return str(save_path)


def export_note(
    sections: dict,
    metadata: dict,
    crossref_result: dict,
    validate_summary: str,
    tags: list,
    root_dir: str,
) -> str:
    """
    一站式导出：组装内容 → 生成文件名 → 保存文件。
    返回最终保存路径。
    """
    # CrossRef 数据优先覆盖 AI 提取的元数据
    effective_meta = dict(metadata)
    if crossref_result.get("status") == "verified" and crossref_result.get("data"):
        effective_meta.update(crossref_result["data"])
    effective_meta["crossref_verified"] = (
        crossref_result.get("status") == "verified"
    )

    crossref_msg = crossref_result.get("message", "")
    content  = build_markdown(effective_meta, sections, crossref_msg,
                              validate_summary, tags)
    filename = build_filename(effective_meta)
    return save_note(root_dir, filename, content)


# ══════════════════════════════════════════════════════════════════════════════
# PDF 导出
# ══════════════════════════════════════════════════════════════════════════════

def export_pdf(
    sections: dict,
    metadata: dict,
    crossref_result: dict,
    validate_summary: str,
    tags: list,
    root_dir: str,
) -> str:
    """
    将笔记内容导出为 PDF 文件。
    使用 reportlab 生成，支持中文（内嵌系统字体）。
    返回最终保存路径。
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    )
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    # ── 注册中文字体（优先找系统字体）────────────────────────────────────────
    font_candidates = [
        ("C:/Windows/Fonts/msyh.ttc",    "MSYaHei"),
        ("C:/Windows/Fonts/simhei.ttf",  "SimHei"),
        ("C:/Windows/Fonts/simsun.ttc",  "SimSun"),
        ("C:/Windows/Fonts/STZHONGS.TTF","STZhongSong"),
    ]
    cn_font = None
    for fpath, fname in font_candidates:
        if Path(fpath).exists():
            try:
                pdfmetrics.registerFont(TTFont(fname, fpath))
                cn_font = fname
                break
            except Exception:
                continue
    if cn_font is None:
        raise RuntimeError("未找到系统中文字体，无法生成 PDF。请确认 Windows 字体目录中含 msyh.ttc / simhei.ttf / simsun.ttc 之一。")

    # ── 样式 ─────────────────────────────────────────────────────────────────
    styles = getSampleStyleSheet()
    def _style(name, parent="Normal", **kw):
        s = ParagraphStyle(name, parent=styles[parent], fontName=cn_font, **kw)
        return s

    style_title   = _style("cn_title",   fontSize=18, spaceAfter=12, leading=26, textColor=colors.HexColor("#1a1a2e"))
    style_h1      = _style("cn_h1",      fontSize=14, spaceAfter=6,  spaceBefore=14, leading=20, textColor=colors.HexColor("#16213e"))
    style_h2      = _style("cn_h2",      fontSize=12, spaceAfter=4,  spaceBefore=10, leading=18, textColor=colors.HexColor("#0f3460"))
    style_body    = _style("cn_body",    fontSize=10, spaceAfter=4,  leading=16)
    style_bullet  = _style("cn_bullet",  fontSize=10, spaceAfter=3,  leading=16, leftIndent=16)
    style_code    = _style("cn_code",    fontSize=9,  spaceAfter=4,  leading=14,
                           backColor=colors.HexColor("#f5f5f5"), leftIndent=8, rightIndent=8)
    style_meta    = _style("cn_meta",    fontSize=9,  spaceAfter=2,  leading=14, textColor=colors.grey)

    # ── 构建内容流 ────────────────────────────────────────────────────────────
    effective_meta = dict(metadata)
    if crossref_result.get("status") == "verified" and crossref_result.get("data"):
        effective_meta.update(crossref_result["data"])

    story = []

    # 标题
    title = effective_meta.get("title") or "论文精读笔记"
    story.append(Paragraph(_escape(title), style_title))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#dee2e6")))
    story.append(Spacer(1, 6))

    # 元信息行
    authors = "、".join(effective_meta.get("authors") or [])
    year    = str(effective_meta.get("year") or "")
    venue   = effective_meta.get("venue") or ""
    meta_line = f"作者：{authors}　|　{year}　|　{venue}　|　阅读日期：{datetime.now().strftime('%Y-%m-%d')}"
    story.append(Paragraph(_escape(meta_line), style_meta))
    story.append(Spacer(1, 4))
    if validate_summary:
        story.append(Paragraph(_escape(validate_summary.lstrip("> ")), style_meta))
    story.append(Spacer(1, 10))

    # 各节内容
    for i in range(1, 9):
        text = sections.get(i, "")
        if not text:
            continue
        _render_markdown_to_story(text, story, style_h1, style_h2, style_body, style_bullet, style_code, cn_font)
        story.append(Spacer(1, 8))

    # ── 写文件 ────────────────────────────────────────────────────────────────
    month_folder = Path(root_dir) / datetime.now().strftime("%Y-%m")
    month_folder.mkdir(parents=True, exist_ok=True)
    md_name  = build_filename(effective_meta)          # e.g. 2024_Vaswani_Transformer.md
    pdf_name = md_name[:-3] + ".pdf"
    save_path = _unique_path(month_folder, pdf_name)

    doc = SimpleDocTemplate(
        str(save_path),
        pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm,  bottomMargin=2*cm,
        title=title,
    )
    doc.build(story)
    return str(save_path)


def _escape(text: str) -> str:
    """转义 ReportLab Paragraph 中的特殊字符。"""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))


def _render_markdown_to_story(md_text, story, style_h1, style_h2, style_body, style_bullet, style_code, cn_font):
    """将 Markdown 文本简单解析后追加到 ReportLab story。"""
    from reportlab.platypus import Paragraph, Spacer, HRFlowable
    from reportlab.lib import colors

    lines = md_text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]

        # 水平分隔线
        if re.match(r'^---+$', line.strip()):
            story.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
            i += 1
            continue

        # 标题
        if line.startswith("## "):
            story.append(Paragraph(_escape(line[3:].strip()), style_h1))
            i += 1
            continue
        if line.startswith("### "):
            story.append(Paragraph(_escape(line[4:].strip()), style_h2))
            i += 1
            continue
        if line.startswith("#### "):
            story.append(Paragraph(_escape(line[5:].strip()), style_h2))
            i += 1
            continue

        # 引用块 >
        if line.startswith("> "):
            story.append(Paragraph(_escape(line[2:].strip()), style_bullet))
            i += 1
            continue

        # 无序列表
        if re.match(r'^[\-\*]\s', line):
            story.append(Paragraph("• " + _escape(line[2:].strip()), style_bullet))
            i += 1
            continue

        # 有序列表
        if re.match(r'^\d+\.\s', line):
            story.append(Paragraph(_escape(line).strip(), style_bullet))
            i += 1
            continue

        # 空行
        if not line.strip():
            story.append(Spacer(1, 4))
            i += 1
            continue

        # 普通段落（处理行内 **bold**）
        safe = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', _escape(line.strip()))
        safe = re.sub(r'\*(.+?)\*', r'<i>\1</i>', safe)
        safe = re.sub(r'`([^`]+)`', r'<font face="Courier">\1</font>', safe)
        story.append(Paragraph(safe, style_body))
        i += 1
