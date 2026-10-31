#!/usr/bin/env python3
"""feature の worktree を、取り込み前に決定的に確認する (読み取り専用)。

    python3 scripts/feature_gate.py check <feature> [--owned GLOB,...] [--json]

リポジトリ本体の作業ツリー (カレント) から実行する。<feature> の worktree は
`.tmp/worktrees/<feature>/` (ブランチ feature/<feature>)。次の check を順に行う。
  scope                   担当範囲の外・本体の変更・worktree 間の重複 (parallel_check.check を再利用)
  numstat_drop            HEAD で 20 行以上あったファイルが空になった・80% 以上減った (整形 hook 直後の空ステージ事故)
  register_tests          新しい試験ファイルが verify.py の選択規則に拾われる
  register_harness_copy   index.ts から import される新規・変更の harness の .ts が、試験用コピー一覧 3 か所に載っている

実 index・ref・作業ツリー・hook は変えない (tree は一時 index で算出する。オブジェクトは追加されうる)。
終了コード: 0 = 全部 ok、1 = 失敗あり、2 = 使い方か git の失敗。
Windows は実機で未検証。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import parallel_check

HARNESS_DIR = "home/dot_config/pi/harness"
COPY_LISTS = (
    "test/agents/test_pi_harness.py",
    "test/agents/test_pi_commit_confirm.py",
    "scripts/pi-harness-spike/compact-real.py",
)
DROP_MIN_LINES = 20
DROP_RATIO = 0.8
IMPORT_RE = re.compile(r"""(?:from|import)\s*\(?\s*["']\./([^"']+\.ts)["']""")


class GateError(Exception):
    """使い方か git の失敗 (終了コード 2)。"""


def _env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def git(
    cwd: Path, *args: str, env: dict[str, str] | None = None, check: bool = True
) -> subprocess.CompletedProcess[bytes]:
    r = subprocess.run(
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.quotepath=false",
            *args,
        ],
        cwd=cwd,
        capture_output=True,
        env=env or _env(),
        check=False,
    )
    if check and r.returncode != 0:
        raise GateError(
            f"git {' '.join(args)} が失敗した ({cwd}): {r.stderr.decode('utf-8', 'replace').strip()}"
        )
    return r


def out(cwd: Path, *args: str) -> str:
    return git(cwd, *args).stdout.decode("utf-8", "replace").strip()


def tree_of(wt: Path) -> str:
    """作業ツリー (HEAD + 変更 + 未追跡。.gitignore は効く) の tree。一時 index を使い、実 index は触らない。"""
    with tempfile.TemporaryDirectory(prefix="feature-gate-") as d:
        env = _env()
        env["GIT_INDEX_FILE"] = str(Path(d) / "index")
        git(wt, "read-tree", "HEAD", env=env)
        git(wt, "add", "-A", env=env)
        return git(wt, "write-tree", env=env).stdout.decode().strip()


def _in_head(wt: Path, path: str) -> bool:
    return git(wt, "cat-file", "-e", f"HEAD:{path}", check=False).returncode == 0


def _lines(data: bytes) -> int:
    return data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)


def check_scope(root: Path, feature: str, owned: list[str] | None) -> tuple[bool, str]:
    if not owned:
        return True, "skipped (no --owned)"
    result = parallel_check.check(root, {feature: owned})
    return result["ok"], "; ".join(result["problems"]) or "ok"


def check_numstat_drop(wt: Path) -> tuple[bool, str]:
    names = (
        git(wt, "diff", "--name-only", "--no-renames", "-z", "HEAD")
        .stdout.decode("utf-8", "replace")
        .split("\0")
    )
    bad: list[str] = []
    for p in (n for n in names if n):
        old = git(wt, "show", f"HEAD:{p}", check=False)
        if old.returncode != 0 or b"\0" in old.stdout:
            continue
        before = _lines(old.stdout)
        if before < DROP_MIN_LINES:
            continue
        f = wt / p
        after = _lines(f.read_bytes()) if f.is_file() else 0
        if after == 0 or after <= before * (1 - DROP_RATIO):
            bad.append(f"{p} ({before} -> {after} 行)")
    return (not bad), ("; ".join(bad) or "ok")


def _load_verify(wt: Path):
    for cand in (wt / "scripts" / "verify.py", Path(__file__).resolve().parent / "verify.py"):
        if cand.is_file():
            spec = importlib.util.spec_from_file_location("_feature_gate_verify", cand)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mod  # dataclass が要る
            spec.loader.exec_module(mod)
            return mod
    return None


def check_register_tests(wt: Path) -> tuple[bool, str]:
    new = sorted(
        p
        for p in set(parallel_check.status_paths(wt))
        if re.fullmatch(r"test/(?:.+/)?test_[^/]+\.py", p)
        and (wt / p).is_file()
        and not _in_head(wt, p)
    )
    if not new:
        return True, "ok (no new test files)"
    verify = _load_verify(wt)
    if verify is None:
        return True, "skipped (verify.py not found)"
    patterns = [p for rule in verify.RULES for p in rule.tests]
    never = [f for f in new if not verify.resolve_tests(patterns, [f])]
    return (not never), ("not selected by verify.py: " + ", ".join(never) if never else "ok")


def _reachable(harness: Path) -> set[str]:
    seen: set[str] = set()
    todo = ["index.ts"]
    while todo:
        name = todo.pop()
        f = harness / name
        if name in seen or not f.is_file():
            continue
        seen.add(name)
        todo.extend(IMPORT_RE.findall(f.read_text(encoding="utf-8", errors="replace")))
    seen.discard("index.ts")
    return seen


def check_register_harness_copy(wt: Path) -> tuple[bool, str]:
    harness = wt / HARNESS_DIR
    lists = {rel: wt / rel for rel in COPY_LISTS}
    if not (harness / "index.ts").is_file() or not all(p.is_file() for p in lists.values()):
        return True, "skipped (copy lists not found)"
    changed = {
        Path(p).name
        for p in parallel_check.status_paths(wt)
        if p.startswith(HARNESS_DIR + "/")
        and p.endswith(".ts")
        and p.count("/") == HARNESS_DIR.count("/") + 1
    }
    targets = sorted(changed & _reachable(harness))
    texts = {rel: p.read_text(encoding="utf-8", errors="replace") for rel, p in lists.items()}
    missing = []
    for t in targets:
        quoted = '"' + t + '"'
        lacking = [rel for rel, txt in texts.items() if quoted not in txt]
        if lacking:
            missing.append(f"{t}: {', '.join(lacking)}")
    return (not missing), ("missing in " + "; ".join(missing) if missing else "ok")


def run_checks(root: Path, feature: str, owned: list[str] | None) -> dict:
    trees = parallel_check.feature_worktrees(root)
    if feature not in trees:
        raise GateError(
            f"feature/{feature} の worktree が見つからない ({parallel_check.WORKTREES_DIR} の下)"
        )
    wt = trees[feature]
    base = out(root, "merge-base", parallel_check.BASE_BRANCH, f"feature/{feature}")
    steps = (
        ("scope", lambda: check_scope(root, feature, owned)),
        ("numstat_drop", lambda: check_numstat_drop(wt)),
        ("register_tests", lambda: check_register_tests(wt)),
        ("register_harness_copy", lambda: check_register_harness_copy(wt)),
    )
    checks = []
    for cid, fn in steps:
        ok, detail = fn()
        checks.append({"id": cid, "ok": ok, "detail": detail})
    return {
        "v": 1,
        "feature": feature,
        "base": base,
        "tree": tree_of(wt),
        "ok": all(c["ok"] for c in checks),
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("feature")
    c.add_argument("--owned", default="", metavar="GLOB,...")
    c.add_argument("--json", action="store_true")
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    try:
        root = Path(out(Path.cwd(), "rev-parse", "--show-toplevel"))
        owned = [g for g in args.owned.split(",") if g]
        if owned:
            parallel_check.parse_owned([f"{args.feature}={args.owned}"])
        result = run_checks(root, args.feature, owned)
    except GateError as e:
        print(str(e), file=sys.stderr)
        return 2
    except SystemExit as e:  # parallel_check.git / parse_owned の失敗
        print(str(e.code), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"feature/{result['feature']} base={result['base'][:12]} tree={result['tree'][:12]}")
        for ck in result["checks"]:
            print(f"  {'ok  ' if ck['ok'] else 'FAIL'} {ck['id']}: {ck['detail']}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
