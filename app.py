"""
app.py — 论文精读助手 Gradio 主界面

工作流：上传 PDF → 分8段 AI 生成精读笔记 → 实时流式预览 → 导出 Markdown

布局：
  左栏：浏览器原生 PDF 预览（<embed>，无需额外依赖）
  右栏：流式 Markdown 笔记实时渲染（gr.Markdown）
  底部：操作按钮 + 状态栏 + 历史记录面板
"""

import os
import re
import sys
import shutil
from pathlib import Path

# --windowed 模式下 stdout/stderr 为 None，uvicorn 日志会崩溃，提前重定向
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

# PyInstaller 打包后 __file__ 指向临时解压目录，运行时数据应放在 exe 同级目录
_BASE_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent

# 切换工作目录到 exe 所在目录，确保 core/ 各模块的相对路径（data/）写在正确位置
os.chdir(_BASE_DIR)

import gradio as gr
from dotenv import load_dotenv

load_dotenv(_BASE_DIR / ".env")

from core.pdf_parser import extract_text_with_pages, split_sections
from core.ai_engine import analyze_paper, load_progress
from core.validator import verify_crossref, cross_validate
from core.exporter import export_note, export_pdf, pick_folder_windows
from core.history import (
    init_data_dir,
    add_record,
    update_record,
    get_all,
    get_incomplete_records,
)
from prompts.note_template import SYSTEM_PROMPT, build_prompts

# PDF 路由所需（注册到 demo.app 上，在 launch 之前执行）
from fastapi.responses import Response

_current_pdf_path: str | None = None


# ── 启动初始化 ─────────────────────────────────────────────────────────────────
init_data_dir()

_ENV_PATH = _BASE_DIR / ".env"
_FIRST_RUN = not os.getenv("ANTHROPIC_API_KEY")

_WARNINGS: list = []
if not os.getenv("ANTHROPIC_API_KEY"):
    pass  # 首次运行由向导处理，不再显示警告
if not shutil.which("tesseract"):
    _WARNINGS.append("⚠️ 未检测到 Tesseract-OCR，扫描版 PDF 将无法 OCR 处理。")
if not shutil.which("pdftoppm"):
    _WARNINGS.append("⚠️ 未检测到 Poppler（pdftoppm），扫描版 PDF 的图像转换将失败，请安装 Poppler 并加入 PATH。")

_incomplete_records = get_incomplete_records()
if _incomplete_records:
    _WARNINGS.append(
        f"📌 发现 {len(_incomplete_records)} 个未完成的断点任务，"
        "上传对应 PDF 后点击「继续」可续传。"
    )


# ── 全局分析状态（每次分析会话刷新） ──────────────────────────────────────────
_state: dict = {
    "pdf_path":         None,
    "sections_text":    {},    # pdf_parser.split_sections() 的返回值
    "sections":         {},    # {1: str, …, 8: str}  AI 输出的各段笔记
    "crossref_result":  {"status": "not_found", "data": None, "message": ""},
    "validate_summary": "",    # 数值核验摘要行
    "metadata":         {},    # 从段1提取 + CrossRef 覆盖后的论文元数据
    "record_id":        None,  # 当前论文在 history.json 的 id
}


# ══════════════════════════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════════════════════════

def _pdf_viewer_html(pdf_path: str | None) -> str:
    """生成左栏 PDF 预览 HTML（通过 FastAPI 同源路由，无 CORS 限制）。"""
    global _current_pdf_path
    if not pdf_path:
        _current_pdf_path = None
        return (
            '<div style="display:flex;align-items:center;justify-content:center;'
            'height:640px;background:#f8f9fa;border-radius:8px;'
            'color:#6c757d;font-size:1.1rem;border:2px dashed #dee2e6;">'
            "📄 请上传论文 PDF</div>"
        )
    _current_pdf_path = pdf_path
    name = Path(pdf_path).name
    import time
    ts = int(time.time())
    return (
        '<div style="height:660px;border:1px solid #dee2e6;'
        'border-radius:8px;overflow:hidden;">'
        f'<embed src="/pdf_serve?t={ts}" '
        'type="application/pdf" width="100%" height="100%">'
        "</div>"
        f'<p style="font-size:0.8rem;color:#6c757d;margin:4px 0 0;">📎 {name}</p>'
    )


def _extract_metadata_from_section1(text: str) -> dict:
    """从段1的 Markdown 表格中提取论文基本元数据。"""
    meta: dict = {}
    patterns = {
        "title":       r"\|\s*\*\*论文标题\*\*\s*\|\s*(.+?)\s*\|",
        "year_str":    r"\|\s*\*\*发表年份\*\*\s*\|\s*(\d{4})\s*\|",
        "doi":         r"\|\s*\*\*来源链接/DOI\*\*\s*\|\s*(.+?)\s*\|",
        "venue":       r"\|\s*\*\*发表期刊/会议\*\*\s*\|\s*(.+?)\s*\|",
        "authors_raw": r"\|\s*\*\*作者\*\*\s*\|\s*(.+?)\s*\|",
    }
    for key, pat in patterns.items():
        m = re.search(pat, text)
        if m:
            meta[key] = m.group(1).strip()

    # 作者字符串 → list
    raw = meta.pop("authors_raw", "")
    if raw:
        meta["authors"] = [a.strip() for a in re.split(r"[，,、]", raw) if a.strip()]

    # year 转 int
    if "year_str" in meta:
        try:
            meta["year"] = int(meta.pop("year_str"))
        except ValueError:
            meta.pop("year_str", None)

    return meta


def _extract_tags_from_section8(text: str) -> list:
    """从段8的 Notion callout 行提取标签列表。"""
    m = re.search(r"📌\s*(.*)", text)
    if m:
        return re.findall(r"`#([^`]+)`", m.group(1))
    return []


def _history_html() -> str:
    """生成历史记录 HTML 表格（最多显示 30 条）。"""
    records = get_all()
    if not records:
        return "<p style='color:#6c757d;padding:12px;'>暂无历史记录</p>"

    status_map = {
        "done":       "✅ 已完成",
        "incomplete": "⏸ 断点",
        "processing": "⏳ 处理中",
        "failed":     "❌ 失败",
    }
    rows = []
    for r in records[:30]:
        dt    = r.get("created_at", "")[:16].replace("T", " ")
        st    = status_map.get(r.get("status", ""), r.get("status", ""))
        title = (r.get("title") or "未知标题")[:36]
        cr    = "✅" if r.get("crossref_verified") else "—"
        rows.append(
            f"<tr style='border-bottom:1px solid #f0f0f0;'>"
            f"<td style='padding:6px 10px;'>{title}</td>"
            f"<td style='padding:6px 10px;text-align:center;'>{dt}</td>"
            f"<td style='padding:6px 10px;text-align:center;'>{st}</td>"
            f"<td style='padding:6px 10px;text-align:center;'>{cr}</td>"
            f"</tr>"
        )
    return (
        "<table style='width:100%;border-collapse:collapse;font-size:0.88rem;'>"
        "<thead><tr style='background:#f1f3f5;font-weight:600;'>"
        "<th style='padding:6px 10px;text-align:left;'>论文标题</th>"
        "<th style='padding:6px 10px;'>处理日期</th>"
        "<th style='padding:6px 10px;'>状态</th>"
        "<th style='padding:6px 10px;'>CrossRef</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


# ══════════════════════════════════════════════════════════════════════════════
# 核心分析 Generator
# ══════════════════════════════════════════════════════════════════════════════

# 各段生成时状态栏的显示文案
_STEP_LABELS = {
    1: "正在提取基本信息…",
    2: "正在分析研究背景…",
    3: "正在解析方法详解…",
    4: "正在整理实验数据…",
    5: "正在生成结论与局限…",
    6: "正在生成个人思考…",
    7: "正在提取参考文献…",
    8: "正在提取关键词标签…",
}


def run_analysis(pdf_file, resume: bool = False):
    """
    主分析 Generator，连接到「开始分析」/「继续」按钮的 click 事件。

    Yields: (note_markdown: str, status_text: str)

    Gradio 4.x streaming 要求每次 yield 完整累积字符串，而不是增量片段。
    """
    global _state

    # ── 输入检查 ──────────────────────────────────────────────────────────────
    if pdf_file is None:
        yield "⚠️ 请先上传 PDF 文件。", "等待上传"
        return

    pdf_path = str(pdf_file)
    _state["pdf_path"] = pdf_path

    yield "**⏳ 正在解析 PDF 文字层…**\n\n", "解析 PDF 中…"

    # ── 阶段1：PDF 解析 ───────────────────────────────────────────────────────
    try:
        pages         = extract_text_with_pages(pdf_path)
        sections_text = split_sections(pages)
    except Exception as e:
        yield (
            f"❌ **PDF 解析失败**\n\n```\n{e}\n```\n\n"
            "请确认文件未加密，或安装 Tesseract-OCR 后重试。",
            "解析失败",
        )
        return

    # 重置全局状态
    _state.update({
        "sections_text":    sections_text,
        "sections":         {},
        "crossref_result":  {"status": "not_found", "data": None, "message": ""},
        "validate_summary": "",
        "metadata":         {},
    })

    # ── 阶段2：断点续传（若 resume=True）────────────────────────────────────
    resume_from    = 0
    accumulated    = ""          # 右栏累积 Markdown 字符串

    if resume:
        prog = load_progress(pdf_path)
        if prog:
            resume_from = prog.get("last_completed_section", 0)
            for i in range(1, resume_from + 1):
                txt = prog["sections"].get(str(i), "")
                if txt:
                    _state["sections"][i] = txt
                    # 只恢复状态，不预填 accumulated
                    # analyze_paper 内部会再 yield 一遍已完成段的内容
            yield "", f"续传：已恢复前 {resume_from} 段，继续第 {resume_from + 1} 段…"
        else:
            resume = False   # 无进度文件，回退全新分析

    # ── 阶段3：构建初始 Prompts ───────────────────────────────────────────────
    # 段6需要前5段摘要（此时为空，在段5完成后就地更新 prompts[6]）
    prompts = build_prompts(sections_text, crossref_data=None, previous_summary="")

    # 若断点续传且段1~5已全部完成，立即填充段6的摘要
    if resume and resume_from >= 5:
        prev_summary = "\n\n".join(_state["sections"].get(i, "") for i in range(1, 6))
        prompts[6]   = build_prompts(sections_text, None, prev_summary)[6]

    # ── 阶段4：记录历史 ───────────────────────────────────────────────────────
    record_id = add_record(
        title     = Path(pdf_path).stem[:40],
        file_path = pdf_path,
        status    = "processing",
    )
    _state["record_id"] = record_id

    # ── 阶段5：流式调用 analyze_paper ─────────────────────────────────────────
    current_sec  = 0          # 当前正在处理的段号
    section_bufs: dict = {}   # {段号: 已累积文本}

    try:
        for sec_num, chunk in analyze_paper(
            pdf_path      = pdf_path,
            sections_text = sections_text,
            system_prompt = SYSTEM_PROMPT,
            prompts       = prompts,
            resume_from   = resume_from,
        ):
            # ── 检测段切换：前一段刚完成 ──────────────────────────────────────
            if sec_num != current_sec and 0 < current_sec < 9:
                finished = section_bufs.get(current_sec, "")
                _state["sections"][current_sec] = finished

                # 段1完成 → CrossRef 验证
                if current_sec == 1:
                    meta = _extract_metadata_from_section1(finished)
                    _state["metadata"] = meta
                    cr   = verify_crossref(
                        doi   = meta.get("doi"),
                        title = meta.get("title"),
                    )
                    _state["crossref_result"] = cr
                    if cr.get("data"):
                        _state["metadata"].update(cr["data"])
                    # 将验证结果消息追加到右栏
                    accumulated += f"\n\n> {cr['message']}\n\n"
                    yield accumulated, "CrossRef 验证完成"

                # 段4完成 → 数值交叉核验
                if current_sec == 4:
                    flagged, summary = cross_validate(
                        finished,
                        sections_text.get("experiment", ""),
                    )
                    _state["sections"][4]     = flagged
                    _state["validate_summary"] = summary
                    accumulated += f"\n\n{summary}\n\n"
                    yield accumulated, "数值核验完成"

                # 段5完成 → 更新段6 Prompt（注入前5段摘要，就地修改 prompts 字典）
                if current_sec == 5:
                    prev_summary = "\n\n".join(
                        _state["sections"].get(i, "") for i in range(1, 6)
                    )
                    prompts[6] = build_prompts(
                        sections_text,
                        _state["crossref_result"].get("data"),
                        prev_summary,
                    )[6]

            # ── 更新当前段缓冲（过滤进度标记，不存入正文）─────────────────────
            _is_marker = chunk.startswith("\n\n**▶")
            if sec_num < 9 and not _is_marker:
                section_bufs.setdefault(sec_num, "")
                section_bufs[sec_num] += chunk

            current_sec  = sec_num
            accumulated += chunk

            # ── 更新状态栏文案 & 推送 ─────────────────────────────────────────
            if sec_num == 9:
                status = "✅ 分析完成！"
            else:
                label  = _STEP_LABELS.get(sec_num, f"第 {sec_num} 节")
                status = f"{label} ({sec_num}/8)"

            yield accumulated, status

    except Exception as e:
        update_record(record_id, status="failed")
        yield accumulated + f"\n\n❌ **分析出错：** `{e}`", "分析出错"
        return

    # ── 收尾：保存最后一段，更新历史记录 ──────────────────────────────────────
    # 段8在 sec_num==9（完成信号）切换时才被写入 _state，需补存
    for i in range(1, 9):
        if i in section_bufs and i not in _state["sections"]:
            _state["sections"][i] = section_bufs[i]

    # 将第8节标签写回第1节关键词行
    tags = _extract_tags_from_section8(_state["sections"].get(8, ""))
    if tags:
        tags_str = " ".join(f"`#{t}`" for t in tags)
        sec1_old = _state["sections"].get(1, "")
        sec1_new = re.sub(
            r'(\|\s*\*\*关键词\*\*\s*\|)([^|\n]*)(\|)',
            rf'\1 {tags_str} \3',
            sec1_old,
        )
        if sec1_new != sec1_old:
            _state["sections"][1] = sec1_new
            accumulated = accumulated.replace(sec1_old, sec1_new, 1)
            yield accumulated, "✅ 分析完成！"

    # 从 validate_summary 文本中提取实际不符数值个数
    _m = re.search(r"(\d+)\s*个与原文不符", _state.get("validate_summary", ""))
    flagged_count = int(_m.group(1)) if _m else 0
    update_record(
        record_id,
        status            = "done",
        crossref_verified = (_state["crossref_result"].get("status") == "verified"),
        num_values_flagged= flagged_count,
    )


def do_resume(pdf_file):
    """「继续」按钮：从断点续传（复用 run_analysis）。"""
    yield from run_analysis(pdf_file, resume=True)


# ══════════════════════════════════════════════════════════════════════════════
# 其他按钮处理函数
# ══════════════════════════════════════════════════════════════════════════════

def do_export():
    """「导出 .md」：弹出 PowerShell 文件夹选择框并保存文件。"""
    if not _state.get("sections"):
        return "⚠️ 请先完成分析。"
    root_dir = pick_folder_windows()
    if not root_dir:
        return "⚠️ 已取消导出。"
    try:
        tags  = _extract_tags_from_section8(_state["sections"].get(8, ""))
        saved = export_note(
            sections        = _state["sections"],
            metadata        = _state["metadata"],
            crossref_result = _state["crossref_result"],
            validate_summary= _state["validate_summary"],
            tags            = tags,
            root_dir        = root_dir,
        )
        if _state.get("record_id"):
            update_record(_state["record_id"], output_file=saved)
        return f"✅ 已导出：{saved}"
    except Exception as e:
        return f"❌ 导出失败：{e}"


def do_export_pdf():
    """「导出 PDF」：将笔记导出为带中文字体的 PDF 文件。"""
    if not _state.get("sections"):
        return "⚠️ 请先完成分析。"
    root_dir = pick_folder_windows()
    if not root_dir:
        return "⚠️ 已取消导出。"
    try:
        tags  = _extract_tags_from_section8(_state["sections"].get(8, ""))
        saved = export_pdf(
            sections        = _state["sections"],
            metadata        = _state["metadata"],
            crossref_result = _state["crossref_result"],
            validate_summary= _state["validate_summary"],
            tags            = tags,
            root_dir        = root_dir,
        )
        return f"✅ PDF 已导出：{saved}"
    except Exception as e:
        return f"❌ PDF 导出失败：{e}"


def do_get_full_text() -> str:
    """「复制全文」：返回完整笔记 Markdown，显示在带复制按钮的 Code 框内。"""
    sections = _state.get("sections", {})
    if not sections:
        return "（暂无笔记内容，请先完成分析）"
    return "\n\n".join(
        sections.get(i, "") for i in range(1, 9) if sections.get(i)
    )


def do_update_pdf_viewer(pdf_file) -> str:
    """上传 PDF 后更新左栏预览。"""
    return _pdf_viewer_html(str(pdf_file) if pdf_file else None)


def do_refresh_history() -> str:
    return _history_html()


# ══════════════════════════════════════════════════════════════════════════════
# Gradio 界面定义
# ══════════════════════════════════════════════════════════════════════════════

_CSS = """
/* 隐藏 Gradio 默认页脚 */
footer { display: none !important; }

/* 左栏 PDF 预览区 */
#pdf-col { min-height: 680px; }

/* 右栏笔记：固定高度 660px，内部独立滚动 */
#note-col {
    height: 660px !important;
    max-height: 660px !important;
    overflow-y: auto !important;
    overflow-x: hidden !important;
    border: 1px solid #dee2e6;
    border-radius: 8px;
    padding: 0 12px 16px !important;
    box-sizing: border-box;
}
/* 取消内部所有子容器的高度限制，让滚动由外层 #note-col 控制 */
#note-col > div,
#note-col .block,
#note-col .wrap,
#note-col .prose {
    height: auto !important;
    max-height: none !important;
    overflow: visible !important;
}

/* 状态栏样式 */
#status-bar textarea {
    font-size: 0.85rem;
    color: #495057;
    background: #f8f9fa;
    border-radius: 4px;
    padding: 4px 10px;
}
"""

with gr.Blocks(title="论文精读助手") as demo:

    # ── 页面标题 ───────────────────────────────────────────────────────────────
    gr.Markdown("## 📄 论文精读助手")

    with gr.Tabs(selected="setup" if _FIRST_RUN else "main") as tabs:

        # ══════════════════════════════════════════════════════════════════════
        # Tab 1：首次配置向导
        # ══════════════════════════════════════════════════════════════════════
        with gr.Tab("⚙️ 初始配置", id="setup"):
            gr.Markdown("""
### 欢迎使用论文精读助手

首次使用需要完成以下配置，配置完成后即可开始使用。

---

#### 第一步：填写 API Key

""")
            setup_key_input = gr.Textbox(
                label       = "Anthropic API Key",
                placeholder = "请输入 API Key",
                type        = "password",
                info        = "密钥仅保存在本地 .env 文件中，不会上传到任何服务器",
            )
            setup_base_url_input = gr.Textbox(
                label       = "中转站地址（可选）",
                placeholder = "https://your-relay.example.com",
                info        = "使用第三方中转站时填写；直连官方 API 请留空",
            )
            gr.Markdown("""
---

#### 第二步：安装系统依赖（可选，仅扫描版 PDF 需要）

| 工具 | 用途 | 下载地址 |
|------|------|--------|
| Tesseract-OCR v5 | 扫描版 PDF 文字识别 | [github.com/UB-Mannheim/tesseract](https://github.com/UB-Mannheim/tesseract/wiki) |
| Poppler for Windows | PDF 图像转换 | [github.com/oschwartz10612/poppler-windows](https://github.com/oschwartz10612/poppler-windows) |

> 如果只使用电子版 PDF（可以直接选中文字的），可以跳过第二步。

---
""")
            setup_save_btn = gr.Button("✅ 保存配置并开始使用", variant="primary")
            setup_msg      = gr.Markdown(visible=False)

        # ══════════════════════════════════════════════════════════════════════
        # Tab 2：主功能界面
        # ══════════════════════════════════════════════════════════════════════
        with gr.Tab("📖 开始精读", id="main"):

            # ── 启动警告（Tesseract / Poppler 缺失） ──────────────────────────
            if _WARNINGS:
                gr.Markdown("\n\n".join(f"> {w}" for w in _WARNINGS))

    # ── 文件上传区 ────────────────────────────────────────────────────────────
            pdf_upload = gr.File(
                label      = "📂 拖放或点击上传论文 PDF",
                file_types = [".pdf"],
                type       = "filepath",
            )

            # ── 主面板：左栏 PDF + 右栏笔记 ──────────────────────────────────────────
            with gr.Row(equal_height=False):
                with gr.Column(scale=5, elem_id="pdf-col"):
                    pdf_viewer = gr.HTML(
                        value    = _pdf_viewer_html(None),
                        label    = "PDF 预览",
                    )

                with gr.Column(scale=5, elem_id="note-col"):
                    note_md = gr.Markdown(
                        value    = "*等待上传 PDF 并开始分析…*",
                    )

            # ── 状态栏 ────────────────────────────────────────────────────────────────
            status_bar = gr.Textbox(
                value       = "就绪",
                label       = "状态",
                interactive = False,
                max_lines   = 1,
                elem_id     = "status-bar",
            )

            # ── 按钮栏 ────────────────────────────────────────────────────────────────
            with gr.Row():
                btn_start      = gr.Button("🚀 开始分析",  variant="primary",    scale=2)
                btn_resume     = gr.Button("▶ 继续",        variant="secondary",  scale=1)
                btn_export     = gr.Button("💾 导出 .md",   variant="secondary",  scale=1)
                btn_export_pdf = gr.Button("📄 导出 PDF",   variant="secondary",  scale=1)
                btn_copy       = gr.Button("📋 复制全文",   variant="secondary",  scale=1)

            # 导出结果提示（点击导出后显示）
            export_msg = gr.Textbox(
                label       = "导出结果",
                interactive = False,
                max_lines   = 2,
                visible     = False,
            )

            # 复制全文展示区（gr.Code 自带一键复制按钮，点击「复制全文」后展开）
            full_text_box = gr.Code(
                value    = "",
                language = None,
                label    = "全文 Markdown（点击右上角图标可一键复制）",
                visible  = False,
                lines    = 20,
            )

            # ── 历史记录面板（可折叠，有断点任务时默认展开） ──────────────────────────
            with gr.Accordion(
                "📚 历史记录",
                open = bool(_incomplete_records),
            ):
                history_html_comp = gr.HTML(value=_history_html())
                btn_refresh_hist  = gr.Button("🔄 刷新", size="sm")

    # ══════════════════════════════════════════════════════════════════════════
    # 事件绑定
    # ══════════════════════════════════════════════════════════════════════════

    # ── 配置向导：保存 API Key → 写入 .env → 跳转主界面 ──────────────────────
    def _on_setup_save(api_key: str, base_url: str):
        api_key  = api_key.strip()
        base_url = base_url.strip().rstrip("/")
        if not api_key:
            return (
                gr.update(value="❌ API Key 不能为空", visible=True),
                gr.update(),
            )
        env_lines = []
        if _ENV_PATH.exists():
            env_lines = [
                l for l in _ENV_PATH.read_text(encoding="utf-8").splitlines()
                if not l.startswith("ANTHROPIC_API_KEY=") and not l.startswith("ANTHROPIC_BASE_URL=")
            ]
        env_lines.append(f"ANTHROPIC_API_KEY={api_key}")
        if base_url:
            env_lines.append(f"ANTHROPIC_BASE_URL={base_url}")
        _ENV_PATH.write_text("\n".join(env_lines) + "\n", encoding="utf-8")
        os.environ["ANTHROPIC_API_KEY"] = api_key
        if base_url:
            os.environ["ANTHROPIC_BASE_URL"] = base_url
        elif "ANTHROPIC_BASE_URL" in os.environ:
            del os.environ["ANTHROPIC_BASE_URL"]
        # 重置 AI 客户端，确保下次调用时用新配置重建
        import core.ai_engine as _ae
        _ae._client = None
        return (
            gr.update(value="✅ 配置已保存！正在跳转到主界面…", visible=True),
            gr.update(selected="main"),
        )

    setup_save_btn.click(
        fn      = _on_setup_save,
        inputs  = [setup_key_input, setup_base_url_input],
        outputs = [setup_msg, tabs],
    )

    # 上传 PDF → 立即更新左栏预览
    pdf_upload.change(
        fn      = do_update_pdf_viewer,
        inputs  = [pdf_upload],
        outputs = [pdf_viewer],
    )

    # 「开始分析」→ 流式更新右栏笔记 + 状态栏
    btn_start.click(
        fn            = run_analysis,
        inputs        = [pdf_upload],
        outputs       = [note_md, status_bar],
        show_progress = False,
    )

    # 「继续」→ 断点续传，同样流式推送
    btn_resume.click(
        fn            = do_resume,
        inputs        = [pdf_upload],
        outputs       = [note_md, status_bar],
        show_progress = False,
    )

    # 「导出 .md」→ 弹出 PowerShell 文件夹对话框并显示结果
    def _on_export():
        msg = do_export()
        return gr.update(value=msg, visible=True)

    btn_export.click(
        fn      = _on_export,
        inputs  = [],
        outputs = [export_msg],
    )

    # 「导出 PDF」→ 弹出文件夹对话框，生成 PDF
    def _on_export_pdf():
        msg = do_export_pdf()
        return gr.update(value=msg, visible=True)

    btn_export_pdf.click(
        fn      = _on_export_pdf,
        inputs  = [],
        outputs = [export_msg],
    )

    # 「复制全文」→ 展开 Code 框（自带复制按钮）
    def _on_copy():
        text = do_get_full_text()
        return gr.update(value=text, visible=True)

    btn_copy.click(
        fn      = _on_copy,
        inputs  = [],
        outputs = [full_text_box],
    )

    # 「刷新」历史记录
    btn_refresh_hist.click(
        fn      = do_refresh_history,
        inputs  = [],
        outputs = [history_html_comp],
    )


# ══════════════════════════════════════════════════════════════════════════════
# 启动
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import time

    # 把 /pdf_serve 路由挂到 Gradio 内置的 FastAPI 实例上（同源同端口）
    @demo.app.get("/pdf_serve")
    def serve_pdf():
        if _current_pdf_path and Path(_current_pdf_path).exists():
            return Response(
                content=Path(_current_pdf_path).read_bytes(),
                media_type="application/pdf",
            )
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content={"detail": "no pdf"})

    demo.launch(
        server_name = "127.0.0.1",
        inbrowser   = True,
        share       = False,
        show_error  = True,
        css         = _CSS,
        prevent_thread_lock = True,
    )

    # 在 launch 之后再次确保路由已注册（launch 会重建 app）
    @demo.app.get("/pdf_serve")
    def serve_pdf2():
        if _current_pdf_path and Path(_current_pdf_path).exists():
            return Response(
                content=Path(_current_pdf_path).read_bytes(),
                media_type="application/pdf",
            )
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content={"detail": "no pdf"})

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
