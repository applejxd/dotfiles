"""worker の課題の採点。run_dir/ws を採点し、run_dir/grade.json に書く。

合格 = 隠しテストが通る (tests は変異をすべて殺す) かつ 担当外の編集が無い かつ 全テストが通る。
see scripts/model-eval/README.md
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE / "base"
HIDDEN = HERE / "hidden"

BASIC = ["feature", "bugfix", "refactor", "tests", "multi"]
HARD = ["semver", "ini"]
TASKS = BASIC + HARD

OWNED = {
    "feature": {"src/tk/durations.py", "tests/test_durations.py"},
    "bugfix": {"src/tk/paginate.py", "tests/test_paginate.py"},
    "refactor": {"src/tk/report.py"},
    "tests": {"tests/test_money.py"},
    "multi": {"src/tk/config.py", "src/tk/client.py", "src/tk/cli.py", "README.md",
              "tests/test_config.py", "tests/test_client.py"},
    "semver": {"src/tk/semver.py", "tests/test_semver.py"},
    "ini": {"src/tk/ini.py", "tests/test_ini.py"},
}

MUTANTS = {
    "half_even": ("rounding=ROUND_HALF_UP", "rounding=ROUND_HALF_EVEN"),
    "truncate": ('int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))',
                 "int(amount * 100)"),
    "no_thousands": ("{dollars:,}", "{dollars}"),
    "sign_after_dollar": ('f"{sign}${dollars:,}', 'f"${sign}{dollars:,}'),
    "no_pad": ("{rem:02d}", "{rem}"),
    "parse_ignores_sign": ("return -value if sign else value", "return value"),
    "loose_grouping": (r"(\d{1,3}(?:,\d{3})+|\d+)", r"([\d,]+)"),
    "no_strip": ("_PATTERN.match(text.strip())", "_PATTERN.match(text)"),
    "sign_after_dollar_parse": (r"^(-)?\$?", r"^\$?(-)?"),
}


def git(ws: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", *args],
        cwd=ws, capture_output=True, text=True, check=True,
    ).stdout


def run_pytest(py: str, cwd: Path, *args: str, pythonpath: str = "src",
               stop_first: bool = True) -> subprocess.CompletedProcess[str]:
    env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": pythonpath, "PYTHONDONTWRITEBYTECODE": "1"}
    cmd = [py, "-m", "pytest", "-q", "-p", "no:cacheprovider",
           *(["-x"] if stop_first else []), *args]
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env, timeout=300)


def pytest(py: str, cwd: Path, *args: str, pythonpath: str = "src") -> tuple[bool, str]:
    r = run_pytest(py, cwd, *args, pythonpath=pythonpath)
    return r.returncode == 0, (r.stdout + r.stderr)[-1500:]


def fresh_copy(ws: Path, dest: Path) -> Path:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(ws, dest, symlinks=True,
                    ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"))
    return dest


def grade(run: Path, task: str, py: str) -> dict:
    ws = run / "ws"
    changed = [line[3:].split(" -> ")[-1] for line in
               git(ws, "status", "--porcelain", "--untracked-files=all").splitlines()]
    out_of_scope = sorted(p for p in changed if p not in OWNED[task])
    commits = int(git(ws, "rev-list", "--count", "HEAD").strip())
    staged = bool(git(ws, "diff", "--cached", "--name-only").strip())

    g = fresh_copy(ws, run / "grade")
    visible_ok, visible_log = pytest(py, g)
    res = {"task": task, "changed": changed, "out_of_scope": out_of_scope,
           "commits": commits, "staged": staged, "visible_ok": visible_ok}
    if task == "tests":
        tf = g / "tests" / "test_money.py"
        orig_ok, _ = pytest(py, g, "tests/test_money.py") if tf.exists() else (False, "no file")
        killed = {}
        base_src = (BASE / "src" / "tk" / "money.py").read_text()
        for name, (a, b) in MUTANTS.items():
            assert a in base_src, name
            m = fresh_copy(ws, run / "mut")
            (m / "src" / "tk" / "money.py").write_text(base_src.replace(a, b))
            ok, _ = pytest(py, m, "tests/test_money.py") if tf.exists() else (True, "")
            killed[name] = not ok
        shutil.rmtree(run / "mut", ignore_errors=True)
        res.update(original_ok=orig_ok, killed=killed, kill=sum(killed.values()),
                   mutants=len(MUTANTS))
        hidden_ok = orig_ok and all(killed.values())
        hidden_log = ""
    else:
        hd = g / "hidden_tests"
        shutil.copytree(HIDDEN / task, hd)
        hidden_ok, hidden_log = pytest(py, g, "hidden_tests/test_hidden.py",
                                       pythonpath=f"src:{hd}")
        # 失敗数も残すので -x なしでもう一度
        r = run_pytest(py, g, "hidden_tests/test_hidden.py", pythonpath=f"src:{hd}",
                       stop_first=False)
        res["hidden_summary"] = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
    res.update(hidden_ok=hidden_ok, passed=hidden_ok and visible_ok and not out_of_scope)
    res["logs"] = {"visible": visible_log, "hidden": hidden_log}
    (run / "grade.json").write_text(json.dumps(res, ensure_ascii=False, indent=2))
    return res


def main() -> None:
    p = argparse.ArgumentParser(description="worker の課題を採点して <run_dir>/grade.json に書く")
    p.add_argument("run_dir", type=Path, help="ws/ (課題の作業リポジトリ) を持つディレクトリ")
    p.add_argument("task", choices=TASKS)
    p.add_argument("--python", default=os.environ.get("EVAL_PYTHON", sys.executable),
                   help="pytest の入った python (既定: $EVAL_PYTHON、無ければこの python)")
    a = p.parse_args()
    if not (a.run_dir / "ws").is_dir():
        p.error(f"{a.run_dir}/ws が無い")
    res = grade(a.run_dir, a.task, a.python)
    print(json.dumps({k: v for k, v in res.items() if k != "logs"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
