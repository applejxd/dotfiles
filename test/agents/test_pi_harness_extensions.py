"""ハーネスへ明示の ``-e`` で足した拡張が、判定・伏字化の中でどう扱われるかを、偽のモデルで試す。

pi が無い環境では skip する (``test_pi_harness.py`` と同じ)。
see docs/research/agents/pi-extension-under-harness.md
"""

from __future__ import annotations

import json
import shutil
import sys

import pytest
from agents_common import ROOT
from test_pi_harness import FIXTURES, SECRET, bash_call, env, run_pi  # noqa: F401

sys.path.insert(0, str(ROOT / "scripts" / "agents"))

EXT = ("-e", str(FIXTURES / "ext_tool.ts"))
CALL = [{"name": "ext_search", "args": {"query": "hello"}}]


def _list_tool_in_role(env, tool):
    """役割 implementer の tools に ``tool`` を足す (判定器の設定は rules.json の judge にある)."""
    path = env["harness"] / "rules.json"
    rules = json.loads(path.read_text(encoding="utf-8"))
    tools = rules["judge"]["common"]["pi"]["profiles"]["implementer"]["tools"]
    assert "mcp__*" in tools, "implementer の tools が変わった (この試験の前提を直す)"
    tools.append(tool)
    path.write_text(json.dumps(rules), encoding="utf-8")


def test_extension_tool_is_denied_unless_the_role_lists_it(env):
    loaded, ran = env["tmp"] / "loaded", env["tmp"] / "ran"
    proc = run_pi(env, CALL, extra=EXT, EXT_LOADED_FILE=str(loaded), EXT_RAN_FILE=str(ran))

    # -ne でも明示の -e は読まれ、ツールはモデルに宣言される。だが役割に無ければ判定で拒否する
    assert loaded.exists()
    assert '"ext_search"' in proc.stdout
    assert "は ext_search を使えない" in proc.stdout, proc.stdout
    assert not ran.exists()
    # bypass でも deny は通らない
    proc = run_pi(env, CALL, extra=EXT, PI_HARNESS_BYPASS="1", EXT_RAN_FILE=str(ran))
    assert "は ext_search を使えない" in proc.stdout, proc.stdout
    assert not ran.exists()


def test_listed_extension_tool_is_asked_and_its_result_is_redacted(env):
    ran = env["tmp"] / "ran"
    _list_tool_in_role(env, "ext_search")
    common = dict(EXT_RAN_FILE=str(ran), EXT_SECRET=SECRET)

    # 役割に載せても、規則が無ければ既定の確認になる (UI の無い起動では拒否)
    proc = run_pi(env, CALL, extra=EXT, **common)
    assert "not approved:" in proc.stdout, proc.stdout
    assert not ran.exists()

    # bypass で実行させると、ハーネスの tool_result が結果の秘密を伏せる
    proc = run_pi(env, CALL, extra=EXT, mode="json", PI_HARNESS_BYPASS="1", **common)
    assert ran.exists()
    assert "伏字" in proc.stdout
    assert SECRET not in proc.stdout
    results = [
        json.loads(line)
        for line in proc.stdout.splitlines()
        if line.startswith("{") and '"toolName":"ext_search"' in line
    ]
    assert results


def test_extension_cannot_replace_a_guarded_tool(env):
    pwned = env["proj"] / "pwned"
    proc = run_pi(
        env,
        bash_call("wc -c /dev/null"),
        extra=(*EXT, "-e", str(FIXTURES / "mutator.ts")),
        MUTATE_TO=f"touch {pwned.as_posix()}",
        EXT_OVERRIDE="guarded_bash",
        EXT_SHELL=shutil.which("bash") or "bash",
    )

    # 同じ名前のツールを後から登録すると、読み込みの失敗で起動が止まる (許可側へは倒れない)
    assert proc.returncode != 0
    assert 'Tool "guarded_bash" conflicts' in proc.stderr, proc.stderr
    assert not pwned.exists()


# ─── MCP の exposure (生成器 → ハーネス) ─────────────────────────────

MCP_SERVER = FIXTURES / "mcp_server.py"


def _common_with_mcp(**extra):
    from agents_common import load_common

    common = json.loads(json.dumps(load_common()))
    common["mcp"] = [
        {
            "id": "spike",
            "purpose": "試験",
            "transport": "stdio",
            "command": sys.executable,
            "args": [str(MCP_SERVER)],
            "clis": ["pi"],
            **extra,
        }
    ]
    return common


def test_generated_mcp_config_defaults_to_direct_and_honours_exposure():
    import generate as gen

    servers = gen.pi_mcp_servers(_common_with_mcp())
    assert servers[0]["config"]["exposure"] == "direct"
    servers = gen.pi_mcp_servers(_common_with_mcp(exposure="deferred"))
    assert servers[0]["config"]["exposure"] == "deferred"
    # Claude / Copilot / OpenCode / Codex へ出す定義には exposure を混ぜない
    shared = gen.mcp_servers(_common_with_mcp(exposure="deferred"))
    assert all("exposure" not in entry for _, entry in shared)
    with pytest.raises(ValueError, match="exposure"):
        gen.pi_mcp_servers(_common_with_mcp(exposure="codemod"))


def test_mcp_tool_from_the_generated_config_is_declared_and_asked_under_the_harness(env):
    """pis は -ne で codemode / tool_search を外す。
    生成器が direct を出さないと、MCP のツールは呼べない (E6)。"""
    import generate as gen

    rules = json.loads((env["harness"] / "rules.json").read_text(encoding="utf-8"))
    rules["mcp"] = gen.pi_mcp_servers(_common_with_mcp())
    (env["harness"] / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
    proc = run_pi(env, [{"name": "mcp__spike__echo_secret", "args": {}}])

    assert '"mcp__spike__echo_secret"' in proc.stdout.splitlines()[0], proc.stdout
    # 実装役では MCP のツールは既定の確認。UI の無い起動では拒否になる (pis で ask)
    assert "isError=true :: not approved:" in proc.stdout, proc.stdout
    assert "mcp-raw-secret" not in proc.stdout


def test_mcp_tool_without_exposure_is_unreachable_under_the_harness(env):
    """欠陥の再現 (exposure を出さない旧い生成)。
    pi が codemode を宣言する版になれば、この試験を見直す。"""
    rules = json.loads((env["harness"] / "rules.json").read_text(encoding="utf-8"))
    config = {"command": sys.executable, "args": [str(MCP_SERVER)]}
    rules["mcp"] = [{"name": "spike", "config": config}]
    (env["harness"] / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
    proc = run_pi(env, [{"name": "mcp__spike__echo_secret", "args": {}}])

    assert "Tool mcp__spike__echo_secret not found" in proc.stdout, proc.stdout


ACTIVITY = ROOT / "home" / "dot_pi" / "agent" / "extensions" / "activity" / "index.ts"


def _bg(command):
    return [{"name": "bg_run", "args": {"command": command}}]


def test_bg_run_is_judged_like_bash_and_denied_commands_do_not_start(env):
    """バックグラウンド実行も、bash と同じ deny を通らない (bypass でも)。"""
    marker = env["tmp"] / "started"
    command = f"touch {marker.as_posix()}; rm -rf ~"
    for extra in ({}, {"PI_HARNESS_BYPASS": "1"}):
        proc = run_pi(env, _bg(command), extra=("-e", str(ACTIVITY)), **extra)
        assert "isError=true" in proc.stdout, proc.stdout
        assert "壊滅的" in proc.stdout, proc.stdout
        assert not marker.exists()


def test_bg_run_starts_an_allowed_command_and_bg_log_and_bg_kill_are_allowed(env):
    proc = run_pi(env, _bg("wc -c /dev/null"), extra=("-e", str(ACTIVITY)))
    assert "isError=false" in proc.stdout, proc.stdout
    proc = run_pi(
        env,
        [{"name": "bg_log", "args": {}}, {"name": "bg_kill", "args": {"id": "j999"}}],
        extra=("-e", str(ACTIVITY)),
    )
    assert "not approved" not in proc.stdout, proc.stdout
    assert "使えない" not in proc.stdout, proc.stdout


def test_bg_run_asks_when_bash_would_ask(env):
    """bash なら確認になるコマンドは、バックグラウンドでも確認になる (UI が無ければ拒否)。"""
    marker = env["tmp"] / "started"
    proc = run_pi(env, _bg(f"touch {marker.as_posix()}"), extra=("-e", str(ACTIVITY)))
    assert "not approved:" in proc.stdout, proc.stdout
    assert not marker.exists()


def test_a_role_without_bash_cannot_use_the_background_tools(env):
    calls = [*_bg("wc -c /dev/null"), {"name": "bg_log", "args": {}}]
    proc = run_pi(env, calls, extra=("-e", str(ACTIVITY)), PI_HARNESS_ROLE="reader")
    assert "は bash を使えない" in proc.stdout, proc.stdout
    assert "は bg_log を使えない" in proc.stdout, proc.stdout
