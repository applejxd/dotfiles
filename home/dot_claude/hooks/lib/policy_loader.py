"""``~/.config/agents/command_policy.py`` (chezmoi 管理) を import する。

``AGENTS_CONFIG_DIR`` で差し替え可能 (テスト・コンテナから repo の実体を指すため)。
import に失敗しても例外は送出しない。拒否するかどうか (fail-closed) は
呼び出し側の hook が ``PolicyImport.error`` を見て決める。
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from types import ModuleType


@dataclass(frozen=True)
class PolicyImport:
    module: ModuleType | None
    agents_dir: str
    error: str | None


def agents_config_dir() -> str:
    override = os.environ.get("AGENTS_CONFIG_DIR")
    if override:
        return override
    config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(config_home, "agents")


@lru_cache(maxsize=1)
def load_policy() -> PolicyImport:
    agents_dir = agents_config_dir()
    sys.path.insert(0, agents_dir)
    try:
        import command_policy
    except Exception as exc:  # pragma: no cover - 構文エラー等も拾う
        return PolicyImport(None, agents_dir, f"{type(exc).__name__}: {exc}")
    return PolicyImport(command_policy, agents_dir, None)
