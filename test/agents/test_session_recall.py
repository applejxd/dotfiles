"""session_recall.py (過去セッションの読み取り) の試験。合成のログだけを使い、実際の ~/.pi/agent/sessions は読まない。"""

from __future__ import annotations

import importlib.util
import json
import ntpath
import os
import re
import shutil
import subprocess
import sys
import tracemalloc
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "home" / "dot_agents" / "skills" / "session-recall" / "scripts"

# 秘密鍵の区切り行を、ソースの中で 1 つの文字列にしない (gitleaks が試験の入力を本物の鍵と誤検出するため)
DASHES = "-----"
BEGIN_PK = DASHES + "BEGIN "
END_PK = DASHES + "END "
EQ = "="  # `api_key=<値>` をソースの中で 1 つの文字列にしない (同じ理由)
PASSWORD = "pass" + "word"  # `password=<値>` も同じ理由で 1 つにしない

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git が無い")


def _load():
    spec = importlib.util.spec_from_file_location("session_recall", SCRIPTS / "session_recall.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["session_recall"] = module
    spec.loader.exec_module(module)
    return module


sr = _load()


def msg(role, content, entry_id="e", stamp="2026-11-01T00:00:01.000Z"):
    return {"type": "message", "id": entry_id, "timestamp": stamp, "message": {"role": role, "content": content}}


def text(value):
    return [{"type": "text", "text": value}]


def write_session(sessions: Path, cwd: str, stamp: str, sid: str, entries: list, subdir: str = "", raw_lines=()):
    """sessions/--<符号化した cwd>--/<時刻>_<id>.jsonl を作る。"""
    directory = sessions / f"--{sr.encode_path(cwd)}--"
    if subdir:
        directory = directory / subdir
    directory.mkdir(parents=True, exist_ok=True)
    header = {"type": "session", "version": 3, "id": sid, "timestamp": stamp, "cwd": cwd}
    path = directory / f"{stamp.replace(':', '-')}_{sid}.jsonl"
    lines = [json.dumps(header), *(json.dumps(e, ensure_ascii=False) for e in entries), *raw_lines]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


_GIT_HOME: dict[str, str] = {}


@pytest.fixture(autouse=True)
def _isolated_git_home(tmp_path):
    home = tmp_path / "githome"
    home.mkdir()
    _GIT_HOME["path"] = str(home)


def _git_env() -> dict[str, str]:
    """試験の準備用の git の環境。GIT_* をすべて除き、global・system の設定から隔離する。"""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        HOME=_GIT_HOME["path"],
        GIT_CONFIG_GLOBAL="/dev/null",
        GIT_CONFIG_SYSTEM="/dev/null",
        GIT_CONFIG_NOSYSTEM="1",
    )
    return env


def _git(cwd, *args) -> str:
    proc = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", *args],
        cwd=cwd,
        env=_git_env(),
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return proc.stdout


def _git_init(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "--allow-empty", "-m", "init")


def run(capsys, argv, cwd, sessions):
    code = sr.main(argv, cwd=str(cwd), sessions_dir=sessions)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


@pytest.fixture
def repo(tmp_path):
    """本物の git リポジトリ(本体と worktree)と、別のリポジトリ 2 つの場所を用意する。"""
    if shutil.which("git") is None:
        pytest.skip("git が無い")
    main = tmp_path / "work" / "proj"
    _git_init(main)
    wt = main / ".tmp" / "worktrees" / "feat"
    _git(main, "worktree", "add", "-q", "-b", "feat", str(wt))
    other = tmp_path / "work" / "other-repo"
    similar = tmp_path / "work" / "proj-other"
    for p in (other, similar):
        p.mkdir()
    sessions = tmp_path / "sessions"
    write_session(sessions, str(main.resolve()), "2026-11-01T00:00:00.000Z", "aaaa1111-main", [msg("user", text("本体の質問 MAIN"))])
    write_session(sessions, str(wt.resolve()), "2026-11-02T00:00:00.000Z", "bbbb2222-wt", [msg("user", text("worktree の質問 WT"))])
    write_session(sessions, str(other.resolve()), "2026-11-03T00:00:00.000Z", "cccc3333-other", [msg("user", text("別リポジトリ FOREIGN"))])
    write_session(sessions, str(similar.resolve()), "2026-11-04T00:00:00.000Z", "dddd4444-similar", [msg("user", text("似た名前 FOREIGN"))])
    return main.resolve(), wt.resolve(), sessions


# 1. 範囲
@needs_git
@pytest.mark.parametrize("where", ["main", "worktree"])
def test_scope_excludes_other_repositories(repo, capsys, where):
    main, wt, sessions = repo
    cwd = main if where == "main" else wt
    for argv in (["list"], ["grep", ".", "--limit", "50"], ["show", "aaaa"], ["show", "bbbb"], ["digest", "aaaa"], ["digest", "bbbb"]):
        code, out, _ = run(capsys, argv, cwd, sessions)
        assert code == 0, argv
        assert "FOREIGN" not in out and "cccc3333" not in out and "dddd4444" not in out
    _, out, _ = run(capsys, ["list"], cwd, sessions)
    assert "aaaa1111" in out and "bbbb2222" in out
    assert "main" in out and "feat" in out
    _, out, _ = run(capsys, ["grep", "質問"], cwd, sessions)
    assert "MAIN" in out and "WT" in out


@needs_git
def test_similar_named_repository_is_rejected_by_header_cwd(repo, capsys):
    """符号化の前方一致で候補に入っても、先頭行の cwd が範囲外なら除く。"""
    main, _, sessions = repo
    # 本体と同じディレクトリ名に見えるが、先頭行の cwd は別のリポジトリ
    write_session(sessions, str(main), "2026-11-05T00:00:00.000Z", "eeee5555-fake", [], subdir="")
    fake = next(sessions.glob(f"--{sr.encode_path(str(main))}--/*eeee5555*"))
    lines = fake.read_text(encoding="utf-8").splitlines()
    header = json.loads(lines[0])
    header["cwd"] = str(main) + "-other"
    fake.write_text(json.dumps(header) + "\n", encoding="utf-8")
    found = {s.short_id for s in sr.discover_sessions(str(main), sessions)}
    assert "eeee5555" not in found and "aaaa1111" in found


def test_without_git_only_exact_cwd(tmp_path, capsys):
    """git の外では、先頭行の cwd が cwd と完全に一致するセッションだけ(配下も、親の下の別リポジトリも出さない)。"""
    cwd = tmp_path / "nogit"
    sub = cwd / "sub"
    sub.mkdir(parents=True)
    sessions = tmp_path / "sessions"
    write_session(sessions, str(cwd), "2026-11-01T00:00:00.000Z", "aaaa1111", [msg("user", text("ここ"))])
    write_session(sessions, str(sub), "2026-11-02T00:00:00.000Z", "bbbb2222", [msg("user", text("下"))])
    write_session(sessions, str(tmp_path / "nogit-other"), "2026-11-03T00:00:00.000Z", "cccc3333", [msg("user", text("外"))])
    found = {s.short_id for s in sr.discover_sessions(str(cwd), sessions)}
    assert found == {"aaaa1111"}


# 2. SESSION の拒否
@needs_git
@pytest.mark.parametrize("spec", ["/etc/passwd", "../x", "a/b", "cccc3333", "dddd", "zzzz", "..", "C:x"])
def test_session_spec_rejected(repo, capsys, spec):
    main, _, sessions = repo
    for command in ("show", "digest"):
        code, out, err = run(capsys, [command, spec], main, sessions)
        assert code == 2 and out == ""
        assert "MAIN" not in err and "FOREIGN" not in err


@needs_git
def test_ambiguous_prefix_lists_candidates(repo, capsys):
    main, _, sessions = repo
    write_session(sessions, str(main), "2026-11-06T00:00:00.000Z", "aaaa9999-dup", [])
    code, out, err = run(capsys, ["show", "aaaa"], main, sessions)
    assert code == 2 and out == "" and "aaaa1111" in err and "aaaa9999" in err


# 3. 本文の抽出
def _rich(tmp_path):
    cwd = tmp_path / "nogit"
    cwd.mkdir()
    sessions = tmp_path / "sessions"
    entries = [
        msg("system", text("SYSTEMPROMPT"), "s0"),
        msg("user", "ユーザの質問 USERQ", "u1"),
        msg(
            "assistant",
            [
                {"type": "thinking", "thinking": "THINKING"},
                {"type": "text", "text": "回答 ASSISTANTA"},
                {"type": "toolCall", "name": "bash", "arguments": {"command": "git status"}},
                {"type": "toolCall", "name": "edit", "arguments": {"path": "src/a.py"}},
            ],
            "a1",
        ),
        msg("toolResult", text("TOOLRESULT " + "x" * 400), "t1"),
        {"type": "compaction", "id": "c1", "timestamp": "2026-11-01T00:00:05.000Z", "summary": "要約 COMPSUM", "firstKeptEntryId": "u1"},
        {"type": "session_info", "id": "i1", "name": "名前つき"},
    ]
    write_session(sessions, str(cwd), "2026-11-01T00:00:00.000Z", "aaaa1111", entries)
    return cwd, sessions


def test_default_extraction(tmp_path, capsys):
    cwd, sessions = _rich(tmp_path)
    _, out, _ = run(capsys, ["show", "latest"], cwd, sessions)
    assert "USERQ" in out and "ASSISTANTA" in out
    assert "[tool: bash `git status`]" in out
    for hidden in ("THINKING", "TOOLRESULT", "SYSTEMPROMPT"):
        assert hidden not in out
    _, out, _ = run(capsys, ["show", "latest", "--tools"], cwd, sessions)
    assert "TOOLRESULT" in out and "x" * 289 in out and "x" * 290 not in out


def test_grep_tools_and_compaction(tmp_path, capsys):
    cwd, sessions = _rich(tmp_path)
    _, out, _ = run(capsys, ["grep", "TOOLRESULT"], cwd, sessions)
    assert "TOOLRESULT" not in out.split("\n", 1)[1]
    _, out, _ = run(capsys, ["grep", "git status"], cwd, sessions)
    assert "(ヒットなし)" in out
    _, out, _ = run(capsys, ["grep", "git status", "--tools"], cwd, sessions)
    assert "assistant" in out and "e" in out
    _, out, _ = run(capsys, ["grep", "toolresult", "-i", "--tools"], cwd, sessions)
    assert "toolResult" in out
    _, out, _ = run(capsys, ["grep", "COMPSUM", "--role", "compaction"], cwd, sessions)
    assert "c1" in out and "compaction" in out
    _, out, _ = run(capsys, ["grep", "THINKING"], cwd, sessions)
    assert "(ヒットなし)" in out


def test_digest(tmp_path, capsys):
    cwd, sessions = _rich(tmp_path)
    _, out, _ = run(capsys, ["digest", "latest"], cwd, sessions)
    assert "COMPSUM" in out and "名前つき" in out and "USERQ" in out
    assert "ASSISTANTA" in out and "src/a.py" in out


def test_show_tail_and_from(tmp_path, capsys):
    cwd, sessions = _rich(tmp_path)
    _, out, _ = run(capsys, ["show", "latest", "--tail", "1"], cwd, sessions)
    assert "COMPSUM" in out and "USERQ" not in out
    _, out, _ = run(capsys, ["show", "latest", "--from", "a1"], cwd, sessions)
    assert "USERQ" not in out and "ASSISTANTA" in out
    code, _, _err = run(capsys, ["show", "latest", "--from", "nope"], cwd, sessions)
    assert code == 2


# 4. 壊れた入力
def test_broken_unknown_and_huge_lines(tmp_path, capsys):
    cwd = tmp_path / "nogit"
    cwd.mkdir()
    sessions = tmp_path / "sessions"
    huge = json.dumps(msg("user", text("H" * (sr.MAX_LINE_BYTES + 10))))
    write_session(
        sessions,
        str(cwd),
        "2026-11-01T00:00:00.000Z",
        "aaaa1111",
        [msg("user", text("生きている発話 ALIVE"), "u1")],
        raw_lines=["{broken json", '{"type":"future_thing","x":1}', "[1,2]", huge, json.dumps(msg("user", text("巨大の後 AFTER"), "u2"))],
    )
    for argv in (["list"], ["grep", "ALIVE"], ["show", "latest"], ["digest", "latest"]):
        code, out, _ = run(capsys, argv, cwd, sessions)
        assert code == 0
        assert "HHHH" not in out
    _, out, _ = run(capsys, ["show", "latest"], cwd, sessions)
    assert "ALIVE" in out and "AFTER" in out
    assert "壊れた行 2・巨大な行 1・未知の type 1" in out


def test_unreadable_header_is_excluded(tmp_path):
    cwd = tmp_path / "nogit"
    cwd.mkdir()
    sessions = tmp_path / "sessions"
    directory = sessions / f"--{sr.encode_path(str(cwd))}--"
    directory.mkdir(parents=True)
    (directory / "x_bad.jsonl").write_text("not json\n", encoding="utf-8")
    (directory / "y_nosession.jsonl").write_text('{"type":"message"}\n', encoding="utf-8")
    (directory / "z_empty.jsonl").write_text("", encoding="utf-8")
    assert sr.discover_sessions(str(cwd), sessions) == []


# 5. 出力の約束
def test_notice_first_line_and_truncation(tmp_path, capsys):
    cwd = tmp_path / "nogit"
    cwd.mkdir()
    sessions = tmp_path / "sessions"
    write_session(sessions, str(cwd), "2026-11-01T00:00:00.000Z", "aaaa1111", [msg("user", text("長い " * 30000), "u1")])
    for argv in (["list"], ["grep", "長い"], ["show", "latest"], ["digest", "latest"]):
        _, out, _ = run(capsys, argv, cwd, sessions)
        assert out.splitlines()[0] == sr.NOTICE
    _, out, _ = run(capsys, ["show", "latest"], cwd, sessions)
    assert len(out) <= 12_000 and "[…省略 " in out and "--tail" in out and out.endswith("\n")
    _, out, _ = run(capsys, ["show", "latest", "--max-chars", "999999"], cwd, sessions)
    assert len(out) <= 60_000 and "[…省略 " in out
    for limit in (500, 777):
        for argv in (["show", "latest"], ["grep", "長い", "--width", "5000"], ["digest", "latest"], ["list"]):
            _, out, _ = run(capsys, [*argv, "--max-chars", str(limit)], cwd, sessions)
            assert len(out) <= limit and out.splitlines()[0] == sr.NOTICE, (argv, limit, len(out))


@pytest.mark.parametrize("value", ["499", "1", "0", "-5"])
def test_max_chars_lower_bound(tmp_path, capsys, value):
    with pytest.raises(SystemExit) as excinfo:
        sr.main(["list", "--max-chars", value], cwd=str(tmp_path), sessions_dir=tmp_path)
    assert excinfo.value.code == 2


def test_secrets_are_redacted(tmp_path, capsys):
    cwd = tmp_path / "nogit"
    cwd.mkdir()
    sessions = tmp_path / "sessions"
    secret = (
        "ghp_" + "a" * 30
        + " Authorization: Bearer abcdefgh12345678xyz"
        + " password=hunter2 token: tok-value-1 Bearer " + "B" * 24
        + f"\n{BEGIN_PK}RSA PRIVATE KEY{DASHES}\nMIIEKEYBODY\n{END_PK}RSA PRIVATE KEY{DASHES}\n後ろ"
    )
    write_session(sessions, str(cwd), "2026-11-01T00:00:00.000Z", "aaaa1111", [msg("user", text(secret), "u1")])
    for argv in (["show", "latest"], ["grep", "後ろ"], ["digest", "latest"], ["list"]):
        _, out, _ = run(capsys, argv, cwd, sessions)
        for leaked in ("a" * 30, "abcdefgh12345678xyz", "hunter2", "tok-value-1", "B" * 24, "MIIEKEYBODY", "PRIVATE KEY"):
            assert leaked not in out, (argv, leaked)
    _, out, _ = run(capsys, ["show", "latest"], cwd, sessions)
    assert "後ろ" in out


# 6. latest / previous / 子のログ
def test_latest_previous_and_subdirectory_logs(tmp_path, capsys):
    cwd = tmp_path / "nogit"
    cwd.mkdir()
    sessions = tmp_path / "sessions"
    write_session(sessions, str(cwd), "2026-11-01T00:00:00.000Z", "aaaa1111", [msg("user", text("OLDEST"))])
    write_session(sessions, str(cwd), "2026-11-02T00:00:00.000Z", "bbbb2222", [msg("user", text("MIDDLE"))])
    write_session(sessions, str(cwd), "2026-11-03T00:00:00.000Z", "cccc3333", [msg("user", text("NEWEST"))])
    write_session(sessions, str(cwd), "2026-11-04T00:00:00.000Z", "dddd4444", [msg("user", text("CHILD"))], subdir="child/run-0")
    _, out, _ = run(capsys, ["show", "latest"], cwd, sessions)
    assert "NEWEST" in out
    _, out, _ = run(capsys, ["show", "previous"], cwd, sessions)
    assert "MIDDLE" in out and "NEWEST" not in out
    _, out, _ = run(capsys, ["list"], cwd, sessions)
    assert "dddd4444" not in out and "CHILD" not in out
    code, _, _ = run(capsys, ["show", "dddd"], cwd, sessions)
    assert code == 2


def test_previous_with_single_session_is_error(tmp_path, capsys):
    cwd = tmp_path / "nogit"
    cwd.mkdir()
    sessions = tmp_path / "sessions"
    write_session(sessions, str(cwd), "2026-11-01T00:00:00.000Z", "aaaa1111", [])
    code, out, _ = run(capsys, ["show", "previous"], cwd, sessions)
    assert code == 2 and out == ""


# 7. --stats
def test_list_stats(tmp_path, capsys):
    cwd = tmp_path / "nogit"
    cwd.mkdir()
    sessions = tmp_path / "sessions"
    path = write_session(sessions, str(cwd), "2026-11-01T00:00:00.000Z", "aaaa1111", [msg("user", text("あいうえお"), "u1")])
    _, out, _ = run(capsys, ["list", "--stats"], cwd, sessions)
    assert f"{path.stat().st_size}B → 5字" in out
    assert "合計:" in out and "%" in out


def test_list_zero_logs_hint(tmp_path, capsys):
    cwd = tmp_path / "nogit"
    cwd.mkdir()
    _, out, _ = run(capsys, ["list"], cwd, tmp_path / "missing")
    assert "囲い" in out


@pytest.mark.parametrize("where", ["home", "parent", "root"])
def test_cwd_at_home_or_above_is_refused(tmp_path, capsys, monkeypatch, where):
    """cwd がホーム・ホームの親・`/` だと、範囲が全リポジトリに及ぶので、中身を出さずに拒否する。"""
    home = tmp_path / "users" / "me"
    (home / "repo").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # Windows の Path.home() は HOME を見ず、USERPROFILE を読む
    sessions = tmp_path / "sessions"
    write_session(sessions, str((home / "repo").resolve()), "2026-11-01T00:00:00.000Z", "aaaa1111", [msg("user", text("SECRET-TOPIC"))])
    cwd = {"home": home, "parent": home.parent, "root": Path("/")}[where]
    code, out, err = run(capsys, ["list"], cwd, sessions)
    assert code == 2
    assert "SECRET-TOPIC" not in out and out == ""
    assert "ホーム" in err
    code, out, _ = run(capsys, ["list"], home / "repo", sessions)  # リポジトリの中なら読める
    assert code == 0 and "aaaa1111"[:8] in out


# ---- 範囲: Windows のパスの規則 (区切りは `\` と `/` の両方・大小を区別しない)。POSIX の機でも ntpath の代役で検査する ----
class _NtOs:
    """session_recall が使う os の代役。path・sep だけを Windows (ntpath) にし、残りは本物の os に任せる。"""

    path = ntpath
    sep = "\\"

    def __getattr__(self, name):
        return getattr(os, name)


@pytest.fixture
def windows_paths(monkeypatch):
    monkeypatch.setattr(sr, "os", _NtOs())
    monkeypatch.setattr(sr, "Path", types.SimpleNamespace(home=lambda: r"C:\Users\me"))


def test_is_under_follows_windows_path_rules(windows_paths):
    assert sr._is_under(r"C:\Users\me\proj\src\deep", "C:/Users/me/proj")  # git は Windows でも `/` 区切りで出す
    assert sr._is_under(r"c:\users\ME\PROJ", r"C:\Users\me\proj")  # 大小を区別しない
    assert sr._is_under(r"C:\Users\me\proj", r"C:\Users\me\proj")
    assert sr._is_under(r"C:\Users\me", "C:\\")  # ドライブの根の配下
    assert not sr._is_under(r"C:\Users\me\proj-other", r"C:\Users\me\proj")  # 似た名前は配下ではない
    assert not sr._is_under(r"C:\Users\me", r"C:\Users\me\proj")  # 親は配下ではない


@pytest.mark.parametrize(
    ("cwd", "refused"),
    [
        (r"C:\Users\me", True),  # ホーム
        ("c:/users/ME", True),  # ホーム (区切りと大小が違う)
        (r"C:\Users", True),  # ホームの親
        ("C:\\", True),  # ドライブの根
        (r"C:\Users\me\proj", False),
        (r"C:\Users\other", False),  # ホームの隣
    ],
)
def test_too_broad_follows_windows_path_rules(windows_paths, cwd, refused):
    assert sr._too_broad(cwd) is refused


class _FixedCommonDirs:
    def __init__(self, common_dir):
        self._common_dir = common_dir

    def get(self, directory):
        return self._common_dir


def test_owning_root_follows_windows_path_rules(windows_paths, monkeypatch):
    git_dir = r"C:\Users\me\proj\.git"
    scope = sr.Scope([r"C:\Users\me\proj", r"C:\Users\me\proj\.tmp\worktrees\feat"], git_dir)
    same_repo = _FixedCommonDirs("c:/users/me/proj/.git")
    # 実在しない cwd: root そのもの (区切り・大小が違っても) だけを認め、配下は認めない
    monkeypatch.setattr(sr.os.path, "isdir", lambda path: False)
    assert sr.owning_root("c:/users/ME/proj", scope, same_repo) == r"C:\Users\me\proj"
    assert sr.owning_root(r"C:\Users\me\proj\src", scope, same_repo) is None
    # 実在する配下: 同じ common dir なら最長の root に入り、別の common dir なら入らない
    monkeypatch.setattr(sr.os.path, "isdir", lambda path: True)
    assert sr.owning_root(r"C:\Users\me\proj\src\deep", scope, same_repo) == r"C:\Users\me\proj"
    assert sr.owning_root(r"C:\Users\me\proj\.tmp\worktrees\feat\src", scope, same_repo) == r"C:\Users\me\proj\.tmp\worktrees\feat"
    assert sr.owning_root(r"C:\Users\me\proj\src\deep", scope, _FixedCommonDirs(r"C:\Users\me\other\.git")) is None
    assert sr.owning_root(r"C:\Users\me\proj-other", scope, same_repo) is None
    assert sr.owning_root(r"C:\Users\me\proj\src", scope, _FixedCommonDirs(None)) is None


# ---- 範囲: 「配下」と「同じリポジトリ」の区別(指摘 1・2) ----
def _all_commands_hide(capsys, cwd, sessions, secret_word, hidden_ids):
    for argv in (["list"], ["grep", ".", "--limit", "50"], ["show", "latest"], ["digest", "latest"]):
        _, out, _ = run(capsys, argv, cwd, sessions)
        assert secret_word not in out, argv
        for hidden in hidden_ids:
            assert hidden not in out, (argv, hidden)
    for hidden in hidden_ids:
        for command in ("show", "digest"):
            code, out, _ = run(capsys, [command, hidden], cwd, sessions)
            assert code == 2 and out == "" and secret_word not in out


@needs_git
def test_nested_independent_repository_is_excluded(repo, capsys):
    main, _, sessions = repo
    nested = main / "vendor" / "B"
    _git_init(nested)
    write_session(sessions, str(nested.resolve()), "2026-11-18T00:00:00.000Z", "ffff6666-nested", [msg("user", text("NESTED-FOREIGN"))])
    _all_commands_hide(capsys, main, sessions, "NESTED-FOREIGN", ["ffff6666"])
    _, out, _ = run(capsys, ["list"], main, sessions)
    assert "aaaa1111" in out


@needs_git
def test_parent_of_repositories_outside_git_shows_nothing_below(tmp_path, capsys):
    projects = tmp_path / "projects"
    sessions = tmp_path / "sessions"
    for name, sid in (("a", "aaaa1111"), ("b", "bbbb2222")):
        _git_init(projects / name)
        write_session(sessions, str((projects / name).resolve()), "2026-11-01T00:00:00.000Z", sid, [msg("user", text("BELOW-FOREIGN"))])
    write_session(sessions, str(projects.resolve()), "2026-11-02T00:00:00.000Z", "cccc3333", [msg("user", text("HERE"))])
    for argv in (["list"], ["grep", ".", "--limit", "50"], ["show", "latest"], ["digest", "latest"]):
        _, out, _ = run(capsys, argv, projects.resolve(), sessions)
        assert "BELOW-FOREIGN" not in out and "aaaa1111" not in out and "bbbb2222" not in out
    _, out, _ = run(capsys, ["list"], projects.resolve(), sessions)
    assert "cccc3333" in out


@needs_git
def test_deleted_worktree_matches_only_exactly(repo, capsys):
    main, _, sessions = repo
    gone = main / ".tmp" / "worktrees" / "gone"
    _git(main, "worktree", "add", "-q", "-b", "gone", str(gone))
    gone = gone.resolve()
    write_session(sessions, str(gone), "2026-11-10T00:00:00.000Z", "gggg7777-gone", [msg("user", text("GONE-EXACT"))])
    write_session(sessions, str(gone / "sub"), "2026-11-11T00:00:00.000Z", "hhhh8888-gonesub", [msg("user", text("GONE-SUB"))])
    shutil.rmtree(gone)
    assert gone.as_posix() in _git(main, "worktree", "list", "--porcelain")  # git は Windows でも `C:/...` と `/` 区切りで出す
    _, out, _ = run(capsys, ["list"], main, sessions)
    assert "gggg7777" in out and "hhhh8888" not in out
    _, out, _ = run(capsys, ["grep", "GONE"], main, sessions)
    assert "GONE-EXACT" in out and "GONE-SUB" not in out


@needs_git
def test_worktree_replaced_by_symlink_to_other_repository_is_excluded(repo, capsys, tmp_path):
    main, _, sessions = repo
    swapped = main / ".tmp" / "worktrees" / "swapped"
    _git(main, "worktree", "add", "-q", "-b", "swapped", str(swapped))
    swapped = swapped.resolve()
    foreign = tmp_path / "foreign-repo"
    _git_init(foreign)
    shutil.rmtree(swapped)
    swapped.symlink_to(foreign, target_is_directory=True)
    write_session(sessions, str(swapped), "2026-11-12T00:00:00.000Z", "iiii9999-swapped", [msg("user", text("SWAPPED-FOREIGN"))])
    write_session(sessions, str(foreign.resolve()), "2026-11-13T00:00:00.000Z", "jjjj0000-foreign", [msg("user", text("FOREIGN-DIRECT"))])
    _all_commands_hide(capsys, main, sessions, "FOREIGN", ["iiii9999", "jjjj0000"])


@needs_git
def test_session_started_in_subdirectory_is_included(repo, capsys):
    main, _, sessions = repo
    sub = main / "src" / "deep"
    sub.mkdir(parents=True)
    write_session(sessions, str(sub), "2026-11-14T00:00:00.000Z", "kkkk1212-sub", [msg("user", text("SUBDIR-OK"))])
    _, out, _ = run(capsys, ["grep", "SUBDIR"], main, sessions)
    assert "SUBDIR-OK" in out


@needs_git
@pytest.mark.skipif(
    os.name == "nt",
    reason="Win32 は名前の末尾の空白を除くので、`.git ` は `.git` と同じ名前になり、別のディレクトリにならない",
)
def test_nested_repository_whose_git_dir_has_trailing_space_is_excluded(repo, capsys):
    """common dir の末尾空白を strip すると、別の git ディレクトリ `<A>/.git ` が `<A>/.git` と同じになる。"""
    main, _, sessions = repo
    nested = main / "vendor" / "B"
    nested.parent.mkdir(parents=True)
    _git(main, "init", "-q", f"--separate-git-dir={main / '.git '}", str(nested))
    write_session(sessions, str(nested.resolve()), "2026-11-19T00:00:00.000Z", "mmmm5656-spacegit", [msg("user", text("SPACEGIT-FOREIGN"))])
    _all_commands_hide(capsys, main, sessions, "SPACEGIT-FOREIGN", ["mmmm5656"])
    _, out, _ = run(capsys, ["list"], main, sessions)
    assert "aaaa1111" in out


ODD_PATH_CASES = {
    "non-ascii-and-spaces": ("日本語 proj ", "wt 日本 語 "),
    "non-ascii-and-inner-spaces": ("日本語 proj", "wt 日本 語"),  # 末尾の空白が無い形。Windows でも作れる
    "newline": ("plain", "wt\nnewline x"),
    "all-together": ("日本語\n本体 ", "追加 wt\n日本 "),
}


def _unusable_on_windows(name: str) -> bool:
    """Win32 のファイル名の規則 (Naming Files, Paths, and Namespaces) で作れない名前。

    制御文字 (1〜31。改行を含む) は使えない。末尾の空白・ピリオドは、パスの正規化で除かれる。
    Windows の CI では、改行を含む名前は mkdir の WinError 123 か `git worktree add` の 128 で、
    末尾の空白つきの名前も `git worktree add` の 128 で落ちた。
    """
    return any(ord(char) < 32 for char in name) or name.endswith((" ", "."))


@needs_git
@pytest.mark.parametrize("case", sorted(ODD_PATH_CASES))
def test_worktree_paths_with_non_ascii_spaces_and_newlines(tmp_path, capsys, case):
    """`git worktree list` の引用符つきの表記ではなく、-z の生のパスで範囲を決める。"""
    main_name, wt_name = ODD_PATH_CASES[case]
    if os.name == "nt" and (_unusable_on_windows(main_name) or _unusable_on_windows(wt_name)):
        pytest.skip("Win32 のファイル名の規則で、この名前のディレクトリは作れない (制御文字・末尾の空白)")
    main = tmp_path / "work" / main_name
    _git_init(main)
    wt = main / ".tmp" / "worktrees" / wt_name
    _git(main, "worktree", "add", "-q", "-b", "feat", str(wt))
    main, wt = main.resolve(), wt.resolve()
    sessions = tmp_path / "sessions"
    write_session(sessions, str(main), "2026-11-01T00:00:00.000Z", "aaaa1111-main", [msg("user", text("ODD-MAIN"))])
    write_session(sessions, str(wt), "2026-11-02T00:00:00.000Z", "bbbb2222-wt", [msg("user", text("ODD-WT"))])
    for cwd in (main, wt):
        _, out, _ = run(capsys, ["list"], cwd, sessions)
        assert "aaaa1111" in out and "bbbb2222" in out, (case, cwd)
        _, out, _ = run(capsys, ["grep", "ODD-"], cwd, sessions)
        assert "ODD-MAIN" in out and "ODD-WT" in out


@needs_git
@pytest.mark.parametrize("variable", ["GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE"])
def test_git_environment_variables_do_not_change_scope(repo, capsys, monkeypatch, tmp_path, variable):
    main, _, sessions = repo
    other = tmp_path / "work" / "env-other"
    _git_init(other)
    write_session(sessions, str(other.resolve()), "2026-11-15T00:00:00.000Z", "llll3434-envother", [msg("user", text("ENV-FOREIGN"))])
    value = {
        "GIT_DIR": other / ".git",
        "GIT_WORK_TREE": other,
        "GIT_COMMON_DIR": other / ".git",
        "GIT_INDEX_FILE": other / ".git" / "index",
    }[variable]
    monkeypatch.setenv(variable, str(value))
    _, out, _ = run(capsys, ["list"], main, sessions)
    assert "aaaa1111" in out and "bbbb2222" in out
    assert "llll3434" not in out and "ENV-FOREIGN" not in out
    _, out, _ = run(capsys, ["grep", "ENV-FOREIGN"], main, sessions)
    assert "ENV-FOREIGN" not in out.split("\n", 1)[1].replace("(ヒットなし)", "")


def _repository_state(repository: Path) -> dict[str, bytes]:
    git_dir = repository / ".git"
    files = [git_dir / "HEAD", git_dir / "index", *sorted(p for p in (git_dir / "refs").rglob("*") if p.is_file())]
    return {str(p.relative_to(git_dir)): p.read_bytes() for p in files if p.exists()}


@needs_git
def test_git_fixture_setup_ignores_inherited_git_environment(tmp_path, tmp_path_factory, monkeypatch):
    """GIT_DIR・GIT_INDEX_FILE・GIT_WORK_TREE や global の設定 (署名・hook) が付いていても、tmp_path の外のリポジトリを変えない。"""
    victim = tmp_path_factory.mktemp("victim")
    _git_init(victim)
    before = _repository_state(victim)
    hostile_config = tmp_path / "hostile-gitconfig"
    hostile_config.write_text("[commit]\n\tgpgSign = true\n[core]\n\thooksPath = /nonexistent-hooks\n", encoding="utf-8")
    monkeypatch.setenv("GIT_DIR", str(victim / ".git"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(victim / ".git" / "index"))
    monkeypatch.setenv("GIT_WORK_TREE", str(victim))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(hostile_config))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "commit.gpgsign")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "true")
    work = tmp_path / "work"
    _git_init(work)
    _git(work, "worktree", "add", "-q", "-b", "feat", str(work / "wt"))
    assert (work / ".git").is_dir() and (work / "wt").is_dir()
    assert _repository_state(victim) == before


# ---- 伏せ字(指摘 3・4) ----
@pytest.mark.parametrize(
    ("raw", "leaked", "kept"),
    [
        ('password="first second" tail', ["first", "second"], ["tail"]),
        ("password='alpha beta' tail", ["alpha", "beta"], ["tail"]),
        ('{"password": "first second", "x": 1}', ["first", "second"], ['"x": 1']),
        ('{"token":"tok val","y":2}', ["tok val"], ['"y":2']),
        (
            'Authorization: Digest username="alice", response="abc123"\nnext line',
            ["alice", "abc123", "Digest"],
            ["Authorization:", "next line"],
        ),
        (f"api_key{EQ}0123456789abcdef after", ["0123456789abcdef"], ["after"]),
        ("api-key: KEYVALUE1 apikey=KEYVALUE2 end", ["KEYVALUE1", "KEYVALUE2"], ["end"]),
        ("auth=AUTHVALUE secret: SECRETVALUE passwd=PWVALUE", ["AUTHVALUE", "SECRETVALUE", "PWVALUE"], []),
        # 空の値が、次の行のキーを飲み込まない (改行を越えて値を探すと、次の行の引用符つきの値が部分的に漏れる)
        ('token=\npassword="alpha beta"\nnext', ["alpha", "beta"], ["token=", "next"]),
        ('token=\r\npassword="alpha beta"\r\nnext', ["alpha", "beta"], ["token=", "next"]),
        ("password:\napi_key=SECONDVALUE\nnext", ["SECONDVALUE"], ["password:", "next"]),
        ("password=\nplain text line", [], ["password=", "plain text line"]),
        ("token=", [], ["token="]),
        ("clone https://alice:pass@localhost/path done", ["alice", "pass@"], ["https://<redacted>@localhost/path", "done"]),
        (
            f"before {BEGIN_PK}PGP PRIVATE KEY BLOCK{DASHES}\nPGPBODY\n{END_PK}PGP PRIVATE KEY BLOCK{DASHES}\nafter",
            ["PGPBODY", "PRIVATE KEY"],
            ["before", "after"],
        ),
        (f"before {BEGIN_PK}PRIVATE KEY{DASHES}\nUNCLOSEDBODY\n後ろ", ["UNCLOSEDBODY", "後ろ"], ["before"]),
        ("contact bob@example.com now", ["bob@example.com"], ["contact", "now"]),
        ("a " + "b" * 70 + "@example.com z", ["bb", "@example.com"], ["a ", " z"]),
        ("a " + "c" * 5000 + ".d+e@example.com z", ["cc", "@example.com"], ["a ", " z"]),
        # 区切りの END が別ラベル (CERTIFICATE) でも、対応する END まで (無ければ末尾まで) 伏せる
        (
            f"before {BEGIN_PK}PRIVATE KEY{DASHES}\nSECRET_A\n{END_PK}CERTIFICATE{DASHES}\nSECRET_B",
            ["SECRET_A", "SECRET_B", "CERTIFICATE"],
            ["before"],
        ),
        (
            f"{BEGIN_PK}RSA PRIVATE KEY{DASHES}\nSECRET_A\n{END_PK}RSA PRIVATE KEY{DASHES}\nafter",
            ["SECRET_A"],
            ["after"],
        ),
        # エスケープつきの引用符・閉じていない引用符
        (f'{PASSWORD}{EQ}"alpha \\" omega" tail', ["alpha", "omega"], ["tail"]),
        (f"{PASSWORD}{EQ}'alpha \\' omega' tail", ["alpha", "omega"], ["tail"]),
        (f'{{"{PASSWORD}":"alpha \\" omega","x":1}}', ["alpha", "omega"], ['"x":1']),
        (f'{PASSWORD}{EQ}"ends with backslash\\\\" tail', ["backslash"], ["tail"]),
        (f'before {PASSWORD}{EQ}"unclosed alpha beta', ["alpha", "beta"], ["before"]),
        ("Cookie: session=COOKIEVALUE\nnext", ["COOKIEVALUE"], ["Cookie:", "next"]),
        ("Set-Cookie: session=COOKIEVALUE; HttpOnly\nnext", ["COOKIEVALUE", "HttpOnly"], ["Set-Cookie:", "next"]),
        ('{"private_key":"BASE64VALUE","k":1}', ["BASE64VALUE"], ['"k":1']),
        (
            '{"client_secret":"CSVALUE","access_token":"ATVALUE","refresh_token":"RTVALUE","z":1}',
            ["CSVALUE", "ATVALUE", "RTVALUE"],
            ['"z":1'],
        ),
        ("sshpass -p PWVALUE ssh host", ["PWVALUE"], ["sshpass -p", "ssh host"]),
        (
            f"run --{PASSWORD} PWVALUE1 --passwd PWVALUE2 --token TOKVALUE --secret SECVALUE --api-key APIVALUE end",
            ["PWVALUE1", "PWVALUE2", "TOKVALUE", "SECVALUE", "APIVALUE"],
            ["run", "end"],
        ),
    ],
)
def test_redact_forms(raw, leaked, kept):
    out = sr.redact(raw)
    for item in leaked:
        assert item not in out, (raw, item, out)
    for item in kept:
        assert item in out, (raw, item, out)


def test_redact_keeps_commit_hashes():
    sha = "0123456789abcdef0123456789abcdef01234567"
    assert sr.redact(f"commit {sha} merged") == f"commit {sha} merged"


def test_tool_call_arguments_are_redacted_before_truncation():
    """80 文字で切ると引用符が閉じなくなる。切る前に伏せる。"""
    command = "a" * 55 + f' {PASSWORD}{EQ}"AAAA BBBB CCCC DDDD EEEE"'
    block = {"type": "toolCall", "name": "bash", "arguments": {"command": command}}
    assert "BBBB" not in sr.format_tool_call(block) and "AAAA" not in sr.format_tool_call(block)
    entry = msg("assistant", [block])
    (_, shown), = sr.extract(entry, calls=True, results=False)
    assert "BBBB" not in shown and "CCCC" not in shown


def test_session_name_is_redacted_before_it_is_cut(tmp_path, capsys):
    cwd = tmp_path / "nogit"
    cwd.mkdir()
    sessions = tmp_path / "sessions"
    name = "n" * 40 + f' {PASSWORD}{EQ}"AAAA BBBB CCCC DDDD EEEE FFFF"'
    write_session(sessions, str(cwd), "2026-11-01T00:00:00.000Z", "aaaa1111", [{"type": "session_info", "id": "i1", "name": name}])
    for argv in (["list"], ["digest", "latest"]):
        _, out, _ = run(capsys, argv, cwd, sessions)
        assert "BBBB" not in out and "AAAA" not in out, argv


REDACT_CHILD = """
import importlib.util, json, sys, time
path, name, dashes, sizes = sys.argv[1], sys.argv[2], sys.argv[3], json.loads(sys.argv[4])
spec = importlib.util.spec_from_file_location("session_recall", path)
module = importlib.util.module_from_spec(spec)
sys.modules["session_recall"] = module
spec.loader.exec_module(module)
quote = chr(34)
attacks = {
    "plain": lambda n: "x" * n,
    "begin-lines": lambda n: (dashes + "BEGIN PRIVATE KEY" + dashes + chr(10)) * (n // 28),
    "at-signs": lambda n: "a@" * (n // 2),
    "long-around-at": lambda n: "x" * (n // 2) + "@" + "y" * (n // 2),
    "long-local-part": lambda n: "b" * n + "@x.example",
    "dot-urls": lambda n: "a.a:" * (n // 4),
    "keyword-spaces": lambda n: "pass" + "word" + " " * n,
    "unclosed-quotes": lambda n: ("pass" + "word" + "=" + quote + "a" + chr(10)) * (n // 12),
    "backslashes": lambda n: "pass" + "word" + "=" + quote + chr(92) * n,
    "flags": lambda n: "--token " * (n // 8),
}
times = []
for size in sizes:
    text = attacks[name](size)
    start = time.process_time()
    module.redact(text)
    times.append(time.process_time() - start)
print(json.dumps(times))
"""
REDACT_ATTACK_NAMES = (
    "plain",
    "begin-lines",
    "at-signs",
    "long-around-at",
    "long-local-part",
    "dot-urls",
    "keyword-spaces",
    "unclosed-quotes",
    "backslashes",
    "flags",
)


def _redact_cpu_times(name: str, sizes: list[int]) -> list[float]:
    """redact を別プロセスで走らせ、各サイズの CPU 時間を返す。期限 (20 秒) を超えたら subprocess.TimeoutExpired で落ちる。"""
    proc = subprocess.run(
        [sys.executable, "-c", REDACT_CHILD, str(SCRIPTS / "session_recall.py"), name, DASHES, json.dumps(sizes)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=True,
    )
    return json.loads(proc.stdout)


@pytest.mark.parametrize("name", REDACT_ATTACK_NAMES)
def test_redact_is_not_slow_on_hostile_input(name):
    (cpu,) = _redact_cpu_times(name, [4_000_000])
    assert cpu < 10.0, cpu


@pytest.mark.parametrize("name", REDACT_ATTACK_NAMES)
def test_redact_time_grows_linearly(name):
    first = _redact_cpu_times(name, [1_000_000, 2_000_000])
    second = _redact_cpu_times(name, [1_000_000, 2_000_000])
    small, large = min(first[0], second[0]), min(first[1], second[1])
    assert large <= small * 3 + 0.2, (small, large)


# ---- メモリ(指摘 5) ----
@pytest.mark.parametrize(
    "argv",
    [["show", "latest"], ["show", "latest", "--tail", "3"], ["digest", "latest"], ["list"], ["grep", "NOHIT-ANYWHERE"]],
    ids=lambda a: " ".join(a),
)
def test_memory_does_not_grow_with_session_size(tmp_path, capsys, argv):
    cwd = tmp_path / "nogit"
    cwd.mkdir()
    sessions = tmp_path / "sessions"
    entries = [msg("user" if i % 2 == 0 else "assistant", text("x " * 200_000), f"m{i}") for i in range(40)]
    path = write_session(sessions, str(cwd), "2026-11-01T00:00:00.000Z", "aaaa1111", entries)
    size = path.stat().st_size
    assert size > 15_000_000
    already_tracing = tracemalloc.is_tracing()
    if already_tracing:
        tracemalloc.reset_peak()
    else:
        tracemalloc.start()
    baseline = tracemalloc.get_traced_memory()[0]
    try:
        code, out, _ = run(capsys, [*argv, "--max-chars", "12000"], cwd, sessions)
        peak = tracemalloc.get_traced_memory()[1] - baseline
    finally:
        if not already_tracing:
            tracemalloc.stop()
    assert code == 0 and len(out) <= 12_000
    assert peak < size / 4, (argv, peak, size)


def test_show_reports_omitted_characters_beyond_budget(tmp_path, capsys):
    cwd = tmp_path / "nogit"
    cwd.mkdir()
    sessions = tmp_path / "sessions"
    entries = [msg("user", text("y" * 50_000), f"m{i}") for i in range(10)]
    write_session(sessions, str(cwd), "2026-11-01T00:00:00.000Z", "aaaa1111", entries)
    _, out, _ = run(capsys, ["show", "latest", "--max-chars", "1000"], cwd, sessions)
    omitted = int(re.search(r"省略 (\d+) 文字", out).group(1))
    assert len(out) <= 1000 and omitted > 400_000


# ---- 壊れた入力: CLI を subprocess で起動(指摘 7) ----
def _cli(args, cwd, agent_dir):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["PI_CODING_AGENT_DIR"] = str(agent_dir)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "session_recall.py"), *args], cwd=cwd, env=env, capture_output=True, timeout=60
    )


def _write_raw_session(agent_dir: Path, cwd: Path, lines: list[bytes], eol: bytes = b"\n", bom: bool = False):
    directory = agent_dir / "sessions" / f"--{sr.encode_path(str(cwd))}--"
    directory.mkdir(parents=True)
    fields = {"type": "session", "version": 3, "id": "rawid1234", "timestamp": "2026-11-01T00:00:00.000Z", "cwd": str(cwd)}
    header = json.dumps(fields).encode()
    if bom:
        header = b"\xef\xbb\xbf" + header
    (directory / "2026-11-01T00-00-00.000Z_rawid1234.jsonl").write_bytes(eol.join([header, *lines]) + eol)


GOOD_LINE = json.dumps({"type": "message", "id": "u1", "message": {"role": "user", "content": "ALIVE-MARK"}}).encode()
HOSTILE_LINES = {
    "lone-surrogate": b'{"type":"message","id":"s1","message":{"role":"user","content":"a\\ud800b SURROGATE"}}',
    "deep-nesting": b'{"type":"custom","data":' + b"[" * 200_000 + b"]" * 200_000 + b"}",
    "invalid-utf8": b'{"type":"message","id":"b1","message":{"role":"user","content":"\xff\xfe BADBYTES"}}',
}


@needs_git
@pytest.mark.parametrize("case", ["lone-surrogate", "deep-nesting", "invalid-utf8", "bom-header", "crlf"])
def test_cli_survives_hostile_input(tmp_path, case):
    repo_dir = tmp_path / "r"
    _git_init(repo_dir)
    repo_dir = repo_dir.resolve()
    agent = tmp_path / "agent"
    if case == "bom-header":
        _write_raw_session(agent, repo_dir, [GOOD_LINE], bom=True)
    elif case == "crlf":
        _write_raw_session(agent, repo_dir, [GOOD_LINE], eol=b"\r\n")
    else:
        _write_raw_session(agent, repo_dir, [HOSTILE_LINES[case], GOOD_LINE])
    for args in (["list"], ["grep", "."], ["show", "latest"], ["digest", "latest"]):
        proc = _cli(args, repo_dir, agent)
        assert proc.returncode == 0, (case, args, proc.stderr[-500:])
        assert b"Traceback" not in proc.stderr
        assert b"rawid123" in proc.stdout if args == ["list"] else b"ALIVE-MARK" in proc.stdout or args[0] == "digest"
    shown = _cli(["show", "latest"], repo_dir, agent).stdout.decode("utf-8")
    assert "ALIVE-MARK" in shown
    if case == "lone-surrogate":
        assert "SURROGATE" in shown
    if case in ("deep-nesting", "invalid-utf8"):
        assert "壊れた行 1" in shown


# ---- 識別子(指摘 8) ----
def test_list_ids_are_unique_even_with_same_first_eight_chars(tmp_path, capsys):
    cwd = tmp_path / "nogit"
    cwd.mkdir()
    sessions = tmp_path / "sessions"
    write_session(sessions, str(cwd), "2026-11-01T00:00:00.000Z", "abcdefgh-1111", [msg("user", text("FIRST"))])
    write_session(sessions, str(cwd), "2026-11-02T00:00:00.000Z", "abcdefgh-2222", [msg("user", text("SECOND"))])
    write_session(sessions, str(cwd), "2026-11-03T00:00:00.000Z", "zzzzzzzz-3333", [msg("user", text("THIRD"))])
    _, out, _ = run(capsys, ["list"], cwd, sessions)
    rows = [line.split(" | ")[0] for line in out.splitlines() if " | " in line and not line.startswith("id ")]
    assert len(rows) == 3 and len(set(rows)) == 3
    for ident in rows:
        assert len(ident) >= 8
        code, _, _ = run(capsys, ["show", ident], cwd, sessions)
        assert code == 0
    code, out, err = run(capsys, ["show", "abcdefgh"], cwd, sessions)
    assert code == 2
    candidates = [c.strip() for c in err.split("候補:", 1)[1].split(",")]
    assert len(candidates) == 2 and len(set(candidates)) == 2
    for ident in candidates:
        assert run(capsys, ["show", ident], cwd, sessions)[0] == 0


def test_id_that_is_a_prefix_of_another_id_is_selectable(tmp_path, capsys):
    cwd = tmp_path / "nogit"
    cwd.mkdir()
    sessions = tmp_path / "sessions"
    write_session(sessions, str(cwd), "2026-11-01T00:00:00.000Z", "abcdefgh", [msg("user", text("SHORT-ID"))])
    write_session(sessions, str(cwd), "2026-11-02T00:00:00.000Z", "abcdefgh9", [msg("user", text("LONG-ID"))])
    _, out, _ = run(capsys, ["list"], cwd, sessions)
    rows = [line.split(" | ")[0] for line in out.splitlines() if " | " in line and not line.startswith("id ")]
    assert sorted(rows) == ["abcdefgh", "abcdefgh9"]
    code, out, _ = run(capsys, ["show", "abcdefgh"], cwd, sessions)
    assert code == 0 and "SHORT-ID" in out and "LONG-ID" not in out
    code, out, _ = run(capsys, ["show", "abcdefgh9"], cwd, sessions)
    assert code == 0 and "LONG-ID" in out


def test_same_full_id_in_two_files_is_ambiguous_with_start_times(tmp_path, capsys):
    cwd = tmp_path / "nogit"
    cwd.mkdir()
    sessions = tmp_path / "sessions"
    write_session(sessions, str(cwd), "2026-11-01T00:00:00.000Z", "samesame-id", [msg("user", text("FIRST"))])
    write_session(sessions, str(cwd), "2026-11-02T00:00:00.000Z", "samesame-id", [msg("user", text("SECOND"))])
    code, out, err = run(capsys, ["show", "samesame-id"], cwd, sessions)
    assert code == 2 and out == ""
    assert "2026-11-01T00:00:00.000Z" in err and "2026-11-02T00:00:00.000Z" in err


# ---- 引数の検証(指摘 9) ----
@pytest.mark.parametrize(
    "argv",
    [
        ["list", "--since", "2026-99-99"],
        ["list", "--since", "20261101"],
        ["grep", "x", "--since", "2026-02-30"],
        ["grep", "x", "--width", "-1"],
    ],
)
def test_invalid_arguments_exit_2(tmp_path, argv):
    with pytest.raises(SystemExit) as excinfo:
        sr.main(argv, cwd=str(tmp_path), sessions_dir=tmp_path)
    assert excinfo.value.code == 2


def test_width_zero_is_allowed(tmp_path, capsys):
    cwd = tmp_path / "nogit"
    cwd.mkdir()
    sessions = tmp_path / "sessions"
    write_session(sessions, str(cwd), "2026-11-01T00:00:00.000Z", "aaaa1111", [msg("user", text("前 HIT 後"))])
    code, out, _ = run(capsys, ["grep", "HIT", "--width", "0"], cwd, sessions)
    assert code == 0 and "HIT" in out and "前 HIT" not in out


@pytest.mark.parametrize(
    "args",
    [
        ["show", "latest", "--tail", "9" * 30],
        ["show", "latest", "--tail", "10001"],
        ["list", "--limit", "9" * 30],
        ["grep", "x", "--limit", "10001"],
    ],
)
def test_huge_counts_are_argument_errors(tmp_path, args):
    agent = tmp_path / "agent"
    _write_raw_session(agent, tmp_path, [GOOD_LINE])  # 引数の検証より先に、巨大な値が使われる経路まで進む状態にする
    proc = _cli(args, tmp_path, agent)
    assert proc.returncode == 2, proc.stderr[-300:]
    assert b"Traceback" not in proc.stderr


_DEEP_MARK = "@@DEEP@@"


def _json_line_with_deep_array(entry: dict, depth: int) -> str:
    """entry の中の `_DEEP_MARK` の文字列を、深さ depth の入れ子の配列に置き換えた JSON の 1 行。

    json.dumps は入れ子の深さだけ再帰するので、深い値は組み立てられない (CPython 3.13 の C の再帰の上限は
    Linux が 10000・Windows が 3000 で、Windows の CI は 3000 で RecursionError になった)。配列はテキストで作る。
    """
    return json.dumps(entry).replace(json.dumps(_DEEP_MARK), "[" * depth + "]" * depth)


@needs_git
# 2000: Windows の C の上限 (3000) の下。JSON として読めた深い値を、実装が扱える。3000・9000: Linux の上限 (10000) の下。
# Windows ではこの 2 つは読み込みが RecursionError になり、壊れた行として読み飛ばす (どちらの経路でも落ちない)
@pytest.mark.parametrize("depth", [2000, 3000, 9000])
@pytest.mark.parametrize("role", ["user", "assistant"])
def test_cli_survives_deeply_nested_string_fields(tmp_path, role, depth):
    """text・name などの文字列のフィールドに、JSON としては読める深い配列が入っていても落ちない。"""
    repo_dir = tmp_path / "r"
    _git_init(repo_dir)
    repo_dir = repo_dir.resolve()
    agent = tmp_path / "agent"
    deep = _DEEP_MARK
    bad_entries = [
        {"type": "message", "id": "d1", "message": {"role": role, "content": [{"type": "text", "text": deep}]}},
        msg("assistant", [{"type": "toolCall", "name": deep, "arguments": {"command": deep}}], "d2"),
        {"type": "session_info", "id": "d3", "name": deep},
        {"type": "compaction", "id": "d4", "summary": deep},
    ]
    bad_lines = [_json_line_with_deep_array(entry, depth) for entry in bad_entries]
    _write_raw_session(agent, repo_dir, [line.encode() for line in bad_lines] + [GOOD_LINE])
    for args in (["list"], ["grep", "."], ["grep", ".", "--tools"], ["show", "latest"], ["digest", "latest"]):
        proc = _cli(args, repo_dir, agent)
        assert proc.returncode == 0, (args, proc.stderr[-500:])
        assert b"Traceback" not in proc.stderr
    assert b"ALIVE-MARK" in _cli(["show", "latest"], repo_dir, agent).stdout


def test_changed_file_keys_are_not_truncated_paths(tmp_path):
    """重複の判定は元のパス全体で行い、表示だけを短くする。"""
    cwd = tmp_path / "nogit"
    cwd.mkdir()
    sessions = tmp_path / "sessions"
    prefix = "d/" * 150
    calls = [{"type": "toolCall", "name": "edit", "arguments": {"path": prefix + name}} for name in ("one.py", "two.py", "one.py")]
    path = write_session(sessions, str(cwd), "2026-11-01T00:00:00.000Z", "aaaa1111", [msg("assistant", calls)])
    session = sr.Session(path, "aaaa1111", "2026-11-01T00:00:00.000Z", str(cwd), "main")
    summary = sr.scan_session(session, sr.ScanStats())
    assert len(summary.files) == 2 and summary.files_omitted == 0
    assert all(len(shown) <= 300 for shown in summary.files.values())


def test_changed_file_key_does_not_collide_with_a_real_path_named_like_a_digest(tmp_path):
    """極端に長いパスのダイジェストと、その文字列そのものを名前にした短い実パスは、別のファイルとして保つ。"""
    import hashlib

    cwd = tmp_path / "nogit"
    cwd.mkdir()
    sessions = tmp_path / "sessions"
    long_path = "d/" * 150 + "one.py"
    digest_named = "sha256:" + hashlib.sha256(long_path.encode("utf-8")).hexdigest()
    calls = [
        {"type": "toolCall", "name": "edit", "arguments": {"path": long_path}},
        {"type": "toolCall", "name": "write", "arguments": {"path": digest_named}},
    ]
    path = write_session(sessions, str(cwd), "2026-11-01T00:00:00.000Z", "aaaa1111", [msg("assistant", calls)])
    session = sr.Session(path, "aaaa1111", "2026-11-01T00:00:00.000Z", str(cwd), "main")
    summary = sr.scan_session(session, sr.ScanStats())
    assert len(summary.files) == 2 and summary.files_omitted == 0


# ---- 範囲を変える引数が無いこと(指摘 11) ----
SCOPE_FLAGS = ("--cwd", "--root", "--repo", "--all", "--path", "--dir")
SUBCOMMAND_ARGV = {"list": ["list"], "grep": ["grep", "x"], "show": ["show", "latest"], "digest": ["digest", "latest"]}


@pytest.mark.parametrize("sub", sorted(SUBCOMMAND_ARGV))
def test_subcommand_help_has_no_scope_options(sub):
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "session_recall.py"), sub, "-h"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert proc.returncode == 0 and "--max-chars" in proc.stdout
    for flag in SCOPE_FLAGS:
        assert not re.search(rf"(?<![\w-]){re.escape(flag)}\b", proc.stdout), (sub, flag)


@pytest.mark.parametrize("sub", sorted(SUBCOMMAND_ARGV))
@pytest.mark.parametrize("flag", SCOPE_FLAGS)
def test_scope_flags_are_rejected(tmp_path, sub, flag):
    with pytest.raises(SystemExit) as excinfo:
        sr.main([*SUBCOMMAND_ARGV[sub], flag, str(tmp_path)], cwd=str(tmp_path), sessions_dir=tmp_path)
    assert excinfo.value.code == 2
