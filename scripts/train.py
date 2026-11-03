#!/usr/bin/env python3
"""複数の feature を 1 本の統合用の枝 (feature/train-N) にまとめて取り込む道具。

    python3 scripts/train.py start [--name train-N] <feature>...
    python3 scripts/train.py continue [--name train-N]
    python3 scripts/train.py verify [--name train-N]
    python3 scripts/train.py status [--name train-N]
    python3 scripts/train.py summary [--name train-N]

<feature> は `a` でも `feature/a` でもよい。リポジトリ (本体か任意の worktree) の中で実行する。
衝突は直さず、止めて終了コード 3 を返す (解消は worker の仕事。docs/spec/orchestration.md#統合用の枝train)。
終了コード: 0 = 成功、1 = verify の失敗、2 = 使い方・前提違反・git の失敗、3 = 衝突で停止。
verify のコマンドは環境変数 TRAIN_VERIFY_CMD で差し替えられる (試験用。既定は `mise run verify:all`)。
Windows は実機で未検証。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

EXIT_OK, EXIT_VERIFY, EXIT_ERROR, EXIT_CONFLICT = 0, 1, 2, 3
LOCK_RE = re.compile(r"owner=(\S+)\s+id=(\S+)\s+pid=(\d+)\s+started=(\d+)")
STATE_FILE = "train-state.json"


class TrainError(Exception):
    pass


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    r = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", check=False
    )
    if check and r.returncode != 0:
        raise TrainError(f"git {' '.join(args)} に失敗: {r.stderr.strip() or r.stdout.strip()}")
    return r


def repo_root(cwd: Path) -> Path:
    common = git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
    return Path(common).parent


def config(root: Path, key: str, default: str) -> str:
    r = git(root, "config", "--get", key, check=False)
    return r.stdout.strip() or default


def feature_prefix(root: Path) -> str:
    return config(root, "gitflow.branch.feature.prefix", "feature/")


def base_branch(root: Path) -> str:
    return config(root, "gitflow.branch.feature.startpoint", "develop")


def normalize(root: Path, name: str) -> str:
    prefix = feature_prefix(root)
    return name if name.startswith(prefix) else prefix + name


def worktree_path(root: Path, short: str) -> Path:
    return root / ".tmp" / "worktrees" / short


def branch_exists(root: Path, branch: str) -> bool:
    return (
        git(
            root, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False
        ).returncode
        == 0
    )


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def live_lock(root: Path, branch: str) -> str | None:
    """枝の worktree に、生きている pid の owner の lock があれば、その理由を返す。"""
    out = git(root, "worktree", "list", "--porcelain").stdout
    for block in out.split("\n\n"):
        lines = block.splitlines()
        if f"branch refs/heads/{branch}" not in lines:
            continue
        for line in lines:
            if line == "locked" or line.startswith("locked "):
                reason = line[len("locked ") :]
                m = LOCK_RE.search(reason)
                if m and pid_alive(int(m.group(3))):
                    return reason
    return None


def check_branch(root: Path, branch: str) -> None:
    base = base_branch(root)
    if not branch_exists(root, branch):
        raise TrainError(f"枝が存在しません: {branch}")
    if git(root, "merge-base", "--is-ancestor", branch, base, check=False).returncode == 0:
        raise TrainError(f"{branch} は既に {base} に統合済みです")
    lock = live_lock(root, branch)
    if lock:
        raise TrainError(f"{branch} の worktree は他の owner が使用中です (lock: {lock})")


def free_name(root: Path) -> str:
    prefix = feature_prefix(root)
    n = 1
    while branch_exists(root, f"{prefix}train-{n}") or worktree_path(root, f"train-{n}").exists():
        n += 1
    return f"train-{n}"


def state_path(wt: Path) -> Path:
    gd = git(wt, "rev-parse", "--path-format=absolute", "--git-dir").stdout.strip()
    return Path(gd) / STATE_FILE


def load_state(wt: Path) -> dict:
    p = state_path(wt)
    if not p.is_file():
        raise TrainError("train の状態がありません (start していない worktree です)")
    return json.loads(p.read_text(encoding="utf-8"))


def save_state(wt: Path, state: dict) -> None:
    state_path(wt).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_wt(root: Path, name: str | None, cwd: Path) -> tuple[str, Path]:
    if not name:
        cur = git(cwd, "branch", "--show-current", check=False).stdout.strip()
        prefix = feature_prefix(root)
        if not cur.startswith(prefix + "train-"):
            raise TrainError("--name train-N を指定してください")
        name = cur[len(prefix) :]
    wt = worktree_path(root, name)
    if not wt.is_dir():
        raise TrainError(f"worktree がありません: {wt}")
    return name, wt


def unmerged_files(wt: Path) -> list[str]:
    return git(wt, "diff", "--name-only", "--diff-filter=U").stdout.split()


def merge_all(wt: Path, state: dict) -> int:
    """state["pending"] を先頭から merge する。衝突したら止めて 3 を返す。"""
    while state["pending"]:
        branch = state["pending"][0]
        short = branch.split("/", 1)[-1]
        r = git(wt, "merge", "--no-edit", "-m", f"merge: {short}を取り込む", branch, check=False)
        if r.returncode != 0:
            files = unmerged_files(wt)
            if not files:
                raise TrainError(f"merge {branch} に失敗: {r.stderr.strip() or r.stdout.strip()}")
            state["conflict"] = branch
            save_state(wt, state)
            print(f"衝突: {branch} の取り込みで止まりました。衝突ファイル:")
            for f in files:
                print(f"  {f}")
            print(
                f"この worktree ({wt}) で worker に解消させてください (自明でもスクリプトは直しません)。"
            )
            print(
                "解消して `git add -A` したあと、`python3 scripts/train.py continue` で続けます。"
            )
            return EXIT_CONFLICT
        state["pending"].pop(0)
        state["merged"].append(branch)
        state["conflict"] = None
        save_state(wt, state)
        print(f"取り込み: {branch}")
    print("すべての枝を取り込みました。次は `python3 scripts/train.py verify`。")
    return EXIT_OK


def cmd_start(args: argparse.Namespace, cwd: Path) -> int:
    root = repo_root(cwd)
    branches: list[str] = []
    for n in args.features:
        b = normalize(root, n)
        if b not in branches:
            branches.append(b)
    for b in branches:
        check_branch(root, b)
    name = args.name or free_name(root)
    prefix = feature_prefix(root)
    tbranch = f"{prefix}{name}" if not name.startswith(prefix) else name
    short = tbranch[len(prefix) :]
    wt = worktree_path(root, short)
    if branch_exists(root, tbranch) or wt.exists():
        raise TrainError(f"{tbranch} か {wt} が既にあります")
    git(root, "worktree", "add", "-b", tbranch, str(wt), base_branch(root))
    print(f"作成: {tbranch} ({wt})")
    state = {"branch": tbranch, "pending": branches, "merged": [], "conflict": None}
    save_state(wt, state)
    return merge_all(wt, state)


def has_markers(wt: Path, files: list[str]) -> list[str]:
    bad = []
    for f in files:
        p = wt / f
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if re.search(r"^(<{7} |>{7} |={7}$)", text, re.M):
            bad.append(f)
    return bad


def cmd_continue(args: argparse.Namespace, cwd: Path) -> int:
    root = repo_root(cwd)
    _, wt = resolve_wt(root, args.name, cwd)
    state = load_state(wt)
    if (
        Path(git(wt, "rev-parse", "--path-format=absolute", "--git-dir").stdout.strip())
        / "MERGE_HEAD"
    ).exists():
        left = unmerged_files(wt)
        if left:
            raise TrainError("未解決のファイルが残っています: " + ", ".join(left))
        dirty = git(wt, "diff", "--name-only").stdout.split()
        if dirty:
            raise TrainError("`git add -A` が済んでいません: " + ", ".join(dirty))
        marked = has_markers(wt, git(wt, "diff", "--cached", "--name-only").stdout.split())
        if marked:
            raise TrainError("衝突マーカーが残っています: " + ", ".join(marked))
        branch = state["conflict"] or state["pending"][0]
        short = branch.split("/", 1)[-1]
        git(wt, "commit", "--no-edit", "-m", f"merge: {short}を取り込む (衝突解消)")
        if state["pending"] and state["pending"][0] == branch:
            state["pending"].pop(0)
        state["merged"].append(branch)
        state["conflict"] = None
        save_state(wt, state)
        print(f"取り込み (衝突解消): {branch}")
    return merge_all(wt, state)


def parse_verify(output: str) -> dict[str, int]:
    """pytest 形式の要約行 ('12 passed', '2 failed' …) の件数を足し上げる。"""
    counts = {"passed": 0, "failed": 0, "error": 0}
    for key in counts:
        for m in re.finditer(rf"\b(\d+) {key}s?\b", output):
            counts[key] += int(m.group(1))
    return counts


def cmd_verify(args: argparse.Namespace, cwd: Path) -> int:
    root = repo_root(cwd)
    _, wt = resolve_wt(root, args.name, cwd)
    cmd = shlex.split(os.environ.get("TRAIN_VERIFY_CMD", "mise run verify:all"))
    r = subprocess.run(cmd, cwd=wt, capture_output=True, text=True, encoding="utf-8", check=False)
    out = r.stdout + r.stderr
    c = parse_verify(out)
    print(
        f"verify: 終了コード {r.returncode} / passed {c['passed']} / failed {c['failed']} / error {c['error']}"
    )
    if r.returncode != 0:
        print("--- 出力の末尾 ---")
        print("\n".join(out.splitlines()[-30:]))
    return EXIT_OK if r.returncode == 0 else EXIT_VERIFY


def cmd_status(args: argparse.Namespace, cwd: Path) -> int:
    root = repo_root(cwd)
    _name, wt = resolve_wt(root, args.name, cwd)
    state = load_state(wt)
    print(f"{state['branch']} ({wt})")
    for b in state["merged"]:
        print(f"  取り込み済み: {b}")
    for b in state["pending"]:
        mark = "衝突中" if b == state["conflict"] else "未取り込み"
        print(f"  {mark}: {b}")
    return EXIT_OK


def cmd_summary(args: argparse.Namespace, cwd: Path) -> int:
    root = repo_root(cwd)
    _, wt = resolve_wt(root, args.name, cwd)
    state = load_state(wt)
    base = base_branch(root)
    print(f"統合用の枝 {state['branch']} (基点 {base})")
    for b in state["merged"]:
        n = git(wt, "rev-list", "--count", f"{base}..{b}").stdout.strip()
        print(f"- {b}: {n} コミット")
    files = git(wt, "diff", "--name-only", f"{base}...HEAD").stdout.split()
    print(f"変更ファイル数: {len(files)}")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("start")
    p.add_argument("--name")
    p.add_argument("features", nargs="+")
    for c in ("continue", "verify", "status", "summary"):
        sub.add_parser(c).add_argument("--name")
    args = ap.parse_args(argv)
    fn = {
        "start": cmd_start,
        "continue": cmd_continue,
        "verify": cmd_verify,
        "status": cmd_status,
        "summary": cmd_summary,
    }[args.cmd]
    try:
        return fn(args, Path.cwd())
    except TrainError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
