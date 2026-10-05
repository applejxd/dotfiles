"""check_bash.py の削除・ファイル操作の判定。

workspace 内外の rm、scratch (./.tmp) の免除、symlink による脱出、
workspace ルートと .git の保護、root guard、ガード設定の改変。

Run with: ``uv run --with pytest --with pyyaml --no-project pytest test/agents/ -q``
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest
from check_bash_hook import COMMON_PATH, HOOK, HOOK_PATH, ROOT, run_hook

# ---------------------------------------------------------------------------
# workspace 内外の rm
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf ../other-repo",
        "rm -rf ~/Documents",
        "cd /home/user/project && rm -rf ./node_modules",
        'bash -c "cd /elsewhere && rm -rf data"',
    ],
)
def test_project_scoped_rm_asks(command):
    decision, reason = run_hook(command)
    assert decision == "ask", f"{command!r} -> {decision} ({reason})"


@pytest.mark.parametrize(
    "command",
    [
        # workspace の外、または基点が変わるので確証できない
        "rm -rf ../other-repo",
        "rm -rf ~/Documents",
        "rm -rf /var/tmp/build",
        "cd /home/user/project && rm -rf ./node_modules",
        # 静的に解決できない
        "rm -rf $BUILD_DIR",
        'rm -rf "$OUT"/*',
        "rm -rf ${TMPDIR}/x",
        "rm -rf $(cat targets.txt)",
    ],
)
def test_rm_outside_workspace_asks(command):
    decision, reason = run_hook(command)
    assert decision == "ask", f"{command!r} -> {decision} ({reason})"


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf ./.tmp",
        "rm -rf build/",
        "rm -rf ./foo/bar",
        "rm -rf .venv && echo done",
        "rm -rf node_modules",
        "rm -f *.pyc",
        "rm src/old_module.py",
        "rm -rf target/debug",
        "env FOO=1 rm -rf ./build",
        'bash -c "rm -rf ./build"',
    ],
)
def test_rm_inside_workspace_is_delegated(command):
    """workspace 内と確証できる削除は auto / assisted の判定へ委ねる."""
    decision, reason = run_hook(command)
    assert decision is None, f"{command!r} -> {decision} ({reason})"


def test_rm_without_cwd_falls_back_to_ask():
    """payload に cwd が無ければ workspace を確定できないので承認を求める."""
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "rm -rf node_modules"},
    }
    env = {**os.environ, "AGENTS_CONFIG_DIR": str(COMMON_PATH.parent)}
    proc = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        env=env,
    )
    data = json.loads(proc.stdout)
    assert data["permissionDecision"] == "ask"


@pytest.mark.parametrize(
    "command",
    [
        # 上位へ抜ける
        "rm -rf foo/..",
        "rm -rf x/../../y",
        "rm -rf a b ../c",
        "rm -rf -- ../x",
        "rm -rf {a,../b}",
        # 基点を変える
        "pushd /elsewhere && rm -rf data",
        "\\cd /elsewhere && rm -rf data",
        "cd$IFS/elsewhere && rm -rf data",
        "builtin cd /elsewhere && rm -rf data",
        # 対象が標準入力から来る
        "find / -name x | xargs rm -rf y",
        "echo ../../secret | xargs rm -rf",
        # 展開で解決できない
        "rm -rf $(echo .git)",
        # 免除は rm だけに効く。後ろのセグメントの ask は残す
        "rm .tmp/x && git clean -fdx",
        "rm .tmp/x; git push --dry-run",
    ],
)
def test_rm_exemption_is_fail_closed(command):
    """workspace 内と確証できない形は免除しない."""
    decision, reason = run_hook(command)
    assert decision in {"ask", "deny"}, f"{command!r} -> {decision} ({reason})"


@pytest.mark.parametrize(
    "command",
    [
        "find . -name '*.pyc' -delete",
        "find ./build -type f -exec rm {} +",
    ],
)
def test_find_deletion_asks(command):
    decision, reason = run_hook(command)
    assert decision == "ask", f"{command!r} -> {decision} ({reason})"


# ---------------------------------------------------------------------------
# scratch (./.tmp) の削除
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf .tmp",
        "rm -rf ./.tmp/run-1",
        "rm -f .tmp/a.log .tmp/b.log",
        f"rm -rf {ROOT}/.tmp",
        f"rm -rf {ROOT}/.tmp/run-1",
        "find ./.tmp -delete",
        "find ./.tmp -name '*.log' -delete",
        "find ./.tmp -type f -exec rm {} +",
        f"find {ROOT}/.tmp -delete",
    ],
)
def test_scratch_dir_deletion_is_delegated(command):
    """使い捨ての ./.tmp 配下の削除は承認を省く (絶対パス・find も含む)."""
    decision, reason = run_hook(command)
    assert decision is None, f"{command!r} -> {decision} ({reason})"


@pytest.mark.parametrize(
    "command",
    [
        # scratch の外が混ざる
        "rm -rf .tmp /etc/hosts",
        "rm -rf .tmp/../src",
        "find ./.tmp -exec rm /etc/hosts {} +",
        # 基点が変わる / 標準入力から来る / 展開が解決できない
        "cd .tmp && rm -rf foo",
        "echo .tmp | xargs rm -rf",
        "rm -rf $PWD/.tmp",
        # 他リポジトリの .tmp は workspace の外
        "rm -rf ../other-repo/.tmp",
    ],
)
def test_scratch_dir_exemption_is_fail_closed(command):
    decision, reason = run_hook(command)
    assert decision in {"ask", "deny"}, f"{command!r} -> {decision} ({reason})"


def test_scratch_dir_git_target_is_still_denied():
    """scratch 免除は `.git` の hard-deny を上書きしない."""
    decision, reason = run_hook("rm -rf .tmp/.git")
    assert decision == "deny", f"-> {decision} ({reason})"


def test_rm_ask_reason_shows_the_exempt_form_for_scratch(tmp_path):
    """免除が落ちた `.tmp` の削除には、通る書き方をその場で示す.

    常時読み込まれる指示に書くとコンテキストを毎ターン消費するので、
    止めた時点のメッセージで誘導する。
    """
    workspace = tmp_path / "ws"
    (workspace / ".tmp").mkdir(parents=True)
    decision, reason = run_hook("cd .tmp && rm -rf foo", cwd=str(workspace))
    assert decision == "ask", f"-> {decision} ({reason})"
    assert "rm -rf .tmp/<名前>" in reason
    assert "cd" in reason and "xargs" in reason
    # `.tmp` と無関係な削除には出さない (的外れな誘導になる)
    _, other = run_hook("cd src && rm -rf build", cwd=str(workspace))
    assert "rm -rf .tmp/<名前>" not in other


# ---------------------------------------------------------------------------
# symlink で workspace の外へ抜ける形
# ---------------------------------------------------------------------------


def test_scratch_symlink_escape_is_not_exempt(tmp_path):
    """`.tmp/<link>` が外を指す symlink なら scratch 免除を与えない."""
    workspace = tmp_path / "ws"
    (workspace / ".tmp").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (workspace / ".tmp" / "escape").symlink_to(outside)
    decision, reason = run_hook(f"rm -rf {workspace}/.tmp/escape", cwd=str(workspace))
    assert decision == "ask", f"-> {decision} ({reason})"


@pytest.mark.parametrize("style", ["relative", "absolute"])
@pytest.mark.parametrize("target", [".tmp/escape", ".tmp/escape/item"])
def test_symlink_escape_is_not_exempt_in_either_path_style(tmp_path, style, target):
    """symlink で外へ抜ける形は、相対でも絶対でも免除しない.

    workspace 免除は scratch 免除より先に成立するのに realpath を見ていな
    かったため、同じ対象でも相対指定だけが素通りしていた。書き方で判定が
    変わると、免除の根拠 (対象が workspace の内側だと確証できる) が崩れる。
    """
    workspace = tmp_path / "ws"
    (workspace / ".tmp").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "item").write_text("x")
    (workspace / ".tmp" / "escape").symlink_to(outside, target_is_directory=True)
    arg = target if style == "relative" else f"{workspace}/{target}"
    decision, reason = run_hook(f"rm -rf {arg}", cwd=str(workspace))
    assert decision == "ask", f"-> {decision} ({reason})"


def test_scratch_root_symlink_escape_is_not_exempt(tmp_path):
    """`.tmp` 自身が外を指す symlink なら、その配下も免除しない.

    scratch 免除は `.tmp` の realpath を基準に内外を判定するので、ルート
    自体が外を向いていると配下がすべて「内側」に見えてしまう。
    """
    workspace = tmp_path / "ws"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (workspace / ".tmp").symlink_to(outside, target_is_directory=True)
    for arg in (".tmp/item", f"{workspace}/.tmp/item"):
        decision, reason = run_hook(f"rm -rf {arg}", cwd=str(workspace))
        assert decision == "ask", f"{arg} -> {decision} ({reason})"


def test_symlinked_workspace_is_still_exempt(tmp_path):
    """workspace 自体が symlink 配下にあっても免除は効く.

    realpath 検査は root 側も realpath に揃えるので、`/tmp` が
    `/private/tmp` の symlink である macOS のような環境でも誤判定しない。
    """
    real = tmp_path / "real"
    (real / ".tmp").mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    for arg in (".tmp/run-1", f"{link}/.tmp/run-1"):
        decision, reason = run_hook(f"rm -rf {arg}", cwd=str(link))
        assert decision is None, f"{arg} -> {decision} ({reason})"


# ---------------------------------------------------------------------------
# workspace ルートと .git の保護
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    ["rm -rf ./*", "rm -rf .", "rm -rf ./", "rm -rf *", "rm -rf **"],
)
def test_workspace_root_rm_is_denied(command):
    """作業ディレクトリ全体の削除は git 管理外まで失うので承認の対象外."""
    decision, reason = run_hook(command)
    assert decision == "deny", f"{command!r} -> {decision} ({reason})"


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf .git",
        "rm -rf .git/objects",
        "rm -rf .git/refs",
        "rm -rf ./.git/logs",
    ],
)
def test_git_directory_rm_is_denied(command):
    """`.git` は自身だけでなく配下もリポジトリを復旧不能にする."""
    decision, reason = run_hook(command)
    assert decision == "deny", f"{command!r} -> {decision} ({reason})"


@pytest.mark.parametrize(
    "command",
    [
        # glob / ブレース展開で `.git` に届く形
        "rm -rf .g*t",
        "rm -rf .gi?",
        "rm -rf .git*",
        "rm -rf {.git,build}",
    ],
)
def test_git_directory_rm_is_denied_through_expansion(command):
    decision, reason = run_hook(command)
    assert decision == "deny", f"{command!r} -> {decision} ({reason})"


# ---------------------------------------------------------------------------
# deny のままであるべきケース (root guard)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /",
        "rm -rf /*",
        "rm -rf ~",
        "rm -rf ~/",
        "rm -rf $HOME",
        "rm -rf ${HOME}",
        "rm -rf ..",
        "rm -rf /etc",
        "rm -rf /usr/*",
        "rm -rf /var",
        "rm -rf /home/someone",
        "rm -rf --no-preserve-root /tmp/x",
        "rm -fr /",
        # 引用・エスケープした先頭もシェルは rm として実行する
        "\\rm -rf ~",
        '"r"m -rf ~',
        "'rm' -rf /",
        # 末尾のリダイレクトを対象と取り違えて見逃さない
        "rm -rf ~ 2>/dev/null",
        "rm -rf / > /dev/null 2>&1",
        "find ~ -delete 2>/dev/null",
    ],
)
def test_catastrophic_rm_targets_are_denied(command):
    decision, reason = run_hook(command)
    assert decision == "deny", f"{command!r} -> {decision} ({reason})"


def test_root_guard_survives_cd_bypass():
    decision, _ = run_hook("cd /elsewhere && rm -rf /")
    assert decision == "deny"


def test_root_guard_survives_compound_bypass():
    decision, _ = run_hook("echo ok; rm -rf ~")
    assert decision == "deny"


@pytest.mark.parametrize(
    "command",
    [
        'sh -c "rm -rf /"',
        "env rm -rf ~",
        "/bin/rm -rf $HOME",
    ],
)
def test_root_guard_survives_wrappers(command):
    decision, reason = run_hook(command)
    assert decision == "deny", f"{command!r} -> {decision} ({reason})"


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf //",
        "rm -rf '/'",
        'rm -rf "/"',
        "rm --recursive --force /",
        "rm -rf /home/applejxd",
    ],
)
def test_rm_root_guard_variants(command):
    decision, reason = run_hook(command)
    assert decision == "deny", f"{command!r} -> {decision} ({reason})"


@pytest.mark.parametrize(
    "command",
    ["rm -rf ~/", "rmdir /", "find ~ -delete", "rm -r --force /", "rm -rf $PWD/../.."],
)
def test_round4_rm_guard_variants(command):
    decision, reason = run_hook(command)
    assert decision == "deny", f"{command!r} -> {decision} ({reason})"


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("/", True),
        ("/*", True),
        ("/etc/", True),
        ("/etc/*", True),
        ("~", True),
        ("$HOME", True),
        ("..", True),
        ("/home/bob", True),
        ("/Users/bob", True),
        ("./foo", False),
        ("build", False),
        ("~/projects/foo", False),
        ("/home/bob/projects", False),
        ("../sibling", False),
    ],
)
def test_is_catastrophic_rm_target(token, expected):
    assert HOOK._is_catastrophic_rm_target(token) is expected


# ---------------------------------------------------------------------------
# ガード設定 (hook・permission 設定) の改変とデバイス破壊
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "git config core.hooksPath /dev/null",
        "rm ~/.claude/hooks/check_bash.py",
        "mv ~/.claude/settings.json ~/.claude/settings.bak",
        "chmod -x ~/.claude/hooks/check_bash.py",
        "sed -i '1d' ~/.config/agents/common.toml",
    ],
)
def test_guard_tampering_is_denied(command):
    """hook や permission 設定そのものの無効化を止めること."""
    decision, reason = run_hook(command)
    assert decision == "deny", f"{command!r} -> {decision} ({reason})"


@pytest.mark.parametrize(
    "command",
    [
        # 閉じ引用符と次の開き引用符の間はクォートされていないシェルコード。
        # ここをガード設定の「引用文字列」と誤認して読み取りを拒否していた。
        'echo "a"; ls ~/.config/agents; echo "b"',
        'echo "before" && cat ~/.claude/settings.json && echo "after"',
        'echo "start"; chezmoi diff ~/.claude; echo "end"',
        'echo "=== x ==="; chezmoi diff --no-pager ~/.copilot ~/.claude; echo "(end)"',
        # 引用符が無い同等のコマンドは元から通っていた (挙動を揃える)
        "cat ~/.claude/settings.json",
        "chezmoi diff ~/.claude",
        "grep -n defaultMode ~/.claude/settings.json",
    ],
)
def test_guard_settings_can_be_read(command):
    """ガード設定の読み取りは、引用符の有無にかかわらず拒否しないこと.

    インラインコード以外では読み書きが区別できるので、読み取りまで
    止める必要はない。書き込みは mutating コマンドとリダイレクトの
    判定が捕捉する。
    """
    decision, reason = run_hook(command)
    assert decision != "deny", f"{command!r} が deny された ({reason})"


@pytest.mark.parametrize(
    "command",
    [
        # インラインコードは読み書きの区別が付かないので deny のまま
        "python3 -c \"open('/home/u/.claude/settings.json', 'w')\"",
        "python3 -c \"print(open('/home/u/.config/agents/common.toml').read())\"",
        "perl -e 'unlink \"/home/u/.claude/hooks/check_bash.py\"'",
        # インラインコード以外の改変も deny のまま
        "echo x > ~/.claude/settings.json",
        "chezmoi forget ~/.claude/hooks/check_bash.py",
        "unlink ~/.claude/hooks/check_bash.py",
    ],
)
def test_guard_settings_writes_are_still_denied(command):
    """読み取りを許可しても、改変とインラインコードは止まったままであること."""
    decision, reason = run_hook(command)
    assert decision == "deny", f"{command!r} -> {decision} ({reason})"


@pytest.mark.parametrize(
    "command",
    [
        "mkfs.ext4 /dev/sda",
        "dd if=/dev/zero of=/dev/sda",
        "socat TCP-LISTEN:4444 EXEC:/bin/sh",
        "> ~/.claude/settings.json",
        "cat /dev/null > ~/.claude/hooks/check_bash.py",
        "truncate -s 0 ~/.claude/settings.json",
        "chmod 000 ~/.config/agents/common.toml",
    ],
)
def test_system_destruction_and_guard_removal_are_denied(command):
    decision, reason = run_hook(command)
    assert decision == "deny", f"{command!r} -> {decision} ({reason})"
