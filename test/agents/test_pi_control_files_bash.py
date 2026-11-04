"""素の pi (Fence が無い) の制御ファイルを、bash から書き換えさせない (``judge/rules_guard.ts`` の GUARD_TARGETS)。

``guarded_write`` / ``guarded_edit`` の拒否 (``[file] write_deny_globs``) とは別に、bash の経由 (リダイレクト・
mv / cp / rm / tee / インラインコード) でも、settings.json・mcp.json・extensions・フルガードを書かせない。
see docs/spec/guard/pi-guard.md#判定の外で動くもの
"""

from __future__ import annotations

import pytest
from test_pi_confirm import _bash, _judge, needs_node

pytestmark = needs_node

TARGETS = [
    "~/.pi/agent/settings.json",
    "~/.pi/agent/mcp.json",
    "~/.pi/agent/extensions/x/index.ts",
    "~/.config/pi/harness/rules.json",
    "$HOME/.pi/agent/settings.json",
]


def _decisions(commands):
    results = _judge([_bash(c) for c in commands])
    return [r["decision"] for r in results]


@pytest.mark.parametrize("target", TARGETS)
def test_redirect_and_mutating_commands_to_the_control_files_are_denied(target):
    commands = [
        f"echo x > {target}",
        f"echo x >> {target}",
        f"tee {target} < /dev/null",
        f"rm {target}",
        f"mv /tmp/a {target}",
        f"cp /tmp/a {target}",
    ]
    assert _decisions(commands) == ["deny"] * len(commands)


@pytest.mark.parametrize("target", TARGETS[:3])
def test_inline_code_touching_the_control_files_is_denied(target):
    command = f"python3 -c \"open('{target}', 'w').write('x')\""
    assert _decisions([command]) == ["deny"]


# 作業台帳の置き場 (ハーネスだけが fs で書く)。書き込みは拒否し、読み取りと通常のファイルは従来どおり
LEDGER = [".git/pi-work/log/x.jsonl", ".tmp/work/journal/x.jsonl", ".git/pi-work/DEGRADED.json"]
ROLES = ["implementer", "worker", "explore"]


def _file(tool, path, role):
    return {
        "tool": tool,
        "input": {"path": path, "content": "x"},
        "cwd": "/work/proj",
        "role": role,
    }


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("path", LEDGER)
def test_ledger_is_denied_for_file_write_tools(role, path):
    for p in (path, f"/work/proj/{path}"):
        reqs = [_file(t, p, role) for t in ("write", "edit")]
        assert [r["decision"] for r in _judge(reqs)] == ["deny", "deny"]


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("path", LEDGER)
def test_ledger_is_denied_for_bash_writes(role, path):
    commands = [
        f"echo x > {path}",
        f"echo x >> {path}",
        f"tee {path} < /dev/null",
        f"cp /tmp/a {path}",
        f"rm {path}",
    ]
    results = _judge([{**_bash(c), "role": role} for c in commands])
    assert [r["decision"] for r in results] == ["deny"] * len(commands)


@pytest.mark.parametrize("path", LEDGER)
def test_ledger_inline_code_is_denied(path):
    assert _decisions([f"python3 -c \"open('{path}', 'w').write('x')\""]) == ["deny"]


def test_ledger_reads_and_ordinary_writes_are_unchanged():
    reads = [_file(t, p, "implementer") for t in ("read", "grep") for p in LEDGER]
    assert all(r["decision"] != "deny" for r in _judge(reads))
    ordinary = [
        _file("write", p, "implementer")
        for p in ("docs/x.md", ".tmp/worktrees/x/f.txt", ".tmp/keep/work/a.md")
    ]
    assert all(r["decision"] != "deny" for r in _judge(ordinary))
    cmds = [
        "grep x .git/pi-work/log/x.jsonl",
        "echo x > .tmp/worktrees/a/f.txt",
        "echo x > docs/x.md",
    ]
    assert "deny" not in _decisions(cmds)


# ─── C1・C2: 台帳そのものの削除・書き込みオプション・symlink の別名 (追加の判定) ───────────────────
FLAGS = [{}, {"bypass": True}]
REPO = "/work/proj"


class _D(str):
    """decision の文字列。失敗時に理由が見えるよう repr へ reason を足す。"""

    def __new__(cls, r):
        obj = super().__new__(cls, r["decision"])
        obj.reason = r.get("reason", "")
        return obj

    def __format__(self, spec):
        return repr(self)

    def __repr__(self):
        return f"{self!s} ({self.reason[:80]})"


def _decide(commands, role="implementer", cwd="/work/proj"):
    reqs = [{**_bash(c, **flags), "role": role, "cwd": cwd} for c in commands for flags in FLAGS]
    return list(
        zip(
            [(c, f) for c in commands for f in FLAGS],
            [_D(r) for r in _judge(reqs)],
            strict=True,
        )
    )


DIR_DELETES = [
    "rm -r .tmp/work",
    "rm -r .tmp/work/",
    "rm -rf .tmp/work",
    f"rm -rf {REPO}/.tmp/work",
    f"rm -rf {REPO}/.tmp/work/",
    "rm -r .git/pi-work",
    "rm -r .git/pi-work/",
    f"rm -rf {REPO}/.git/pi-work",
    "rmdir .tmp/work",
    "mv .tmp/work /tmp/gone",
    "rm -rf .tmp/../.tmp/work",
    "rm -rf .tmp/worktrees/../work",
    f"rm -r {REPO}/.git/pi-work/log/x",
]


@pytest.mark.parametrize("role", ROLES)
def test_c1_deleting_the_ledger_directory_itself_is_denied(role):
    for (cmd, flags), decision in _decide(DIR_DELETES, role):
        assert decision == "deny", f"{cmd!r} {flags} -> {decision}"


def test_c1_worktrees_and_lookalikes_are_not_matched():
    cmds = [
        "rm -r .tmp/worktrees/x",
        f"rm -rf {REPO}/.tmp/worktrees/x",
        "echo x > .tmp/worktrees/x/f.txt",
        "rm -r .tmp/workbench/x",
        "cp /tmp/a .tmp/work2/x",
    ]
    for (cmd, flags), decision in _decide(cmds):
        assert decision != "deny", f"{cmd!r} {flags} -> {decision}"


WRITE_OPTIONS = [
    "git log -1 --output=.tmp/work/journal/x.jsonl",
    f"git -C {REPO} log --output={REPO}/.tmp/work/x",
    f"git -C {REPO} diff --output=.tmp/work/x",
    "git diff -o .tmp/work/x",
    "git log --output .git/pi-work/log/x",
    "sort -o .tmp/work/x /tmp/a",
    "sort --output=.tmp/work/x /tmp/a",
    "curl -o .tmp/work/journal/x http://example.invalid/",
    "wget -O .tmp/work/x http://example.invalid/",
    "dd if=/tmp/a of=.tmp/work/x",
    f"dd if=/tmp/a of={REPO}/.git/pi-work/log/x",
    "sed -i s/a/b/ .tmp/work/journal/x.jsonl",
    "sed -i s/a/b/ .git/pi-work/log/x",
    "find .tmp/work -delete",
    "find .tmp/work -exec rm {} ;",
    "find .git/pi-work -fprint .tmp/keep/x",
    "less -o .tmp/work/x /tmp/a",
    "touch .tmp/work/x",
    "install -m 644 /tmp/a .tmp/work/x",
    "cd .tmp/work",
    "echo x | tee .tmp/work/journal/x",
    "echo x | tee -a .git/pi-work/log/x",
]


@pytest.mark.parametrize("role", ROLES)
def test_c2_write_option_commands_against_the_ledger_are_denied(role):
    for (cmd, flags), decision in _decide(WRITE_OPTIONS, role):
        assert decision == "deny", f"{cmd!r} {flags} -> {decision}"


def test_c2_read_only_known_commands_are_unchanged():
    cmds = [
        "grep -c x .tmp/work/journal/x.jsonl",
        "ls .tmp/work",
        "ls -la .git/pi-work/log",
        "grep x .tmp/work/journal/x.jsonl",
        "wc -c .git/pi-work/log/x.jsonl",
        "wc -l .tmp/work/journal/x.jsonl",
        "find .tmp/work -name '*.jsonl'",
        "git -C /work/proj log -1 -- .tmp/work",
        "jq . .git/pi-work/DEGRADED.json",
        "diff .tmp/work/a .tmp/work/b",
    ]
    for (cmd, flags), decision in _decide(cmds):
        assert decision != "deny", f"{cmd!r} {flags} -> {decision}"


def test_c2_symlink_alias_of_the_ledger_is_denied(tmp_path):
    (tmp_path / ".tmp" / "work" / "journal").mkdir(parents=True)
    (tmp_path / ".git" / "pi-work" / "log").mkdir(parents=True)
    (tmp_path / "ledger").symlink_to(tmp_path / ".tmp" / "work")
    (tmp_path / "gl").symlink_to(tmp_path / ".git" / "pi-work")
    cmds = [
        "cp x ledger/journal/y",
        "echo x > ledger/journal/y",
        "rm -r ledger",
        "rm -rf ledger/journal",
        "mv x gl/log/y",
        f"cp x {tmp_path}/ledger/journal/y",
        "git log --output=ledger/x",
        "tee gl/log/y",
    ]
    for role in ROLES:
        for (cmd, flags), decision in _decide(cmds, role, cwd=str(tmp_path)):
            assert decision == "deny", f"{cmd!r} {flags} -> {decision}"
    reads = ["grep x ledger/journal/y", "ls ledger"]
    for (cmd, flags), decision in _decide(reads, cwd=str(tmp_path)):
        assert decision != "deny", f"{cmd!r} {flags} -> {decision}"


def test_c2_unresolvable_symlink_target_falls_back_to_lexical_deny(tmp_path):
    # 実体を引けない (存在しない) 環境でも、字句の台帳パスは deny
    cmds = ["rm -r .tmp/work", "cp x .tmp/work/journal/y"]
    for (cmd, flags), decision in _decide(cmds, cwd=str(tmp_path / "missing")):
        assert decision == "deny", f"{cmd!r} {flags} -> {decision}"


def test_c2_absolute_common_dir_paths_are_denied():
    cmds = [
        f"cp x {REPO}/.git/pi-work/log/x",
        "cp x /abs/repo/.git/pi-work/log/x",
        "echo x > /abs/repo/.git/pi-work/log/x",
        "rm -rf /abs/repo/.git/pi-work",
    ]
    for (cmd, flags), decision in _decide(cmds):
        assert decision == "deny", f"{cmd!r} {flags} -> {decision}"


def test_existing_protections_are_unchanged():
    cmds = [
        "rm ~/.pi/agent/settings.json",
        "cp /tmp/a .git/hooks/pre-commit",
        "echo x > .git/config",
        "mv /tmp/a ~/.config/pi/harness/rules.json",
        "tee ~/.claude/settings.json < /dev/null",
    ]
    for (cmd, flags), decision in _decide(cmds):
        assert decision == "deny", f"{cmd!r} {flags} -> {decision}"
    reads = ["grep x .git/config", "ls .git/hooks", "grep x ~/.pi/agent/settings.json"]
    for (cmd, flags), decision in _decide(reads):
        assert decision != "deny", f"{cmd!r} {flags} -> {decision}"
