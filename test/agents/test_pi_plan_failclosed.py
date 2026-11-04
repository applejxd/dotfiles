"""judge/plan.ts の fail-closed (``analyze`` は失敗を例外でなく ``ok: false`` で返し、呼び出し側が deny にできる) の試験。

- 読み込み (``vendor`` の欠損・sha 不一致・評価失敗)、構文エラー、制御文字 (CR・NUL ほか)、上限 (長さ・実行箇所・深さ・語)、型の不正は
  すべて ``ok: false``。上限の境界は、許可側 (上限ちょうど) と拒否側 (上限 + 1) の両方を固定する。

see docs/spec/guard/pi-decide.md#解析結果-plan-g1a
"""

from __future__ import annotations

import shlex
import shutil

import pytest
from plan_helper import VENDOR, needs_node, run_cases

pytestmark = needs_node


def _fail(cmd, **kw):
    r = run_cases([{"cmd": cmd, **kw}])[0]
    assert r["ok"] is False, r
    assert r["why"] and r["detail"], r
    return r


def _ok(cmd, **kw):
    r = run_cases([{"cmd": cmd, **kw}])[0]
    assert r["ok"] is True, r
    return r


# --- 読み込み


def test_missing_vendor_is_load_failure(tmp_path):
    assert _fail("git log", vendor=str(tmp_path / "none"))["why"] == "load"


def test_empty_vendor_dir_is_load_failure(tmp_path):
    assert _fail("git log", vendor=str(tmp_path))["why"] == "load"


def test_sha_mismatch_is_sha_failure(tmp_path):
    dst = tmp_path / "mvdan-sh"
    shutil.copytree(VENDOR, dst)
    index = dst / "index.js"
    index.write_bytes(index.read_bytes() + b"\n")
    assert _fail("git log", vendor=str(dst))["why"] == "sha"


def test_same_size_tamper_is_sha_failure(tmp_path):
    dst = tmp_path / "mvdan-sh"
    shutil.copytree(VENDOR, dst)
    index = dst / "index.js"
    data = bytearray(index.read_bytes())
    data[-1] ^= 1
    index.write_bytes(bytes(data))
    assert _fail("git log", vendor=str(dst))["why"] == "sha"


def test_evaluation_failure_is_eval_failure(tmp_path):
    """sha は一致するが評価 (new Function) が失敗する状況を、driver の breakEval で再現する。"""
    dst = tmp_path / "mvdan-sh"
    shutil.copytree(VENDOR, dst)
    r = _fail("git log", vendor=str(dst), breakEval=True)
    assert r["why"] == "eval", r


def test_valid_vendor_copy_loads(tmp_path):
    dst = tmp_path / "mvdan-sh"
    shutil.copytree(VENDOR, dst)
    assert _ok("git log", vendor=str(dst))["sites"]


# --- 構文エラー・入力の型


@pytest.mark.parametrize(
    "cmd",
    [
        'echo "unterminated',
        "if true; then",
        "(",
        "a &&",
        "echo $(",
        "echo `a",
        "a | | b",
        "fi",
        "cat <<E\nbody",
        "echo ${",
    ],
)
def test_syntax_error_is_failure(cmd):
    assert _fail(cmd)["why"] == "syntax"


def test_null_command_is_failure():
    assert _fail(None)["why"] == "throw"


@pytest.mark.parametrize("cmd", [None, 5, ["a"], {"a": 1}])
def test_non_string_never_raises(cmd):
    r = run_cases([{"cmd": cmd}])[0]
    assert r["ok"] is False and r["why"] == "throw"


def test_syntax_error_inside_bash_c_is_failure():
    assert _fail("bash -c 'echo \"x'")["why"] == "syntax"


def test_syntax_error_inside_heredoc_to_shell_is_failure():
    assert _fail('bash <<E\necho "x\nE')["why"] == "syntax"


# --- 制御文字 (CR は mvdan-sh が空白扱い、NUL は黙って落とすので、構文木に渡す前に拒否する)


@pytest.mark.parametrize(
    "cmd",
    [
        "git log\r",
        "git\rpush",
        "echo \x00",
        "echo a\x00b",
        "echo \x01",
        "echo \x0b",
        "echo \x0c",
        "echo \x1b[0m",
        "echo \x1f",
        "\x08ls",
    ],
)
def test_control_characters_are_ctl_failure(cmd):
    assert _fail(cmd)["why"] == "ctl"


@pytest.mark.parametrize("cmd", ["echo a\tb", "echo a\nb", "echo \u3000", "echo \x7f"])
def test_tab_newline_and_non_c0_are_allowed(cmd):
    _ok(cmd)


# --- 上限の境界: 許可側 (ちょうど) と拒否側 (+1)


def test_length_10000_is_allowed_and_10001_is_not():
    _ok("echo " + "a" * 9995)
    r = _fail("echo " + "a" * 9996)
    assert r["why"] == "limit:len"


def test_length_counts_characters_not_bytes():
    _ok("echo " + "あ" * 9995)
    assert _fail("echo " + "あ" * 9996)["why"] == "limit:len"


def test_sites_200_is_allowed_and_201_is_not():
    assert len(_ok(";".join(["a"] * 200))["sites"]) == 200
    assert _fail(";".join(["a"] * 201))["why"] == "limit:sites"


def test_sites_counted_across_nested_sites():
    inner = ";".join(["a"] * 99)
    assert len(_ok(f"echo $({inner}) $({inner})")["sites"]) == 199
    assert _fail(f"echo $({inner}) $({inner}) $({inner})")["why"] == "limit:sites"


def test_depth_4_is_allowed_and_5_is_not():
    four = "echo $(echo $(echo $(echo $(echo x))))"
    five = "echo $(echo $(echo $(echo $(echo $(echo x)))))"
    assert max(s["depth"] for s in _ok(four)["sites"]) == 4
    assert _fail(five)["why"] == "limit:depth"


def _nest_bash_c(n):
    cmd = "true"
    for _ in range(n):
        cmd = "bash -c " + shlex.quote(cmd)
    return cmd


def test_depth_through_bash_c_counts():
    assert max(s["depth"] for s in _ok(_nest_bash_c(4))["sites"]) == 4
    assert _fail(_nest_bash_c(5))["why"] == "limit:depth"


def test_words_4000_is_allowed_and_4001_is_not():
    assert len(_ok("echo " + "a " * 3999)["sites"][0]["argv"]) == 4000
    assert _fail("echo " + "a " * 4000)["why"] == "limit:words"


def test_words_counted_across_statements():
    one = "echo " + "a " * 1999  # 2000 語
    assert _fail(f"{one}; {one}; echo b")["why"] == "limit:words"
    _ok(f"{one}; {one}")


def test_failure_carries_the_original_source():
    r = _fail('echo "x')
    assert r["source"] == 'echo "x'
