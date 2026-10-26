"""素の ``pi`` が、``settings.json`` だけで ``pis --no-sandbox`` と同じフルガード付きになる試験。

生成 (``merge_pi_settings``) の出力と、その出力だけで本物の pi を偽のモデルで起動したときの
ツール一覧を見る。Windows は subagents を足し commit-confirm を外す。実機 (Windows) は確かめられない。
see docs/spec/guard/pi-guard.md#pi-の設定
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tomllib

import pytest
import test_pi_harness as _harness
from agents_common import ROOT
from test_pi_harness import FIXTURES, PI

sys.path.insert(0, str(ROOT / "scripts" / "agents"))
import generate as gen

env = _harness.env  # フィクスチャを使い回す (import のままだと引数名が再定義と見なされる)

HARNESS_ENTRY = "~/.config/pi/harness"
needs_pi = pytest.mark.skipif(PI is None, reason="pi is not installed")


def _render(os_name: str) -> dict:
    chezmoi = shutil.which("chezmoi")
    if chezmoi is None:
        pytest.skip("chezmoi is not installed")
    context = json.dumps(
        json.dumps({"chezmoi": {"os": os_name, "username": "applejxd", "homeDir": "/test-home"}})
    )
    template = (
        f"{{{{ with {context} | fromJson }}}}"
        '{{ includeTemplate "dot_config/agents/common.toml.tmpl" . }}{{ end }}'
    )
    result = subprocess.run(
        [chezmoi, "--source", str(ROOT), "execute-template", template],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return gen.resolve_pi_shared(tomllib.loads(result.stdout))


def _settings(os_name: str, existing: dict | None = None) -> dict:
    return gen.merge_pi_settings(existing or {}, _render(os_name))


# ─── 生成 ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("os_name", ["linux", "darwin"])
def test_unix_settings_carry_the_full_guard(os_name):
    common = _render(os_name)
    out = gen.merge_pi_settings({}, common)
    own = [f"+extensions/{n}/index.ts" for n in gen.pi_own_extensions(common)]
    assert own, "自作の拡張の一覧が空"
    assert out["extensions"] == [
        HARNESS_ENTRY,
        "!extensions/**",
        *own,
        "+extensions/orca-agent-status.ts",
        "-builtin:codemode",
        "-builtin:tool-search",
        "-builtin:llama.cpp",
    ]
    assert out["defaultTools"] == []
    assert "defaultProjectTrust" not in out  # 信頼の拒否は pis の --no-approve が担う
    assert out["skills"] == ["~/.claude/skills"]


def test_windows_settings_carry_the_full_guard_without_commit_confirm():
    common = _render("windows")
    out = gen.merge_pi_settings({}, common)
    own = [f"+extensions/{n}/index.ts" for n in gen.pi_own_extensions(common)]
    assert out["extensions"] == [
        HARNESS_ENTRY,
        "!extensions/**",
        *own,
        "+extensions/orca-agent-status.ts",
        "+extensions/subagents/index.ts",
        "-builtin:codemode",
        "-builtin:tool-search",
        "-builtin:llama.cpp",
    ]
    assert out["defaultTools"] == []
    assert "commit-confirm" not in json.dumps(out)


@pytest.mark.parametrize("os_name", ["linux", "darwin"])
def test_unix_settings_do_not_load_subagents(os_name):
    assert "subagents" not in json.dumps(_settings(os_name))


def test_windows_rules_are_generated_with_a_backslash_home(monkeypatch):
    """Windows のホーム (C:\\Users\\x) でも rules.json が生成でき、post_edit のパスが崩れない。"""
    common = _render("windows")  # chezmoi のキャッシュが壊れるので、HOME の差し替えは描画の後
    monkeypatch.setenv("HOME", "C:\\Users\\x")
    monkeypatch.setenv("USERPROFILE", "C:\\Users\\x")
    rules = gen.build_pi_harness({}, common)
    assert rules["extensions"] == gen.pi_own_extensions(common)
    assert rules["post_edit"], "post_edit が空"
    for hook in rules["post_edit"]:
        assert hook["script"].startswith("C:/Users/x/.claude/hooks/"), hook
        assert "\\" not in hook["script"]


def test_settings_merge_is_idempotent_and_keeps_foreign_keys():
    first = _settings("linux", {"lastChangelogVersion": "1.3.0", "theme": "dark"})
    assert first["lastChangelogVersion"] == "1.3.0" and first["theme"] == "dark"
    assert _settings("linux", first) == first


def test_settings_drop_declared_keys_that_were_removed():
    common = _render("linux")
    del common["pi"]["settings"]["defaultTools"]
    out = gen.merge_pi_settings({"defaultTools": ["read"]}, common)
    assert "defaultTools" not in out


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("defaultTools", "read"),
        ("defaultTools", [1]),
        ("extensions", "x"),
    ],
)
def test_settings_reject_bad_types(key, value):
    common = _render("linux")
    common["pi"]["settings"][key] = value
    with pytest.raises(SystemExit, match=r"pi\.settings"):
        gen.merge_pi_settings({}, common)


# ─── 起動 (本物の pi。生成した settings.json だけで起動する) ────────────


def _launch(env, *, harness=None, flags=(), own=("todo",), rogue=True):
    """生成した settings.json (フルガードの場所だけ tmp のものにする) で pi を起動する。"""
    settings = gen.merge_pi_settings({}, _render("linux"))
    settings["extensions"] = [
        str(harness or env["harness"]) if e == HARNESS_ENTRY else e for e in settings["extensions"]
    ]
    agent = env["tmp"] / "agent"
    (agent / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    ext = agent / "extensions"
    for name in own:
        (ext / name).mkdir(parents=True)
        shutil.copy2(FIXTURES / "own_tool.ts", ext / name / "index.ts")
    if rogue:  # 審査していない拡張 (自動検出される置き場に置いてある)
        (ext / "rogue").mkdir(parents=True)
        shutil.copy2(FIXTURES / "ext_tool.ts", ext / "rogue" / "index.ts")
        shutil.copy2(FIXTURES / "ext_tool.ts", ext / "ext_tool.ts")
    args = [PI, "--no-session", "--model", "faux/spike", *flags]
    args += ["-e", str(FIXTURES / "faux.ts"), "-p", "go"]
    return subprocess.run(
        args,
        cwd=env["proj"],
        env={**env["env"], "FAUX_TOOL_CALLS": "[]"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )


def _tools(proc) -> list[str]:
    first = proc.stdout.strip().splitlines()[0]
    return json.loads(first.removeprefix("TOOLS="))


@needs_pi
def test_bare_pi_starts_with_the_guarded_tools_only(env):
    proc = _launch(env)
    assert proc.returncode == 0, proc.stderr
    tools = _tools(proc)
    assert "bash" not in tools and "edit" not in tools and "write" not in tools
    assert "guarded_bash" in tools and "guarded_write" in tools
    assert not [t for t in tools if not t.startswith("guarded_") and t != "own_probe"]


@needs_pi
def test_own_extension_is_loaded_and_unreviewed_one_is_not(env):
    proc = _launch(env)
    assert proc.returncode == 0, proc.stderr
    tools = _tools(proc)
    assert "own_probe" in tools, "自作の拡張が読まれていない"
    assert "ext_search" not in tools, "審査していない拡張が読まれた"


@needs_pi
def test_missing_own_extension_is_skipped_without_failing(env):
    proc = _launch(env, own=())
    assert proc.returncode == 0, proc.stderr
    tools = _tools(proc)
    assert "own_probe" not in tools and "ext_search" not in tools
    assert "guarded_bash" in tools


@needs_pi
def test_pis_style_flags_with_settings_do_not_double_load(env):
    flags = ["--no-approve", "-nbt", "-ne", "-e", "builtin:mcp", "-e", str(env["harness"])]
    proc = _launch(env, flags=flags)
    assert proc.returncode == 0, proc.stderr
    tools = _tools(proc)
    assert "guarded_bash" in tools and "ext_search" not in tools
    assert "bash" not in tools


@needs_pi
def test_missing_harness_fails_closed(env):
    proc = _launch(env, harness=env["tmp"] / "no-such-harness", own=())
    assert proc.returncode == 0, proc.stderr
    assert _tools(proc) == []


@needs_pi
def test_orca_status_extension_is_loaded_explicitly_but_other_files_are_not(env):
    """自動検出を外しても、Orca が置く状態表示の拡張だけは名前で足してある。"""
    ext = env["tmp"] / "agent" / "extensions"
    ext.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        FIXTURES / "ext_tool.ts", ext / "orca-agent-status.ts"
    )  # 目印の確認はできない (ext_search で読み込みを見る)
    shutil.copy2(FIXTURES / "ext_tool.ts", ext / "other.ts")
    proc = _launch(env, rogue=False)
    assert proc.returncode == 0, proc.stderr
    assert _tools(proc).count("ext_search") == 1


@needs_pi
def test_bg_run_refuses_to_run_when_the_full_guard_did_not_load(env):
    """フルガードのパスが無い起動で、自作の拡張 (activity) の bg_run が判定なしの shell にならない。"""
    settings = gen.merge_pi_settings({}, _render("linux"))
    settings["extensions"] = [
        str(env["tmp"] / "nowhere") if e == HARNESS_ENTRY else e for e in settings["extensions"]
    ]
    agent = env["tmp"] / "agent"
    (agent / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    shutil.copytree(
        ROOT / "home" / "dot_pi" / "agent" / "extensions" / "activity",
        agent / "extensions" / "activity",
    )
    marker = env["tmp"] / "ran"
    call = [{"name": "bg_run", "args": {"command": f"touch {marker}"}}]
    proc = subprocess.run(
        [PI, "--no-session", "--model", "faux/spike", "-e", str(FIXTURES / "faux.ts"), "-p", "go"],
        cwd=env["proj"],
        env={**env["env"], "FAUX_TOOL_CALLS": json.dumps(call)},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )
    assert proc.returncode == 0, proc.stderr
    assert "フルガードが読み込まれていない" in proc.stdout, proc.stdout
    assert not marker.exists()
