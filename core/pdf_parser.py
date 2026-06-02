"""
core/pdf_parser.py — PDF 解析模块

职责：
1. 文字层提取（pdfplumber）+ OCR 兜底（pytesseract + pdf2image）
2. 双栏论文正确合并文字流（左栏→右栏）
3. 页眉/页脚过滤（顶部5%、底部5%）
4. 章节关键词定位与文本切割
5. 公式编号正则预处理（[EQ_NUM:N]）
"""

import re
import pdfplumber
import pytesseract
from pdf2image import convert_from_path
from pathlib import Path

# ── 配置常量 ───────────────────────────────────────────────────────────────
TESSERACT_CONFIG = r'--oem 3 --psm 6'
TESSERACT_LANG   = 'eng+chi_sim'
PDF2IMAGE_DPI    = 300
CHAR_THRESHOLD   = 200   # 每页平均字符数低于此值 → 判定为扫描版

# 章节标题关键词（用于识别章节边界），按优先级排列
SECTION_KEYWORDS = {
    'abstract':   ['abstract', '摘要'],
    'intro':      ['introduction', '引言', '1. introduction', '1 introduction',
                   '1.introduction'],
    'method':     ['method', 'approach', 'model', 'methodology', '方法',
                   'proposed method', 'our approach', 'framework'],
    'experiment': ['experiment', 'evaluation', 'result', 'ablation', '实验',
                   '评估', 'benchmark', 'performance'],
    'conclusion': ['conclusion', 'discussion', 'limitation', '结论', '讨论',
                   'future work', 'summary'],
    'references': ['references', 'bibliography', '参考文献'],
}


def preprocess_equation_numbers(text: str) -> str:
    """
    将公式编号替换为 [EQ_NUM:N] 标记，防止 AI 将其识别为实验数值。
    同时标记章节编号如 (3.2)。
    """
    # 行末独立括号数字，如 (1) (12)
    text = re.sub(r'\((\d+)\)\s*$', r'[EQ_NUM:\1]', text, flags=re.MULTILINE)
    # Eq.(N) 格式
    text = re.sub(r'Eq\.\s*\((\d+)\)', r'[EQ_NUM:\1]', text)
    # Equation N 格式
    text = re.sub(r'Equation\s+(\d+)', r'[EQ_NUM:\1]', text, flags=re.IGNORECASE)
    # 章节编号如 (3.2)
    text = re.sub(r'\((\d+\.\d+)\)', r'[SEC_NUM:\1]', text)
    return text


def _is_dual_column(page) -> bool:
    """
    判断当前页是否为双栏布局。
    策略：统计词汇 x0 坐标分布，若左右两侧各有超过 30% 的词汇则判定为双栏。
    """
    words = page.extract_words()
    if len(words) < 20:
        return False
    mid = page.width / 2
    left_count  = sum(1 for w in words if w['x0'] < mid - 20)
    right_count = sum(1 for w in words if w['x0'] > mid + 20)
    total = len(words)
    return (left_count / total > 0.3) and (right_count / total > 0.3)


def _extract_page_text(page) -> str:
    """
    从单页提取文字：
    - 过滤页眉（顶部5%）、页脚（底部5%）
    - 双栏时按左栏→右栏顺序合并
    - 使用 page.bbox 取真实坐标，兼容非零原点的 PDF
    """
    try:
        # 用真实 bbox 而非 (0, height)，避免坐标偏移的 PDF 崩溃
        bx0, btop, bx1, bbot = page.bbox
        bh = bbot - btop
        bw = bx1 - bx0
        margin = bh * 0.05
        y0 = btop + margin
        y1 = bbot - margin

        if _is_dual_column(page):
            mid = bx0 + bw / 2
            left_col  = page.crop((bx0, y0, mid, y1))
            right_col = page.crop((mid, y0, bx1, y1))
            left_text  = left_col.extract_text()  or ''
            right_text = right_col.extract_text() or ''
            return left_text + '\n' + right_text
        else:
            cropped = page.crop((bx0, y0, bx1, y1))
            return cropped.extract_text() or ''
    except Exception:
        # 任何裁剪异常兜底：直接提取整页
        try:
            return page.extract_text() or ''
        except Exception:
            return ''


def extract_text_with_pages(pdf_path: str) -> list:
    """
    主入口：提取 PDF 全文，按页返回。
    返回格式：list[{"page": int, "text": str}]
    自动判断是否需要 OCR 兜底。
    """
    page_texts = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            total_chars = 0
            for i, page in enumerate(pdf.pages):
                text = _extract_page_text(page)
                page_texts.append({"page": i + 1, "text": text})
                total_chars += len(text)

            avg_chars = total_chars / max(len(pdf.pages), 1)

            if avg_chars >= CHAR_THRESHOLD:
                return page_texts  # 数字原生 PDF，直接返回
            else:
                return _ocr_fallback(pdf_path)  # 扫描版，切换 OCR

    except Exception as e:
        raise RuntimeError(f"PDF 解析失败：{e}") from e


def _ocr_fallback(pdf_path: str) -> list:
    """pdf2image + pytesseract OCR 兜底（扫描版 PDF）"""
    try:
        images = convert_from_path(pdf_path, dpi=PDF2IMAGE_DPI)
    except Exception as e:
        raise RuntimeError(f"OCR 转图失败（是否安装 Poppler？）：{e}") from e

    results = []
    for i, img in enumerate(images):
        try:
            text = pytesseract.image_to_string(
                img, lang=TESSERACT_LANG, config=TESSERACT_CONFIG
            )
        except Exception:
            text = ''
        results.append({"page": i + 1, "text": text})
    return results


def split_sections(pages: list) -> dict:
    """
    将页面文字按章节分割。
    返回：
    {
      'first_page': str,   # 首页全文（标题、作者、摘要）
      'intro':      str,   # Introduction
      'method':     str,   # Method / Approach
      'experiment': str,   # Experiment / Results
      'conclusion': str,   # Conclusion / Limitation
      'references': str,   # References
      'full_text':  str,   # 全文（用于关键词提取）
    }
    所有文本均已完成公式编号预处理。
    """
    if not pages:
        return {k: '' for k in
                ['first_page', 'intro', 'method', 'experiment',
                 'conclusion', 'references', 'full_text']}

    full_text = preprocess_equation_numbers(
        '\n'.join(p['text'] for p in pages)
    )

    # 定位各章节起始页索引（首次出现）
    section_starts = {}
    for i, page in enumerate(pages):
        lower = page['text'].lower()
        for section, keywords in SECTION_KEYWORDS.items():
            if section not in section_starts:
                for kw in keywords:
                    # 关键词出现在独立行或段首
                    if re.search(r'(^|\n)\s*' + re.escape(kw), lower):
                        section_starts[section] = i
                        break

    def _slice(start_key: str, end_keys: list, default_start: int = 0) -> str:
        """提取从 start_key 章节到 end_keys 中最先出现章节之间的文本"""
        start = section_starts.get(start_key, default_start)
        end = len(pages)
        for ek in end_keys:
            if ek in section_starts and section_starts[ek] > start:
                end = min(end, section_starts[ek])
        return preprocess_equation_numbers(
            '\n'.join(p['text'] for p in pages[start:end])
        )

    return {
        'first_page':  preprocess_equation_numbers(pages[0]['text']),
        'intro':       _slice('intro',      ['method', 'experiment', 'conclusion', 'references']),
        'method':      _slice('method',     ['experiment', 'conclusion', 'references']),
        'experiment':  _slice('experiment', ['conclusion', 'references']),
        'conclusion':  _slice('conclusion', ['references']),
        'references':  _slice('references', []),
        'full_text':   full_text,
    }
