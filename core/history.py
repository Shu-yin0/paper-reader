"""
core/history.py — 历史记录模块

职责：读写 data/history.json，记录每篇论文的处理状态与输出路径。
应用启动时调用 init_data_dir() 确保目录和文件存在。
"""

import json
import uuid
from datetime import datetime
from pathlib import Path

HISTORY_PATH = Path("data/history.json")


def init_data_dir():
    """应用启动时调用，确保数据目录与历史文件存在。"""
    Path("data/progress").mkdir(parents=True, exist_ok=True)
    if not HISTORY_PATH.exists():
        HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        _save([])


def _load() -> list:
    if not HISTORY_PATH.exists():
        return []
    try:
        return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(records: list):
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def add_record(
    title: str,
    file_path: str,
    output_file: str = None,
    status: str = "processing",
    crossref_verified: bool = False,
    num_values_flagged: int = 0,
) -> str:
    """添加新历史记录，返回生成的 uuid id。"""
    records = _load()
    record_id = str(uuid.uuid4())
    records.append(
        {
            "id": record_id,
            "title": title[:40],
            "file_path": str(file_path),
            "output_file": str(output_file) if output_file else None,
            "status": status,
            "crossref_verified": crossref_verified,
            "num_values_flagged": num_values_flagged,
            "created_at": datetime.now().isoformat(),
            "completed_at": None,
        }
    )
    _save(records)
    return record_id


def update_record(record_id: str, **kwargs):
    """更新指定 id 的历史记录字段。"""
    records = _load()
    for r in records:
        if r["id"] == record_id:
            r.update(kwargs)
            if kwargs.get("status") == "done":
                r["completed_at"] = datetime.now().isoformat()
            break
    _save(records)


def get_all() -> list:
    """返回全部历史记录（最新在前）。"""
    return list(reversed(_load()))


def delete_record(record_id: str):
    """删除指定历史记录。"""
    records = [r for r in _load() if r["id"] != record_id]
    _save(records)


def get_incomplete_records() -> list:
    """返回疑似未完成的记录（status 为 processing，说明上次未正常退出）。"""
    return [r for r in _load() if r.get("status") == "processing"]
