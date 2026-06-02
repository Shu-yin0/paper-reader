"""
prompts/note_template.py — 笔记 Prompt 模板

职责：
1. SYSTEM_PROMPT：8段 API 调用共用的 System Prompt
2. _SECTION_N_TEMPLATE（N=1~8）：各段 User Prompt 模板
3. _truncate()：文本截断工具函数
4. build_prompts()：填充模板变量，返回 {1: str, ..., 8: str}

修改笔记格式或 AI 提取逻辑时，只需编辑本文件，不用改动业务代码。
"""

from datetime import datetime

# ── 常量 ──────────────────────────────────────────────────────────────────────
MAX_INPUT_CHARS = 3000   # 每段正文输入的最大字符数（约 1500 token）


# ── System Prompt（8段共用，作为 cache_control ephemeral 节省 token）──────────

SYSTEM_PROMPT = """你是一名专业的学术论文分析助手，专注于 VLA、具身智能、强化学习（RL）、World Model、自动驾驶领域。

【输出规则】
1. 使用中文输出。专业术语、模型名称（如 RT-2）、数据集名称（如 RLBench）保留英文。
2. 数学公式使用 Unicode 数学符号直接输出（如 θ = argmax Σ rₜ）。
   严禁使用 LaTeX 语法，严禁输出 $...$ 或 $$...$$。
3. 图表和表格不生成文字内容，仅标注原始页码，格式：见原文第N页图M。
4. 输出严格遵循给定的 Markdown 模板格式，不添加额外章节。
5. 不编造数据，不过度推断，如信息不足请注明"原文未明确说明"。"""


# ── 各段 User Prompt 模板 ─────────────────────────────────────────────────────

_SECTION_1_TEMPLATE = """请从以下论文首页文本中提取基本信息，以 Markdown 表格格式输出。

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
| **关键词** | （论文原始关键词，将由第八节标签自动更新） |
| **研究方法** | （一句话概括核心技术路线，如"基于Transformer的端到端VLA模型"） |
| **阅读日期** | {today_date} |
| **来源链接/DOI** | （DOI 字符串或 URL） |
| **代码仓库** | （GitHub 链接，无则填"原文未提供"） |"""


_SECTION_2_TEMPLATE = """请基于以下论文 Introduction 内容，生成"研究背景与问题定义"章节。

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
- [ ] 贡献3：（如有）"""


_SECTION_3_TEMPLATE = """请基于以下论文方法部分，生成"方法详解"章节。

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
| 推理效率 | | |"""


_SECTION_4_TEMPLATE = """请基于以下论文实验部分，生成"实验分析"章节。

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
（描述 case study 规律；图表标注页码）"""


_SECTION_5_TEMPLATE = """请基于以下论文结论部分，生成"结论与局限性"章节。

【论文结论部分文本】
{conclusion_text}

请严格按以下格式输出：

## 五、结论与局限性

### 5.1 作者结论
（总结结论段，2~3条要点）

### 5.2 局限性与未来工作
- **作者指出的局限：**
- **我认为的局限：**（客观分析，1~2条）
- **未来方向：**"""


_SECTION_6_TEMPLATE = """请基于以下笔记摘要，从学术研究视角生成"研究评述与延伸"章节。

【已生成笔记摘要】
{summary_of_previous_sections}

请严格按以下格式输出：

## 六、研究评述与延伸

### 6.1 核心创新点总结
（用简洁语言概括本文最核心的技术贡献，不超过120字）

### 6.2 当前热门研究方向关联
列出与本文直接相关的2~3个当前热门研究方向，每条说明该方向的研究现状与本文的定位。

- **方向1：**（方向名称）
  - 研究现状：
  - 本文定位：

- **方向2：**（方向名称）
  - 研究现状：
  - 本文定位：

### 6.3 可借鉴的思路与改进方向
- **可借鉴的思路：**（本文哪些设计思路可迁移到其他任务或场景）
- **可能的改进方向：**（指出本文方法的不足，提出具体可行的改进思路）
- **是否值得复现？** 是 / 否，理由：

### 6.4 推荐进一步完善的研究点
列出2~3个基于本文可以继续深入的具体研究点，给出可行性说明。

- **研究点1：**（具体描述）
  - 可行性与思路：

- **研究点2：**（具体描述）
  - 可行性与思路：

### 6.5 开放问题
- 问题1：
- 问题2："""


_SECTION_7_TEMPLATE = """请从以下参考文献中，筛选出与本文最密切相关的5篇论文，重点标注本文所改进或基于的基础架构。

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
| （标题，作者，年份） | 延伸阅读推荐 |"""


_SECTION_8_TEMPLATE = """请从论文内容中提取5~8个关键词标签，生成"关键词标签"章节。

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

---"""


# ── 模板映射 ──────────────────────────────────────────────────────────────────

_TEMPLATES = {
    1: _SECTION_1_TEMPLATE,
    2: _SECTION_2_TEMPLATE,
    3: _SECTION_3_TEMPLATE,
    4: _SECTION_4_TEMPLATE,
    5: _SECTION_5_TEMPLATE,
    6: _SECTION_6_TEMPLATE,
    7: _SECTION_7_TEMPLATE,
    8: _SECTION_8_TEMPLATE,
}


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _truncate(text: str, max_chars: int = MAX_INPUT_CHARS) -> str:
    """
    文本截断：超出 max_chars 时保留前段并追加省略说明。
    优先保留靠前内容（摘要/方法核心段）。
    """
    if not text or len(text) <= max_chars:
        return text or ""
    return text[:max_chars] + "\n\n[…内容已截断，超出输入预算…]"


# ── 主函数 ────────────────────────────────────────────────────────────────────

def build_prompts(
    sections_text: dict,
    crossref_data: dict = None,
    previous_summary: str = "",
) -> dict:
    """
    填充所有段的 Prompt 变量，返回 {1: str, 2: str, ..., 8: str}。

    参数：
        sections_text    — pdf_parser.split_sections() 的返回值
        crossref_data    — verify_crossref() 返回的 data 字段（可为 None）
        previous_summary — 前5段笔记的压缩摘要（用于段6，可为空）
    """
    today = datetime.now().strftime("%Y-%m-%d")
    cr_str = str(crossref_data) if crossref_data else "（未查询到 CrossRef 数据）"

    return {
        1: _TEMPLATES[1].format(
            first_page_text=_truncate(sections_text.get("first_page", ""), 2000),
            crossref_data=cr_str,
            today_date=today,
        ),
        2: _TEMPLATES[2].format(
            introduction_text=_truncate(sections_text.get("intro", "")),
        ),
        3: _TEMPLATES[3].format(
            method_text=_truncate(sections_text.get("method", "")),
        ),
        4: _TEMPLATES[4].format(
            experiment_text=_truncate(sections_text.get("experiment", "")),
        ),
        5: _TEMPLATES[5].format(
            conclusion_text=_truncate(sections_text.get("conclusion", ""), 2000),
        ),
        6: _TEMPLATES[6].format(
            summary_of_previous_sections=_truncate(previous_summary, 2000),
        ),
        7: _TEMPLATES[7].format(
            references_text=_truncate(sections_text.get("references", "")),
        ),
        8: _TEMPLATES[8].format(
            keywords=sections_text.get("full_text", "")[:500],
        ),
    }
