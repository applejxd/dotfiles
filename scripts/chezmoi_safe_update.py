#!/usr/bin/env python3
"""隔離プレフライト ＋ 自動ファイル切り戻し ＋ 副作用明示を備えた chezmoi 安全更新 CLI。

不変条件:
1. 実機 `$HOME` へ触れる前に、必ず target SHA（および未検証の切り戻し候補 SHA）を一時 worktree ＋
   隔離環境でプレフライト検証する。テンプレート破損・modify エラー・JSON/シェル/Vim 破損は
   実機を 1 バイトも変えずに阻止する。
2. 本番適用とロールバック適用は、一時 worktree ではなく **恒久の本体 `source` ディレクトリ自身** を
   `-S <repo>`（`--working-tree <repo>`）として実行する。これにより `.chezmoi.sourceDir` や
   `.chezmoi.workingTree` を埋め込むテンプレート（`ccd`・`chezmoi.toml` hooks・`run_once_` ハッシュ）に
   使い捨てパスが焼き込まれる事故（P0）を構造的に防ぐ。
3. 本番適用（タイムアウト例外含む）または実機スモークが失敗した場合は、source を直前の正常 SHA へ
   安全に戻した上で、本体 `source` から `--exclude scripts,externals` で管理ファイルを自動復元する。
4. `run_` / `run_once_` / `run_onchange_` が走る適用で失敗した場合は、ファイル復元に加えて
   「外部副作用（パッケージ・レジストリ・OS 設定・scriptState）は自動では戻らない」旨と
   該当スクリプト一覧を明示警告する。

see docs/adr/0045-stage3-smoke-promotion-and-safe-update.md
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import isolated_smoke  # noqa: E402

ROOT = SCRIPT_DIR.parent
DEFAULT_STATE_DIR = Path.home() / ".local" / "state" / "dotfiles-safe-update"


class SafeUpdateError(RuntimeError):
    """安全更新 CLI のエラー。"""


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _run(
    cmd: Sequence[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int | None = 900,
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


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = _run(["git", *args], cwd=repo, timeout=120)
    if check and proc.returncode != 0:
        raise SafeUpdateError(f"git {' '.join(args)} が失敗しました: {proc.stderr.strip()}")
    return proc


@contextlib.contextmanager
def _exclusive_lock(state_dir: Path) -> Iterator[None]:
    """同一端末での多重 update / rollback を防ぐ OS レベル排他ロック。"""
    state_dir.mkdir(parents=True, exist_ok=True)
    lock_path = state_dir / "update.lock"
    fh = lock_path.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt

            fh.seek(0)
            if fh.tell() == 0 and lock_path.stat().st_size == 0:
                fh.write(b"\0")
                fh.flush()
            fh.seek(0)
            try:
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise SafeUpdateError(f"別の safe-update が実行中です: {lock_path}") from exc
            try:
                yield
            finally:
                fh.seek(0)
                with contextlib.suppress(OSError):
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise SafeUpdateError(f"別の safe-update が実行中です: {lock_path}") from exc
            try:
                yield
            finally:
                with contextlib.suppress(OSError):
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    finally:
        fh.close()


def load_state(state_dir: Path) -> dict[str, object]:
    path = state_dir / "state.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(state_dir: Path, state: dict[str, object]) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / "state.json"
    fd, tmp_name = tempfile.mkstemp(prefix="state-", suffix=".tmp", dir=str(state_dir))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)


@contextlib.contextmanager
def _detached_worktree(repo: Path, commit_sha: str, work_parent: Path) -> Iterator[Path]:
    """プレフライト専用の一時 detached worktree を作って後始末する。本番 apply には使わない。"""
    work_parent.mkdir(parents=True, exist_ok=True)
    wt_dir = Path(tempfile.mkdtemp(prefix="safe-update-wt-", dir=str(work_parent)))
    wt_dir.rmdir()
    _git(repo, "worktree", "add", "--detach", str(wt_dir), commit_sha)
    try:
        yield wt_dir
    finally:
        _git(repo, "worktree", "remove", "--force", str(wt_dir), check=False)
        shutil.rmtree(wt_dir, ignore_errors=True)


def _checkout_repo_at(repo: Path, sha: str, *, branch: str = "") -> None:
    """クリーン確認済みの source 本体を、`git reset --hard` を使わずに指定 SHA へ切り替える。"""
    if branch:
        _git(repo, "checkout", "-B", branch, sha)
    else:
        _git(repo, "checkout", "--detach", sha)


def _chezmoi_base_cmd(
    chezmoi: str,
    repo_root: Path,
    dest_dir: Path,
    config_file: Path | None,
    state_db: Path | None,
) -> list[str]:
    cmd = [chezmoi, "-S", str(repo_root), "--working-tree", str(repo_root), "-D", str(dest_dir)]
    if config_file is not None:
        cmd.extend(["-c", str(config_file)])
    if state_db is not None:
        cmd.extend(["--persistent-state", str(state_db)])
    return cmd


def _detect_pending_scripts(
    chezmoi: str,
    repo_root: Path,
    dest_dir: Path,
    config_file: Path | None,
    state_db: Path | None,
) -> tuple[list[str], bool]:
    """`chezmoi status --include scripts` から今回実行予定の `R` エントリ一覧と取得成否を返す。"""
    cmd = [
        *_chezmoi_base_cmd(chezmoi, repo_root, dest_dir, config_file, state_db),
        "status",
        "--include",
        "scripts",
        "--no-tty",
    ]
    proc = _run(cmd, timeout=90)
    if proc.returncode != 0:
        return [], False
    scripts: list[str] = []
    for line in proc.stdout.splitlines():
        if len(line) >= 4 and "R" in line[:2]:
            scripts.append(line[3:].strip())
    return scripts, True


def _apply_from_real_repo(
    *,
    chezmoi: str,
    repo: Path,
    dest_dir: Path,
    config_file: Path | None,
    state_db: Path | None,
    run_init: bool,
    exclude_scripts: bool,
    apply_timeout: int | None,
) -> tuple[bool, str]:
    """恒久の本体 `repo` から `dest_dir` へ chezmoi init / apply を実行する（一時パスを焼き込まない）。"""
    base = _chezmoi_base_cmd(chezmoi, repo, dest_dir, config_file, state_db)
    if run_init:
        r_init = _run([*base, "init", "--force", "--no-tty"], timeout=120)
        if r_init.returncode != 0:
            return False, f"chezmoi init failed (exit {r_init.returncode}): {r_init.stderr.strip()[:400]}"
    apply_cmd = [*base, "apply", "--no-tty", "--force"]
    if exclude_scripts:
        apply_cmd.extend(["--exclude", "scripts,externals"])
    r_apply = _run(apply_cmd, timeout=apply_timeout)
    if r_apply.returncode != 0:
        return False, f"chezmoi apply failed (exit {r_apply.returncode}): {r_apply.stderr.strip()[:400]}"
    return True, "ok"


def _preflight_commit(repo: Path, sha: str, work_parent: Path, *, min_entries: int) -> isolated_smoke.SmokeReport:
    with _detached_worktree(repo, sha, work_parent) as wt:
        return isolated_smoke.run_isolated_smoke(wt, work_parent=work_parent, min_entries=min_entries)


def _cmd_status(args: argparse.Namespace) -> int:
    repo = args.source.resolve()
    state_dir = args.state_dir.resolve()
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    branch = _git(repo, "branch", "--show-current").stdout.strip()
    dirty = bool(_git(repo, "status", "--porcelain").stdout.strip())
    st = load_state(state_dir)
    out = {
        "source": str(repo),
        "branch": branch,
        "head_sha": head,
        "dirty": dirty,
        "state_dir": str(state_dir),
        "last_good_sha": st.get("last_good_sha"),
        "last_good_at": st.get("last_good_at"),
        "last_attempt": st.get("last_attempt"),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def _cmd_update(args: argparse.Namespace) -> int:
    chezmoi = shutil.which("chezmoi")
    if not chezmoi:
        raise SafeUpdateError("chezmoi が PATH に見つかりません")

    repo = args.source.resolve()
    dest = args.dest.resolve()
    state_dir = args.state_dir.resolve()
    cfg_file = args.chezmoi_config.resolve() if args.chezmoi_config else None
    state_db = args.chezmoi_state.resolve() if args.chezmoi_state else None
    work_parent = repo / ".tmp" / "safe-update"
    apply_timeout = None if args.apply_timeout <= 0 else args.apply_timeout

    with _exclusive_lock(state_dir):
        if _git(repo, "status", "--porcelain").stdout.strip():
            raise SafeUpdateError("source リポジトリに未コミットの変更があります。先に片付けてください。")

        from_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
        cur_branch = _git(repo, "branch", "--show-current").stdout.strip()
        st = load_state(state_dir)
        recorded_good = st.get("last_good_sha")
        has_recorded_good = isinstance(recorded_good, str) and bool(recorded_good)
        fallback_good_sha = str(recorded_good) if has_recorded_good else from_sha

        # 1. 更新先 SHA の解決（--target 未指定時は origin/<branch> を fetch して解決）
        if args.target:
            if not args.no_fetch:
                _git(repo, "fetch", "origin", check=False)
            target_sha = _git(repo, "rev-parse", "--verify", f"{args.target}^{{commit}}").stdout.strip()
            can_ff_branch = False
        else:
            ref_branch = args.branch or cur_branch or "main"
            if not args.no_fetch:
                _git(repo, "fetch", "origin", ref_branch)
            remote_ref = f"origin/{ref_branch}"
            if _git(repo, "rev-parse", "--verify", "--quiet", remote_ref, check=False).returncode == 0:
                target_sha = _git(repo, "rev-parse", remote_ref).stdout.strip()
            else:
                target_sha = _git(repo, "rev-parse", ref_branch).stdout.strip()
            can_ff_branch = bool(cur_branch and cur_branch == ref_branch)

        if can_ff_branch and _git(repo, "merge-base", "--is-ancestor", from_sha, target_sha, check=False).returncode != 0:
            raise SafeUpdateError(
                f"現在の HEAD ({from_sha[:8]}) から更新先 ({target_sha[:8]}) へ fast-forward できません。"
            )

        # 2. 実機を触る前の隔離プレフライト（失敗時は実機・ブランチとも無傷で即停止）
        preflight = _preflight_commit(repo, target_sha, work_parent, min_entries=args.min_entries)
        if not preflight.ok:
            failed = [f"{s.name}: {s.detail}" for s in preflight.steps if s.status == "failed"]
            st["last_attempt"] = {
                "at": _now_iso(),
                "from_sha": from_sha,
                "to_sha": target_sha,
                "status": "preflight_failed",
                "reason": "; ".join(failed),
                "pending_scripts": [],
            }
            save_state(state_dir, st)
            print(
                json.dumps(
                    {
                        "ok": False,
                        "stage": "preflight",
                        "from_sha": from_sha,
                        "to_sha": target_sha,
                        "dest_untouched": True,
                        "failed_steps": failed,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 1

        # 初回実行（last_good_sha 未記録）かつ from_sha != target_sha の場合、切り戻し先になる from_sha も先に検証しておく
        fallback_preflight_ok = True
        if not has_recorded_good and fallback_good_sha != target_sha:
            fb_report = _preflight_commit(repo, fallback_good_sha, work_parent, min_entries=args.min_entries)
            fallback_preflight_ok = fb_report.ok

        if args.dry_run:
            with _detached_worktree(repo, target_sha, work_parent) as target_wt:
                pending_scripts, status_ok = (
                    ([], True)
                    if args.exclude_scripts
                    else _detect_pending_scripts(chezmoi, target_wt, dest, cfg_file, state_db)
                )
            print(
                json.dumps(
                    {
                        "ok": True,
                        "dry_run": True,
                        "preflight": "passed",
                        "from_sha": from_sha,
                        "to_sha": target_sha,
                        "already_up_to_date": from_sha == target_sha,
                        "pending_scripts": pending_scripts,
                        "pending_scripts_known": status_ok,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        # 3. 本体 source を target_sha へ向け、恒久パス（repo）から本番 init/apply を実行する
        target_branch_for_apply = cur_branch if can_ff_branch else ""
        if can_ff_branch and from_sha != target_sha:
            _git(repo, "merge", "--ff-only", target_sha)
        elif not can_ff_branch and from_sha != target_sha:
            _checkout_repo_at(repo, target_sha, branch="")

        pending_scripts: list[str] = []
        status_ok = True
        apply_ok = False
        apply_detail = "interrupted"
        post_failed: list[str] = []

        try:
            if not args.exclude_scripts:
                pending_scripts, status_ok = _detect_pending_scripts(chezmoi, repo, dest, cfg_file, state_db)
            apply_ok, apply_detail = _apply_from_real_repo(
                chezmoi=chezmoi,
                repo=repo,
                dest_dir=dest,
                config_file=cfg_file,
                state_db=state_db,
                run_init=not args.no_init,
                exclude_scripts=args.exclude_scripts,
                apply_timeout=apply_timeout,
            )
            if apply_ok:
                post_steps = isolated_smoke.check_destination(dest, min_entries=args.min_entries)
                post_failed = [f"{s.name}: {s.detail}" for s in post_steps if s.status == "failed"]
        except KeyboardInterrupt:
            apply_ok = False
            apply_detail = "interrupted by user (KeyboardInterrupt)"

        # 4a. 成功: target_branch で無かった場合（--target 指定）は元のブランチ位置へ戻すか detached を整理し、last_good_sha を記録
        if apply_ok and not post_failed:
            if not target_branch_for_apply and cur_branch:
                _checkout_repo_at(repo, from_sha, branch=cur_branch)
            now = _now_iso()
            st["last_good_sha"] = target_sha
            st["last_good_at"] = now
            st["last_attempt"] = {
                "at": now,
                "from_sha": from_sha,
                "to_sha": target_sha,
                "status": "ok",
                "pending_scripts": pending_scripts,
            }
            save_state(state_dir, st)
            print(
                json.dumps(
                    {
                        "ok": True,
                        "from_sha": from_sha,
                        "to_sha": target_sha,
                        "branch_ff_updated": bool(can_ff_branch and from_sha != target_sha),
                        "last_good_sha": target_sha,
                        "pending_scripts": pending_scripts,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        # 4b. 失敗: 本体 source を切り戻し先へ戻し、恒久パス（repo）から管理ファイルを自動復元する
        failure_reason = apply_detail if not apply_ok else f"post-smoke failed: {'; '.join(post_failed)}"
        rb_sha = fallback_good_sha

        if not fallback_preflight_ok:
            # 初回実行で元の from_sha 自体が壊れていた場合は壊れた元世代を上書きせず停止する
            _checkout_repo_at(repo, from_sha, branch=cur_branch)
            rb_ok = False
            rb_detail = f"切り戻し候補 {rb_sha[:8]} が未検証かつ隔離スモーク不合格のため再適用を中止しました"
            rb_smoke_failed: list[str] = []
        else:
            rb_branch = cur_branch if (cur_branch and rb_sha == from_sha) else ""
            _checkout_repo_at(repo, rb_sha, branch=rb_branch)
            rb_ok, rb_detail = _apply_from_real_repo(
                chezmoi=chezmoi,
                repo=repo,
                dest_dir=dest,
                config_file=cfg_file,
                state_db=state_db,
                run_init=not args.no_init,
                exclude_scripts=True,
                apply_timeout=300,
            )
            if not rb_branch and cur_branch:
                _checkout_repo_at(repo, from_sha, branch=cur_branch)
            rb_smoke_failed = []
            if rb_ok:
                rb_steps = isolated_smoke.check_destination(dest, min_entries=args.min_entries)
                rb_smoke_failed = [f"{s.name}: {s.detail}" for s in rb_steps if s.status == "failed"]

        rollback_clean = rb_ok and not rb_smoke_failed
        scripts_may_have_run = (not args.exclude_scripts) and (bool(pending_scripts) or not status_ok)
        side_effect_warning = None
        if scripts_may_have_run:
            side_effect_warning = (
                "管理ファイルは直前世代へ戻しましたが、chezmoi scripts による外部副作用"
                "（パッケージ導入・レジストリ・OS 設定・scriptState 記録）および新規追加専用ファイルは自動では戻りません。"
                "必要に応じてログとスクリプト内容を確認してください。"
            )

        now = _now_iso()
        st["last_attempt"] = {
            "at": now,
            "from_sha": from_sha,
            "to_sha": target_sha,
            "status": "rolled_back" if rollback_clean else "rollback_failed",
            "reason": failure_reason,
            "rolled_back_to": rb_sha,
            "rollback_detail": rb_detail if not rb_ok else "; ".join(rb_smoke_failed) or "ok",
            "pending_scripts": pending_scripts if status_ok else ["<unknown: chezmoi status failed>"],
            "side_effect_warning": side_effect_warning,
        }
        save_state(state_dir, st)

        print(
            json.dumps(
                {
                    "ok": False,
                    "stage": "apply_or_post_smoke",
                    "reason": failure_reason,
                    "rolled_back": rollback_clean,
                    "rolled_back_to": rb_sha,
                    "rollback_detail": st["last_attempt"]["rollback_detail"],
                    "pending_scripts": st["last_attempt"]["pending_scripts"],
                    "side_effect_warning": side_effect_warning,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1


def _cmd_rollback(args: argparse.Namespace) -> int:
    chezmoi = shutil.which("chezmoi")
    if not chezmoi:
        raise SafeUpdateError("chezmoi が PATH に見つかりません")

    repo = args.source.resolve()
    dest = args.dest.resolve()
    state_dir = args.state_dir.resolve()
    cfg_file = args.chezmoi_config.resolve() if args.chezmoi_config else None
    state_db = args.chezmoi_state.resolve() if args.chezmoi_state else None
    work_parent = repo / ".tmp" / "safe-update"

    with _exclusive_lock(state_dir):
        if _git(repo, "status", "--porcelain").stdout.strip():
            raise SafeUpdateError("source リポジトリに未コミットの変更があります。先に片付けてください。")

        orig_head = _git(repo, "rev-parse", "HEAD").stdout.strip()
        orig_branch = _git(repo, "branch", "--show-current").stdout.strip()
        st = load_state(state_dir)
        raw_target = args.to or st.get("last_good_sha")
        if not raw_target or not isinstance(raw_target, str):
            raise SafeUpdateError("ロールバック先 SHA が指定されておらず、state.json に last_good_sha もありません。")
        target_sha = _git(repo, "rev-parse", "--verify", f"{raw_target}^{{commit}}").stdout.strip()

        pre = _preflight_commit(repo, target_sha, work_parent, min_entries=args.min_entries)
        if not pre.ok:
            failed = [f"{s.name}: {s.detail}" for s in pre.steps if s.status == "failed"]
            raise SafeUpdateError(f"ロールバック先 {target_sha[:8]} が隔離スモークに不合格です: {'; '.join(failed)}")

        if args.dry_run:
            print(
                json.dumps(
                    {"ok": True, "dry_run": True, "rollback_to": target_sha, "preflight": "passed"},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        # 恒久の本体 repo を一時的に target_sha（detached）へ切り替えて適用し、
        # 終了後に元のブランチへ戻す（--keep-checkout 指定時は target_sha に留める）
        _checkout_repo_at(repo, target_sha, branch="")
        try:
            ok, detail = _apply_from_real_repo(
                chezmoi=chezmoi,
                repo=repo,
                dest_dir=dest,
                config_file=cfg_file,
                state_db=state_db,
                run_init=not args.no_init,
                exclude_scripts=True,
                apply_timeout=300,
            )
        finally:
            if not args.keep_checkout and orig_branch:
                _checkout_repo_at(repo, orig_head, branch=orig_branch)

        if not ok:
            raise SafeUpdateError(f"ロールバック適用に失敗しました: {detail}")

        steps = isolated_smoke.check_destination(dest, min_entries=args.min_entries)
        failed = [f"{s.name}: {s.detail}" for s in steps if s.status == "failed"]
        if failed:
            raise SafeUpdateError(f"ロールバック後の起動スモークに失敗しました: {'; '.join(failed)}")

        now = _now_iso()
        st["last_good_sha"] = target_sha
        st["last_good_at"] = now
        st["last_attempt"] = {
            "at": now,
            "from_sha": orig_head,
            "to_sha": target_sha,
            "status": "manual_rollback_ok",
            "note": "scripts/externals は再実行していません（管理ファイルのみ復元）",
        }
        save_state(state_dir, st)
        print(
            json.dumps(
                {
                    "ok": True,
                    "rolled_back_to": target_sha,
                    "note": "管理ファイルを復元しました（chezmoi scripts の外部副作用と新規追加専用ファイルは対象外です）。",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0


def _add_common_paths(p: argparse.ArgumentParser) -> None:
    p.add_argument("--source", type=Path, default=ROOT, help="chezmoi リポジトリのルート")
    p.add_argument("--dest", type=Path, default=Path.home(), help="適用先ホームディレクトリ（既定: $HOME）")
    p.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR, help="last_good_sha 等の記録先")
    p.add_argument("--chezmoi-config", type=Path, default=None, help="隔離試験用の chezmoi.toml パス")
    p.add_argument("--chezmoi-state", type=Path, default=None, help="隔離試験用の chezmoistate.boltdb パス")
    p.add_argument("--min-entries", type=int, default=50, help="スモーク時の最低エントリ数")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="隔離プレフライト＋自動ファイル切り戻し付き chezmoi 安全更新 CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_st = sub.add_parser("status", help="現在の HEAD と last_good_sha・直近の試行状態を表示する")
    _add_common_paths(p_st)
    p_st.set_defaults(func=_cmd_status)

    p_up = sub.add_parser("update", help="隔離プレフライト後に更新適用し、失敗時は直前正常世代へ自動切り戻す")
    _add_common_paths(p_up)
    p_up.add_argument("--branch", default=None, help="追跡対象ブランチ（既定: 現在のブランチまたは main）")
    p_up.add_argument("--target", default=None, help="特定のコミット/ref へ適用する（試験・検証用）")
    p_up.add_argument("--no-fetch", action="store_true", help="git fetch を省略する")
    p_up.add_argument("--no-init", action="store_true", help="chezmoi init --force を省略する")
    p_up.add_argument("--exclude-scripts", action="store_true", help="scripts と externals を除外してファイルのみ適用する")
    p_up.add_argument("--apply-timeout", type=int, default=3600, help="本番 apply のタイムアウト秒数（0 以下で無制限、既定 3600）")
    p_up.add_argument("--dry-run", action="store_true", help="隔離プレフライトと実行予定スクリプト確認だけ行う")
    p_up.set_defaults(func=_cmd_update)

    p_rb = sub.add_parser("rollback", help="指定 SHA または last_good_sha の管理ファイルへ切り戻す")
    _add_common_paths(p_rb)
    p_rb.add_argument("--to", default=None, help="切り戻し先コミット SHA（省略時は last_good_sha）")
    p_rb.add_argument("--no-init", action="store_true", help="chezmoi init --force を省略する")
    p_rb.add_argument("--keep-checkout", action="store_true", help="ロールバック後も source を detached のまま切り戻し先 SHA に留める")
    p_rb.add_argument("--dry-run", action="store_true", help="ロールバック先の隔離スモーク確認だけ行う")
    p_rb.set_defaults(func=_cmd_rollback)

    parsed = parser.parse_args(argv)
    try:
        return int(parsed.func(parsed))
    except SafeUpdateError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
