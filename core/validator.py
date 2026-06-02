"""
core/validator.py — 数据真实性验证模块

职责：
1. CrossRef REST API 验证论文真实存在性（通过 DOI 或标题）
2. 数值交叉核验：比对 AI 输出数值与 PDF 原文数值，标记不符项（❗）
"""

import re
import requests

CROSSREF_BASE    = "https://api.crossref.org/works"
CROSSREF_TIMEOUT = 5  # 秒

# DOI 合法格式正则：必须以 10. 开头，后跟注册机构码和后缀
_DOI_RE = re.compile(r'^10\.\d{4,}/\S+$')

# ── 数字提取预编译正则 ─────────────────────────────────────────────────────
_YEAR_PAT = re.compile(r'\b(19|20)\d{2}\b')
_CITE_PAT = re.compile(r'\[\d+\]')
_EQNUM_PAT = re.compile(r'\[EQ_NUM:\d+\]')
_SECNUM_PAT = re.compile(r'\[SEC_NUM:[\d.]+\]')


# ══════════════════════════════════════════════════════════════════════════════
# CrossRef 验证
# ══════════════════════════════════════════════════════════════════════════════

def verify_crossref(doi: str = None, title: str = None) -> dict:
    """
    通过 DOI 或标题查询 CrossRef。

    返回：
    {
      "status":  "verified" | "not_found" | "timeout" | "error",
      "data":    {...} | None,   # 见 _parse_crossref()
      "message": str            # 用于 GUI 显示
    }
    """
    headers = {"User-Agent": "PaperReader/1.0 (mailto:reader@local)"}

    try:
        # 优先用 DOI 精确查询（先验证格式，过滤"原文未提供"等占位符）
        if doi and doi.strip() and _DOI_RE.match(doi.strip()):
            resp = requests.get(
                f"{CROSSREF_BASE}/{doi.strip()}",
                timeout=CROSSREF_TIMEOUT,
                headers=headers,
            )
            if resp.status_code == 200:
                return {
                    "status":  "verified",
                    "data":    _parse_crossref(resp.json()["message"]),
                    "message": "✅ CrossRef 已验证",
                }

        # 标题模糊查询兜底
        if title and title.strip():
            resp = requests.get(
                CROSSREF_BASE,
                params={"query.title": title.strip(), "rows": 1},
                timeout=CROSSREF_TIMEOUT,
                headers=headers,
            )
            if resp.status_code == 200:
                items = resp.json()["message"].get("items", [])
                if items:
                    return {
                        "status":  "verified",
                        "data":    _parse_crossref(items[0]),
                        "message": "✅ CrossRef 已验证",
                    }

        return {
            "status":  "not_found",
            "data":    None,
            "message": "⚠️ CrossRef 未找到，请人工核实",
        }

    except requests.Timeout:
        return {
            "status":  "timeout",
            "data":    None,
            "message": "⚠️ CrossRef 验证超时，跳过",
        }
    except Exception as e:
        return {
            "status":  "error",
            "data":    None,
            "message": f"⚠️ CrossRef 验证失败：{e}",
        }


def _parse_crossref(item: dict) -> dict:
    """从 CrossRef API 响应体提取关键字段。"""
    authors = [
        f"{a.get('given', '')} {a.get('family', '')}".strip()
        for a in item.get("author", [])
    ]
    year = None
    for field in ["published-print", "published-online", "created"]:
        parts = item.get(field, {}).get("date-parts", [[]])
        if parts and parts[0]:
            year = parts[0][0]
            break
    return {
        "title":   (item.get("title") or [""])[0],
        "authors": authors,
        "year":    year,
        "venue":   (item.get("container-title") or [""])[0],
        "doi":     item.get("DOI", ""),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 数值交叉核验
# ══════════════════════════════════════════════════════════════════════════════

def extract_numbers(text: str) -> set:
    """
    从文本中提取实验数值（百分比、小数）。
    排除：年份(1900-2030)、引用编号[N]、公式编号[EQ_NUM:N]、章节编号[SEC_NUM:N]
    """
    # 先清除干扰项
    clean = _EQNUM_PAT.sub('', _SECNUM_PAT.sub('', _CITE_PAT.sub('', text)))
    clean = _YEAR_PAT.sub('', clean)

    nums = set()
    # 百分比数值，如 87.3% 或 91%
    for m in re.finditer(r'(\d+\.?\d*)\s*%', clean):
        nums.add(float(m.group(1)))
    # 纯小数，如 0.856、12.34（排除整数避免噪音过多）
    for m in re.finditer(r'\b\d+\.\d+\b', clean):
        v = float(m.group())
        if not (1900 <= v <= 2030):
            nums.add(v)
    return nums


def cross_validate(ai_section4: str, pdf_experiment_text: str) -> tuple:
    """
    对 AI 生成的第四节（实验分析）进行数值核验。

    返回：(flagged_text: str, summary: str)
    - flagged_text：将不符数值后追加 ❗ 的修改版文本
    - summary：核验摘要行（用于笔记顶部显示）
    容差：±0.1（避免四舍五入误报）
    """
    TOLERANCE = 0.1
    ai_nums  = extract_numbers(ai_section4)
    pdf_nums = extract_numbers(pdf_experiment_text)

    flagged = 0
    result  = ai_section4

    # 从大到小替换，避免短数字匹配到长数字中
    for num in sorted(ai_nums, reverse=True):
        if not any(abs(num - p) <= TOLERANCE for p in pdf_nums):
            # 只替换第一次出现，避免误伤相同数字的正确出现
            result = result.replace(str(num), f"{num} ❗", 1)
            flagged += 1

    total   = len(ai_nums)
    summary = (
        f"> 🔍 数值核验：共提取 {total} 个数值，"
        f"{flagged} 个与原文不符（已用 ❗ 标注）"
    )
    return result, summary
