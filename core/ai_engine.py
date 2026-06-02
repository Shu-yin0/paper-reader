"""
core/ai_engine.py — AI 分析引擎

职责：
1. 分 8 段依次调用 Claude API，流式输出
2. System Prompt 启用 prompt caching（节省重复 token）
3. 每段完成后写入断点续传进度文件
4. 支持从指定段落继续（resume_from）
5. 失败时最多重试 3 次，仍失败则保存进度并退出
"""

import json
import hashlib
import time
from datetime import datetime
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv
import os

load_dotenv()

# ── 配置 ──────────────────────────────────────────────────────────────────────
MODEL_NAME           = os.getenv("MODEL_NAME", "claude-sonnet-4-6")
MAX_TOKENS_PER_SEC   = 2000   # 每段最大输出 token
PROGRESS_DIR         = Path("data/progress")

_client: Anthropic | None = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        base_url = os.getenv("ANTHROPIC_BASE_URL", "").strip()
        if base_url:
            _client = Anthropic(
                api_key=os.getenv("ANTHROPIC_API_KEY", ""),
                base_url=base_url,
                timeout=120.0,   # 中转站响应较慢，给足 120 秒
            )
        else:
            _client = Anthropic(timeout=120.0)
    return _client


# ── 进度文件 ──────────────────────────────────────────────────────────────────

def _progress_path(pdf_path: str) -> Path:
    md5 = hashlib.md5(pdf_path.encode("utf-8")).hexdigest()
    return PROGRESS_DIR / f"{md5}.json"


def load_progress(pdf_path: str) -> dict | None:
    """加载断点进度文件，不存在则返回 None。"""
    p = _progress_path(pdf_path)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def save_progress(
    pdf_path: str,
    sections: dict,
    last_completed: int,
    pdf_text_cache: dict,
    created_at: str = None,
):
    """将当前进度写入 JSON 文件（断点续传用）。"""
    PROGRESS_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "file_path":             pdf_path,
        "file_md5":              hashlib.md5(Path(pdf_path).read_bytes()).hexdigest(),
        "last_completed_section": last_completed,
        "sections": {str(i): sections.get(i) for i in range(1, 9)},
        "pdf_text_cache":        pdf_text_cache,
        "created_at":            created_at or datetime.now().isoformat(),
        "updated_at":            datetime.now().isoformat(),
    }
    _progress_path(pdf_path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def delete_progress(pdf_path: str):
    """分析成功完成后删除进度文件。"""
    p = _progress_path(pdf_path)
    if p.exists():
        p.unlink()


# ── 流式调用 ──────────────────────────────────────────────────────────────────

def _stream_section(system_prompt: str, user_prompt: str):
    """
    单段流式调用 Claude API。
    注意：中转站通常不支持 prompt caching beta 头，故不使用 cache_control。
    """
    client = _get_client()
    with client.messages.stream(
        model=MODEL_NAME,
        max_tokens=MAX_TOKENS_PER_SEC,
        temperature=0.3,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    ) as stream:
        yield from stream.text_stream


# ── 主分析函数 ────────────────────────────────────────────────────────────────

def analyze_paper(
    pdf_path: str,
    sections_text: dict,
    system_prompt: str,
    prompts: dict,
    resume_from: int = 0,
):
    """
    主分析入口，分 8 段依次调用 Claude API。

    参数：
        pdf_path      — PDF 文件路径（用于进度文件命名）
        sections_text — pdf_parser.split_sections() 的返回值（作为进度缓存）
        system_prompt — 共用 System Prompt
        prompts       — {1: str, 2: str, ..., 8: str}，各段 User Prompt
        resume_from   — 从第几段之后继续（0 = 全新开始）

    Yields: (section_num: int, chunk: str)
        section_num 供 GUI 更新进度条；
        chunk 为文字片段（流式）或整段已完成内容（续传时）。
    """
    completed_sections: dict = {}
    created_at = datetime.now().isoformat()

    # 如果是续传，先把已完成的段从进度文件加载进来
    if resume_from > 0:
        prog = load_progress(pdf_path)
        if prog:
            for i in range(1, resume_from + 1):
                txt = prog["sections"].get(str(i))
                if txt:
                    completed_sections[i] = txt
                    yield (i, txt)   # 把已有内容推给 GUI

    # 逐段调用 AI
    for i in range(resume_from + 1, 9):
        # 先 yield 标记，让 app.py 有机会在我们读取 prompts[i] 之前更新它（段6摘要注入）
        yield (i, f"\n\n**▶ 正在生成第 {i} 节…**\n\n")

        user_prompt = prompts.get(i, "")
        if not user_prompt:
            continue

        section_text = ""
        retries = 0
        success = False

        while retries < 3:
            try:
                section_text = ""
                for chunk in _stream_section(system_prompt, user_prompt):
                    section_text += chunk
                    yield (i, chunk)
                success = True
                break
            except Exception as e:
                retries += 1
                err_msg = str(e)
                # 余额不足直接终止
                if "credit" in err_msg.lower() or "billing" in err_msg.lower():
                    yield (i, f"\n\n❌ API Key 余额不足，请充值后重试\n")
                    save_progress(pdf_path, completed_sections,
                                  i - 1, sections_text, created_at)
                    return
                if retries < 3:
                    time.sleep(2 ** retries)  # 指数退避
                else:
                    yield (i, f"\n\n⚠️ AI 请求失败（{err_msg[:200]}），已保存进度，可点击「继续」重试\n")
                    save_progress(pdf_path, completed_sections,
                                  i - 1, sections_text, created_at)
                    return

        if success:
            completed_sections[i] = section_text
            save_progress(pdf_path, completed_sections, i,
                          sections_text, created_at)

    # 所有段完成，清理进度文件
    delete_progress(pdf_path)
    yield (9, "\n\n✅ 分析完成！\n")
