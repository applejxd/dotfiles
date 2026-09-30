"""採点の自己テスト。

模範解答 (solutions/) で合格し、元のリポジトリ (base/) で隠しテストが落ちるかを見る。

課題や隠しテストを直したら、計測の前に通す。モデルは呼ばない。
see scripts/model-eval/README.md
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from grade import TASKS, grade

HERE = Path(__file__).resolve().parent


def make_run(root: Path, name: str, task: str, solved: bool) -> Path:
    run = root / name
    ws = run / "ws"
    subprocess.run(["bash", str(HERE / "mkws.sh"), str(ws)], check=True)
    if solved:
        subprocess.run(
            ["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "apply",
             str(HERE / "solutions" / f"{task}.patch")],
            cwd=ws, check=True,
        )
    return run


def check(task: str, py: str, root: Path) -> list[str]:
    errors = []
    ok = grade(make_run(root, f"ok-{task}", task, solved=True), task, py)
    if not ok["passed"]:
        errors.append(f"{task}: 模範解答が不合格 {ok.get('hidden_summary') or ok.get('killed')}"
                      f" oos={ok['out_of_scope']} {ok['logs']}")
    bad = grade(make_run(root, f"base-{task}", task, solved=False), task, py)
    if bad["hidden_ok"]:
        errors.append(f"{task}: 元のリポジトリで隠しテストが通る")
    if not bad["visible_ok"]:
        errors.append(f"{task}: 元のリポジトリで既存のテストが落ちる")
    summary = ok.get("hidden_summary") or f"kill {ok.get('kill')}/{ok.get('mutants')}"
    base = bad.get("hidden_summary") or f"kill {bad.get('kill')}/{bad.get('mutants')}"
    print(f"{task:9} 模範解答: {summary} / 元: {base}")
    return errors


def main() -> int:
    p = argparse.ArgumentParser(description="採点 (grade.py) を模範解答と元のリポジトリで確かめる")
    p.add_argument("tasks", nargs="*", help=f"課題 (省略時は全部): {' '.join(TASKS)}")
    p.add_argument("--python", default=os.environ.get("EVAL_PYTHON", sys.executable),
                   help="pytest の入った python (既定: $EVAL_PYTHON、無ければこの python)")
    a = p.parse_args()
    unknown = sorted(set(a.tasks) - set(TASKS))
    if unknown:
        p.error(f"未知の課題: {' '.join(unknown)}")
    errors = []
    with tempfile.TemporaryDirectory(prefix="model-eval-selftest-") as tmp:
        for task in a.tasks or TASKS:
            errors += check(task, a.python, Path(tmp))
    for e in errors:
        print("NG", e, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
