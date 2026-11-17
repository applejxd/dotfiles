"""タスクの保存先。TB_DATA_DIR(既定 ~/.local/share/taskboard)の tasks.json に書く。"""

from __future__ import annotations

import json
import os
from pathlib import Path


def data_path() -> Path:
    base = os.environ.get("TB_DATA_DIR") or str(Path.home() / ".local" / "share" / "taskboard")
    return Path(base) / "tasks.json"


def load() -> list[dict]:
    path = data_path()
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def save(tasks: list[dict]) -> None:
    path = data_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")
