#!/usr/bin/env python3
"""3 OS（Linux / Windows / macOS）共通の隔離 chezmoi apply ＋ 起動スモーク検査。

2 つのモードを持つ:
1. 隔離スモーク（既定、`isolate`）:
   使い捨てディレクトリへ `chezmoi init --force` → `apply --exclude scripts,externals`
   → 残差分 0 件検査 → 生成済みファイルの非破壊起動スモークを実行する。
   実機の `$HOME` を一切書き換えず、`develop` → `main` 昇格ゲートや更新前プレフライトに使う。
2. 宛先検査（`check-dest`）:
   既存の展開先（実 `$HOME` や任意の隔離先）に対し、非破壊の起動スモークだけを実行する。
   `chezmoi_safe_update.py` の本番適用後ヘルスチェック・ロールバック後確認に使う。

see docs/adr/0045-stage3-smoke-promotion-and-safe-update.md
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PI_JSON_TARGETS: tuple[str, ...] = (
    ".pi/agent/settings.json",
    ".pi/agent/mcp.json",
    ".pi/agent/compaction.json",
    ".pi/agent/pi-plan-mode.json",
    ".pi/agent/extensions/pi-permission-system/config.json",
    ".pi/agent/extensions/subagent/config.json",
)


class SmokeError(RuntimeError):
    """スモーク検査の失敗。"""


@dataclass
class StepResult:
    name: str
    status: str  # "passed" | "skipped" | "failed"
    detail: str = ""


@dataclass
class SmokeReport:
    ok: bool
    mode: str
    os_name: str
    source: str
    dest: str
    applied_entries: int = 0
    steps: list[StepResult] = field(default_factory=list)


def _run(
    cmd: Sequence[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int | None = 180,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(cmd),
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        return subprocess.CompletedProcess(list(cmd), 124, stdout, f"timed out after {timeout}s: {stderr}")
    except OSError as exc:
        return subprocess.CompletedProcess(list(cmd), 127, "", f"os error: {exc}")


def _isolated_env(dest: Path) -> dict[str, str]:
    """起動スモークが実機の認証・Bitwarden・SSH 状態に触れない最小環境を作る。"""
    env = dict(os.environ)
    env["HOME"] = str(dest)
    env["USERPROFILE"] = str(dest)
    env["PYTHONUTF8"] = "1"
    for key in (
        "BW_SESSION",
        "SSH_CONNECTION",
        "SSH_CLIENT",
        "SSH_TTY",
        "CHEZMOI",
        "CHEZMOI_ARGS",
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
    ):
        env.pop(key, None)
    return env


def check_destination(dest: Path, *, min_entries: int = 1) -> list[StepResult]:
    """展開済みディレクトリ dest に対して非破壊の整合・起動スモークを実行する。"""
    results: list[StepResult] = []
    dest = dest.resolve()

    if not dest.is_dir():
        results.append(StepResult("dest-exists", "failed", f"ディレクトリが存在しません: {dest}"))
        return results

    # 1. 生成済み Pi JSON ファイル群の構文とルート型
    bad_json: list[str] = []
    checked_json = 0
    for rel in PI_JSON_TARGETS:
        fp = dest / rel
        if not fp.is_file():
            bad_json.append(f"{rel} (missing)")
            continue
        try:
            parsed = json.loads(fp.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            bad_json.append(f"{rel} ({exc})")
            continue
        if not isinstance(parsed, dict):
            bad_json.append(f"{rel} (root is {type(parsed).__name__}, expected object)")
            continue
        checked_json += 1

    if bad_json:
        results.append(StepResult("pi-json", "failed", "; ".join(bad_json)))
    else:
        results.append(StepResult("pi-json", "passed", f"{checked_json} files valid"))

    # 2. git 設定ファイルの構文検査
    git_bin = shutil.which("git")
    git_cfg = dest / ".config" / "git" / "config"
    if not git_cfg.is_file():
        results.append(StepResult("git-config", "failed", ".config/git/config が存在しません"))
    elif not git_bin:
        results.append(StepResult("git-config", "skipped", "git が PATH にありません"))
    else:
        proc = _run([git_bin, "config", "--file", str(git_cfg), "--list"], env=_isolated_env(dest), timeout=20)
        if proc.returncode != 0:
            results.append(StepResult("git-config", "failed", proc.stderr.strip()[:300]))
        else:
            count = len([ln for ln in proc.stdout.splitlines() if ln.strip()])
            results.append(StepResult("git-config", "passed", f"{count} entries"))

    # 3. Vim 起動スモーク（ローカル設定と SSH 接続時の unnamedplus 抑止の両方）
    vimrc = dest / ".vimrc"
    vim_bin = shutil.which("vim")
    if not vimrc.is_file():
        results.append(StepResult("vim-smoke", "failed", ".vimrc が存在しません"))
    elif not vim_bin:
        results.append(StepResult("vim-smoke", "skipped", "vim が PATH にありません"))
    else:
        env_local = _isolated_env(dest)
        p_local = _run([vim_bin, "-Nu", str(vimrc), "-es", "-c", "qa!"], env=env_local, timeout=20)
        env_ssh = dict(env_local, SSH_CONNECTION="192.0.2.1 50000 192.0.2.2 22")
        p_ssh = _run(
            [vim_bin, "-Nu", str(vimrc), "-es", "-c", 'if &clipboard !=# "" | cquit 2 | endif | qa!'],
            env=env_ssh,
            timeout=20,
        )
        if p_local.returncode != 0:
            results.append(StepResult("vim-smoke", "failed", f"local exit {p_local.returncode}: {p_local.stderr.strip()[:240]}"))
        elif p_ssh.returncode != 0:
            results.append(StepResult("vim-smoke", "failed", f"ssh clipboard guard exit {p_ssh.returncode}: {p_ssh.stderr.strip()[:240]}"))
        else:
            results.append(StepResult("vim-smoke", "passed", "local + SSH_CONNECTION guard ok"))

    # 4. OS 別のシェル・補助コマンド起動スモーク
    if os.name == "nt":
        pwsh = shutil.which("pwsh")
        prof = dest / ".config" / "powershell" / "profile.ps1"
        if not prof.is_file():
            results.append(StepResult("pwsh-profile", "failed", ".config/powershell/profile.ps1 が存在しません"))
        elif not pwsh:
            results.append(StepResult("pwsh-profile", "skipped", "pwsh が PATH にありません"))
        else:
            cmd = f'. "{prof}"; Write-Output "SMOKE_PWSH_OK"'
            proc = _run([pwsh, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", cmd], env=_isolated_env(dest), timeout=45)
            if proc.returncode != 0 or "SMOKE_PWSH_OK" not in proc.stdout:
                detail = (proc.stderr.strip() or proc.stdout.strip())[:300]
                results.append(StepResult("pwsh-profile", "failed", f"exit {proc.returncode}: {detail}"))
            else:
                results.append(StepResult("pwsh-profile", "passed", "profile.ps1 loaded"))
    else:
        shellenv = dest / ".config" / "shell" / "shellenv.sh"
        zshenv = dest / ".zshenv"
        pk_bin = dest / ".local" / "bin" / "pk"
        env_unix = _isolated_env(dest)

        bash_bin = shutil.which("bash")
        if not shellenv.is_file():
            results.append(StepResult("bash-shellenv", "failed", ".config/shell/shellenv.sh が存在しません"))
        elif not bash_bin:
            results.append(StepResult("bash-shellenv", "skipped", "bash が PATH にありません"))
        else:
            proc = _run(
                [bash_bin, "--norc", "--noprofile", "-c", '. "$HOME/.config/shell/shellenv.sh" && printf SMOKE_BASH_OK'],
                env=env_unix,
                timeout=20,
            )
            if proc.returncode != 0 or "SMOKE_BASH_OK" not in proc.stdout:
                results.append(StepResult("bash-shellenv", "failed", f"exit {proc.returncode}: {proc.stderr.strip()[:240]}"))
            else:
                results.append(StepResult("bash-shellenv", "passed", "shellenv.sh loaded"))

        zsh_bin = shutil.which("zsh")
        if not zshenv.is_file():
            results.append(StepResult("zsh-startup", "failed", ".zshenv が存在しません"))
        elif not zsh_bin:
            results.append(StepResult("zsh-startup", "skipped", "zsh が PATH にありません"))
        else:
            proc = _run(
                [zsh_bin, "-f", "-c", '. "$HOME/.zshenv" && . "$HOME/.config/shell/shellenv.sh" && printf SMOKE_ZSH_OK'],
                env=env_unix,
                timeout=20,
            )
            if proc.returncode != 0 or "SMOKE_ZSH_OK" not in proc.stdout:
                results.append(StepResult("zsh-startup", "failed", f"exit {proc.returncode}: {proc.stderr.strip()[:240]}"))
            else:
                results.append(StepResult("zsh-startup", "passed", ".zshenv + shellenv.sh loaded"))

        if not pk_bin.is_file():
            results.append(StepResult("pk-cli", "failed", ".local/bin/pk が存在しません"))
        else:
            proc = _run([sys.executable, str(pk_bin), "--help"], env=env_unix, timeout=15)
            if proc.returncode != 0:
                results.append(StepResult("pk-cli", "failed", f"exit {proc.returncode}: {proc.stderr.strip()[:240]}"))
            else:
                results.append(StepResult("pk-cli", "passed", "pk --help ok"))

    if min_entries > 0:
        # 巨大な実 $HOME でも min_entries 個に到達した時点で即打ち切る
        count = sum(1 for _ in itertools.islice(dest.rglob("*"), min_entries))
        if count < min_entries:
            results.append(StepResult("entry-count", "failed", f"展開エントリ数が少なすぎます: {count} < {min_entries}"))
        else:
            results.append(StepResult("entry-count", "passed", f">= {count} entries"))

    return results


def run_isolated_smoke(
    source_root: Path,
    *,
    work_parent: Path | None = None,
    keep_temp: bool = False,
    min_entries: int = 50,
) -> SmokeReport:
    """source_root を隔離環境へ init + 2 回 apply + 残差分 0 検査 + 起動スモークする。"""
    source_root = source_root.resolve()
    chezmoi = shutil.which("chezmoi")
    if not chezmoi:
        raise SmokeError("chezmoi が PATH に見つかりません")

    steps: list[StepResult] = []
    parent_dir = str(work_parent.resolve()) if work_parent else None
    if parent_dir:
        Path(parent_dir).mkdir(parents=True, exist_ok=True)

    tmp_ctx = tempfile.mkdtemp(prefix="chezmoi-smoke-", dir=parent_dir)
    tmp_dir = Path(tmp_ctx)
    dest = tmp_dir / "dest"
    dest.mkdir(parents=True, exist_ok=True)
    cfg = tmp_dir / "chezmoi.toml"
    state_db = tmp_dir / "chezmoistate.boltdb"

    env = _isolated_env(dest)
    base_cmd = [
        chezmoi,
        "-S",
        str(source_root),
        "-D",
        str(dest),
        "-c",
        str(cfg),
        "--persistent-state",
        str(state_db),
    ]

    try:
        # 1. init --force（.chezmoi.toml.tmpl 描画検証を含む）
        r_init = _run([*base_cmd, "init", "--force", "--no-tty"], env=env, timeout=60)
        if r_init.returncode != 0 or not cfg.is_file() or not cfg.read_text(encoding="utf-8").strip():
            steps.append(StepResult("chezmoi-init", "failed", r_init.stderr.strip()[:400] or "chezmoi.toml が生成されませんでした"))
            return SmokeReport(False, "isolate", sys.platform, str(source_root), str(dest), 0, steps)
        steps.append(StepResult("chezmoi-init", "passed", "config rendered"))

        # Unix では modify_ スクリプト用の Python 3.11+ shim を現在の Python（3.11+）で用意する
        if os.name != "nt":
            shim = dest / ".local" / "bin" / "chezmoi-python3"
            shim.parent.mkdir(parents=True, exist_ok=True)
            if not shim.exists():
                try:
                    shim.symlink_to(sys.executable)
                except OSError:
                    shim.write_text(f"#!/bin/sh\nexec '{sys.executable}' \"$@\"\n", encoding="utf-8")
                    shim.chmod(0o755)

        # 2. 1 回目 apply（scripts と externals を除外して純粋なテンプレート・modify 展開を検査）
        r_apply1 = _run(
            [*base_cmd, "apply", "--exclude", "scripts,externals", "--no-tty", "--force"],
            env=env,
            timeout=180,
        )
        if r_apply1.returncode != 0:
            steps.append(StepResult("chezmoi-apply-1", "failed", r_apply1.stderr.strip()[:400]))
            return SmokeReport(False, "isolate", sys.platform, str(source_root), str(dest), 0, steps)
        applied_entries = sum(1 for _ in dest.rglob("*"))
        steps.append(StepResult("chezmoi-apply-1", "passed", f"{applied_entries} entries"))

        # 3. 1 回目直後の残差分検査（modify_ の初回冪等性違反もここで検出する）
        r_diff1 = _run([*base_cmd, "diff", "--exclude", "scripts,externals", "--no-tty"], env=env, timeout=120)
        diff_files = [
            ln.split(" b/", 1)[0].removeprefix("diff --git a/")
            for ln in r_diff1.stdout.splitlines()
            if ln.startswith("diff --git ")
        ]
        if r_diff1.returncode != 0:
            steps.append(StepResult("residual-diff", "failed", f"diff exit {r_diff1.returncode}: {r_diff1.stderr.strip()[:300]}"))
            return SmokeReport(False, "isolate", sys.platform, str(source_root), str(dest), applied_entries, steps)
        if diff_files:
            sample = ", ".join(diff_files[:8])
            steps.append(StepResult("residual-diff", "failed", f"残差分 {len(diff_files)} 件: {sample}"))
            return SmokeReport(False, "isolate", sys.platform, str(source_root), str(dest), applied_entries, steps)
        steps.append(StepResult("residual-diff", "passed", "0 residual diffs"))

        # 4. 2 回目 apply（再実行時のエラー無し・冪等性の確認）
        r_apply2 = _run(
            [*base_cmd, "apply", "--exclude", "scripts,externals", "--no-tty", "--force"],
            env=env,
            timeout=180,
        )
        if r_apply2.returncode != 0:
            steps.append(StepResult("chezmoi-apply-2", "failed", r_apply2.stderr.strip()[:400]))
            return SmokeReport(False, "isolate", sys.platform, str(source_root), str(dest), applied_entries, steps)
        steps.append(StepResult("chezmoi-apply-2", "passed", "idempotent"))

        # 5. 展開物への起動スモーク
        dest_steps = check_destination(dest, min_entries=min_entries)
        steps.extend(dest_steps)
        ok = all(s.status != "failed" for s in steps)
        return SmokeReport(ok, "isolate", sys.platform, str(source_root), str(dest), applied_entries, steps)
    finally:
        if not keep_temp:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="隔離 chezmoi apply ＋ 起動スモーク検査")
    sub = parser.add_subparsers(dest="cmd")

    p_iso = sub.add_parser("isolate", help="使い捨てディレクトリへ init/apply/diff + 起動スモークを実行する（既定）")
    p_iso.add_argument("--source", type=Path, default=ROOT, help="chezmoi リポジトリのルート")
    p_iso.add_argument("--work-dir", type=Path, default=None, help="一時ディレクトリの親パス")
    p_iso.add_argument("--min-entries", type=int, default=50, help="最低展開エントリ数")
    p_iso.add_argument("--keep-temp", action="store_true", help="デバッグ用に一時ディレクトリを残す")

    p_dest = sub.add_parser("check-dest", help="既存の展開先に対して非破壊の起動スモークだけを実行する")
    p_dest.add_argument("dest", type=Path, help="検査対象のホームディレクトリ")
    p_dest.add_argument("--min-entries", type=int, default=1, help="最低エントリ数")

    parsed = parser.parse_args(argv)
    try:
        if parsed.cmd == "check-dest":
            dest = parsed.dest.resolve()
            steps = check_destination(dest, min_entries=parsed.min_entries)
            ok = all(s.status != "failed" for s in steps)
            report = SmokeReport(ok, "check-dest", sys.platform, "", str(dest), 0, steps)
        else:
            src = getattr(parsed, "source", ROOT)
            work_dir = getattr(parsed, "work_dir", None)
            min_entries = getattr(parsed, "min_entries", 50)
            keep_temp = getattr(parsed, "keep_temp", False)
            report = run_isolated_smoke(src, work_parent=work_dir, keep_temp=keep_temp, min_entries=min_entries)
    except SmokeError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1

    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
