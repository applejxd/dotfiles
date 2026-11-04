#!/usr/bin/env python3
"""ローカル PR ビューアの起動・常駐（systemd user ユニット）・tailnet への公開を扱う。

    python3 scripts/pr_app.py serve [<リポジトリ>…]      前面で起動する（止めるのは Ctrl+C。OS を問わない）
    python3 scripts/pr_app.py install [<リポジトリ>…]    pr-viewer.service を作って enable --now（Linux のみ）
    python3 scripts/pr_app.py uninstall | restart | logs | status
    python3 scripts/pr_app.py expose | unexpose          tailnet へ HTTPS で出す／やめる（tailscale serve。Funnel は使わない）

設定ファイル（既定 ~/.config/pr-viewer/env。`PRAPP_ENV_FILE` で変更）は systemd の EnvironmentFile 形式。
キー: PRAPP_ALLOW_MERGE・PRAPP_ALLOW_CREATE・PRAPP_PORT・PRAPP_REPOS・PRAPP_ROOT。
呼び出し側の環境変数が設定ファイルより優先する。**権限の旗は既定で全部無効**（`1` のときだけ `--allow-*` を付ける）。
起動元は、このスクリプトが入っているチェックアウトの根（`PRAPP_ROOT` で上書き可）。`apps/pr-viewer/server.ts` が無ければ停止する。
`PRAPP_DRY_RUN=1` では systemd・tailscale を触らず、ユニットの内容と実行するコマンドを表示するだけ。
常駐（`serve --pinned`。ユニットが使う）は、起動元の `develop` を `.tmp/pr-app/current/` へ書き出した版から動く。
`restart` のときだけ、その版を作り直す。仕様: docs/spec/pr-viewer.md#稼働版の固定。
仕様: docs/spec/pr-viewer.md#6-アプリ。終了コード: 0 = 成功、2 = 使い方・前提の不足。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path

UNIT = "pr-viewer.service"
KEYS = (
    "PRAPP_ALLOW_MERGE",
    "PRAPP_ALLOW_CREATE",
    "PRAPP_PORT",
    "PRAPP_REPOS",
    "PRAPP_ROOT",
)
DEFAULT_PORT = "8780"
# 稼働版として書き出す ref と範囲（サーバが読むのは apps/pr-viewer と、そこから import する harness だけ）
PIN_REF = "develop"
PIN_PATHS = ("apps/pr-viewer", "home/dot_config/pi/harness")
PIN_FILE = "PINNED.json"
WSL_TAILSCALE = "/mnt/c/Program Files/Tailscale/tailscale.exe"
EXIT_USAGE = 2

USAGE = """使い方: pr_app.py <サブコマンド> [リポジトリのパス…]
  serve [リポジトリ…]    前面で起動する（既定は設定ファイルの PRAPP_REPOS → 起動元）。作業ツリーをそのまま使う
  serve --pinned …       稼働版（.tmp/pr-app/current）から起動する（ユニットが使う。無ければ作る）
  install [リポジトリ…]  systemd の user ユニットを作って enable --now（Linux のみ）
  restart                稼働版を develop の先頭で作り直して再起動する / logs / uninstall / status
  expose / unexpose      tailnet へ HTTPS で出す／やめる（tailscale serve。Funnel は使わない）
PRAPP_DRY_RUN=1 で、systemd・tailscale を触らずに内容とコマンドだけ表示する。
"""


class Stop(Exception):
    """理由を表示して終了コード 2 で止める。"""


def dry_run() -> bool:
    return os.environ.get("PRAPP_DRY_RUN") == "1"


def is_linux() -> bool:
    return sys.platform.startswith("linux")


def env_file() -> Path:
    return Path(os.environ.get("PRAPP_ENV_FILE") or Path.home() / ".config" / "pr-viewer" / "env")


def unit_dir() -> Path:
    return Path.home() / ".config" / "systemd" / "user"


def default_root() -> Path:
    return Path(__file__).resolve().parents[1]


def read_env_file(path: Path) -> dict[str, str]:
    """設定ファイルの KEY=VALUE を読む（同じキーは後勝ち。値の前後の二重引用符は外す）。"""
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if key not in KEYS:
            continue
        if len(val) >= 2 and val[0] == val[-1] == '"':
            val = val[1:-1]
        out[key] = val
    return out


def setting(name: str, file_values: dict[str, str]) -> str:
    """呼び出し側の環境（空でないもの）→ 設定ファイルの順で値を返す。"""
    return os.environ.get(name) or file_values.get(name, "")


def resolve_root(file_values: dict[str, str]) -> Path:
    root = Path(setting("PRAPP_ROOT", file_values) or default_root())
    if not (root / "apps" / "pr-viewer" / "server.ts").is_file():
        raise Stop(
            f"アプリ（apps/pr-viewer/server.ts）が見つからない: {root}\n"
            "PRAPP_ROOT に、apps/pr-viewer/ があるチェックアウトの根を指定する（別の worktree へは自動で切り替えない）"
        )
    return root


def require_linux(what: str) -> None:
    if not is_linux():
        raise Stop(f"{what} は Linux（WSL を含む）だけ対応している。前面で起動するなら: serve")


def systemd_quote(text: str) -> str:
    """systemd の ExecStart 用に、空白・引用符・% を含む引数を安全に二重引用符で囲む。"""
    esc = text.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
    return f'"{esc}"'


def unit_text(root: Path) -> str:
    script = root / "scripts" / "pr_app.py"
    ef = env_file()
    default_ef = Path.home() / ".config" / "pr-viewer" / "env"
    env_path = "%h/.config/pr-viewer/env" if ef == default_ef else str(ef).replace("%", "%%")
    return (
        "[Unit]\n"
        "Description=ローカル PR ビューア (pr_app.py)\n"
        "After=network.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"EnvironmentFile=-{env_path}\n"
        "Environment=PATH=%h/.local/bin:%h/.local/share/mise/shims:/usr/local/bin:/usr/bin:/bin\n"
        f"ExecStart=/usr/bin/env python3 {systemd_quote(str(script))} serve --pinned\n"
        "Restart=on-failure\n"
        "RestartSec=5\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def env_text(repos: str, port: str) -> str:
    """新規の設定。権限の旗はすべて無効（0）。"""
    return (
        "# pr_app.py の設定（systemd の EnvironmentFile 形式。変えたら: pr_app.py restart）\n"
        "# 旗は 1 で有効。既定は全部無効。有効にする前に docs/spec/pr-viewer.md の §6 を読む\n"
        "PRAPP_ALLOW_MERGE=0\n"
        "PRAPP_ALLOW_CREATE=0\n"
        f"PRAPP_PORT={port}\n"
        f'PRAPP_REPOS="{repos}"\n'
    )


def write_env(root: Path, repos: list[str]) -> None:
    """設定ファイルを（無ければ）作る。既存は上書きせず、リポジトリを渡されたときだけ PRAPP_REPOS の行を直す。"""
    path = env_file()
    if path.is_file():
        if not repos:
            return
        lines = path.read_text(encoding="utf-8").splitlines()
        new = f'PRAPP_REPOS="{" ".join(repos)}"'
        if any(ln.startswith("PRAPP_REPOS=") for ln in lines):
            lines = [new if ln.startswith("PRAPP_REPOS=") else ln for ln in lines]
        else:
            lines.append(new)
        text = "\n".join(lines) + "\n"
    else:
        text = env_text(" ".join(repos) or str(root), os.environ.get("PRAPP_PORT") or DEFAULT_PORT)
    if dry_run():
        print(f"[dry-run] 設定ファイル {path} へ書く内容:")
        print(text, end="")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)
    print(f"設定ファイルを書いた: {path}")


def run(argv: list[str], *, check: bool = False) -> int:
    """外部コマンドを実行する（ドライランでは表示だけ）。"""
    if dry_run():
        print("[dry-run] " + " ".join(argv))
        return 0
    return subprocess.run(argv, check=check, encoding="utf-8").returncode


def sc(*args: str, check: bool = False) -> int:
    return run(["systemctl", "--user", *args], check=check)


def need_systemd() -> None:
    require_linux("常駐（systemd）")
    if dry_run():
        return
    ok = shutil.which("systemctl") is not None and (
        subprocess.run(
            ["systemctl", "--user", "show-environment"],
            capture_output=True,
            encoding="utf-8",
        ).returncode
        == 0
    )
    if not ok:
        raise Stop(
            "systemctl --user が使えない（WSL は /etc/wsl.conf の [boot] systemd=true が要る）。前面で起動するなら: serve"
        )


def tailscale_bin() -> str:
    found = os.environ.get("PRAPP_TAILSCALE") or shutil.which("tailscale")
    if found:
        return found
    if os.access(WSL_TAILSCALE, os.X_OK):
        return WSL_TAILSCALE
    raise Stop(
        "tailscale が見つからない（PATH か PRAPP_TAILSCALE か WSL の Windows 側のインストール）"
    )


def pin_dir(root: Path) -> Path:
    return root / ".tmp" / "pr-app" / "current"


def read_pin(d: Path) -> dict | None:
    """固定の記録（PINNED.json）。無い・壊れているときは None。"""
    try:
        j = json.loads((d / PIN_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    oid = j.get("oid") if isinstance(j, dict) else None
    return (
        j
        if isinstance(oid, str) and len(oid) == 40 and all(c in "0123456789abcdef" for c in oid)
        else None
    )


def pin_valid(d: Path) -> bool:
    return (
        read_pin(d) is not None
        and (d / "apps" / "pr-viewer" / "server.ts").is_file()
        and (d / "apps" / "pr-viewer" / "web" / "index.html").is_file()
    )


def build_pin(root: Path) -> Path:
    """root の PIN_REF の先頭を git archive で current.new へ書き出す。worktree は作らない（本体の一覧・統合の判定を乱さない）。"""
    git = shutil.which("git")
    if git is None:
        raise Stop("git が見つからない。稼働版を作れない")
    r = subprocess.run(
        [git, "-C", str(root), "rev-parse", "--verify", f"{PIN_REF}^{{commit}}"],
        capture_output=True,
        encoding="utf-8",
        check=False,
    )
    oid = r.stdout.strip()
    if r.returncode != 0 or len(oid) != 40:
        raise Stop(f"{root} に {PIN_REF} が見つからない（稼働版は git のチェックアウトから作る）")
    stage = pin_dir(root).with_name("current.new")
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    try:
        proc = subprocess.Popen(
            [git, "-C", str(root), "archive", "--format=tar", oid, "--", *PIN_PATHS],
            stdout=subprocess.PIPE,
        )
        assert proc.stdout is not None
        with tarfile.open(fileobj=proc.stdout, mode="r|") as tf:
            if hasattr(tarfile, "data_filter"):
                tf.extractall(stage, filter="data")
            else:  # pragma: no cover
                tf.extractall(stage)
        if proc.wait() != 0:
            raise Stop("git archive が失敗した")
        stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        (stage / PIN_FILE).write_text(
            json.dumps({"oid": oid, "ref": PIN_REF, "pinnedAt": stamp}) + "\n", encoding="utf-8"
        )
        if not pin_valid(stage):
            raise Stop(f"{PIN_REF} の先頭に apps/pr-viewer/server.ts と web/ が無い")
    except (tarfile.TarError, OSError) as e:
        shutil.rmtree(stage, ignore_errors=True)
        raise Stop(f"稼働版の書き出しに失敗した: {e}") from e
    except Stop:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return stage


def swap_pin(root: Path, stage: Path) -> None:
    """作った版を current へ入れ替える（古い版は消す）。"""
    cur = pin_dir(root)
    old = cur.with_name("current.old")
    shutil.rmtree(old, ignore_errors=True)
    if cur.exists():
        cur.rename(old)
    stage.rename(cur)
    shutil.rmtree(old, ignore_errors=True)


def cmd_serve(repos: list[str], pinned: bool = False) -> int:
    fv = read_env_file(env_file())
    root = resolve_root(fv)
    port = setting("PRAPP_PORT", fv) or DEFAULT_PORT
    if not port.isdigit():
        raise Stop(f"PRAPP_PORT が数字ではない: {port}")
    repo_list = repos or setting("PRAPP_REPOS", fv).split() or [str(root)]
    flags: list[str] = []
    for name, flag, note in (
        (
            "PRAPP_ALLOW_MERGE",
            "--allow-merge",
            "統合を有効にして起動します。Funnel（公開）を使っていないことを確かめてください",
        ),
        ("PRAPP_ALLOW_CREATE", "--allow-create", "「起票」を有効にして起動します"),
    ):
        if setting(name, fv) == "1":
            flags.append(flag)
            print(f"注意: {note}", file=sys.stderr)
    run_dir = root
    if pinned:
        run_dir = pin_dir(root)
        if not pin_valid(run_dir):
            swap_pin(root, build_pin(root))  # 初回（または壊れているとき）だけ、起動時に作る
        flags += ["--pinned-file", str(run_dir / PIN_FILE)]
        info = read_pin(run_dir) or {}
        print(
            f"稼働版: {info.get('oid', '?')}（{info.get('ref', '?')}・{info.get('pinnedAt', '?')}）",
            flush=True,
        )
    argv = ["node", "apps/pr-viewer/server.ts"]
    for r in repo_list:
        argv += ["--repo", r]
    argv += ["--port", port, *flags]
    if shutil.which("mise"):
        if pinned:
            # 稼働版の場所には mise.toml が無い。本体で node を解決して絶対パスで使う
            w = subprocess.run(
                ["mise", "which", "node"],
                cwd=root,
                capture_output=True,
                encoding="utf-8",
                check=False,
            )
            if w.returncode == 0 and w.stdout.strip():
                argv[0] = w.stdout.strip()
        else:
            argv = ["mise", "exec", "--", *argv]
    print(
        f"起動: http://127.0.0.1:{port}/ （リポジトリ: {' '.join(repo_list)}。止める: Ctrl+C）",
        flush=True,
    )
    os.chdir(run_dir)
    os.execvp(argv[0], argv)
    return 0  # pragma: no cover


def is_linked_worktree(root: Path) -> bool:
    """root が linked worktree か。git が無い・git 管理外なら False（判定できないときは止めない）。"""
    vals = []
    for opt in ("--git-dir", "--git-common-dir"):
        try:
            r = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "--path-format=absolute", opt],
                capture_output=True,
                encoding="utf-8",
                check=False,
            )
        except OSError:
            return False
        if r.returncode != 0:
            return False
        vals.append(r.stdout.strip())
    return vals[0] != vals[1]


def cmd_install(repos: list[str]) -> int:
    need_systemd()
    fv = read_env_file(env_file())
    root = resolve_root(fv)
    if is_linked_worktree(root):
        raise Stop(
            f"linked worktree からは install できない: {root}\n"
            "unit が worktree の絶対パスに固定され、worktree の掃除後に Restart のループになる。"
            "本体のチェックアウトで実行する"
        )
    write_env(root, repos)
    text = unit_text(root)
    target = unit_dir() / UNIT
    if dry_run():
        print(f"[dry-run] {target} へ書く内容:")
        print(text, end="")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        print(f"ユニットを書いた: {target}")
    sc("daemon-reload", check=True)
    sc("enable", "--now", UNIT, check=True)
    sc("--no-pager", "status", UNIT)
    print("WSL でログアウト後も動かすなら（1 回だけ）: sudo loginctl enable-linger $USER")
    return 0


def cmd_uninstall() -> int:
    need_systemd()
    sc("disable", "--now", UNIT)
    target = unit_dir() / UNIT
    if dry_run():
        print(f"[dry-run] rm -f {target}")
    else:
        target.unlink(missing_ok=True)
    sc("daemon-reload")
    print(f"削除した（設定ファイル {env_file()} は残している）")
    return 0


def cmd_restart() -> int:
    need_systemd()
    fv = read_env_file(env_file())
    root = resolve_root(fv)
    if dry_run():
        print(f"[dry-run] {PIN_REF} の先頭を {pin_dir(root)} へ作り直す")
        sc("restart", UNIT, check=True)
    else:
        stage = build_pin(root)  # 失敗したら、ここで止める（稼働中の版はそのまま）
        sc("stop", UNIT)
        swap_pin(root, stage)
        print(f"稼働版を作り直した: {(read_pin(pin_dir(root)) or {}).get('oid', '?')}")
        sc("start", UNIT, check=True)
    unit = unit_dir() / UNIT
    if unit.is_file() and "--pinned" not in unit.read_text(encoding="utf-8"):
        print(
            "注意: このユニットは旧形式で、稼働版を使わない。本体のチェックアウトで install をやり直す",
            file=sys.stderr,
        )
    sc("--no-pager", "status", UNIT)
    return 0


def cmd_logs() -> int:
    need_systemd()
    return run(["journalctl", "--user", "-u", "pr-viewer", "-f"])


def cmd_expose() -> int:
    require_linux("tailnet への公開")
    ts = tailscale_bin()
    fv = read_env_file(env_file())
    port = setting("PRAPP_PORT", fv) or DEFAULT_PORT
    # Funnel（公開）は使わない。tailscale serve だけ。同じ 443 の古い設定を先に外す
    run([ts, "serve", "--https=443", "off"])
    rc = run([ts, "serve", "--bg", port])
    run([ts, "serve", "status"])
    return rc


def cmd_unexpose() -> int:
    require_linux("tailnet への公開の取り消し")
    ts = tailscale_bin()
    run([ts, "serve", "--https=443", "off"])
    print("tailnet への公開をやめた")
    return 0


def cmd_status() -> int:
    require_linux("status")
    print("== サービス (pr-viewer) ==")
    if dry_run() or shutil.which("systemctl"):
        sc("--no-pager", "status", UNIT)
    else:
        print("systemctl が無い")
    print("== tailnet の公開 ==")
    try:
        run([tailscale_bin(), "serve", "status"])
    except Stop as e:
        print(str(e))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    cmd = args[0] if args else "help"
    rest = args[1:]
    try:
        if cmd == "serve":
            pinned = "--pinned" in rest
            return cmd_serve([a for a in rest if a != "--pinned"], pinned)
        if cmd == "install":
            return cmd_install(rest)
        simple = {
            "uninstall": cmd_uninstall,
            "restart": cmd_restart,
            "logs": cmd_logs,
            "expose": cmd_expose,
            "unexpose": cmd_unexpose,
            "status": cmd_status,
        }
        if cmd in simple:
            return simple[cmd]()
    except Stop as e:
        print(f"停止: {e}", file=sys.stderr)
        return EXIT_USAGE
    print(USAGE, end="")
    return 0 if cmd in ("help", "-h", "--help") else EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
