"""OpenCode: 作業ツリーの外の読み取りと、スキルのスクリプトの確認なし実行。

``[opencode.external_read]`` と ``[opencode.skill_scripts]`` から生成する規則を、
OpenCode の照合 (後勝ち・``*`` は ``/`` を跨ぐ) で評価して確かめる。
see docs/spec/agent-config-generation.md#作業ツリーの外の読み取り

Run with: ``uv run --with pytest --no-project pytest test/agents/ -q``
"""

from __future__ import annotations

import copy
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "agents"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import generate as gen  # noqa: E402
from agents_common import load_common  # noqa: E402

COMMON = load_common()
HOME = os.path.expanduser("~")


def normal() -> list[dict]:
    return gen.build_opencode_permissions(COMMON)


def isolated() -> list[dict]:
    return gen.build_opencode_sandbox_permissions(COMMON)


def _matches(pattern: str, value: str, *, action: str) -> bool:
    """OpenCode の照合。``*`` は ``/`` を含む 0 文字以上、``?`` は 1 文字で全体一致。

    shell の末尾 `` *`` は引数なしにも当たる。``~`` は shell 以外だけ展開する。
    """
    # OpenCode の Wildcard.match は両辺の ``\`` を ``/`` に揃えてから照合する
    # (Windows の ``C:\Users\x/.claude`` のような混在を同じ形にする)
    pattern = pattern.replace("\\", "/")
    value = value.replace("\\", "/")
    if action != "shell" and pattern.startswith("~/"):
        pattern = HOME.replace("\\", "/") + pattern[1:]
    if action == "shell" and pattern.endswith(" *") and value == pattern[:-2]:
        return True
    body = "".join(".*" if c == "*" else "." if c == "?" else re.escape(c) for c in pattern)
    return re.fullmatch(body, value, re.DOTALL) is not None


def effect(action: str, resource: str, permissions: list[dict] | None = None) -> str | None:
    """最後に一致した規則の effect。一致が無ければ None (OpenCode の既定へ落ちる)。"""
    found = None
    for rule in normal() if permissions is None else permissions:
        if rule["action"] == action and _matches(rule["resource"], resource, action=action):
            found = rule["effect"]
    return found


def home(path: str) -> str:
    return HOME + path[1:] if path.startswith("~/") else path


# ---------------------------------------------------------------------------
# 作業ツリーの外の読み取り
# ---------------------------------------------------------------------------


def test_external_read_opens_skill_dirs_and_work_read():
    """スキルの置き場と、隔離版の work_read を同じ一覧から開ける (二重に並べない)。"""
    expected = [
        *COMMON["opencode"]["external_read"]["paths"],
        *COMMON["opencode"]["sandbox"]["work_read"],
    ]
    assert gen.opencode_external_read_dirs(COMMON) == expected
    for d in expected:
        assert effect("external_directory", home(d) + "/proj/*") == "allow", d


def test_other_external_dirs_are_left_to_the_default():
    for d in ("/etc/*", home("~/.ssh/*"), home("~/Downloads/*"), home("~/.config/*")):
        assert effect("external_directory", d) is None, d


def test_external_read_keeps_edit_behind_a_confirmation():
    """external_directory は edit の前段でもあるので、同じ場所の edit を ask に戻す。

    戻さないと既定の ``{*, *, allow}`` で作業ツリーの外へ確認なしに書ける。
    """
    for d in gen.opencode_external_read_dirs(COMMON):
        assert effect("edit", home(d) + "/proj/a.txt") == "ask", d


def test_read_is_not_allowed_explicitly():
    """read の allow は deny の例外 (``.env.example`` など) だけ。それ以外は足さない。"""
    allowed = {r["resource"] for r in normal() if r["action"] == "read" and r["effect"] == "allow"}
    expected = {
        p
        for e in COMMON["file"]["deny_exceptions"]
        for g in e["except"]
        for p in gen.opencode_path_patterns(g)
    }
    assert allowed == expected


@pytest.mark.parametrize(
    ("action", "path"),
    [
        ("read", "~/src/proj/.ssh/id_ed25519"),
        ("read", "~/.local/share/chezmoi/secrets/token.txt"),
        ("read", "~/.claude/skills/x/service-account-1.json"),
        ("edit", "~/src/proj/.git/config"),
        ("edit", "~/.local/share/chezmoi/.git/hooks/pre-commit"),
    ],
)
def test_secret_deny_still_wins_inside_opened_dirs(action: str, path: str):
    assert effect(action, home(path)) == "deny"


def test_external_read_rules_come_before_the_file_rules():
    """秘密の deny を後勝ちで効かせるため、開ける規則は read / edit の規則より前に置く。"""
    perms = normal()
    opened = [i for i, r in enumerate(perms) if r["action"] == "external_directory"]
    files = [i for i, r in enumerate(perms) if r["action"] in ("read", "edit")]
    edit_ask = {f"{d}/*" for d in gen.opencode_external_read_dirs(COMMON)}
    others = [i for i in files if perms[i]["resource"] not in edit_ask]
    assert opened
    assert max(opened) < min(others)


def test_isolated_opens_the_same_dirs():
    """隔離版も既定は ask。Fence が読ませる場所は確認なしに読めるようにする。

    edit の ask は残す。``~/`` 始まりの read / edit の規則は隔離版では捨てるが、
    これを捨てると以前は external_directory が止めていた edit が確認なしになる。
    """
    perms = isolated()
    for d in gen.opencode_external_read_dirs(COMMON):
        assert effect("external_directory", home(d) + "/proj/*", perms) == "allow", d
        assert effect("edit", home(d) + "/proj/a.txt", perms) == "ask", d


# deny の例外 (.env.example など) は、`.env.*` の deny で潰されたものを戻すだけにする。
# 作業ツリーの外の edit の確認 (ask) や、別の deny に勝ってはいけない。
@pytest.mark.parametrize("build", [normal, isolated], ids=["通常版", "隔離版"])
@pytest.mark.parametrize(
    ("action", "path", "expected"),
    [
        ("edit", "app/.env.example", "allow"),
        ("read", "app/.env.example", "allow"),
        ("edit", "app/.env.local", "deny"),
        ("edit", "~/.claude/skills/foo/.env.example", "ask"),
        ("edit", "~/.claude/skills/.env.example", "ask"),
        ("edit", "~/.claude/skills/foo/bar/.env.template", "ask"),
        ("read", "~/.claude/skills/foo/.env.example", "allow"),
        ("edit", "~/.claude/skills/foo/.env.local", "deny"),
        ("edit", "~/.ssh/.env.example", "deny"),
        ("read", "~/.ssh/.env.example", "deny"),
        ("edit", "~/.claude/skills/foo/.ssh/.env.example", "deny"),
    ],
)
def test_deny_exceptions_do_not_override_external_edit_asks(build, action, path, expected):
    assert effect(action, home(path), build()) == expected, path


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("~/s/*", "*/.env.example", {"~/s/*/.env.example", "~/s/.env.example"}),
        ("~/s/*", ".env.example", set()),
        ("mise.toml", "*/.env.example", set()),
        ("mise.toml", "*mise.toml", {"mise.toml"}),
        ("a/*", "b/*", set()),
        ("a/*", "a/b/*", {"a/b/*"}),
    ],
)
def test_wildcard_intersection(a, b, expected):
    assert set(gen.wildcard_intersection(a, b)) == expected


@pytest.mark.parametrize(("a", "b"), [("a/?", "*/x"), ("a/*/b/*", "*/x"), ("*/x", "a/**")])
def test_wildcard_intersection_refuses_shapes_it_cannot_cross(a, b):
    with pytest.raises(ValueError, match="交差"):
        gen.wildcard_intersection(a, b)


# ---------------------------------------------------------------------------
# スキルのスクリプト
# ---------------------------------------------------------------------------

SDD = "~/.claude/skills/sdd-docs/scripts"
CP = "~/.config/opencode/skills/checkpoint/scripts/checkpoint.py"


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (f"python3 {SDD}/lint_docs.py --docs docs", "allow"),
        (f"python3 {HOME}/.claude/skills/sdd-docs/scripts/lint_docs.py --docs docs", "allow"),
        (f"python3 {SDD}/lint_docs.py", "allow"),
        (f"python3 {SDD}/check_refs.py --save", "allow"),
        (f"python3 {SDD}/check_refs.py --baseline", "allow"),
        (f"python3 {CP} paths --session ses_x --ensure-ignored", "allow"),
        (f"python3 {CP} lint /w/.tmp/checkpoint-x.md --structure --session ses_x", "allow"),
        (f"python3 {CP} read --session ses_x", "allow"),
        # 引数のパスへ書ける形は確認に残る (完全一致なので引用符・変数・省略形でも外れない)
        (f"python3 {SDD}/check_refs.py --save .tmp/refs-before.txt", "ask"),
        (f"python3 {SDD}/check_refs.py --baseline a --sa {HOME}/.bashrc", "ask"),
        (f"python3 {SDD}/check_refs.py '--'save {HOME}/.bashrc", "ask"),
        (f"python3 {SDD}/check_refs.py $X {HOME}/.bashrc", "ask"),
        (f"python3 {SDD}/check_refs.py --save > {HOME}/.bashrc", "ask"),
        (f"python3 {CP} write /w/.tmp/c.md --keep-prev /w/.tmp/p.md", "ask"),
        # リダイレクトは任意書き込みの手段になる
        (f"python3 {SDD}/lint_docs.py --docs docs > ~/.bashrc", "deny"),
        (f"python3 {SDD}/lint_docs.py --docs docs 2>&1", "deny"),
        (f"python3 {CP} lint - < draft.md", "deny"),
        (f"python3 {CP} paths --session x >> ~/.profile", "deny"),
        # 載せたスクリプト以外・別の起動形式は既定の ask のまま
        (f"python3 {SDD}/lint_docs.py.bak", "ask"),
        (f"python3 {SDD}/lint_docs.py/../../../../evil.py", "ask"),
        ("python3 ~/.claude/skills/../../evil.py", "ask"),
        (f"uv run --no-project python {SDD}/lint_docs.py --docs docs", "ask"),
        ('uv run --no-project python "$S/lint_docs.py" --docs docs', "ask"),
        (f'python3 "{HOME}/.claude/skills/sdd-docs/scripts/lint_docs.py"', "ask"),
        ("bash ~/.claude/skills/hook-creator/scripts/verify-hook.sh h.sh", "ask"),
    ],
)
def test_skill_scripts(command: str, expected: str):
    assert effect("shell", command) == expected


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("python3 C:\\Users\\x/.claude/skills/sdd-docs/scripts/lint_docs.py --docs docs", "allow"),
        ("python3 C:\\Users\\x\\.claude\\skills\\sdd-docs\\scripts\\lint_docs.py", "allow"),
        ("python3 C:/Users/x/.claude/skills/sdd-docs/scripts/lint_docs.py", "allow"),
        ("python3 ~/.claude/skills/sdd-docs/scripts/lint_docs.py", "allow"),
        ("python3 C:\\Users\\x\\.claude\\skills\\sdd-docs\\scripts\\lint_docs.py > a", "deny"),
        ("python3 C:\\Users\\x\\.claude\\skills\\evil.py", "ask"),
        ("python3 C:\\Users\\x\\.ssh\\evil.py", "ask"),
    ],
)
def test_skill_scripts_windows_shapes(monkeypatch, command: str, expected: str):
    """Windows の混在区切りでも、skills 配下の載せたスクリプトだけが通る。"""
    monkeypatch.setattr(gen, "expand_user", lambda p: p.replace("~", "C:\\Users\\x", 1))
    perms = gen.build_opencode_permissions(COMMON)
    assert effect("shell", command, perms) == expected


def test_skill_script_allow_is_not_widened_silently():
    """確認なしに実行できるスクリプトが増えたら気付けるようにする。

    足すときは、引数で書き込み先や実行するものを決められないか・git などを通して
    リポジトリの設定からコマンドを起動しないかを確かめる (see 冒頭の docs)。
    """
    allow, _ = gen.opencode_skill_script_rules(COMMON)
    assert [r for r in allow if r.startswith(("python3 ~/", "bash ~/"))] == [
        f"python3 {SDD}/lint_docs.py *",
        f"python3 {SDD}/check_refs.py --save",
        f"python3 {SDD}/check_refs.py --baseline",
        f"python3 {CP} paths *",
        f"python3 {CP} lint *",
        f"python3 {CP} read *",
    ]


def test_skill_script_redirect_deny_follows_its_allow():
    """リダイレクトの deny は allow より後ろ (後勝ち)。"""
    resources = [r["resource"] for r in normal()]
    allow, deny = gen.opencode_skill_script_rules(COMMON)
    assert max(map(resources.index, allow)) < min(map(resources.index, deny))


def test_skill_script_runners_do_not_read_the_workspace_python_version():
    """``uv run --no-project python`` は作業ツリーの .python-version の実行ファイルを起動する。"""
    for runners in COMMON["opencode"]["skill_scripts"]["runners"].values():
        for runner in runners:
            assert not runner.startswith("uv"), runner


@pytest.mark.parametrize(
    "script",
    [
        "~/src/proj/tool.py",
        "~/.claude/skills/../src/tool.py",
        "~/.claude/skills/x/scripts/tool.rb",
        {"script": "~/.claude/skills/x/a.py", "exact": ["--x"], "subcommands": ["y"]},
    ],
)
def test_skill_scripts_are_limited_to_skill_dirs_and_known_runners(script):
    common = copy.deepcopy(COMMON)
    entry = script if isinstance(script, dict) else {"script": script}
    common["opencode"]["skill_scripts"]["allow"] = [entry]
    with pytest.raises(ValueError, match="skill_scripts"):
        gen.build_opencode_permissions(common)


def test_isolated_drops_the_skill_script_rules():
    """隔離版は既定が allow。リダイレクトの deny を残すと拒否が増えるだけ。"""
    perms = isolated()
    for command in (
        f"python3 {SDD}/check_refs.py --save .tmp/refs-before.txt",
        f"python3 {SDD}/lint_docs.py --docs docs > out.txt",
    ):
        assert effect("shell", command, perms) == "allow", command
    skill = {r for group in gen.opencode_skill_script_rules(COMMON) for r in group}
    assert not [r for r in perms if r["resource"] in skill]


SKILL_DOCS = (
    ROOT / "home/dot_claude/skills/sdd-docs/SKILL.md",
    ROOT / "home/dot_config/opencode/skills/checkpoint/SKILL.md",
)


@pytest.mark.parametrize("path", SKILL_DOCS, ids=lambda p: p.parent.name)
def test_skill_docs_call_their_scripts_in_the_allowed_form(path: Path):
    """スキルが書いている呼び出しが、そのまま allow に当たる。

    変数に入れたパス (``"$S/…"``) や ``uv run`` を挟む形は当たらない。
    引数のパスへ書く形 (``--save <パス>`` / ``write``) だけは確認に残る。
    """
    calls = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith(("python3 ~/", "uv run", 'S="', "CP="))
    ]
    assert calls
    for call in calls:
        # 説明用の山括弧を実際の値に見立てる
        command = re.sub(r"<[^>]+>", "x", call).replace('"x"', "x")
        writes = " write " in command or re.search(r" --save \S", command)
        assert effect("shell", command) == ("ask" if writes else "allow"), call
