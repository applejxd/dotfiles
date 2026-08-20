"""Tests for scripts/agents/critical_deny.py.

Run with: ``python3 -m pytest test/agents/`` or
``python3 test/agents/test_critical_deny.py`` for ad-hoc execution.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "home" / "dot_config" / "agents"))

import critical_deny as cd  # noqa: E402


# マッチャの動作を確認するための固定パターン (live な common.toml とは独立)。
# 実際の分類 (critical_deny / critical_ask) は test_check_bash_decision.py で検証する。
PATTERNS = ["sudo", "rm -rf", "git push", "git reset --hard", "git rebase"]


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def test_split_compound_and():
    assert cd.normalize("a && b") == ["a", "b"]


def test_split_compound_semicolon():
    assert cd.normalize("a; b ; c") == ["a", "b", "c"]


def test_split_compound_pipe():
    assert cd.normalize("a | b") == ["a", "b"]


def test_split_respects_quotes():
    assert cd.normalize("echo 'a && b' && true") == ["echo 'a && b'", "true"]


def test_strip_cd_prefix():
    # compound 分割で ["cd /foo", "git push"] になり、cd-only は drop されて
    # 残るのは "git push" のみ
    assert cd.normalize("cd /foo && git push") == ["git push"]


def test_strip_cd_prefix_semicolon():
    assert cd.normalize("cd /foo; git push") == ["git push"]


def test_strip_git_dash_c():
    assert cd.normalize("git -C /foo commit -m hi") == ["git commit -m hi"]


def test_strip_double_git_dash_c():
    assert cd.normalize("git -C /a -C /b status") == ["git status"]


def test_cd_then_git_dash_c():
    assert cd.normalize("cd /x && git -C /y push") == ["git push"]


def test_idempotent_cd():
    # bare cd 単独は drop される (matching に影響しないので)
    assert cd.normalize("cd /foo") == []


# ---------------------------------------------------------------------------
# Matching (positive cases)
# ---------------------------------------------------------------------------

def test_match_plain_git_push():
    assert cd.find_critical_match("git push origin main", PATTERNS) == "git push"


def test_match_cd_bypass():
    assert cd.find_critical_match("cd /elsewhere && git push", PATTERNS) == "git push"


def test_match_git_dash_c_bypass():
    assert cd.find_critical_match("git -C /repo push origin", PATTERNS) == "git push"


def test_match_compound_second_segment():
    assert cd.find_critical_match("echo ok && rm -rf /tmp/x", PATTERNS) == "rm -rf"


def test_match_sudo():
    assert cd.find_critical_match("sudo apt-get install foo", PATTERNS) == "sudo"


def test_match_git_reset_hard():
    assert cd.find_critical_match("git reset --hard HEAD~1", PATTERNS) == "git reset --hard"


def test_match_git_rebase():
    assert cd.find_critical_match("git rebase main", PATTERNS) == "git rebase"


# ---------------------------------------------------------------------------
# Matching (negative cases)
# ---------------------------------------------------------------------------

def test_no_match_pushd():
    assert cd.find_critical_match("pushd /foo", PATTERNS) is None


def test_no_match_git_status():
    assert cd.find_critical_match("git status", PATTERNS) is None


def test_no_match_git_reset_soft():
    assert cd.find_critical_match("git reset HEAD~1", PATTERNS) is None


def test_no_match_rm_without_rf():
    assert cd.find_critical_match("rm foo.txt", PATTERNS) is None


def test_no_match_empty():
    assert cd.find_critical_match("", PATTERNS) is None


def test_no_match_empty_patterns():
    assert cd.find_critical_match("git push", []) is None


# ---------------------------------------------------------------------------
# Edge cases reported in real-world Claude Code bugs
# ---------------------------------------------------------------------------

def test_real_bug_59498_cd_bypass():
    """anthropics/claude-code#59498: cd /diff && git push --dry-run"""
    assert cd.find_critical_match("cd /different/path && git push --dry-run", PATTERNS) == "git push"


def test_real_bug_59006_git_dash_c_bypass():
    """anthropics/claude-code#59006: git -C /path commit -m '...'"""
    assert cd.find_critical_match("git -C /path commit -m foo", ["git commit"]) == "git commit"


def test_real_bug_20085_compound():
    """anthropics/claude-code#20085: compound commands treated as single pattern"""
    assert cd.find_critical_match("ls && sudo rm -rf /", PATTERNS) == "sudo"


# ---------------------------------------------------------------------------
# Ad-hoc runner so we can execute without pytest
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import traceback

    funcs = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in funcs:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:  # pragma: no cover
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(funcs) - failed}/{len(funcs)} passed")
    sys.exit(1 if failed else 0)
