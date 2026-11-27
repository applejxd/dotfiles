#!/usr/bin/env python3
"""PR の保護パス判定・PR タイトル検証・JUnit 検査・CI 集約判定（ci-gate）の単一ソース。

see docs/adr/0044-github-app-auto-merge-and-3os-ci.md
"""

from __future__ import annotations

import argparse
import json
import os
import posixpath
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from pathlib import Path

# 保護パスの正本（ADR-0044）。小文字化して比較し、Windows / macOS の大文字小文字差を吸収する。
# - .github/workflows/** は App の権限でも物理拒否されるが、人間の PR や念のための二重防御として含める。
# - AGENTS.md・スキル・プロンプト・一般 dotfiles は意図的に含めない（無承認自動統合の対象）。
PROTECTED_EXACT: frozenset[str] = frozenset(
    p.lower()
    for p in (
        ".gitattributes",
        ".gitleaks.toml",
        ".gitleaksignore",
        ".pre-commit-config.yaml",
        ".python-version",
        "mise.toml",
        "pyproject.toml",
        "home/.chezmoi.toml.tmpl",
        "home/.chezmoiexternal.toml.tmpl",
        "home/.chezmoiignore.tmpl",
        "home/.chezmoitemplates/modify_pi_permission_config.py.tmpl",
        "home/.chezmoitemplates/modify_pi_stock_settings.py.tmpl",
        "home/.chezmoitemplates/pi-mcp-servers.toml",
        "home/.chezmoitemplates/pi-permission-policy.json",
        "home/dot_local/bin/executable_pi-sandbox-runner",
        "home/dot_pi/agent/modify_mcp.json.py.tmpl",
        "home/dot_pi/agent/modify_settings.json.py.tmpl",
        "scripts/agents/validate_mcp.py",
        "scripts/agents/validate_skills.py",
        "scripts/ai_pr.py",
        "scripts/check_staged_drop.py",
        "scripts/ci_policy.py",
        "scripts/gitleaks_prepush.py",
        "scripts/lint_templates.py",
        "test/agents/agents_common.py",
        "test/agents/conftest.py",
        "test/agents/pi_stock/permission_cases.json",
        "test/test_ai_pr.py",
        "test/test_ci_policy.py",
        "test/test_pi_permission_decisions.py",
    )
)

PROTECTED_PREFIXES: tuple[str, ...] = tuple(
    p.lower()
    for p in (
        ".github/workflows/",
        "home/.chezmoiscripts/",
        "home/dot_cc-safety-net/",
        "home/dot_config/pi-sandbox/",
        "home/dot_pi/agent/agents/",
        "home/dot_pi/agent/extensions/",
        "home/dot_pi/agent/local-packages/",
    )
)

PROTECTED_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^home/dot_local/bin/executable_pib(?:$|-)", re.IGNORECASE),
    re.compile(r"^scripts/verify[^/]*\.py$", re.IGNORECASE),
    re.compile(r"^test/test_verify[^/]*\.py$", re.IGNORECASE),
    re.compile(r"^test/test_pi_sandbox_[^/]+\.py$", re.IGNORECASE),
)

# Conventional Commits の件名規則（PR タイトル → Squash コミット件名）。
CONVENTIONAL_TITLE = re.compile(
    r"^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)"
    r"(?:\([a-z0-9._/-]+\))?!?: .+$"
)
MAX_TITLE_LEN = 72


def normalize_path(path: str) -> str:
    cleaned = path.replace("\\", "/").strip()
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return posixpath.normpath(cleaned) if cleaned else ""


def is_protected_path(path: str) -> bool:
    norm = normalize_path(path)
    if not norm or norm == ".":
        return False
    low = norm.lower()
    if low in PROTECTED_EXACT:
        return True
    if any(low.startswith(prefix) for prefix in PROTECTED_PREFIXES):
        return True
    return any(pattern.match(norm) for pattern in PROTECTED_PATTERNS)


def find_protected_paths(paths: Sequence[str]) -> list[str]:
    return sorted({normalize_path(p) for p in paths if is_protected_path(p)})


def validate_pr_title(title: str) -> str | None:
    """PR タイトルが Conventional Commits に合えば None、違反なら理由文字列を返す。"""
    stripped = title.strip()
    if not stripped:
        return "PR タイトルが空です"
    if "\n" in stripped or "\r" in stripped:
        return "PR タイトルに改行を含められません"
    if len(stripped) > MAX_TITLE_LEN:
        return f"PR タイトルは {MAX_TITLE_LEN} 文字以内にしてください（現在 {len(stripped)} 文字）"
    if stripped.endswith("."):
        return "PR タイトルの末尾にピリオドを付けないでください"
    if not CONVENTIONAL_TITLE.match(stripped):
        return (
            "PR タイトルは Conventional Commits 形式"
            "（例: fix(vim): SSH 経由では unnamedplus を無効にする）にしてください"
        )
    return None


def evaluate_gate(
    job_results: dict[str, str],
    *,
    protected_required: bool,
    approval_result: str | None = None,
) -> tuple[bool, list[str]]:
    """ci-gate の合否を判定する。

    - 全必須ジョブが厳密に 'success' でなければ不合格（'skipped' / 'cancelled' / 'failure' を通過させない）。
    - 保護パス変更がある場合は承認ジョブ結果も厳密に 'success' を要求する。
    """
    reasons: list[str] = []
    if not job_results:
        return False, ["必須ジョブの結果が空です"]
    for name, result in sorted(job_results.items()):
        if result != "success":
            reasons.append(f"必須ジョブ '{name}' が success ではありません（result={result!r}）")
    if protected_required and approval_result != "success":
        reasons.append(
            f"保護パスの変更に対する承認ジョブが success ではありません（result={approval_result!r}）"
        )
    return (not reasons), reasons


def summarize_junit(xml_path: Path) -> dict[str, int]:
    """pytest の JUnit XML を集計する。"""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    tests = sum(int(s.attrib.get("tests", 0)) for s in suites)
    failures = sum(int(s.attrib.get("failures", 0)) for s in suites)
    errors = sum(int(s.attrib.get("errors", 0)) for s in suites)
    skipped = sum(int(s.attrib.get("skipped", 0)) for s in suites)
    passed = max(0, tests - failures - errors - skipped)
    return {
        "tests": tests,
        "passed": passed,
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
    }


def evaluate_junit(
    stats: dict[str, int],
    *,
    min_passed: int,
    max_skipped: int,
) -> tuple[bool, list[str]]:
    """0 件収集・失敗・想定外の大量 skip を不合格にする。"""
    reasons: list[str] = []
    if stats["tests"] <= 0:
        reasons.append("収集されたテストが 0 件です")
    if stats["failures"] > 0 or stats["errors"] > 0:
        reasons.append(f"失敗またはエラーがあります（failures={stats['failures']}, errors={stats['errors']}）")
    if stats["passed"] < min_passed:
        reasons.append(f"passed が下限を下回っています（passed={stats['passed']} < min_passed={min_passed}）")
    if stats["skipped"] > max_skipped:
        reasons.append(f"skipped が上限を超えています（skipped={stats['skipped']} > max_skipped={max_skipped}）")
    return (not reasons), reasons


def changed_files_between(base_ref: str, head_ref: str = "HEAD", cwd: Path | None = None) -> list[str]:
    proc = subprocess.run(
        ["git", "diff", "--name-only", "--no-renames", "-z", f"{base_ref}...{head_ref}"],
        cwd=cwd,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace").strip()
        raise SystemExit(f"git diff に失敗しました: {err}")
    raw = proc.stdout.decode("utf-8", errors="replace")
    return sorted({normalize_path(p) for p in raw.split("\0") if p})


def _write_github_output(values: dict[str, str]) -> None:
    out_path = os.environ.get("GITHUB_OUTPUT")
    if not out_path:
        return
    with Path(out_path).open("a", encoding="utf-8", newline="\n") as fh:
        for key, value in values.items():
            fh.write(f"{key}={value}\n")


def _cmd_check_paths(args: argparse.Namespace) -> int:
    if args.files:
        paths = list(args.files)
    elif args.base:
        paths = changed_files_between(args.base, args.head)
    else:
        paths = [line.strip() for line in sys.stdin if line.strip()]
    protected = find_protected_paths(paths)
    has_protected = bool(protected)
    payload = {
        "changed_count": len(paths),
        "protected": has_protected,
        "protected_paths": protected,
    }
    _write_github_output(
        {
            "protected": "true" if has_protected else "false",
            "protected_count": str(len(protected)),
        }
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def _cmd_check_title(args: argparse.Namespace) -> int:
    err = validate_pr_title(args.title)
    if err:
        print(err, file=sys.stderr)
        return 1
    print(f"OK: {args.title.strip()}")
    return 0


def _cmd_check_gate(args: argparse.Namespace) -> int:
    results: dict[str, str] = {}
    for item in args.job:
        if "=" not in item:
            print(f"--job は name=result 形式で指定してください: {item}", file=sys.stderr)
            return 2
        name, result = item.split("=", 1)
        results[name] = result
    ok, reasons = evaluate_gate(
        results,
        protected_required=(args.protected == "true"),
        approval_result=args.approval,
    )
    if ok:
        print("ci-gate: PASS")
        return 0
    for reason in reasons:
        print(f"ci-gate: FAIL: {reason}", file=sys.stderr)
    return 1


def _cmd_check_junit(args: argparse.Namespace) -> int:
    xml_path = Path(args.xml)
    if not xml_path.is_file():
        print(f"JUnit XML が見つかりません: {xml_path}", file=sys.stderr)
        return 1
    stats = summarize_junit(xml_path)
    ok, reasons = evaluate_junit(stats, min_passed=args.min_passed, max_skipped=args.max_skipped)
    print(json.dumps({"ok": ok, **stats, "reasons": reasons}, ensure_ascii=False))
    if not ok:
        for reason in reasons:
            print(f"junit-gate: FAIL: {reason}", file=sys.stderr)
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CI ポリシー（保護パス・PR タイトル・JUnit・ci-gate）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_paths = sub.add_parser("check-paths", help="保護パスの変更有無を判定する")
    p_paths.add_argument("--base", help="比較元の git ref（base...head で差分を取る）")
    p_paths.add_argument("--head", default="HEAD", help="比較先の git ref（既定 HEAD）")
    p_paths.add_argument("files", nargs="*", help="明示するファイル一覧（省略時は --base か標準入力）")
    p_paths.set_defaults(func=_cmd_check_paths)

    p_title = sub.add_parser("check-title", help="PR タイトルが Conventional Commits か検査する")
    p_title.add_argument("title", help="PR タイトル文字列")
    p_title.set_defaults(func=_cmd_check_title)

    p_gate = sub.add_parser("check-gate", help="ci-gate の集約合否を判定する")
    p_gate.add_argument("--job", action="append", default=[], help="必須ジョブ結果 (name=result)")
    p_gate.add_argument("--protected", choices=("true", "false"), default="false")
    p_gate.add_argument("--approval", default="", help="承認ジョブの結果")
    p_gate.set_defaults(func=_cmd_check_gate)

    p_junit = sub.add_parser("check-junit", help="JUnit XML の 0 件収集・skip 超過を検査する")
    p_junit.add_argument("xml", help="pytest --junitxml の出力ファイル")
    p_junit.add_argument("--min-passed", type=int, required=True, help="最低限必要な passed 件数")
    p_junit.add_argument("--max-skipped", type=int, required=True, help="許容する最大 skipped 件数")
    p_junit.set_defaults(func=_cmd_check_junit)

    parsed = parser.parse_args(argv)
    return int(parsed.func(parsed))


if __name__ == "__main__":
    raise SystemExit(main())
