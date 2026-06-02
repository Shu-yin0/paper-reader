# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## 项目概述

**论文精读助手（Paper Reader）** — 一款运行于 Windows 本地的浏览器 GUI 工具。  
核心工作流：上传论文 PDF → AI 分8段自动生成精读笔记 → 实时预览 → 导出 Markdown → 粘贴 Notion。

完整技术规范见 `SPEC.md`（桌面路径，若需参考）；实现方案详见计划文件。

---

## 快速启动

```bash
# 安装依赖
pip install -r requirements.txt

# 配置 API Key
copy .env.example .env
# 编辑 .env，填入 ANTHROPIC_API_KEY

# 启动应用（自动打开浏览器 http://localhost:7860）
python app.py
```

**系统依赖（Windows，需手动安装）：**
- [Tesseract-OCR v5.x](https://github.com/UB-Mannheim/tesseract/wiki) — 安装时勾选 Chinese Simplified + English，加入 PATH
- [Poppler for Windows](https://github.com/oschwartz10612/poppler-windows) — 将 `bin/` 目录加入 PATH

---

## 架构总览

### 数据流

```
PDF 上传
  → core/pdf_parser.py     # 文字提取（pdfplumber）或 OCR 兜底（pytesseract）
  → core/pdf_parser.py     # 章节分割 + 公式编号预处理（正则标记 [EQ_NUM:N]）
  → core/ai_engine.py      # 分8段调用 Claude API，streaming yield
  → core/validator.py      # CrossRef 验证 + 数值交叉核验（标记 ❗）
  → core/exporter.py       # 拼装 YAML Front Matter + Markdown，保存文件
  → core/history.py        # 写入 data/history.json
```

### 关键模块职责

| 文件 | 核心职责 | 关键函数 |
|------|---------|---------|
| `app.py` | Gradio UI 入口，split-pane 布局，流式推送 | `analyze()` generator，PDF.js iframe |
| `core/pdf_parser.py` | 文字提取、双栏合并、章节切割 | `extract_text_with_pages()`, `split_sections()` |
| `core/ai_engine.py` | 8段分段 Claude API 调用，断点续传 | `analyze_paper()`, `save_progress()` |
| `core/validator.py` | CrossRef API 验证 + 数值核验 | `verify_crossref()`, `cross_validate()` |
| `core/exporter.py` | Markdown 生成、文件命名、PowerShell 文件夹对话框 | `export_note()`, `build_filename()` |
| `core/history.py` | 历史记录 JSON 读写 | `add_record()`, `update_record()` |
| `prompts/note_template.py` | 全部 Prompt 模板常量 + 变量填充 | `build_prompts()`, `SYSTEM_PROMPT` |

### 跨模块关键约定

**公式编号预处理**：`pdf_parser.py` 在将文本传给 AI 之前，用正则将 `Eq.(N)`、`(N)` 行末、`Equation N` 替换为 `[EQ_NUM:N]`。AI Prompt（段4）中明确指示跳过此标记，`validator.py` 的数字提取也会排除它。三处必须保持一致。

**流式输出约定**：`ai_engine.analyze_paper()` 是 Python generator，`yield (section_num: int, chunk: str)`。`app.py` 的 Gradio handler 消费此 generator，将 `chunk` 累积到字符串后 `yield accumulated_string` 推送给 `gr.Markdown`（Gradio 4.x streaming 要求 yield 完整累积字符串，不是增量片段）。

**断点续传**：进度文件路径为 `data/progress/{md5(pdf_path)}.json`，字段 `last_completed_section` 记录最后完成的段号（1-8）。`analyze_paper(resume_from=N)` 跳过前 N 段，直接从缓存读取已完成内容。

**CrossRef 字段优先级**：CrossRef 返回数据优先覆盖 AI 提取的 `title/authors/year/venue/doi`，最终写入 YAML Front Matter。

---

## Prompt 模板管理

所有 Prompt 模板集中在 `prompts/note_template.py`，分为：
- `SYSTEM_PROMPT`：8段共用，作为 Anthropic API 的 `system` 参数，启用 `cache_control: {"type": "ephemeral"}` 节省重复 token
- `_SECTION_N_TEMPLATE`（N=1~8）：各段 User Prompt，用 `.format()` 填充变量
- `build_prompts(sections_text, crossref_data, previous_summary)` → `dict[int, str]`

修改笔记格式或提取逻辑时，**只改 `prompts/note_template.py`**，不动业务代码。

---

## 输出文件规范

**文件名格式**：`{year}_{FirstAuthorLastName}_{KeywordSlug}.md`  
示例：`2024_Vaswani_Transformer.md`

**保存路径**：用户选择根目录 → 自动创建 `YYYY-MM/` 子文件夹  
示例：`D:/论文笔记/2026-04/2024_Vaswani_Transformer.md`

**文件结构**：YAML Front Matter（含 `crossref_verified` 字段）→ 数值核验摘要行 → 8节笔记正文 → 署名行

---

## 环境变量

`.env` 文件（不提交 git）：

```
ANTHROPIC_API_KEY=your_anthropic_api_key_here
MODEL_NAME=claude-3-5-sonnet-20241022   # 可选，切换模型无需改代码
```

---

## 数据目录

```
data/
├── history.json          # 历史记录，结构见 SPEC.md §13.1
└── progress/             # 断点续传，每篇论文一个 {md5}.json
```

应用首次启动时由 `core/history.py:init_data_dir()` 自动创建。

---

## 常见开发场景

**修改某节笔记的输出格式**：编辑 `prompts/note_template.py` 中对应的 `_SECTION_N_TEMPLATE`。

**调整章节识别关键词**（论文章节标题未被正确切割）：编辑 `core/pdf_parser.py` 中的 `SECTION_KEYWORDS` 字典。

**更换 AI 模型**：修改 `.env` 中的 `MODEL_NAME`，或直接改 `core/ai_engine.py` 中的 `model` 参数。

---

## 注意事项


**PDF.js 页面跳转**（右栏引用点击跳转左栏页码）：跳转逻辑在 `app.py` 的 `gr.HTML` 内嵌 JavaScript 中，通过 `PDFViewerApplication.page = N` 实现（同源 iframe）。
