"""pi を Fence で囲って起動する (``ocs --harness pi``)。

境界の組み立て・危険な起動場所の拒否・起動前の退避は OpenCode と共通 (``boundary`` / ``backup``)。
ここは pi だけの部分: 境界用の agent 置き場の作成、起動コマンド、内側へ渡さない環境変数。

pi は設定と認証を読むときにも隣へ ``.lock`` を作るので、agent 置き場は書ける必要がある。
一方、本物の ``~/.pi/agent`` を境界に入れると、内側で作られた拡張を外の通常の pi が読む。
そこで**起動ごとに境界用の agent 置き場を作り**、認証・モデルの一覧・設定を写す。
see docs/spec/pi-harness.md#境界
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from .common import HOME, die

RULES = HOME / ".config/pi/harness/rules.json"
HARNESS = HOME / ".config/pi/harness"
PI = HOME / "bin/pi"
REAL_AGENT = HOME / ".pi/agent"
# 境界用の agent 置き場の親。境界の内側から読み書きできる場所 (ocs の状態領域は見えない)。
# ★ここ全体ではなく、起動ごとの 1 つだけを書き込み可能にする。
AGENT_HOME = HOME / ".local/share/pi-sandbox"
AGENT_MAX_AGE_SECONDS = 3 * 24 * 60 * 60
# 本物から写すファイル。認証の写しは更新されても本物へ戻らない
COPY_FILES = ("auth.json", "models-store.json", "settings.json")
# 内側から書き換えられたくないもの (pi が読むだけ)。無いと denyWrite が効かないので作っておく
FROZEN_FILES = ("settings.json", "trust.json", "mcp.json")
FROZEN_DIRS = ("extensions",)
# 境界の内側へ渡さない環境変数。子エージェントの印は自分で付け直す
DROP_ENV = (
    "PI_CODING_AGENT_DIR",
    "PI_HARNESS_CHILD",
    "PI_HARNESS_TEST_CHILD_EXT",
    "PI_HARNESS_BOUNDARY",
)


def check_installed() -> None:
    for path, hint in (
        (PI, "pi を入れる (chezmoi apply)"),
        (HARNESS / "index.ts", "chezmoi apply でハーネスを配る"),
        (RULES, "chezmoi apply でハーネスを配る"),
    ):
        if not path.is_file():
            die(f"{path} が無い", hint)


def _prune_agents(home: Path) -> None:
    """古い境界用の agent 置き場を捨てる。並行して動いているものを消さないよう、古いものだけ。"""
    if not home.is_dir():
        return
    cutoff = time.time() - AGENT_MAX_AGE_SECONDS
    for path in home.glob("agent-*"):
        try:
            if path.stat().st_mtime < cutoff:
                shutil.rmtree(path)
        except OSError:
            pass  # 消せなくても起動は妨げない


def prepare_agent_dir(real: Path | None = None, home: Path | None = None) -> Path:
    """境界用の agent 置き場を作り、本物から必要なものだけを写す。

    既定の置き場は呼び出しのときに引く (定義時に固定すると、差し替えが効かない)。
    """
    real = real if real is not None else REAL_AGENT
    home = home if home is not None else AGENT_HOME
    home.mkdir(parents=True, exist_ok=True)
    os.chmod(home, 0o700)
    _prune_agents(home)
    agent = Path(tempfile.mkdtemp(prefix="agent-", dir=str(home)))
    for name in COPY_FILES:
        source = real / name
        if source.is_file():
            shutil.copy2(source, agent / name)
    for name in FROZEN_FILES:
        if not (agent / name).exists():
            (agent / name).write_text("{}\n", encoding="utf-8")
    for name in FROZEN_DIRS:
        (agent / name).mkdir(exist_ok=True)
    return agent


def frozen_paths(agent: Path) -> list[str]:
    """境界で書き込みを塞ぐ、境界用 agent 置き場の中の設定・拡張。"""
    return [str(agent / n) for n in (*FROZEN_FILES, *FROZEN_DIRS)]


def sessions_dir(workspace: Path, real: Path | None = None) -> Path:
    """この作業ディレクトリのセッションの置き場。外の ``pi -c`` と同じ場所にする (再開できる)。

    pi は ``sessions/--<作業ディレクトリ>--`` に置く (``dist/core/session-manager.js`` の
    ``getDefaultSessionDirPath``。先頭の区切りを外し、``/`` ``\\`` ``:`` を ``-`` にする)。
    ``--session-dir`` は渡した場所へそのまま置くので、この 1 つだけを開ける。
    """
    safe = re.sub(r"[/\\:]", "-", str(workspace).lstrip("/\\"))
    path = (real if real is not None else REAL_AGENT) / "sessions" / f"--{safe}--"
    path.mkdir(parents=True, exist_ok=True)
    return path


def inner_env(agent: Path) -> dict[str, str]:
    """境界の内側へ渡す環境変数。役割と bypass は ``pis`` が環境変数で渡す。"""
    from .cli import DROP_ENV as COMMON_DROP

    env = {k: v for k, v in os.environ.items() if k not in (*COMMON_DROP, *DROP_ENV)}
    env["PI_CODING_AGENT_DIR"] = str(agent)
    env["PI_HARNESS_BOUNDARY"] = "1"
    return env


def inner_command(passthrough: list[str], path: str, sessions: Path) -> list[str]:
    """境界の内側で走らせるコマンド。``pis`` と同じ形の引数に、セッションの置き場を足す。"""
    from .cli import INNER_STATE

    return [
        "/usr/bin/env",
        f"PATH={path}",
        "TMPDIR=/tmp",
        f"XDG_STATE_HOME={INNER_STATE}",
        str(PI),
        "--no-approve",
        "-nbt",
        "-ne",
        "-e",
        "builtin:mcp",
        "-e",
        str(HARNESS),
        "--session-dir",
        str(sessions),
        *passthrough,
    ]


def _expires(entry: object) -> float:
    value = entry.get("expires") if isinstance(entry, dict) else None
    return float(value) if isinstance(value, (int, float)) else 0.0


def sync_auth_back(agent: Path, real: Path | None = None) -> bool:
    """境界の内側で更新された認証を本物の ``auth.json`` へ戻す。

    OAuth のリフレッシュトークンは更新のたびに入れ替わりうる。写しの中だけで更新されると、
    本物のトークンが失効する。**有効期限が本物より新しいプロバイダの分だけ**戻し、ほかは触らない。
    本物は pi と同じ ``auth.json.lock`` を取って書く。取れなければ戻さない (False)。
    """
    real = real if real is not None else REAL_AGENT
    copy_path, real_path = agent / "auth.json", real / "auth.json"
    try:
        theirs = json.loads(copy_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(theirs, dict):
        return False
    lock = real / "auth.json.lock"
    for _ in range(50):
        try:
            lock.mkdir()
            break
        except FileExistsError:
            time.sleep(0.1)
        except OSError:
            return False
    else:
        return False
    try:
        try:
            ours = json.loads(real_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if not isinstance(ours, dict):
            return False
        changed = False
        for name, entry in theirs.items():
            if entry != ours.get(name) and _expires(entry) > _expires(ours.get(name)):
                ours[name] = entry
                changed = True
        if not changed:
            return False
        tmp = real_path.with_name(real_path.name + ".ocs-tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(ours, f, indent=2)
        os.replace(tmp, real_path)
        return True
    finally:
        with contextlib.suppress(OSError):
            lock.rmdir()


def run(argv: list[str], env: dict[str, str], agent: Path) -> int:
    """境界の内側の pi を子プロセスとして動かし、終わったら認証を本物へ戻して置き場を消す。

    ``execve`` で置き換えると終了後の処理ができない。Ctrl-C は端末が子へも届けるので、
    親は無視して終了を待つ。親が SIGTERM / SIGHUP (端末を閉じた) を受けたら子へ渡し、
    終わるのを待ってから後始末する。
    """
    proc = subprocess.Popen(argv, env=env)
    saved = {
        signal.SIGINT: signal.signal(signal.SIGINT, signal.SIG_IGN),
        signal.SIGTERM: signal.signal(signal.SIGTERM, lambda *_: proc.terminate()),
        signal.SIGHUP: signal.signal(signal.SIGHUP, lambda *_: proc.terminate()),
    }
    try:
        return proc.wait()
    finally:
        for number, handler in saved.items():
            signal.signal(number, handler)
        cleanup(agent)


def cleanup(agent: Path) -> None:
    """認証を戻して、写しを置いた境界用の agent 置き場を消す。"""
    sync_auth_back(agent)
    shutil.rmtree(agent, ignore_errors=True)
