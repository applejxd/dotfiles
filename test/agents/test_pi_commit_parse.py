"""commit-confirm の解釈・表示・退避 (純関数。home/dot_config/pi/commit-confirm/*.ts) の試験。

node で直接動かす (Node 22.18 以上は型を取り除いて .ts を読める)。pi は使わない。
see docs/spec/pi-guard.md#commit-の確認-素の-pi
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from agents_common import ROOT

EXT = ROOT / "home" / "dot_config" / "pi" / "commit-confirm"
CLI = Path(__file__).resolve().parent / "pi" / "commit_confirm_cli.mjs"


def _node_ok() -> bool:
    node = shutil.which("node")
    if node is None:
        return False
    version = subprocess.run(
        [node, "--version"], capture_output=True, text=True, encoding="utf-8", check=False
    )
    major, minor = (int(x) for x in version.stdout.strip().lstrip("v").split(".")[:2])
    return (major, minor) >= (22, 18)


pytestmark = pytest.mark.skipif(not _node_ok(), reason="node 22.18 以上が要る")


def node(mode, *args, stdin="", env=None):
    done = subprocess.run(
        ["node", str(CLI), mode, *args],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "EXT": str(EXT), **(env or {})},
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


def analyze(*commands):
    return json.loads(node("analyze", stdin=json.dumps(list(commands))))


# ─── 解釈 ────────────────────────────────────────────────────────────

HEREDOC = "git commit -m \"$(cat <<'EOF'\nfeat: 件名\n\n本文 1\n本文 2\nEOF\n)\""

# (コマンド, 種類, 構造化できるか)。できるときの中身は下の個別の試験で見る
KINDS = [
    ('git commit -m "feat: x"', "commit", True),
    ("git commit -am 'fix: y'", "commit", True),
    (HEREDOC, "commit", True),
    ("git commit -F - <<'EOF'\nfeat: a\nEOF", "commit", True),
    ('git add -- a b && git commit -m "x"', "commit", True),
    ('git add -A && git commit -m "x"', "commit", True),
    ('cd sub && git commit -m "x"', "commit", True),
    ('git -C sub commit -m "x"', "commit", True),
    ('git commit -m "x" -- a.txt', "commit", True),
    ("git commit --amend --no-edit", "commit", True),
    ('git commit --amend -m "x"', "commit", True),
    ('git commit --no-verify -m "x"', "commit", True),
    # 読めない形は「読めない」と言う (読めたことにして表示しない)
    ('GIT_AUTHOR_NAME=bob git commit -m "x"', "commit", False),
    ('sudo git commit -m "x"', "commit", False),
    ('FOO=1 git add -A && git commit -m "x"', "commit", False),
    ('git commit -m "x" | tee log', "commit", False),
    ('git commit -m "x" > out', "commit", False),
    ('git commit -m "x"; rm -rf y', "commit", False),
    ('git commit -m "fix: $MSG"', "commit", False),
    ('git commit -m "fix: `date`"', "commit", False),
    ('git commit -m "fix: $(date)"', "commit", False),
    ("git commit", "commit", False),
    ("git commit -e", "commit", False),
    ("git commit -C HEAD", "commit", False),
    # 表示の git に同じ条件を渡せない、または git が拒否・競合する形
    ("git --git-dir=/x/.git commit -m x", "commit", False),
    ("git --work-tree /x commit -m x", "commit", False),
    ("git -c core.hooksPath=/dev/null commit -m x", "commit", False),
    ("git commit -a -m x -- f.txt", "commit", False),
    ("git commit -m x -F msg.txt", "commit", False),
    ("git commit -F - <<EOF\nfeat: a\\nb\nEOF", "commit", False),
    ('git add *.ts && git commit -m "x"', "commit", False),
    ('git rm -f x && git commit -m "x"', "commit", False),
    ('echo hi && git commit -m "x"', "commit", False),
    ("git commit -F msg.txt && echo done", "commit", False),
    ("sh -c 'git commit -m x'", "commit", False),
    # commit ではない
    ('echo "== git commit (説明)"', "none", None),
    ("git commit-tree HEAD^{tree} -m x", "none", None),
    ("git log --grep=commit --oneline", "none", None),
    ("git status --short", "none", None),
    ('git stash push -m "x"', "none", None),
    ("ls", "none", None),
]


@pytest.mark.parametrize(("command", "kind", "recognized"), KINDS)
def test_commands_are_classified(command, kind, recognized):
    [got] = analyze(command)
    assert got["kind"] == kind, got
    if kind == "commit":
        assert got["recognized"] is recognized, got


PUSHES = [
    "git push",
    "git push origin main",
    "git -C /tmp/x push",
    "git -c core.x=1 push --force",
    'git commit -m "x" && git push',
    "cd sub && git push origin HEAD",
    "echo hi; git push",
    "sh -c 'git push origin main'",
    'bash -c "git commit -m x && git push"',
    "git push $(echo origin)",
    # git の前に付く wrapper とそのオプション、パス付きの git、別名 (-c alias.…)
    "env -i git push",
    "sudo -n git push",
    "sudo -u root git push origin main",
    "command -p git push",
    "timeout 10 git push",
    "nice -n 5 git push",
    "xargs -n1 git push",
    "FOO=1 git push",
    "/usr/bin/git push",
    "git -C/tmp/repo push",
    "git -c alias.x=push x",
    "git -c 'alias.x=!git push origin' x",
]


@pytest.mark.parametrize("command", PUSHES)
def test_push_is_always_denied(command):
    assert analyze(command)[0]["kind"] == "push"


@pytest.mark.parametrize(
    "command",
    [
        'echo "git push は手動"',
        "git stash push -m x",
        "git pull",
        "echo push",
        "git log --grep=push",
    ],
)
def test_push_lookalikes_are_not_denied(command):
    assert analyze(command)[0]["kind"] != "push"


def test_the_heredoc_message_is_read_as_a_value():
    [got] = analyze(HEREDOC)
    assert got["spec"]["messages"] == ["feat: 件名\n\n本文 1\n本文 2"]


def test_quotes_and_escapes_in_messages():
    cases = {
        "git commit -m 'fix: $HOME と `cmd` はそのまま'": "fix: $HOME と `cmd` はそのまま",
        'git commit -m "fix: \\"quoted\\" and \\$5"': 'fix: "quoted" and $5',
        'git commit -m "a" -m "b"': None,
        "git commit --message=x": "x",
        "git commit -mx": "x",
        "git commit -am x": "x",
    }
    for command, expected in cases.items():
        [got] = analyze(command)
        assert got["recognized"] is True, command
        if expected is not None:
            assert got["spec"]["messages"] == [expected], command
    [two] = analyze('git commit -m "a" -m "b"')
    assert two["spec"]["messages"] == ["a", "b"]


def test_options_and_steps_are_extracted():
    [got] = analyze('cd sub && git add -A && git -C deep commit -a --no-verify --amend -S -m "x"')
    assert got["steps"] == [
        {"kind": "cd", "dir": "sub"},
        {"kind": "add", "dirs": [], "args": ["-A"]},
    ]
    assert got["dirs"] == ["deep"]
    spec = got["spec"]
    assert spec["all"] and spec["noVerify"] and spec["amend"] and spec["sign"]
    [paths] = analyze('git commit -m "x" -- a.txt b.txt')
    assert paths["spec"]["pathspec"] == ["a.txt", "b.txt"]


def test_an_unreadable_chain_still_offers_its_first_commit_for_the_backup_only():
    [chain, pipe, dynamic, shell] = analyze(
        'git commit -m "x" && printf a > b.txt && git log',
        'git commit -m "x" | tee log',
        'git commit -m "fix: $MSG"',
        "sh -c 'git commit -m x'",
    )
    assert chain["recognized"] is False and chain["approx"]["spec"]["messages"] == ["x"]
    assert pipe["recognized"] is False and pipe["approx"]["spec"]["messages"] == ["x"]
    assert "approx" not in dynamic or dynamic["approx"] is None, (
        "変数入りのメッセージを近似に使った"
    )
    assert shell["recognized"] is False and shell.get("approx") is None


def test_a_dash_heredoc_drops_leading_tabs_like_the_shell():
    [got] = analyze("git commit -F - <<-'EOF'\n\tfeat: x\n\t\tbody\n\tEOF")
    assert got["spec"]["fileMessage"] == {"stdin": "feat: x\nbody"}


def test_an_unquoted_heredoc_with_expansion_is_not_read():
    [got] = analyze("git commit -F - <<EOF\nfeat: $VAR\nEOF")
    assert got["recognized"] is False


# ─── 表示 ────────────────────────────────────────────────────────────

ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}


def git(cwd, *args, check=True):
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=ENV,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=check,
    )


def state(repo):
    """本物の HEAD・インデックス・作業ツリー。表示・退避が変えないことの確認に使う。"""
    parts = [
        git(repo, "rev-parse", "-q", "--verify", "HEAD", check=False).stdout,
        git(repo, "ls-files", "-s").stdout,
        git(repo, "status", "--porcelain=v1").stdout,
    ]
    return "\n".join(parts)


@pytest.fixture
def repo(tmp_path):
    remote = tmp_path / "remote.git"
    remote.mkdir()
    git(remote, "init", "-q", "--bare", "-b", "main")
    work = tmp_path / "work"
    work.mkdir()
    git(work, "init", "-q", "-b", "main")
    for name, text in {"a.txt": "a\n", "b.txt": "b\n", "c.txt": "c\n"}.items():
        (work / name).write_text(text, encoding="utf-8")
    (work / "docs").mkdir()
    (work / "docs" / "d.md").write_text("d\n", encoding="utf-8")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "init: first")
    git(work, "remote", "add", "origin", str(remote))
    git(work, "push", "-q", "-u", "origin", "main")
    (work / "local.txt").write_text("x\n", encoding="utf-8")
    git(work, "add", "local.txt")
    git(work, "commit", "-qm", "chore: local ahead")
    # a.txt: ステージ済みの変更 / b.txt: 未ステージ / n.txt: 未追跡 / c.txt: ステージ済みの削除
    (work / "a.txt").write_text("a\nmore\nlines\n", encoding="utf-8")
    git(work, "add", "a.txt")
    (work / "b.txt").write_text("b\nunstaged\n", encoding="utf-8")
    (work / "n.txt").write_text("new\n", encoding="utf-8")
    git(work, "rm", "-q", "c.txt")
    return {"work": work, "remote": remote, "tmp": tmp_path}


def describe(repo, command, cwd=None):
    return node("describe", str(cwd or repo["work"]), stdin=command, env=ENV)


def test_the_display_is_structured_with_blank_lines(repo):
    before = state(repo["work"])
    out = describe(repo, HEREDOC)
    head = f"リポジトリ: {repo['remote']}\nブランチ:   main  → origin/main (1 ahead, 0 behind)\n"
    assert out.startswith(head + "\n対象:")
    assert "\n  M a.txt (+2 −0)\n" in out and "\n  D c.txt (+0 −1)\n" in out
    assert "(含まれない未ステージの変更: 1 ファイル)" in out
    assert "\n\nメッセージ:\n  feat: 件名\n  本文 1\n  本文 2" in out
    assert "git commit" not in out, "生のコマンドを出している"
    assert state(repo["work"]) == before, "表示が本物の状態を変えた"


def test_the_repository_line_is_the_origin_url_without_credentials(repo):
    git(
        repo["work"], "remote", "set-url", "origin", "https://user:secret-token@example.com/o/r.git"
    )
    out = describe(repo, 'git commit -m "x"')
    assert out.splitlines()[0] == "リポジトリ: https://example.com/o/r.git"
    assert "secret-token" not in out
    git(repo["work"], "remote", "set-url", "origin", "git@github.com:o/r.git")
    assert (
        describe(repo, 'git commit -m "x"').splitlines()[0] == "リポジトリ: git@github.com:o/r.git"
    )
    git(repo["work"], "remote", "remove", "origin")
    assert (
        describe(repo, 'git commit -m "x"').splitlines()[0].startswith("リポジトリ: (origin なし) ")
    )


@pytest.mark.parametrize(
    ("command", "files", "absent"),
    [
        ('git commit -am "x"', ["M a.txt", "M b.txt", "D c.txt"], ["n.txt"]),
        ('git add -- n.txt && git commit -m "x"', ["M a.txt", "D c.txt", "A n.txt"], ["b.txt"]),
        ('git add -A && git commit -m "x"', ["A n.txt", "M b.txt"], []),
        ('git commit -m "x" -- b.txt', ["M b.txt"], ["a.txt", "c.txt"]),
        ("git commit --amend --no-edit", ["A local.txt", "M a.txt"], []),
    ],
)
def test_the_target_files_follow_what_the_command_would_commit(repo, command, files, absent):
    before = state(repo["work"])
    out = describe(repo, command)
    for f in files:
        assert f"  {f} " in out, (f, out)
    for f in absent:
        assert f not in out, (f, out)
    assert state(repo["work"]) == before


def test_amend_and_flags_are_called_out(repo):
    out = describe(repo, 'git commit -s --amend --no-verify -m "chore: reword"')
    assert "  -s: Signed-off-by の行がメッセージの末尾に付く" in out
    assert "注意:\n  --amend: 直前のコミットを書き換える (" in out and "chore: local ahead" in out
    assert "  --no-verify: コミットの hook を飛ばす" in out


def test_nothing_to_commit_is_said(repo):
    git(repo["work"], "reset", "-q", "--hard")
    assert "コミットする変更が無い" in describe(repo, 'git commit -m "x"')


def test_unborn_and_detached_and_many_files(repo, tmp_path):
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    git(fresh, "init", "-q", "-b", "main")
    (fresh / "first.txt").write_text("1\n", encoding="utf-8")
    git(fresh, "add", "first.txt")
    out = node("describe", str(fresh), stdin='git commit -m "chore: initial"', env=ENV)
    assert "ブランチ:   main (初回のコミット)" in out and "A first.txt" in out
    work = repo["work"]
    git(work, "checkout", "-q", "--detach")
    for i in range(15):
        (work / f"f{i:02d}.txt").write_text("x\n", encoding="utf-8")
    git(work, "add", "-A")
    out = describe(repo, 'git commit -m "x"')
    assert "(detached HEAD " in out and "…ほか " in out


def test_long_bodies_are_clipped_and_the_subject_is_not(repo):
    body = "\n".join(f"本文の {i} 行目: " + "全角の長い行がここに入ります。" * 4 for i in range(12))
    out = describe(repo, f"git commit -m '件名 {'あ' * 40}' -m '{body}'")
    assert f"件名 {'あ' * 40}\n" in out
    assert "…ほか 4 行" in out and out.count("…\n") >= 8


def test_unreadable_commands_are_shown_raw_with_a_warning(repo):
    out = describe(repo, 'git commit -m "x" | tee log')
    assert out.startswith("解釈できない形のコマンドです。次がそのまま実行されます:\n")
    assert 'git commit -m "x" | tee log' in out


def test_a_non_repository_is_reported(tmp_path):
    outside = tmp_path / "plain"
    outside.mkdir()
    env = {**ENV, "GIT_CEILING_DIRECTORIES": str(tmp_path)}
    out = node("describe", str(outside), stdin='git commit -m "x"', env=env)
    assert out.strip() == "NULL", "リポジトリを特定できないのに構造化した"


def test_a_failure_to_read_the_message_file_is_not_shown_as_structured(repo):
    # 取れないものを「取れない」と書いて承認させない。呼び出し側は生のコマンドの表示に切り替える
    assert describe(repo, "git commit -F missing-message.txt").strip() == "NULL"


def test_a_long_raw_command_never_hides_its_tail_silently(repo):
    short = "\n".join(["git commit -m x | cat"] + [f"echo line{i}" for i in range(40)])
    out = describe(repo, short)
    assert "echo line39" in out and "省略" not in out, "60 行以内は全文を出す"
    long = "\n".join(
        ["git commit -m x | cat"] + [f"echo line{i}" for i in range(100)] + ["echo tail-marker"]
    )
    out = describe(repo, long)
    assert "途中の " in out and "行を省略" in out and "⚠ 長いので途中を省略" in out
    assert out.rstrip().splitlines()[-2] == "echo tail-marker", "末尾を出していない"
    wide_line = "git commit -m x | cat # " + "x" * 500
    out = describe(repo, wide_line)
    assert "文字を省略" in out and out.rstrip().endswith("してください")


# ─── 退避 ────────────────────────────────────────────────────────────


def pending(repo, command, cwd=None, env=None):
    return json.loads(
        node("pending", str(cwd or repo["work"]), stdin=command, env={**ENV, **(env or {})})
    )


def refs(work):
    return git(
        work, "for-each-ref", "--sort=refname", "--format=%(refname)", "refs/pi/pending/"
    ).stdout.split()


def test_a_pending_commit_is_saved_without_touching_the_repository(repo):
    work = repo["work"]
    before = state(work)
    got = pending(repo, HEREDOC)
    assert got["ok"] and got["ref"].startswith("refs/pi/pending/") and got["files"] == 2
    assert state(work) == before, "退避が HEAD・インデックス・作業ツリーを変えた"
    assert refs(work) == [got["ref"]]
    assert (
        git(work, "log", "-1", "--format=%B", got["ref"])
        .stdout.strip()
        .startswith("feat: 件名\n\n本文 1")
    )
    tree = git(work, "ls-tree", "-r", "--name-only", got["ref"]).stdout.split()
    assert "a.txt" in tree and "c.txt" not in tree and "n.txt" not in tree
    assert git(work, "rev-parse", f"{got['ref']}^").stdout == git(work, "rev-parse", "HEAD").stdout


@pytest.mark.parametrize(
    ("command", "present", "absent"),
    [
        ('git commit -am "x"', ["a.txt", "b.txt"], ["n.txt", "c.txt"]),
        ('git add -- n.txt && git commit -m "x"', ["a.txt", "n.txt"], ["c.txt"]),
        ('git commit -m "x" -- b.txt', ["a.txt", "b.txt", "c.txt"], ["n.txt"]),
    ],
)
def test_the_snapshot_matches_what_the_command_would_commit(repo, command, present, absent):
    got = pending(repo, command)
    assert got["ok"], got
    tree = git(repo["work"], "ls-tree", "-r", "--name-only", got["ref"]).stdout.split()
    for f in present:
        assert f in tree, (f, tree)
    for f in absent:
        assert f not in tree, (f, tree)
    if "b.txt" in command and "--" in command:
        assert git(repo["work"], "show", f"{got['ref']}:a.txt").stdout == "a\n", (
            "パス指定にステージ済みの a.txt が入った"
        )


def test_pending_commits_form_a_chain(repo):
    work = repo["work"]
    first = pending(repo, 'git commit -m "one"')
    (work / "e.txt").write_text("e\n", encoding="utf-8")
    second = pending(repo, 'git add -- e.txt && git commit -m "two"')
    assert first["ok"] and second["ok"]
    assert refs(work) == [first["ref"], second["ref"]], "ref の名前が順番になっていない"
    assert (
        git(work, "rev-parse", f"{second['ref']}^").stdout
        == git(work, "rev-parse", first["ref"]).stdout
    )
    # 2 つ目の差分は、1 つ目からの増分だけ
    diff = git(work, "diff", "--name-only", first["ref"], second["ref"]).stdout.split()
    assert diff == ["e.txt"]
    # パス指定の土台も直前の保留 (HEAD ではない)。1 つ目の内容が消えない
    third = pending(repo, 'git commit -m "three" -- b.txt')
    tree = git(work, "ls-tree", "-r", "--name-only", third["ref"]).stdout.split()
    assert "e.txt" in tree and "b.txt" in tree


def test_the_chain_restarts_from_head_after_a_real_commit(repo):
    work = repo["work"]
    first = pending(repo, 'git commit -m "one"')
    git(work, "commit", "-qm", "manual: real commit")
    (work / "e.txt").write_text("e\n", encoding="utf-8")
    second = pending(repo, 'git add -- e.txt && git commit -m "two"')
    assert second["ok"]
    assert (
        git(work, "rev-parse", f"{second['ref']}^").stdout == git(work, "rev-parse", "HEAD").stdout
    )
    assert first["ref"] != second["ref"]


def test_a_chained_command_is_saved_as_an_approximation(repo):
    work = repo["work"]
    got = pending(repo, 'git commit -m "feat: chained" && printf a > b.txt && git log')
    assert got["ok"] and got["approx"] is True
    assert git(work, "log", "-1", "--format=%s", got["ref"]).stdout.strip() == "feat: chained"
    tree = git(work, "ls-tree", "-r", "--name-only", got["ref"]).stdout.split()
    assert "a.txt" in tree and "n.txt" not in tree, (
        "連結の他の操作 (b.txt の作成など) を再現していないこと"
    )
    assert pending(repo, HEREDOC)["approx"] is False


def test_nothing_to_save_amend_and_unreadable_are_not_saved(repo):
    work = repo["work"]
    assert pending(repo, "git commit --amend --no-edit")["ok"] is False
    assert pending(repo, 'git commit -m "fix: $MSG"')["ok"] is False
    assert pending(repo, "sh -c 'git commit -m x'")["ok"] is False
    git(work, "reset", "-q", "--hard")
    got = pending(repo, 'git commit -m "x"')
    assert got["ok"] is False and "変更が無い" in got["reason"]
    assert refs(work) == []


def test_saving_does_not_run_hooks_or_signing_and_works_without_identity(repo, tmp_path):
    work = repo["work"]
    hook = work / ".git" / "hooks" / "pre-commit"
    marker = tmp_path / "hook-ran"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    git(work, "config", "commit.gpgsign", "true")
    git(work, "config", "gpg.program", "/nonexistent")
    no_identity = {
        "HOME": str(tmp_path / "nohome"),
        "XDG_CONFIG_HOME": str(tmp_path / "nohome"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "",
        "GIT_AUTHOR_EMAIL": "",
        "GIT_COMMITTER_NAME": "",
        "GIT_COMMITTER_EMAIL": "",
    }
    clean = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    got = json.loads(
        node(
            "pending",
            str(work),
            stdin='git commit -m "x"',
            env={**clean, **no_identity, "GIT_AUTHOR_NAME": "", "GIT_COMMITTER_NAME": ""},
        )
    )
    assert got["ok"], got
    assert not marker.exists(), "退避が pre-commit hook を呼んだ"
    author = git(work, "log", "-1", "--format=%an <%ae>", got["ref"]).stdout.strip()
    assert author == "pi pending <pi-pending@localhost>"


def test_the_origin_url_has_no_scheme_leak_in_pending_messages(repo):
    # 退避は URL を扱わない (表示だけ)。メッセージに余計なものを足していない
    got = pending(repo, 'git commit -m "feat: only this"')
    assert (
        git(repo["work"], "log", "-1", "--format=%B", got["ref"]).stdout.strip()
        == "feat: only this"
    )
    assert re.fullmatch(r"[0-9a-f]{7}", got["short"])
