"""コミットの計画を固定し、表示し、確かめてから実行する (判断はモデル、表示と実行はこのスクリプト)。

    python3 commit_plan.py snapshot            # 今の状態を記録し、計画 ID を出す
    python3 commit_plan.py save <ID> '<JSON>'  # 計画を保存する (1 回だけ)
    python3 commit_plan.py show <ID>           # 計画の全文を出す (親はこれをそのまま返答に書く)
    python3 commit_plan.py apply <ID>          # 状態を確かめ、単位ごとにステージしてコミットする

計画の JSON: {"units": [{"paths": ["相対パス", ...], "message": "件名\\n\\n本文"}]}
置き場は <git の共通ディレクトリ>/commit-plan/<ID>/ (作業ツリーを汚さない)。
標準ライブラリだけで動かす。
see docs/change/0014-deterministic-commit-runner.md
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

MAX_MESSAGE = 10_000
MAX_UNITS = 50
# 進行中の操作。どれかがあれば計画も実行もしない
IN_PROGRESS = (
    "MERGE_HEAD",
    "CHERRY_PICK_HEAD",
    "REVERT_HEAD",
    "REBASE_HEAD",
    "rebase-merge",
    "rebase-apply",
    "BISECT_LOG",
)


class PlanError(Exception):
    pass


def git(*args: str, input_text: str | None = None, check: bool = True) -> str:
    done = subprocess.run(
        ["git", "-c", "core.quotepath=off", *args],
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if check and done.returncode != 0:
        raise PlanError(
            f"git {' '.join(args)} が失敗した: {done.stderr.strip() or done.stdout.strip()}"
        )
    return done.stdout


def repo_root() -> Path:
    return Path(git("rev-parse", "--show-toplevel").strip())


def state_dir() -> Path:
    common = Path(git("rev-parse", "--git-common-dir").strip())
    if not common.is_absolute():
        common = Path.cwd() / common
    return common.resolve() / "commit-plan"


def git_dir() -> Path:
    path = Path(git("rev-parse", "--git-dir").strip())
    return path if path.is_absolute() else (Path.cwd() / path).resolve()


def head() -> str | None:
    out = subprocess.run(
        ["git", "rev-parse", "--verify", "-q", "HEAD"], capture_output=True, text=True, check=False
    )
    return out.stdout.strip() or None


def branch() -> str:
    return git("branch", "--show-current").strip()


def require_clean_state() -> None:
    gd = git_dir()
    busy = [name for name in IN_PROGRESS if (gd / name).exists()]
    if busy:
        raise PlanError(f"進行中の操作があります ({', '.join(busy)})。終えてから計画してください")
    if not branch():
        raise PlanError(
            "ブランチに居ません (detached HEAD)。ブランチに切り替えてから計画してください"
        )
    staged = git("diff", "--cached", "--name-only", "-z").strip("\0")
    if staged:
        raise PlanError(
            "ステージ済みの変更があります。この計画はステージの空いた状態からだけ作れます"
            f" (ステージ済み: {', '.join(staged.split(chr(0)))})"
        )


def fingerprint(root: Path, rel: str) -> dict[str, object] | None:
    """ファイルの中身とモードの指紋。無ければ None。"""
    path = root / rel
    if path.is_symlink():
        return {"kind": "symlink", "sha256": hashlib.sha256(os.readlink(path).encode()).hexdigest()}
    if not path.exists():
        return None
    if path.is_dir():
        raise PlanError(f"{rel} はディレクトリです (サブモジュールなどは対象外)")
    return {
        "kind": "file",
        "exec": os.access(path, os.X_OK),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def changed_files() -> dict[str, str]:
    """ステージの空いた状態での変更 (パス -> 状態の 2 文字)。"""
    out = git("status", "--porcelain=v1", "-z", "--untracked-files=all")
    entries: dict[str, str] = {}
    items = out.split("\0")
    i = 0
    while i < len(items):
        item = items[i]
        i += 1
        if not item:
            continue
        code, path = item[:2], item[3:]
        if code[0] in "RC":
            i += 1  # 名前の変更の元。ステージが空なら出ない
        entries[path] = code
    return entries


def plan_dir(plan_id: str) -> Path:
    if not plan_id.replace("-", "").isalnum():
        raise PlanError(f"計画 ID の形が違います: {plan_id!r}")
    path = state_dir() / plan_id
    if not (path / "snapshot.json").exists():
        raise PlanError(f"計画 {plan_id} が見つかりません。snapshot からやり直してください")
    return path


def load(path: Path) -> dict:
    return json.loads(path.read_text("utf-8"))


def write_new(path: Path, text: str) -> None:
    """新規作成だけ。既にあれば失敗する (計画は書き換えない)。"""
    with path.open("x", encoding="utf-8") as fh:
        fh.write(text)


# --- snapshot -----------------------------------------------------------------


def cmd_snapshot() -> int:
    require_clean_state()
    root = repo_root()
    files = changed_files()
    if not files:
        raise PlanError("コミットする変更がありません")
    plan_id = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
    path = state_dir() / plan_id
    path.mkdir(parents=True)
    snapshot = {
        "id": plan_id,
        "root": str(root),
        "head": head(),
        "branch": branch(),
        "files": {
            rel: {"status": code, "print": fingerprint(root, rel)} for rel, code in files.items()
        },
    }
    write_new(path / "snapshot.json", json.dumps(snapshot, ensure_ascii=False, indent=2))
    print(f"計画 ID: {plan_id}")
    print(f"ブランチ: {snapshot['branch']}")
    print(f"変更 ({len(files)} 件):")
    for rel, code in files.items():
        print(f"  {code} {rel}")
    return 0


# --- save / show ----------------------------------------------------------------


def validate_plan(raw: str, snapshot: dict) -> list[dict]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as err:
        raise PlanError(f"計画の JSON を読めません: {err}") from err
    units = data.get("units") if isinstance(data, dict) else None
    if not isinstance(units, list) or not units:
        raise PlanError(
            '計画は {"units": [{"paths": [...], "message": "..."}]} の形で書いてください'
        )
    if len(units) > MAX_UNITS:
        raise PlanError(f"単位が多すぎます ({len(units)} 件。上限 {MAX_UNITS})")
    known = snapshot["files"]
    seen: set[str] = set()
    out = []
    for n, unit in enumerate(units, start=1):
        if not isinstance(unit, dict) or set(unit) != {"paths", "message"}:
            raise PlanError(f"単位 {n} は paths と message だけを持ちます")
        paths, message = unit["paths"], unit["message"]
        if not isinstance(paths, list) or not paths or not all(isinstance(p, str) for p in paths):
            raise PlanError(f"単位 {n} の paths はパスの文字列の並びです")
        for rel in paths:
            if rel not in known:
                raise PlanError(f"単位 {n} の {rel!r} は snapshot の変更にありません")
            if rel in seen:
                raise PlanError(f"{rel!r} が複数の単位にあります")
            seen.add(rel)
        if not isinstance(message, str) or "\0" in message or len(message) > MAX_MESSAGE:
            raise PlanError(f"単位 {n} の message は {MAX_MESSAGE} 文字以内の文字列です")
        message = "\n".join(line.rstrip() for line in message.strip().splitlines())
        if not message or not message.splitlines()[0].strip():
            raise PlanError(f"単位 {n} の message の 1 行目 (件名) が空です")
        out.append({"paths": paths, "message": message})
    return out


def render(snapshot: dict, units: list[dict]) -> str:
    """計画の全文。親はこれを一字一句そのまま ```text ブロックで返答に書く。"""
    lines = [f"コミット計画 {snapshot['id']}（{snapshot['branch']}、全 {len(units)} 件）"]
    for n, unit in enumerate(units, start=1):
        lines += ["", f"[{n}/{len(units)}] 対象 {len(unit['paths'])} 件"]
        lines += [f"  {snapshot['files'][rel]['status']} {rel}" for rel in unit["paths"]]
        lines += ["  ---", *[f"  {line}" if line else "" for line in unit["message"].splitlines()]]
    rest = [rel for rel in snapshot["files"] if not any(rel in u["paths"] for u in units)]
    if rest:
        lines += ["", f"コミットしない変更 {len(rest)} 件"]
        lines += [f"  {snapshot['files'][rel]['status']} {rel}" for rel in rest]
    return "\n".join(lines)


def cmd_save(plan_id: str, raw: str) -> int:
    path = plan_dir(plan_id)
    snapshot = load(path / "snapshot.json")
    units = validate_plan(raw, snapshot)
    text = render(snapshot, units)
    try:
        write_new(path / "plan.json", json.dumps({"units": units}, ensure_ascii=False, indent=2))
    except FileExistsError as err:
        raise PlanError(
            f"計画 {plan_id} は保存済みです。直すときは snapshot からやり直してください"
        ) from err
    write_new(path / "plan.txt", text)
    print(text)
    return 0


def cmd_show(plan_id: str) -> int:
    path = plan_dir(plan_id)
    if not (path / "plan.txt").exists():
        raise PlanError(f"計画 {plan_id} はまだ保存されていません")
    print((path / "plan.txt").read_text("utf-8"))
    return 0


# --- apply ----------------------------------------------------------------------


def verify_unchanged(snapshot: dict, units: list[dict]) -> None:
    if str(repo_root()) != snapshot["root"]:
        raise PlanError(f"リポジトリが違います (計画: {snapshot['root']})")
    if branch() != snapshot["branch"] or head() != snapshot["head"]:
        raise PlanError("計画の後にブランチか HEAD が変わりました。snapshot からやり直してください")
    require_clean_state()
    root = Path(snapshot["root"])
    for unit in units:
        for rel in unit["paths"]:
            if fingerprint(root, rel) != snapshot["files"][rel]["print"]:
                raise PlanError(f"計画の後に {rel} が変わりました。snapshot からやり直してください")


def cmd_apply(plan_id: str) -> int:
    path = plan_dir(plan_id)
    if not (path / "plan.json").exists():
        raise PlanError(f"計画 {plan_id} はまだ保存されていません")
    snapshot = load(path / "snapshot.json")
    units = load(path / "plan.json")["units"]
    if (path / "plan.txt").read_text("utf-8") != render(snapshot, units):
        raise PlanError("計画の全文が保存時と食い違います")
    if (path / "applied").exists():
        raise PlanError(f"計画 {plan_id} は実行済みです")
    verify_unchanged(snapshot, units)
    try:
        write_new(path / "applied", time.strftime("%Y-%m-%dT%H:%M:%S"))
    except FileExistsError as err:
        raise PlanError(f"計画 {plan_id} は実行済みです") from err
    done: list[str] = []
    for n, unit in enumerate(units, start=1):
        label = f"[{n}/{len(units)}]"
        try:
            git("--literal-pathspecs", "add", "--all", "--", *unit["paths"])
            staged = set(filter(None, git("diff", "--cached", "--name-only", "-z").split("\0")))
            if staged != set(unit["paths"]):
                raise PlanError(f"{label} ステージした内容が計画と違います: {sorted(staged)}")
            git("commit", "--cleanup=verbatim", "-F", "-", input_text=unit["message"] + "\n")
        except PlanError as err:
            print("\n".join(done))
            raise PlanError(
                f"{err}\n{label} で止まりました。{len(done)} 件はコミット済みです。"
                "ステージに残った変更を確かめ、残りは snapshot からやり直してください"
            ) from err
        sha = git("rev-parse", "--short", "HEAD").strip()
        actual = git("log", "-1", "--format=%B").strip()
        note = "" if actual == unit["message"] else "（hook がメッセージを変えました）"
        done.append(f"{label} {sha} {unit['message'].splitlines()[0]}{note}")
    print("\n".join(done))
    left = git("status", "--short", "--untracked-files=all").rstrip()
    print("残りの変更: なし" if not left else f"残りの変更:\n{left}")
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    sub, args = argv[0], argv[1:]
    expected = {"snapshot": 0, "save": 2, "show": 1, "apply": 1}
    if sub not in expected or len(args) != expected[sub]:
        print(f"使い方が違います: {' '.join(argv)}\n{__doc__}", file=sys.stderr)
        return 2
    try:
        if sub == "snapshot":
            return cmd_snapshot()
        if sub == "save":
            return cmd_save(args[0], args[1])
        if sub == "show":
            return cmd_show(args[0])
        return cmd_apply(args[0])
    except PlanError as err:
        print(f"中止: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
