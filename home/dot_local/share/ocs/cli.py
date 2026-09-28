"""OpenCode を OS のアクセス制御で囲って起動する (CHG-0004 段階 2)。

``srt -s <境界> -c "opencode --standalone"`` の形で、TUI とサーバを同じ
プロセスのまま境界の内側へ入れる。境界をまたぐ接続が無いので成立する。
see docs/change/closed/0004-opencode-sandbox.md

**このスクリプトは境界が張られる前にホストで動く。** したがって:

- 実体は絶対パスで呼ぶ (PATH の差し替えを防ぐ)
- ワークスペース内のコード (mise タスク・シェル設定) を経由しない
- 境界の設定は ``denyWrite`` で保護された生成物だけを読む

失敗したら**起動しない**。素の OpenCode へ落とすと境界にならない。
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
import tempfile
import time
from pathlib import Path

from . import backup, boundary, check, config, session
from .common import HOME, OPENCODE, die

# 境界の設定を渡す場所。★ワークスペースの外に置くこと。
#   tempfile の既定は TMPDIR に従い、TMPDIR はワークスペース内を指している。
#   そこは allowWrite 領域なので、srt が読む前に**内側から書き換えられる**
#   (同一 UID では 0600 でも別セッションを隔離できない)。
#   さらに execve のため finally が走らず、残骸が溜まり続けていた (実測 19 個)。
BOUNDARIES = HOME / ".local/state/opencode-sandbox/boundaries"
# 残骸の掃除。execve で消せないので、次回起動時に古いものを捨てる。
BOUNDARY_MAX_AGE_SECONDS = 24 * 60 * 60


def inner_env(sandbox: dict, project: dict) -> dict[str, str]:
    """境界の内側へ渡す環境変数。継承する資格情報を落とす。"""
    drop = {
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "GH_ENTERPRISE_TOKEN",
        "SSH_AUTH_SOCK",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "OPENCODE_CONFIG",
        "OPENCODE_CLI_CONFIG_CONTENT",
    }
    env = {k: v for k, v in os.environ.items() if k not in drop}
    # ★XDG_DATA_HOME を永続領域へ向けないと snapshot が境界終了時に消える。
    #   捕捉は成功したように見えるので気づけない。
    env["XDG_DATA_HOME"] = project["data_home"]
    env["OPENCODE_DB"] = project["db"]
    env["OPENCODE_CONFIG_DIR"] = sandbox["config_dir"]
    env["OCS_ISOLATED"] = "1"
    return env


def inner_command(passthrough: list[str], path: str) -> str:
    """境界の内側で走らせるコマンド文字列を組み立てる。

    ★``srt -c`` はコマンド文字列を 1 個しか取らない。追加の引数を後ろへ
      並べても srt の位置引数になり、**エラーも出さずに捨てられる**
      (``ocs --continue`` が素の起動になっていた)。渡したい引数は
      必ずこの文字列の中に入れる。
    ★srt には固定した PATH を渡す (:func:`check.srt_env`)。内側の opencode
      には利用者の ``path`` をここで戻す。

    ``-c`` は「エスケープしない sh -c」なので、こちらで引用符を付ける。
    """
    return shlex.join(
        ["/usr/bin/env", f"PATH={path}", str(OPENCODE), "--standalone", *passthrough]
    )


def resolve_node() -> str:
    """node の実体を返す。**shim を使わない。**

    mise の shim は mise 本体への symlink なので、呼ぶたびに版解決が走り、
    ネットワーク確認で止まることがある (実地で踏んだ)。加えて mise は
    ワークスペース内の設定を読むので、**境界を張る前に可変な入力を
    経由する**ことになり、信頼の鎖が切れる。
    see docs/change/closed/0004-opencode-sandbox.md 「信頼の鎖」
    """
    installs = HOME / ".local/share/mise/installs/node"
    candidates = sorted(
        (p for p in installs.glob("*/bin/node") if p.is_file() and not p.is_symlink()),
        # 24.5.0 のような完全な版を優先し、新しいものから選ぶ
        key=lambda p: (len(p.parent.parent.name.split(".")), p.parent.parent.name),
        reverse=True,
    )
    for path in (*candidates, Path("/usr/bin/node"), Path("/usr/local/bin/node")):
        if path.is_file():
            return str(path)
    die("node の実体が見つからない", "mise install node で入れる")
    raise AssertionError  # die は必ず終了する


def prune_boundaries() -> None:
    """境界設定の残骸を捨てる。

    ★``execve`` はプロセスを置き換えるので ``finally`` が走らない。自分では
    消せないので、**次の起動が前回の分を捨てる**。稼働中のセッションのものを
    消さないよう、古いものだけに絞る。
    """
    cutoff = time.time() - BOUNDARY_MAX_AGE_SECONDS
    for path in BOUNDARIES.glob("opencode-boundary-*.json"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            pass  # 消せなくても起動は妨げない


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
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
    parser.add_argument("--skip-check", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--recheck",
        action="store_true",
        help="前回の合格を使わず、境界チェックをやり直す",
    )
    parser.add_argument(
        "--trust",
        action="store_true",
        help=".opencode/sandbox.toml の要求を確認せず承認する (自動化用)",
    )
    parser.add_argument(
        "--handoff",
        metavar="ID",
        help="隔離セッションをホストの DB へ移す (以後 opencode -s ID で再開できる)",
    )
    parser.add_argument(
        "--list-sessions",
        action="store_true",
        help="隔離用 DB のセッションを並べる (--handoff に渡す ID を選ぶため)",
    )
    args, passthrough = parser.parse_known_args(argv)

    sandbox = boundary.load_boundary()
    runtime = Path(sandbox["runtime_path"])
    if not runtime.is_file():
        die(f"srt が無い: {runtime}")
    if not OPENCODE.is_file():
        die(f"opencode が無い: {OPENCODE}")

    # ★管理用の操作は**境界を張らずにホストで動く**。境界の中からは
    #   ホストの DB へ書けないので、移送は外側でしかできない。
    #   起動ディレクトリの検査も要らない (境界を作らないため)。
    if args.list_sessions:
        return session.list_isolated_sessions(Path.cwd().resolve())
    if args.handoff:
        return session.handoff_session(Path.cwd().resolve(), args.handoff)

    node = resolve_node()

    # ★起動ディレクトリ以下は無条件に許可する。どこで起動するかは利用者の責務。
    #   追加の許可は <起動ディレクトリ>/.opencode/sandbox.toml で**要求**され、
    #   人が承認して初めて効く。リポジトリは付与できない。
    workspace = Path.cwd().resolve()
    # ★境界を組み立てる前に、境界を無意味にする起動ディレクトリを弾く。
    boundary.reject_unsafe_workspace(sandbox, workspace)
    # ★要求は**ここで一度だけ**読む。承認と適用で読み直すと、間に書き換え
    #   られたとき「承認していない許可が境界へ入る」ことになる。
    request = boundary.read_request(workspace)
    # ★境界を組み立てる前に承認を通すこと。順序を逆にすると、未承認の要求で
    #   境界を張ってから尋ねることになる。
    boundary.ensure_trusted(workspace, args.trust, request)
    project = {
        "workspace": str(workspace),
        "config": boundary.build_boundary(sandbox, workspace, request),
        **boundary.workspace_paths(sandbox, workspace),
    }

    backup.backup_worktree(workspace, args.no_backup)
    Path(project["data_home"]).mkdir(parents=True, exist_ok=True)
    config.write_isolated_config(sandbox, project)
    session.seed_db(Path(project["db"]))
    project["config"]["ripgrep"] = {"command": check.resolve_ripgrep(project["config"])}

    # 境界の設定は**ワークスペースの外**へ置く (srt は外側で読む)。
    # 内側からは deny_read の ~ 配下で見えないため、読む前の改竄ができない。
    BOUNDARIES.mkdir(parents=True, exist_ok=True)
    os.chmod(BOUNDARIES, 0o700)
    prune_boundaries()
    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", prefix="opencode-boundary-", dir=str(BOUNDARIES), delete=False
    ) as f:
        json.dump(project["config"], f)
        boundary_file = f.name
    os.chmod(boundary_file, 0o600)

    env = inner_env(sandbox, project)
    host_env = check.srt_env(env)
    hidden = check.hidden_targets()
    digest = check.check_digest(sandbox, project["config"], hidden["present"])
    try:
        if not args.skip_check:
            # ★fail-closed。検査スクリプトが無ければ**起動しない**。
            #   以前は `and CHECK.is_file()` で、配備の失敗やファイル消失が
            #   「検査を飛ばして起動」に化けていた。境界を張れないなら
            #   起動しない、という方針とここだけ逆向きだった。
            if not check.CHECK.is_file():
                die(
                    f"境界チェックが無い: {check.CHECK}",
                    "chezmoi apply で配備する。検査を省くなら --skip-check を明示する。",
                )
            # ★入力が 1 つでも変われば digest が変わり、再検査になる。
            #   有効期間を過ぎたときも同じ。合格を無期限には使わない。
            if not args.recheck and check.check_is_fresh(digest):
                print("境界チェック: 前回の合格を再利用 (--recheck でやり直す)", file=sys.stderr)
            else:
                check.run_check(node, runtime, boundary_file, project, env, hidden)
                check.save_check(digest)

        os.execve(
            node,
            [
                node,
                str(runtime),
                "-s",
                boundary_file,
                "-c",
                inner_command(passthrough, env.get("PATH", check.SRT_PATH)),
            ],
            host_env,
        )
    finally:
        # execve が成功するとここは走らない (その場合 srt が読み終えている)
        Path(boundary_file).unlink(missing_ok=True)
    return 0
