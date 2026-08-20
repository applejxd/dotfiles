"""Tests for home/dot_config/agents/command_policy.py.

Run with: ``python3 -m pytest test/agents/`` or
``python3 test/agents/test_command_policy.py`` for ad-hoc execution.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "home" / "dot_config" / "agents"))

import command_policy as policy  # noqa: E402


# マッチャの動作を確認するための固定パターン (live な common.toml とは独立)。
# 実際の分類 ([bash] deny / ask) は test_check_bash_decision.py で検証する。
PATTERNS = ["sudo", "rm -rf", "git push", "git reset --hard", "git rebase"]


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def test_split_compound_and():
    assert policy.normalize("a && b") == ["a", "b"]


def test_split_compound_semicolon():
    assert policy.normalize("a; b ; c") == ["a", "b", "c"]


def test_split_compound_pipe():
    assert policy.normalize("a | b") == ["a", "b"]


def test_split_respects_quotes():
    assert policy.normalize("echo 'a && b' && true") == ["echo 'a && b'", "true"]


def test_strip_cd_prefix():
    # compound 分割で ["cd /foo", "git push"] になり、cd-only は drop されて
    # 残るのは "git push" のみ
    assert policy.normalize("cd /foo && git push") == ["git push"]


def test_strip_cd_prefix_semicolon():
    assert policy.normalize("cd /foo; git push") == ["git push"]


def test_strip_git_dash_c():
    assert policy.normalize("git -C /foo commit -m hi") == ["git commit -m hi"]


def test_strip_double_git_dash_c():
    assert policy.normalize("git -C /a -C /b status") == ["git status"]


def test_cd_then_git_dash_c():
    assert policy.normalize("cd /x && git -C /y push") == ["git push"]


def test_idempotent_cd():
    # bare cd 単独は drop される (matching に影響しないので)
    assert policy.normalize("cd /foo") == []


# ---------------------------------------------------------------------------
# Matching (positive cases)
# ---------------------------------------------------------------------------

def test_match_plain_git_push():
    assert policy.find_match("git push origin main", PATTERNS) == "git push"


def test_match_cd_bypass():
    assert policy.find_match("cd /elsewhere && git push", PATTERNS) == "git push"


def test_match_git_dash_c_bypass():
    assert policy.find_match("git -C /repo push origin", PATTERNS) == "git push"


def test_match_compound_second_segment():
    assert policy.find_match("echo ok && rm -rf /tmp/x", PATTERNS) == "rm -rf"


def test_match_sudo():
    assert policy.find_match("sudo apt-get install foo", PATTERNS) == "sudo"


def test_match_git_reset_hard():
    assert policy.find_match("git reset --hard HEAD~1", PATTERNS) == "git reset --hard"


def test_match_git_rebase():
    assert policy.find_match("git rebase main", PATTERNS) == "git rebase"


# ---------------------------------------------------------------------------
# Matching (negative cases)
# ---------------------------------------------------------------------------

def test_no_match_pushd():
    assert policy.find_match("pushd /foo", PATTERNS) is None


def test_no_match_git_status():
    assert policy.find_match("git status", PATTERNS) is None


def test_no_match_git_reset_soft():
    assert policy.find_match("git reset HEAD~1", PATTERNS) is None


def test_no_match_rm_without_rf():
    assert policy.find_match("rm foo.txt", PATTERNS) is None


def test_no_match_empty():
    assert policy.find_match("", PATTERNS) is None


def test_no_match_empty_patterns():
    assert policy.find_match("git push", []) is None


# ---------------------------------------------------------------------------
# Edge cases reported in real-world Claude Code bugs
# ---------------------------------------------------------------------------

def test_real_bug_59498_cd_bypass():
    """anthropics/claude-code#59498: cd /diff && git push --dry-run"""
    assert policy.find_match("cd /different/path && git push --dry-run", PATTERNS) == "git push"


def test_real_bug_59006_git_dash_c_bypass():
    """anthropics/claude-code#59006: git -C /path commit -m '...'"""
    assert policy.find_match("git -C /path commit -m foo", ["git commit"]) == "git commit"


def test_real_bug_20085_compound():
    """anthropics/claude-code#20085: compound commands treated as single pattern"""
    assert policy.find_match("ls && sudo rm -rf /", PATTERNS) == "sudo"


# ---------------------------------------------------------------------------
# 先頭トークンを変える飾りの剥がし
# ---------------------------------------------------------------------------

def test_normalize_strips_grouping():
    assert policy.normalize("(git push)") == ["git push"]
    assert policy.normalize("{ git push; }") == ["git push"]


def test_normalize_strips_env_assignments():
    assert policy.normalize("GIT_DIR=/x git push") == ["git push"]
    assert policy.normalize("FOO=1 BAR=2 git push") == ["git push"]


def test_normalize_strips_absolute_path():
    assert policy.normalize("/usr/bin/git push") == ["git push"]


def test_normalize_strips_wrappers():
    assert policy.normalize("env git push") == ["git push"]
    assert policy.normalize("command git push") == ["git push"]
    assert policy.normalize("nohup git push") == ["git push"]
    assert policy.normalize("timeout 5 git push") == ["git push"]
    assert policy.normalize("timeout 1.5s git push") == ["git push"]
    assert policy.normalize("nice -n 5 git push") == ["git push"]
    assert policy.normalize("xargs -I{} git push") == ["git push"]


def test_normalize_expands_shell_invocation():
    assert "git push" in policy.normalize('bash -c "git push"')
    assert "git push" in policy.normalize("sh -c 'git push'")
    assert "git push" in policy.normalize('bash -lc "git push"')


def test_normalize_expands_eval():
    assert "git push" in policy.normalize("eval 'git push'")


def test_normalize_keeps_the_shell_segment_itself():
    """`curl x | sh` を検出できるよう、シェル起動自体もセグメントに残す."""
    segments = policy.normalize('bash -c "git push"')
    assert segments[0].startswith("bash")


def test_normalize_handles_nested_wrappers():
    assert "git push" in policy.normalize('env FOO=1 /usr/bin/timeout 5 bash -c "git push"')


def test_normalize_recursion_is_bounded():
    """自己参照的な入力でも停止すること."""
    nested = 'bash -c "bash -c \\"bash -c \\\\\\"git push\\\\\\"\\""'
    assert policy.normalize(nested)  # 例外にならず何か返ればよい


def test_normalize_does_not_strip_script_arguments():
    """`bash script.sh` はスクリプト実行なので中身を展開しない."""
    assert policy.normalize("bash test/test.sh") == ["bash test/test.sh"]


def test_find_match_sees_through_wrappers():
    assert policy.find_match('bash -c "git push"', PATTERNS) == "git push"
    assert policy.find_match("timeout 5 git push", PATTERNS) == "git push"
    assert policy.find_match("(sudo apt install foo)", PATTERNS) == "sudo"


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
