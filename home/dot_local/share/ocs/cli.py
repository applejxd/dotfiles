"""OpenCode を OS のアクセス制御で囲って起動する (隔離起動 ``ocs``)。

``fence --settings <境界> -- opencode --standalone`` の形で、TUI とサーバを同じ
プロセスのまま境界の内側へ入れる。

**このスクリプトは境界が張られる前にホストで動く。** 失敗したら**起動しない**。
素の OpenCode へ落とすと境界にならない。
see docs/spec/opencode-sandbox.md
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from pathlib import Path

from . import backup, boundary, check, config
from .common import HOME, OPENCODE, STATE, die

# 境界の設定を渡す場所。★ワークスペースの外に置くこと (内側から書き換えられない場所)。
BOUNDARIES = STATE / "boundaries"
# Fence がホスト側で使う TMPDIR (seccomp のフィルタとプロキシのソケット)
FENCE_TMP = STATE / "tmp"
# 残骸の掃除。execve で消せないので、次回起動時に古いものを捨てる。
BOUNDARY_MAX_AGE_SECONDS = 24 * 60 * 60
# Fence は起動時に seccomp のフィルタを書いて直後に開く。それより古いものは要らない。
SECCOMP_MAX_AGE_SECONDS = 10 * 60
# 内側の XDG_STATE_HOME (内側の /tmp は tmpfs で、終了時に消える)
INNER_STATE = "/tmp/xdg-state"
# 境界の内側へ渡さない環境変数 (資格情報と、OpenCode の DB・設定の差し替え)
DROP_ENV = (
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "GH_ENTERPRISE_TOKEN",
    "SSH_AUTH_SOCK",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "OPENCODE_CONFIG",
    "OPENCODE_CLI_CONFIG_CONTENT",
    "OPENCODE_DB",
)


def inner_env(sandbox: dict) -> dict[str, str]:
    """境界の内側へ渡す環境変数。

    ``XDG_DATA_HOME`` は変えない (DB と snapshot をホストと共有する)。
    ``OPENCODE_DB`` は落とす。残ると常駐サービスと別の DB を使う。
    """
    env = {k: v for k, v in os.environ.items() if k not in DROP_ENV}
    env["OPENCODE_CONFIG_DIR"] = sandbox["config_dir"]
    env["OCS_ISOLATED"] = "1"
    return env


def opencode_data_dir() -> Path:
    """OpenCode のデータディレクトリ (DB・snapshot・ログ)。境界の内側から書けるようにする。"""
    data_home = os.environ.get("XDG_DATA_HOME") or ""
    root = Path(data_home) if os.path.isabs(data_home) else HOME / ".local/share"
    return root / "opencode"


def inner_command(passthrough: list[str], path: str) -> list[str]:
    """境界の内側で走らせるコマンド。

    Fence は固定した PATH と状態領域の TMPDIR で動かす (:func:`check.host_env`)。
    内側の opencode には利用者の PATH と ``/tmp`` をここで戻す。
    ``XDG_STATE_HOME`` は内側の ``/tmp`` へ向ける (``~/.local/state`` は開けないので、
    そのままでは opencode が起動時に作るディレクトリを作れない)。
    """
    return [
        "/usr/bin/env",
        f"PATH={path}",
        "TMPDIR=/tmp",
        f"XDG_STATE_HOME={INNER_STATE}",
        str(OPENCODE),
        "--standalone",
        *passthrough,
    ]


def _prune(pattern: Path, max_age: int) -> None:
    cutoff = time.time() - max_age
    for path in pattern.parent.glob(pattern.name):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            pass  # 消せなくても起動は妨げない


def prune_leftovers() -> None:
    """境界の設定と seccomp のフィルタの残骸を捨てる。

    ★``execve`` はプロセスを置き換えるので自分では消せない。次の起動が前回の分を
    捨てる。並行して動いているセッションの分を消さないよう、古いものだけに絞る。
    """
    _prune(BOUNDARIES / "opencode-boundary-*.json", BOUNDARY_MAX_AGE_SECONDS)
    _prune(FENCE_TMP / "fence-seccomp" / "fence-seccomp-*.bpf", SECCOMP_MAX_AGE_SECONDS)


def write_boundary(config_: dict) -> str:
    """境界の設定を**ワークスペースの外**へ書き、パスを返す。"""
    for directory in (BOUNDARIES, FENCE_TMP):
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
    prune_leftovers()
    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", prefix="opencode-boundary-", dir=str(BOUNDARIES), delete=False
    ) as f:
        json.dump(config_, f)
        boundary_file = f.name
    os.chmod(boundary_file, 0o600)
    return boundary_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "ここで解釈しない引数は opencode へそのまま渡す。"
            "例: ocs --continue / ocs --session ses_xxx"
        ),
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="起動前の退避をしない (壊した未コミットの変更は戻せなくなる)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="起動せず、この起動ディレクトリの境界を内側から検査する",
    )
    args, passthrough = parser.parse_known_args(argv)

    sandbox = boundary.load_boundary()
    runtime = Path(sandbox["runtime_path"])
    if not runtime.is_file():
        die(f"Fence が無い: {runtime}", "mise install で入れる")
    if not OPENCODE.is_file():
        die(f"opencode が無い: {OPENCODE}")

    # ★起動ディレクトリ以下は無条件に書ける。境界を組み立てる前に広すぎる場所・制御ファイルの
    #   置き場・保護対象の中を弾く。
    workspace = Path.cwd().resolve()
    boundary.reject_unsafe_workspace(sandbox, workspace)
    request = boundary.read_request(workspace)
    boundary.reject_control_dirs(sandbox, workspace, request)
    boundary.reject_protected_workspace(sandbox, workspace, request)
    boundary.announce_request(request)
    data_dir = opencode_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    # 境界は無いパスを落とすので、初回に allowRead から抜けないよう組む前に作る
    Path(sandbox["config_dir"]).mkdir(parents=True, exist_ok=True)
    project = {
        "workspace": str(workspace),
        "data_dir": str(data_dir),
        "db": str(data_dir / "opencode.db"),
        "config": boundary.build_boundary(sandbox, workspace, request, data_dir),
    }
    env = inner_env(sandbox)

    if args.check:
        boundary_file = write_boundary(project["config"])
        try:
            return check.run_check(runtime, boundary_file, project, env, FENCE_TMP)
        finally:
            Path(boundary_file).unlink(missing_ok=True)

    backup.backup_worktree(workspace, args.no_backup)
    config.write_isolated_config(sandbox, project)
    boundary_file = write_boundary(project["config"])
    try:
        os.execve(
            str(runtime),
            [
                str(runtime),
                "--settings",
                boundary_file,
                "--",
                *inner_command(passthrough, env.get("PATH", check.HOST_PATH)),
            ],
            check.host_env(env, FENCE_TMP),
        )
    finally:
        # execve が成功するとここは走らない (その場合 Fence が読み終えている)
        Path(boundary_file).unlink(missing_ok=True)
    return 0
