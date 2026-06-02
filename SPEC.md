# SPEC.md — 论文精读助手 技术规范文档

> **项目名称**：论文精读助手（Paper Reader）
> **文档版本**：v1.0
> **撰写日期**：2026-04-17
> **作者**：周芷若 · 武汉理工大学 智能汽车与汽车电子专业
> **研究方向**：VLA / 具身智能

---

## 目录

1. [产品定位](#1-产品定位)
2. [技术栈](#2-技术栈)
3. [项目结构](#3-项目结构)
4. [PDF 解析模块](#4-pdf-解析模块)
5. [AI 提取引擎](#5-ai-提取引擎)
6. [数据真实性验证](#6-数据真实性验证)
7. [GUI 界面规范](#7-gui-界面规范)
8. [输出文件规范](#8-输出文件规范)
9. [笔记模板与 Prompt 设计](#9-笔记模板与-prompt-设计)
10. [批量处理与断点续传](#10-批量处理与断点续传)
11. [错误处理与边界情况](#11-错误处理与边界情况)
12. [环境配置与启动方式](#12-环境配置与启动方式)
13. [数据存储规范](#13-数据存储规范)
14. [非功能性要求](#14-非功能性要求)

---

## 1. 产品定位

### 1.1 概述

一款运行于 Windows 本地的 **浏览器 GUI 工具**，面向个人学术研究使用场景。
核心工作流：上传论文 PDF → AI 自动生成精读笔记 → 导出 Markdown → 粘贴至 Notion 整理。

### 1.2 使用对象

| 维度 | 说明 |
|------|------|
| 用户 | 周芷若，武汉理工大学，智能汽车与汽车电子专业 |
| 研究方向 | VLA · RL · World Model · 具身智能 · 自动驾驶 |
| 使用场景 | 个人独用，本地运行，非团队协作 |

### 1.3 核心目标

1. **自动化**：上传 PDF 后，无需人工干预，自动完成全部章节的笔记生成
2. **可信**：对 AI 提取的数值进行原文交叉核验，标记存疑内容
3. **Notion 友好**：输出标准 Markdown，含 YAML Front Matter，直接粘贴可用
4. **可追溯**：笔记中引用内容标注原始 PDF 页码，支持一键跳转

---

## 2. 技术栈

### 2.1 后端

| 组件 | 选型 | 说明 |
|------|------|------|
| Web 框架 | **Gradio** | 快速搭建本地浏览器 GUI，无需前端开发 |
| PDF 文字提取 | **pdfplumber** | 优先提取数字原生 PDF 的文字层 |
| OCR 兜底 | **pytesseract + pdf2image** | 扫描版 PDF 自动切换，需安装 Tesseract-OCR |
| AI 模型调用 | **anthropic Python SDK** | 调用 Claude claude-3-5-sonnet |
| 论文元数据验证 | **CrossRef REST API** | 通过 DOI 或标题查询论文真实存在性 |
| 环境变量管理 | **python-dotenv** | 读取 `.env` 中的 `ANTHROPIC_API_KEY` |

### 2.2 前端（Gradio 内置）

| 组件 | 说明 |
|------|------|
| PDF 预览 | Gradio `gr.HTML` 嵌入 PDF.js 渲染器 |
| 笔记预览 | Gradio `gr.Markdown` 实时渲染 |
| 拖放上传 | Gradio `gr.File`，支持多文件 |
| 进度显示 | Gradio `gr.Textbox` / `gr.Progress` 流式更新 |

### 2.3 运行环境

| 项目 | 要求 |
|------|------|
| 操作系统 | Windows 10 / 11 |
| Python | 3.10+ |
| 浏览器 | Chrome / Edge（现代浏览器） |
| Tesseract | v5.x，需加入系统 PATH |
| 网络 | 需要访问 Anthropic API 和 CrossRef API |

---

## 3. 项目结构

```
paper-reader/
├── app.py                  # Gradio 主入口，启动 Web 服务
├── .env                    # API Key 配置（不提交到 git）
├── .env.example            # 配置模板
├── requirements.txt        # Python 依赖列表
├── README.md               # 快速启动说明
│
├── core/
│   ├── pdf_parser.py       # PDF 解析模块（文字提取 + OCR 兜底）
│   ├── ai_engine.py        # Claude API 调用，分段 Prompt，流式输出
│   ├── validator.py        # 数据真实性验证（数值核验 + CrossRef）
│   ├── exporter.py         # Markdown 文件生成、命名、保存
│   └── history.py          # 历史记录读写（JSON 持久化）
│
├── prompts/
│   └── note_template.py    # 各章节 Prompt 模板常量
│
├── data/
│   ├── history.json        # 历史记录文件
│   └── progress/           # 断点续传进度文件（每篇论文一个 .json）
│
└── assets/
    └── pdfjs/              # PDF.js 静态资源（本地离线使用）
```

---

## 4. PDF 解析模块

### 4.1 解析流程

```
上传 PDF
    │
    ▼
尝试 pdfplumber 提取文字层
    │
    ├─── 成功（字符数 > 阈值 200字/页）─────► 返回文字内容
    │
    └─── 失败或字符过少（扫描版）──────────► pdf2image 转图片
                                                    │
                                                    ▼
                                             pytesseract OCR
                                             （语言：eng+chi_sim）
                                                    │
                                                    ▼
                                             返回 OCR 文字内容
```

### 4.2 文字提取规则

| 规则 | 说明 |
|------|------|
| 判断阈值 | 每页平均字符数 < 200，判定为扫描版，切换 OCR |
| 页码记录 | 提取时保留每段文字所在的原始页码（page_number），用于后续引用标注 |
| 页眉页脚过滤 | 过滤掉位于页面顶部 5% 和底部 5% 区域的重复文本（页眉/页脚/页码行） |
| 栏目分割 | 支持双栏论文，按左栏→右栏顺序合并文字流 |
| 参考文献定位 | 识别 "References" / "参考文献" 章节起始位置，单独分段传给参考文献 Prompt |

### 4.3 OCR 配置

```python
# pytesseract 配置
TESSERACT_CONFIG = r'--oem 3 --psm 6'
TESSERACT_LANG   = 'eng+chi_sim'
# pdf2image 配置
PDF2IMAGE_DPI    = 300   # 分辨率，保证识别质量
```

### 4.4 公式编号误识别规则

> **重要**：AI 提取数值时，以下格式识别为公式编号，**不计入实验数据提取**：

- `Eq.(N)`、`Equation N`、`式(N)` — N 为任意数字
- 括号内纯数字且位于行末（如 `(1)` `(12)`）
- 形如 `(N.M)` 的章节编号（如 `(3.2)`）

实现方式：在将文本传给 AI 前，用正则预处理标记公式编号：

```python
import re
text = re.sub(r'\((\d+)\)\s*$', r'[EQ_NUM:\1]', text, flags=re.MULTILINE)
text = re.sub(r'Eq\.\s*\((\d+)\)', r'[EQ_NUM:\1]', text)
text = re.sub(r'Equation\s+(\d+)', r'[EQ_NUM:\1]', text, flags=re.IGNORECASE)
```

---

## 5. AI 提取引擎

### 5.1 模型配置

| 参数 | 值 |
|------|----|
| 模型 | `claude-3-5-sonnet-20241022` |
| 最大输出 Token | 每篇论文 ≤ 10,000 tokens（分段累计） |
| 温度（temperature） | `0.3`（保证稳定性，减少幻觉） |
| 输出语言 | 中文为主；专业术语、模型名、数据集名保留英文原文 |
| 公式格式 | Unicode 数学符号直接输出（如 `θ = argmax Σ rₜ`），**禁止输出任何 LaTeX 代码** |
| 图表处理 | 不生成图表内容，仅输出页码引用（如 `见原文第5页图2`） |

### 5.2 分段调用策略

为控制 token 消耗并实现进度反馈，按章节分段调用 API：

| 调用段 | 覆盖内容 | 输入来源 |
|--------|---------|---------|
| 段1：基本信息 | 第一节 | PDF 首页文本 + CrossRef 补全 |
| 段2：背景与问题 | 第二节 | Introduction 部分文本 |
| 段3：方法详解 | 第三节 | Method / Approach 部分文本 |
| 段4：实验分析 | 第四节 | Experiment / Results 部分文本 |
| 段5：结论与局限 | 第五节 | Conclusion / Limitation 部分文本 |
| 段6：个人思考 | 第六节 | 基于前5段生成内容综合生成 |
| 段7：参考文献 | 第七节 | References 部分文本 |
| 段8：关键词标签 | 第八节 | 基于全文关键词提取 |

### 5.3 Prompt 设计规范

每段 Prompt 结构：

```
[System Prompt]
你是一名专业的学术论文分析助手，专注于 VLA、具身智能、RL、World Model 领域。
输出语言：中文。专业术语/模型名/数据集名保留英文。
公式使用 Unicode 数学符号（如 θ、Σ、argmax），禁止输出 LaTeX 代码（禁止 $...$ 或 $$...$$）。
图表和表格不生成内容，仅注明 "见原文第X页图Y"。

[User Prompt — 各段具体指令，见第9节]
```

### 5.4 流式输出

使用 Anthropic SDK 的流式模式，将输出实时推送至 GUI 右栏：

```python
with client.messages.stream(
    model="claude-3-5-sonnet-20241022",
    max_tokens=2000,
    messages=[{"role": "user", "content": prompt}]
) as stream:
    for text in stream.text_stream:
        yield text  # Gradio generator 实时推送
```

### 5.5 Token 预算控制

- 每段 Prompt 输入文本截断至 **3000 字符**（约 1500 tokens）
- 若某章节文本超过截断阈值，优先保留前半部分（摘要/核心段）
- 全篇 8 段累计输出上限 **10,000 tokens**，超出则截断并提示用户

---

## 6. 数据真实性验证

### 6.1 论文真实存在性验证（CrossRef API）

**触发时机**：第一段基本信息提取完成后自动触发

**验证流程**：

```
AI 提取 DOI / 标题
        │
        ▼
CrossRef API 查询
https://api.crossref.org/works/{DOI}
或 https://api.crossref.org/works?query={标题}&rows=1
        │
        ├─── 匹配成功 ──► 用 CrossRef 数据补全/校正基本信息
        │                  末尾显示：✅ CrossRef 已验证
        │
        └─── 未找到 ─────► 末尾显示：⚠️ CrossRef 未找到，请人工核实
```

**字段优先级**：CrossRef 数据 > AI 提取数据

**超时处理**：请求超时阈值 5 秒，超时跳过验证，显示 `⚠️ CrossRef 验证超时，跳过`

### 6.2 数值交叉核验

**触发时机**：第四节实验分析生成后自动执行

**核验逻辑**：

```python
ai_numbers  = extract_numbers_from_ai_output(section_4_text)
pdf_numbers = extract_numbers_from_pdf(experiment_section_raw)

for num in ai_numbers:
    if num not in pdf_numbers:
        section_4_text = section_4_text.replace(str(num), f"{num} ❗")
```

**数字提取规则**：
- 提取：百分比（`87.3%`）、小数（`0.856`）、整数（`1024`）
- 排除：年份（1900–2030）、引用编号（`[1]`）、已标记公式编号（`[EQ_NUM:N]`）
- 容差：±0.1%（避免四舍五入误报）

**核验摘要**（显示于笔记顶部）：

```
> 🔍 数值核验：共提取 N 个数值，M 个与原文不符（已用 ❗ 标注）
```

### 6.3 公式编号误识别防护

见 [4.4 节](#44-公式编号误识别规则)，预处理阶段完成，AI 不接触原始公式编号。

---

## 7. GUI 界面规范

### 7.1 整体布局

```
┌─────────────────────────────────────────────────────────────────┐
│  📄 论文精读助手                              [历史记录] [设置]  │
├──────────────────────┬──────────────────────────────────────────┤
│                      │                                          │
│   左栏：PDF 预览     │   右栏：笔记预览（Markdown 实时渲染）    │
│   （PDF.js 渲染）    │                                          │
│                      │                                          │
│   [← 上一页] [页码]  │   [进度条：正在提取基本信息…]            │
│   [下一页  →]        │                                          │
│                      │                                          │
├──────────────────────┴──────────────────────────────────────────┤
│  [拖放或点击上传 PDF]  [开始分析]  [继续]  [导出.md]  [复制全文] │
└─────────────────────────────────────────────────────────────────┘
```

### 7.2 功能模块详细说明

#### 7.2.1 文件上传区

| 特性 | 说明 |
|------|------|
| 交互方式 | 拖拽文件到上传区，或点击弹出文件选择框 |
| 支持格式 | 仅 `.pdf` |
| 批量支持 | 支持同时拖入多个 PDF，依次加入处理队列 |
| 队列显示 | 上传区下方显示队列列表（文件名 + 状态：等待中/处理中/已完成/失败） |

#### 7.2.2 左栏 PDF 预览

| 特性 | 说明 |
|------|------|
| 渲染引擎 | PDF.js（本地静态资源，离线可用） |
| 嵌入方式 | `gr.HTML` 内嵌 `<iframe>` 加载 PDF.js viewer |
| 页面跳转 | 提供「上一页」「下一页」按钮，显示当前页码/总页码 |
| 点击跳转 | 右栏笔记中带 `[第N页]` 标注的文字可点击，触发左栏跳转到第 N 页 |
| 初始状态 | 未上传时显示占位提示：「请上传论文 PDF」 |

#### 7.2.3 右栏笔记预览

| 特性 | 说明 |
|------|------|
| 渲染方式 | `gr.Markdown`，实时流式渲染（逐段追加） |
| 进度指示 | 每段生成前，在右栏顶部显示当前步骤：`正在提取基本信息… (1/8)` |
| 页码链接 | `见原文第N页图M` 中的页码渲染为可点击蓝色链接 |
| 数值标记 | 核验不符的数值后面跟随红色 `❗` 符号，悬停显示提示 |
| 验证摘要 | 笔记顶部固定显示 CrossRef 验证状态 + 数值核验摘要 |

#### 7.2.4 操作按钮栏

| 按钮 | 触发条件 | 行为 |
|------|---------|------|
| **开始分析** | 上传至少一个 PDF | 开始分段 AI 分析，按队列依次处理 |
| **继续** | 存在未完成的进度文件 | 从上次中断的章节继续处理 |
| **导出 .md** | 当前笔记生成完成 | 弹出文件夹选择框，保存 .md 文件 |
| **复制全文** | 当前笔记生成完成 | 将完整 Markdown 内容复制到剪贴板 |
| **历史记录** | 任意时刻可点击 | 打开历史面板（侧边抽屉或弹窗） |

#### 7.2.5 历史记录面板

| 字段 | 说明 |
|------|------|
| 论文标题 | AI 提取的标题（截断至 40 字） |
| 处理日期 | `YYYY-MM-DD HH:MM` |
| 状态 | `已完成` / `未完成（断点）` / `失败` |
| 操作 | 「重新打开」→ 加载对应笔记到右栏；「删除」→ 删除历史记录和进度文件 |

历史记录存储于 `data/history.json`，每次应用启动时自动加载。

### 7.3 实时进度显示规范

分析过程中，右栏顶部固定显示进度条，格式：

```
[████████░░░░░░░░] 正在分析实验结果… (4/8)
```

各步骤文案：

| 步骤 | 显示文案 |
|------|---------|
| 1/8 | 正在解析 PDF 文字层… |
| 2/8 | 正在提取基本信息… |
| 3/8 | CrossRef 验证中… |
| 4/8 | 正在分析研究背景… |
| 5/8 | 正在解析方法详解… |
| 6/8 | 正在整理实验数据… |
| 7/8 | 正在生成结论与思考… |
| 8/8 | 正在提取参考文献与标签… |

---

## 8. 输出文件规范

### 8.1 文件命名规则

格式：`{年份}_{第一作者姓}_{标题关键词}.md`

| 字段 | 提取来源 | 处理规则 |
|------|---------|---------|
| 年份 | CrossRef 或 AI 提取 | 4位数字，如 `2024` |
| 第一作者姓 | CrossRef 或 AI 提取 | 英文姓（Last Name），首字母大写，如 `Vaswani` |
| 标题关键词 | AI 从标题中提取2~3个核心词 | 去除冠词介词，驼峰或下划线连接，如 `Transformer` |

示例：`2024_Vaswani_Transformer.md`

特殊情况：
- 标题过长：AI 自动截取前3个核心名词
- 中文论文：作者姓使用拼音，关键词使用英文翻译
- 无法提取：降级为 `未知年份_未知作者_论文.md`

### 8.2 保存位置

| 规则 | 说明 |
|------|------|
| 根目录 | 每次点击「导出 .md」时弹出文件夹选择框，手动选择根目录 |
| 子文件夹 | 工具自动按当前年月在根目录下创建子文件夹，如 `2026-04/` |
| 完整路径示例 | `D:/论文笔记/2026-04/2024_Vaswani_Transformer.md` |
| 重名处理 | 同名文件存在时，在末尾追加 `_2`、`_3`，不覆盖原文件 |

### 8.3 Markdown 文件结构

每个输出文件结构如下：

```markdown
---
title: "Attention Is All You Need"
authors: ["Ashish Vaswani", "Noam Shazeer", "..."]
year: 2017
venue: "NeurIPS"
doi: "10.48550/arXiv.1706.03762"
tags: ["Transformer", "Attention", "NLP"]
read_date: "2026-04-17"
crossref_verified: true
---

> 🔍 数值核验：共提取 23 个数值，0 个与原文不符
> ✅ CrossRef 已验证

## 一、基本信息
...（各章节内容）...

---
*阅读人：周芷若 | 武汉理工大学 智能汽车与汽车电子专业*
```

### 8.4 YAML Front Matter 字段说明

| 字段 | 类型 | 来源 | 说明 |
|------|------|------|------|
| `title` | string | CrossRef 优先 | 论文完整标题 |
| `authors` | list | CrossRef 优先 | 全部作者列表 |
| `year` | int | CrossRef 优先 | 发表年份 |
| `venue` | string | CrossRef 优先 | 期刊/会议名称 |
| `doi` | string | CrossRef 优先 | DOI 字符串 |
| `tags` | list | AI 提取 | 关键词标签，与第八节一致 |
| `read_date` | string | 系统时间 | 格式 `YYYY-MM-DD` |
| `crossref_verified` | bool | 验证模块 | `true` / `false` |

### 8.5 第八节关键词标签格式

关键词标签使用 **Notion callout 块** 兼容格式输出：

```markdown
## 八、关键词标签

> 📌 `#VLA` `#WorldModel` `#RL` `#具身智能` `#Transformer` `#自动驾驶`
```

标签生成规则：
- AI 从论文中提取 5~8 个关键词
- 必须包含：领域标签（VLA/RL/WorldModel/具身智能/自动驾驶）+ 方法标签 + 任务标签
- 中文领域词保留中文，英文技术词保留英文

---

## 9. 笔记模板与 Prompt 设计

> 以下为各章节的完整 Prompt 指令，直接对应 `prompts/note_template.py` 中的常量。

### 9.1 系统 Prompt（所有段共用）

```
你是一名专业的学术论文分析助手，专注于 VLA、具身智能、强化学习（RL）、World Model、自动驾驶领域。

【输出规则】
1. 使用中文输出。专业术语、模型名称（如 RT-2）、数据集名称（如 RLBench）保留英文。
2. 数学公式使用 Unicode 数学符号直接输出（如 θ = argmax Σ rₜ）。
   严禁使用 LaTeX 语法，严禁输出 $...$ 或 $$...$$。
3. 图表和表格不生成文字内容，仅标注原始页码，格式：见原文第N页图M。
4. 输出严格遵循给定的 Markdown 模板格式，不添加额外章节。
5. 不编造数据，不过度推断，如信息不足请注明"原文未明确说明"。
```

### 9.2 段1 Prompt — 基本信息

**输入**：PDF 首页文本（约500字符）+ CrossRef 查询结果（若有）

```
请从以下论文首页文本中提取基本信息，以 Markdown 表格格式输出。

【论文首页文本】
{first_page_text}

【CrossRef 数据】（如有，优先使用此数据）
{crossref_data}

请严格按以下格式输出：

## 一、基本信息

| 项目 | 内容 |
|------|------|
| **论文标题** | （英文原标题） |
| **作者** | （所有作者，逗号分隔） |
| **所属机构** | （第一作者机构） |
| **发表期刊/会议** | （全称） |
| **发表年份** | （4位数字） |
| **关键词** | （论文原始关键词） |
| **阅读日期** | {today_date} |
| **来源链接/DOI** | （DOI 字符串或 URL） |
| **代码仓库** | （GitHub 链接，无则填"原文未提供"） |
```

### 9.3 段2 Prompt — 研究背景与问题定义

**输入**：Abstract + Introduction 文本（截断至3000字符）

```
请基于以下论文 Introduction 内容，生成"研究背景与问题定义"章节。

【论文 Introduction 文本】
{introduction_text}

请严格按以下格式输出：

## 二、研究背景与问题定义

### 2.1 研究背景
（描述该领域当前研究现状，3~5句中文）

### 2.2 核心问题
- **本文要解决的问题是：**
- **问题的形式化描述（如有）：**（Unicode 数学符号，无则填"原文未给出形式化定义"）

### 2.3 现有方法的局限性

| 现有方法 | 存在的问题 |
|----------|-----------|
| （方法名1） | （问题描述） |
| （方法名2） | （问题描述） |

### 2.4 本文贡献（作者自述）
- [ ] 贡献1：
- [ ] 贡献2：
- [ ] 贡献3：（如有）
```

### 9.4 段3 Prompt — 方法详解

**输入**：Method / Approach / Model 章节文本（截断至3000字符）

```
请基于以下论文方法部分，生成"方法详解"章节。

【论文方法部分文本】
{method_text}

请严格按以下格式输出：

## 三、方法详解

### 3.1 整体框架
（文字描述模型整体结构和数据流）

### 3.2 关键技术模块

#### 模块1：（名称）
- 功能：
- 原理：（公式用 Unicode 数学符号）

#### 模块2：（名称）
- 功能：
- 原理：

### 3.3 训练策略
- **损失函数：**
- **优化方法：**
- **训练数据来源：**
- **特殊训练技巧：**

### 3.4 与相关工作的区别

| 对比维度 | 本文方法 | 代表性对比方法 |
|---------|---------|--------------|
| 模型结构 | | |
| 泛化能力 | | |
| 训练方式 | | |
| 推理效率 | | |
```

### 9.5 段4 Prompt — 实验分析

**输入**：Experiment / Results / Evaluation 章节文本（截断至3000字符）

```
请基于以下论文实验部分，生成"实验分析"章节。

注意：图表和表格不生成内容，仅注明：见原文第N页图M
注意：[EQ_NUM:N] 为公式编号，不是实验数值，跳过

【论文实验部分文本】
{experiment_text}

请严格按以下格式输出：

## 四、实验分析

### 4.1 实验设置
- **数据集/仿真环境：**
- **评估指标：**
- **Baseline 方法：**
- **实现细节（硬件/框架/超参数）：**

### 4.2 主实验结果
（关键数值直接列出；表格标注：见原文第N页表M）

### 4.3 消融实验
（描述消融关键结论；如无则填"原文未进行消融实验"）

### 4.4 可视化/定性分析
（描述 case study 规律；图表标注页码）
```

### 9.6 段5 Prompt — 结论与局限性

**输入**：Conclusion / Limitation / Future Work 章节文本（截断至2000字符）

```
请基于以下论文结论部分，生成"结论与局限性"章节。

【论文结论部分文本】
{conclusion_text}

请严格按以下格式输出：

## 五、结论与局限性

### 5.1 作者结论
（总结结论段，2~3条要点）

### 5.2 局限性与未来工作
- **作者指出的局限：**
- **我认为的局限：**（客观分析，1~2条）
- **未来方向：**
```

### 9.7 段6 Prompt — 个人思考（AI 全自动）

**输入**：前5段生成内容的压缩摘要

```
请以武汉理工大学 VLA/具身智能方向大一学生的视角，基于以下笔记摘要生成"个人思考"章节。

【已生成笔记摘要】
{summary_of_previous_sections}

请严格按以下格式输出：

## 六、个人思考

### 6.1 这篇文章的核心创新点
（用自己的语言，不超过100字）

### 6.2 与我当前研究方向的关联
- **可借鉴的思路：**（结合 VLA/具身智能方向）
- **可能的改进方向：**
- **是否值得复现？** 是 / 否，理由：

### 6.3 遗留问题与疑惑
- 问题1：
- 问题2：
```

### 9.8 段7 Prompt — 参考与延伸阅读

**输入**：References 章节文本（截断至3000字符）

```
请从以下参考文献中，筛选出与本文最密切相关的5篇论文，重点标注本文所改进或基于的基础架构。

【参考文献文本】
{references_text}

请严格按以下格式输出：

## 七、参考与延伸阅读

| 论文 | 关系 |
|------|------|
| （标题，作者，年份） | 本文基础架构（本文在此基础上改进） |
| （标题，作者，年份） | 本文对比 Baseline |
| （标题，作者，年份） | 核心对比方法 |
| （标题，作者，年份） | 延伸阅读推荐 |
| （标题，作者，年份） | 延伸阅读推荐 |
```

### 9.9 段8 Prompt — 关键词标签

**输入**：全文关键词 + 基本信息

```
请从论文内容中提取5~8个关键词标签，生成"关键词标签"章节。

【论文关键词】{keywords}
【研究领域】VLA / 具身智能 / RL / World Model / 自动驾驶

要求：
- 必须包含领域标签（#VLA #RL #WorldModel #具身智能 #自动驾驶 中选）
- 包含方法标签（如 #Transformer #扩散模型）
- 包含任务标签（如 #操作任务 #导航）
- 使用 Notion callout 兼容格式

请严格按以下格式输出：

## 八、关键词标签

> 📌 `#标签1` `#标签2` `#标签3` `#标签4` `#标签5`

---
*阅读人：周芷若 | 武汉理工大学 智能汽车与汽车电子专业*
```

---

## 10. 批量处理与断点续传

### 10.1 批量队列机制

```
用户上传多个 PDF
        │
        ▼
加入全局处理队列（Queue）
        │
        ▼
顺序取出第一个 PDF → 开始分析
        │
        ▼
完成 → 自动取下一个 PDF
        │
        ▼
全部完成 → 显示"全部处理完成 ✅"
```

**队列状态字段**（每条记录）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `file_path` | string | PDF 文件路径 |
| `status` | enum | `waiting` / `processing` / `done` / `failed` |
| `progress_file` | string | 对应的断点进度文件路径 |
| `output_file` | string | 输出 .md 文件路径（完成后填写） |

### 10.2 断点续传机制

**进度文件路径**：`data/progress/{md5_of_filepath}.json`

**进度文件结构**：

```json
{
  "file_path": "C:/Papers/attention.pdf",
  "file_md5": "a1b2c3d4...",
  "last_completed_section": 3,
  "sections": {
    "1": "## 一、基本信息\n...",
    "2": "## 二、研究背景\n...",
    "3": "## 三、方法详解\n...",
    "4": null,
    "5": null,
    "6": null,
    "7": null,
    "8": null
  },
  "pdf_text_cache": {
    "intro": "...",
    "method": "...",
    "experiment": "...",
    "conclusion": "...",
    "references": "..."
  },
  "created_at": "2026-04-17T10:30:00",
  "updated_at": "2026-04-17T10:45:00"
}
```

**续传触发条件**：
- 用户点击「继续」按钮
- 或应用启动时检测到 `data/progress/` 下存在未完成的进度文件，自动提示用户

**续传逻辑**：
1. 读取进度文件，找到 `last_completed_section`
2. 从第 `last_completed_section + 1` 段开始继续调用 AI
3. 使用进度文件中缓存的 `pdf_text_cache`，无需重新解析 PDF

---

## 11. 错误处理与边界情况

### 11.1 错误类型与处理策略

| 错误场景 | 处理方式 | 用户提示 |
|---------|---------|---------|
| PDF 解析失败（损坏文件） | 跳过该文件，继续下一个 | `❌ PDF 解析失败：文件可能损坏，请检查文件` |
| OCR 失败 | 记录错误，输出部分笔记 | `⚠️ OCR 识别失败，部分内容可能缺失` |
| Anthropic API 超时（>30s） | 重试3次，仍失败则保存进度 | `⚠️ AI 请求超时，已保存进度，可点击「继续」重试` |
| Anthropic API 余额不足 | 停止处理，弹出提示 | `❌ API Key 余额不足，请充值后重试` |
| CrossRef API 不可用 | 跳过验证，继续生成 | `⚠️ CrossRef 验证服务不可用，跳过验证` |
| Token 超出预算 | 截断当前段，继续下一段 | `⚠️ 第N节内容过长，已自动截断` |
| 输出目录无写入权限 | 提示用户选择其他目录 | `❌ 无法写入所选目录，请重新选择` |
| .env 文件缺失 | 启动时弹出配置引导 | `❌ 未找到 .env 文件，请参考 .env.example 配置 API Key` |

### 11.2 边界情况处理

| 边界情况 | 处理规则 |
|---------|---------|
| 论文无 Abstract | 使用 Introduction 前500字代替 |
| 论文无 References 章节 | 第七节填写"原文未附参考文献列表" |
| 论文无 Conclusion 章节 | 使用最后一个正文章节代替 |
| PDF 仅1页（摘要/预印本） | 全页文本统一传给段1~段5，各章节尽力提取 |
| 中文论文 | Tesseract 使用 `chi_sim+eng`，Prompt 同样适用 |
| 论文超过50页 | 提示用户，仍正常处理但提醒分析质量可能下降 |

---

## 12. 环境配置与启动方式

### 12.1 依赖安装

**requirements.txt**：

```
gradio>=4.0.0
anthropic>=0.25.0
pdfplumber>=0.10.0
pdf2image>=1.16.0
pytesseract>=0.3.10
python-dotenv>=1.0.0
requests>=2.31.0
```

**系统依赖**：
- Tesseract-OCR v5.x（[下载地址](https://github.com/UB-Mannheim/tesseract/wiki)）
  - 安装时勾选语言包：Chinese Simplified + English
  - 安装后将 Tesseract 路径加入系统 PATH
- Poppler（pdf2image 依赖，Windows 需单独安装）
  - 下载 poppler-windows，将 `bin/` 目录加入 PATH

### 12.2 .env 配置

**.env.example**（提交到 git）：

```
ANTHROPIC_API_KEY=your_anthropic_api_key_here
```

**.env**（本地实际使用，不提交到 git）：

```
ANTHROPIC_API_KEY=your_anthropic_api_key_here
```

### 12.3 启动方式

```bash
# 1. 克隆项目
git clone <repo_url>
cd paper-reader

# 2. 安装 Python 依赖
pip install -r requirements.txt

# 3. 配置 API Key
copy .env.example .env
# 编辑 .env，填入真实的 ANTHROPIC_API_KEY

# 4. 启动应用
python app.py
# 浏览器自动打开 http://localhost:7860
```

### 12.4 app.py 启动逻辑

```python
# app.py 启动时执行：
# 1. 加载 .env，验证 ANTHROPIC_API_KEY 是否存在
# 2. 检查 Tesseract 是否在 PATH 中
# 3. 检查 data/progress/ 下是否有未完成进度文件，若有则提示用户
# 4. 加载 data/history.json 历史记录
# 5. 启动 Gradio 服务，自动打开浏览器
```

---

## 13. 数据存储规范

### 13.1 history.json 结构

```json
[
  {
    "id": "uuid-xxxx",
    "title": "Attention Is All You Need",
    "file_path": "C:/Papers/attention.pdf",
    "output_file": "D:/论文笔记/2026-04/2017_Vaswani_Transformer.md",
    "status": "done",
    "crossref_verified": true,
    "num_values_flagged": 0,
    "created_at": "2026-04-17T10:30:00",
    "completed_at": "2026-04-17T10:52:00"
  }
]
```

### 13.2 数据目录初始化

应用首次启动时自动创建：

```python
os.makedirs("data/progress", exist_ok=True)
if not os.path.exists("data/history.json"):
    with open("data/history.json", "w") as f:
        json.dump([], f)
```

---

## 14. 非功能性要求

| 维度 | 要求 |
|------|------|
| **性能** | 单篇论文（20页以内）完整分析时间 ≤ 3分钟（网络正常情况下） |
| **可靠性** | 任意步骤异常不崩溃应用，错误信息友好展示 |
| **可维护性** | Prompt 模板统一管理在 `prompts/note_template.py`，修改模板无需改动业务逻辑 |
| **隐私安全** | PDF 文件和笔记内容仅在本地处理，不上传至任何第三方服务器（CrossRef 仅发送标题/DOI） |
| **离线能力** | PDF 预览使用本地 PDF.js，无网络时仍可查看历史笔记 |
| **可扩展性** | 模型型号通过 `.env` 中的 `MODEL_NAME` 变量配置，无需修改代码即可切换 |

---

## 附录 A：核心数据流总览

```
用户上传 PDF
    │
    ▼
[pdf_parser.py] 解析 PDF
    ├── 文字层提取（pdfplumber）
    └── OCR 兜底（pytesseract）
    │
    ▼
[pdf_parser.py] 章节分割
    └── 公式编号预处理（正则标记）
    │
    ▼
[ai_engine.py] 分段调用 Claude API（8段）
    ├── 段1~8 依次调用，流式输出
    └── 每段完成后写入进度文件
    │
    ▼
[validator.py] 数据验证
    ├── CrossRef API 验证论文真实性
    └── 数值交叉核验，标记 ❗
    │
    ▼
[exporter.py] 生成 Markdown 文件
    ├── 拼接 YAML Front Matter
    ├── 按规则生成文件名
    └── 保存到 {根目录}/{年月}/文件名.md
    │
    ▼
[history.py] 写入历史记录
    └── 更新 data/history.json
```

---

## 附录 B：文件命名示例

| 输入论文 | 生成文件名 |
|---------|----------|
| Attention Is All You Need (Vaswani, 2017) | `2017_Vaswani_Transformer.md` |
| RT-2: Vision-Language-Action Models (Brohan, 2023) | `2023_Brohan_RT2_VLA.md` |
| Diffusion Policy (Chi, 2023) | `2023_Chi_DiffusionPolicy.md` |
| OpenVLA: An Open-Source Vision-Language-Action Model (Kim, 2024) | `2024_Kim_OpenVLA.md` |

---

*文档版本：v1.0 | 生成日期：2026-04-17 | 周芷若 · 武汉理工大学*
