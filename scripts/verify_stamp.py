#!/usr/bin/env python3
"""コミット前の検証の印 (stamp)。verify.py --all の成功時に作業ツリーの内容を残し、
コミット時にステージ済みの内容と照合して、一致しなければ警告だけ出す (常に終了コード 0)。

    python3 scripts/verify_stamp.py write | check | check-push

see docs/spec/development.md#コミット前の検証の印
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

VERSION = 1
SHOWN_PATHS = 5

Entries = dict[str, list[str]]


def _clean_env(index: Path | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    if index is not None:
        env["GIT_INDEX_FILE"] = str(index)
    return env


def _git(
    repo: Path, *args: str, env: dict[str, str] | None = None, check: bool = True
) -> subprocess.CompletedProcess[bytes]:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=_clean_env() if env is None else env,
        capture_output=True,
        check=False,
    )
    if check and proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"git {' '.join(args)} が失敗しました: {detail}")
    return proc


def _git_path(repo: Path, name: str) -> Path:
    out = _git(repo, "rev-parse", "--git-path", name).stdout.decode().strip()
    return repo / out


def _head(repo: Path) -> str | None:
    proc = _git(repo, "rev-parse", "--verify", "-q", "HEAD", check=False)
    return proc.stdout.decode().strip() if proc.returncode == 0 else None


def snapshot(repo: Path) -> Entries:
    """作業ツリー (HEAD + 変更 + 未追跡。.gitignore は効く) の path → [mode, blob]。"""
    repo = Path(repo)
    index = _git_path(repo, "verify-stamp.index")
    env = _clean_env(index)
    index.unlink(missing_ok=True)
    try:
        if _head(repo) is not None:
            _git(repo, "read-tree", "HEAD", env=env)
        _git(repo, "add", "-A", env=env)
        raw = _git(repo, "ls-files", "-s", "-z", env=env).stdout
    finally:
        index.unlink(missing_ok=True)
    entries: Entries = {}
    for rec in raw.decode("utf-8", "surrogateescape").split("\0"):
        if not rec:
            continue
        meta, path = rec.split("\t", 1)
        mode, blob, _stage = meta.split(" ")
        entries[path] = [mode, blob]
    return entries


def _now() -> str:
    return datetime.now(UTC).isoformat()


def write_stamp(repo: Path, entries: Entries | None = None) -> Path:
    """印を書く。entries を渡すと、その内容 (検証の開始時の snapshot) を記録する。"""
    repo = Path(repo)
    data = {
        "version": VERSION,
        "head": _head(repo),
        "created": _now(),
        "entries": snapshot(repo) if entries is None else entries,
    }
    dest = _git_path(repo, "verify-stamp.json")
    tmp = dest.with_name(dest.name + f".{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)
    return dest


def _parse_raw(raw: bytes) -> Entries:
    """`git diff --raw -z` の出力 → 追加・変更の path → [新しい mode, 新しい blob] (削除は含めない)。"""
    tokens = raw.decode("utf-8", "surrogateescape").split("\0")
    entries: Entries = {}
    i = 0
    while i + 1 < len(tokens):
        meta = tokens[i]
        if not meta.startswith(":"):
            i += 1
            continue
        _old_mode, new_mode, _old_blob, new_blob, status = meta[1:].split(" ")
        if not status.startswith("D"):
            entries[tokens[i + 1]] = [new_mode, new_blob]
        i += 2
    return entries


def staged(repo: Path) -> Entries:
    """ステージ済みの追加・変更の path → [新しい mode, 新しい blob] (削除は含めない)。"""
    # GIT_INDEX_FILE は落とさない (pre-commit は部分コミットで一時 index を渡す)
    raw = _git(
        Path(repo),
        "diff",
        "--cached",
        "--no-renames",
        "--no-abbrev",
        "--raw",
        "-z",
        env=dict(os.environ),
    ).stdout
    return _parse_raw(raw)


def _is_commit(repo: Path, ref: str) -> bool:
    proc = _git(repo, "rev-parse", "--verify", "-q", f"{ref}^{{commit}}", check=False)
    return proc.returncode == 0


def pushed(repo: Path, from_ref: str | None, to_ref: str | None) -> Entries | None:
    """push する範囲の追加・変更の path → [mode, blob]。範囲が決められなければ None。

    from_ref が無い・全ゼロ・存在しない (新しいブランチ) ときは、origin/develop (あれば。gitflow の feature の親)、
    無ければ origin/main との merge-base から。
    to_ref が無い・全ゼロ (ブランチの削除) ときは None。
    """
    repo = Path(repo)
    if not to_ref or set(to_ref) == {"0"} or not _is_commit(repo, to_ref):
        return None
    base = from_ref if from_ref and set(from_ref) != {"0"} and _is_commit(repo, from_ref) else None
    if base is None:
        for parent in ("origin/develop", "origin/main"):
            if not _is_commit(repo, parent):
                continue
            proc = _git(repo, "merge-base", parent, to_ref, check=False)
            base = proc.stdout.decode().strip() if proc.returncode == 0 else None
            if base:
                break
    if not base:
        return None
    raw = _git(repo, "diff", "--raw", "--no-renames", "--no-abbrev", "-z", base, to_ref).stdout
    return _parse_raw(raw)


def _load_stamp(repo: Path) -> Entries | None:
    try:
        data = json.loads(_git_path(repo, "verify-stamp.json").read_text(encoding="utf-8"))
        entries = data["entries"]
    except (OSError, ValueError, KeyError, RuntimeError):
        return None
    return entries if data.get("version") == VERSION and isinstance(entries, dict) else None


def _plan_needs_full(paths: Sequence[str]) -> bool:
    """paths の変更が verify.py の plan() で全件になるか。判定できなければ真。"""
    try:
        verify = sys.modules.get("verify")
        if verify is None or not hasattr(verify, "plan"):
            script = Path(__file__).resolve().with_name("verify.py")
            spec = importlib.util.spec_from_file_location("verify", script)
            if spec is None or spec.loader is None:
                return True
            verify = importlib.util.module_from_spec(spec)
            sys.modules["verify"] = verify
            spec.loader.exec_module(verify)
        # 削除は staged() が含めないので、存在するものとして選択規則だけを見る
        result = verify.plan(
            list(paths), verify.discover_test_files(), exists=lambda _p: True, refs={}
        )
        return bool(result.full)
    except Exception:
        return True


def _log(repo: Path, result: str, count: int) -> None:
    # 記録の失敗でコミットを止めない
    with contextlib.suppress(Exception):
        line = json.dumps({"at": _now(), "result": result, "count": count})
        with _git_path(repo, "verify-stamp.log").open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def _compare(
    repo: Path,
    now: Entries,
    subject: str,
    deadline: str,
    needs_full: Callable[[Sequence[str]], bool] | None,
) -> int:
    """now を印と照合する。警告のみで常に 0。subject は警告文の主語 (「このコミット」など)。"""
    if not now:
        return 0
    stamp = _load_stamp(repo)
    if stamp is None:
        mismatched = sorted(now)
        result = "no-stamp"
    else:
        mismatched = sorted(p for p, v in now.items() if stamp.get(p) != v)
        result = "mismatch"
    if not mismatched or not (needs_full or _plan_needs_full)(mismatched):
        return 0
    shown = ", ".join(mismatched[:SHOWN_PATHS])
    rest = len(mismatched) - SHOWN_PATHS
    where = "印がありません" if stamp is None else shown + (f" ほか {rest} 件" if rest > 0 else "")
    sys.stderr.write(
        f"警告: {subject}の内容は、全件検証 (verify.py --all) を通した内容と"
        f"一致しません: {where}。急ぐときはこのまま進めてよいが、"
        f"{deadline}に 1 回 verify:all を回す約束です (docs/spec/development.md)\n"
    )
    _log(repo, result, len(mismatched))
    return 0


def check(repo: Path, needs_full: Callable[[Sequence[str]], bool] | None = None) -> int:
    """警告のみ。常に 0。needs_full は不一致パス → 全件検証が要るか (省略時は plan())。"""
    repo = Path(repo)
    return _compare(repo, staged(repo), "このコミット", "コミット前", needs_full)


def check_push(
    repo: Path,
    from_ref: str | None,
    to_ref: str | None,
    needs_full: Callable[[Sequence[str]], bool] | None = None,
) -> int:
    """push する範囲の内容を照合する。警告のみ。常に 0。範囲が決められなければ何も言わない。"""
    repo = Path(repo)
    now = pushed(repo, from_ref, to_ref)
    return _compare(repo, now or {}, "push するコミット", "push 前", needs_full)


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1 or args[0] not in {"write", "check", "check-push"}:
        sys.stderr.write("使い方: verify_stamp.py write | check | check-push\n")
        return 2
    top = Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
            env=_clean_env(),
        ).stdout.strip()
    )
    if args[0] == "write":
        write_stamp(top)
        return 0
    try:
        if args[0] == "check-push":
            return check_push(
                top,
                os.environ.get("PRE_COMMIT_FROM_REF"),
                os.environ.get("PRE_COMMIT_TO_REF"),
            )
        return check(top)
    except Exception as exc:
        sys.stderr.write(f"verify-stamp: 照合できませんでした (無視します): {exc}\n")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
