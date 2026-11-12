"""pi の MCP サーバの宣言 (pi-mcp-servers.toml) から mcp.json が生成されることを固定する。

ユーザ・機 (is-work) による出し分けは pi-mcp-servers.toml 側の chezmoi テンプレートが行うので、
生成側 (generate.py) には条件が無い。ここでは「描画結果が mcp.json・mcp-adapter.json へそのまま
伝わること」と、壊れた宣言が apply を止めることを確かめる。

Run with: ``uv run --with pytest --no-project pytest test/agents/ -q``
"""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "agents"))

import generate as gen  # noqa: E402
from agents_common import load_mcp_servers, render_mcp_servers  # noqa: E402

# 家の機 (applejxd) と会社 PC (それ以外)。出し分けの両側を確かめる
HOME = load_mcp_servers("applejxd")
WORK = load_mcp_servers("tester")
USERS = ["applejxd", "tester"]

HTTP = {"id": "x", "transport": "http", "url": "https://example.com/mcp"}
STDIO = {"id": "x", "transport": "stdio", "command": "uvx", "args": ["demo"]}


# ---------------------------------------------------------------------------
# 宣言 (pi-mcp-servers.toml) の健全性
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("username", USERS)
def test_rendered_declaration_is_valid_toml(username):
    """テンプレート化で check-toml が効かなくなる分をここで担保する。"""
    rendered = tomllib.loads(render_mcp_servers(username))
    assert len(rendered.get("mcp", [])) >= 1


def test_deepwiki_is_declared_nowhere():
    """★deepwiki を戻さないこと。

    索引が古く、実ソース (v2.0.14) と食い違う説明を返した。上流を読むなら
    `gh api` でタグを指定して取る。
    """
    for common in (HOME, WORK):
        assert "deepwiki" not in [s["id"] for s in common["mcp"]]


@pytest.mark.parametrize("common", [HOME, WORK], ids=["home", "work"])
def test_declared_servers_pass_validation(common):
    assert [name for name, _ in gen.mcp_servers(common)] == [s["id"] for s in common["mcp"]]
    for server in common["mcp"]:
        assert server["purpose"], f"{server['id']}: purpose が空"


def test_home_has_the_own_search_and_work_has_only_agentcore():
    """個人の機には自作の検索 MCP (websearch) が入る。会社 PC は AgentCore の 1 本だけ。"""
    assert [name for name, _ in gen.mcp_servers(HOME)] == ["agentcore-websearch", "websearch"]
    assert [name for name, _ in gen.mcp_servers(WORK)] == ["agentcore-websearch"]


def test_agentcore_websearch_runs_the_deployed_wrapper():
    """ラッパーを絶対パスで指す (MCP クライアントは `~` を展開しない)。"""
    (server,) = [s for s in WORK["mcp"] if s["id"] == "agentcore-websearch"]
    assert server["command"] == "uv"
    assert server["requires_env"] == "AGENTCORE_GATEWAY_URL"
    assert "/test-home/.config/agents/agentcore_websearch_mcp.py" in server["args"]
    assert (ROOT / "home/dot_config/agents/agentcore_websearch_mcp.py").is_file()
    # Windows でも展開する
    ignore = (ROOT / "home/.chezmoiignore.tmpl").read_text(encoding="utf-8")
    assert "!.config/agents/agentcore_websearch_mcp.py" in ignore


@pytest.mark.parametrize(
    "server",
    [
        {**HTTP, "transport": "sse"},
        {**HTTP, "url": ""},
        {k: v for k, v in HTTP.items() if k != "url"},
        {**HTTP, "id": ""},
        {**HTTP, "id": "bad name"},
        {**HTTP, "id": "bad.name"},
        # transport が持てないキーは typo とみなす
        {**HTTP, "command": "uvx"},
        {**STDIO, "url": "https://example.com/mcp"},
        {**STDIO, "command": ""},
        {k: v for k, v in STDIO.items() if k != "command"},
        {**STDIO, "args": "demo"},
        {**STDIO, "args": [1]},
        {**HTTP, "typo": 1},
        # 生成先が 1 つになったので、clis は書けない
        {**HTTP, "clis": ["pi"]},
    ],
)
def test_broken_declaration_stops_generation(server):
    """未対応・壊れた宣言は、黙って書き出さず apply を止める。"""
    with pytest.raises(ValueError):
        gen.mcp_servers({"mcp": [server]})


def test_duplicate_id_stops_generation():
    with pytest.raises(ValueError):
        gen.mcp_servers({"mcp": [HTTP, dict(HTTP)]})


@pytest.mark.parametrize("value", ["", "lower", "1BAD", "A B", 3, ["X"]])
def test_requires_env_must_be_an_uppercase_variable_name(value):
    with pytest.raises(ValueError):
        gen.mcp_servers({"mcp": [{**STDIO, "requires_env": value}]})


def test_requires_env_is_accepted_and_does_not_reach_mcp_json():
    common = {"mcp": [{**STDIO, "requires_env": "X_URL"}]}
    assert [n for n, _ in gen.mcp_servers(common)] == ["x"]
    assert "requires_env" not in gen.merge_pi_mcp({}, common)["mcpServers"]["x"]


def test_pi_exposure_is_validated():
    with pytest.raises(ValueError, match="pi_exposure"):
        gen.mcp_servers({"mcp": [{**STDIO, "pi_exposure": "bogus"}]})


# ---------------------------------------------------------------------------
# stock の pi (~/.pi/agent/mcp.json)
# ---------------------------------------------------------------------------


def test_pi_mcp_targets_are_registered():
    assert {
        "pi-mcp": gen.merge_pi_mcp,
        "pi-mcp-adapter": gen.merge_pi_mcp_adapter,
    } == gen.TARGETS
    for modifier, target in (
        ("modify_mcp.json.py.tmpl", "pi-mcp"),
        ("modify_mcp-adapter.json.py.tmpl", "pi-mcp-adapter"),
    ):
        text = (ROOT / "home/dot_pi/agent" / modifier).read_text(encoding="utf-8")
        assert f'"target" "{target}"' in text
    ignore = (ROOT / "home/.chezmoiignore.tmpl").read_text(encoding="utf-8")
    # adapter は adapter を入れる機 (is-work) だけ
    assert ignore.splitlines().count(".pi/agent/mcp-adapter.json") == 1


@pytest.mark.parametrize("common", [HOME, WORK], ids=["home", "work"])
def test_pi_mcp_is_generated_from_the_declaration(common):
    merged = gen.merge_pi_mcp({}, common)
    assert merged["mcpServers"] == {
        name: {
            "command": s["command"],
            "args": s["args"],
            **({"exposure": s["pi_exposure"]} if "pi_exposure" in s else {}),
        }
        for name, s in gen.mcp_servers(common)
    }


def test_pi_mcp_search_servers_are_direct_so_plan_mode_can_allow_them():
    for common in (HOME, WORK):
        servers = gen.merge_pi_mcp({}, common)["mcpServers"]
        assert servers["agentcore-websearch"]["exposure"] == "direct"
    assert gen.merge_pi_mcp({}, HOME)["mcpServers"]["websearch"]["exposure"] == "direct"


def test_pi_exposure_fills_only_when_missing():
    common = {"mcp": [{**STDIO, "pi_exposure": "direct"}]}
    merged = gen.merge_pi_mcp({}, common)
    assert merged["mcpServers"]["x"]["exposure"] == "direct"
    # 利用者が /mcp で変えた値は保つ
    kept = gen.merge_pi_mcp({"mcpServers": {"x": {"exposure": "codemode"}}}, common)
    assert kept["mcpServers"]["x"]["exposure"] == "codemode"
    assert gen.merge_pi_mcp(merged, common) == merged


def test_pi_mcp_websearch_only_on_personal_machine():
    assert "websearch" in gen.merge_pi_mcp({}, HOME)["mcpServers"]
    assert "websearch" not in gen.merge_pi_mcp({}, WORK)["mcpServers"]


def test_pi_mcp_adapter_has_the_same_servers_as_mcp_json_without_exposure():
    """会社 PC (is-work) の pi-mcp-adapter 用。pi-subagents が子の mcp: を ~/.pi/agent/mcp.json から解決しないため。"""
    merged = gen.merge_pi_mcp_adapter({}, WORK)
    plain = gen.merge_pi_mcp({}, WORK)["mcpServers"]
    for name, entry in merged["mcpServers"].items():
        assert entry == {k: v for k, v in plain[name].items() if k != "exposure"}
    assert "exposure" in plain["agentcore-websearch"]  # mcp.json 側は従来どおり
    # 利用者のサーバ・キーは保ち、何度流しても同じ
    existing = {
        "mcpServers": {"mine": {"url": "https://example.com/mcp"}},
        "settings": {"toolPrefix": "none"},
    }
    kept = gen.merge_pi_mcp_adapter(existing, WORK)
    assert kept["mcpServers"]["mine"] == {"url": "https://example.com/mcp"}
    assert kept["settings"] == {"toolPrefix": "none"}
    assert gen.merge_pi_mcp_adapter(kept, WORK) == kept


@pytest.mark.parametrize(("common", "server"), [(WORK, "agentcore-websearch"), (HOME, "websearch")])
def test_the_server_given_to_search_agents_is_declared_on_that_machine(common, server):
    """settings の researcher・evidence-auditor が mcp: で指すサーバは、その機に宣言されている。"""
    assert server in dict(gen.mcp_servers(common))
    source = (ROOT / "home/.chezmoitemplates/modify_pi_stock_settings.py.tmpl").read_text(
        encoding="utf-8"
    )
    assert f'"mcp:{server}"' in source


def test_pi_mcp_keeps_user_servers_and_keys_and_drops_pi_unknown_keys():
    declared = {**STDIO, "requires_env": "FOO"}
    existing = {
        "mcpServers": {
            "mine": {"url": "https://example.com/mcp"},
            "x": {"url": "u", "enabled": False},
        },
        "autoEnableCodemode": False,
    }
    merged = gen.merge_pi_mcp(existing, {"mcp": [declared]})
    assert merged["autoEnableCodemode"] is False
    assert merged["mcpServers"]["mine"] == {"url": "https://example.com/mcp"}
    assert merged["mcpServers"]["x"] == {"command": "uvx", "args": ["demo"], "enabled": False}
    assert gen.merge_pi_mcp(merged, {"mcp": [declared]}) == merged


def test_broken_existing_json_is_returned_untouched(tmp_path, capsys, monkeypatch):
    """利用者も書くファイル。壊れていたら触らずそのまま返す (apply を止めない)。"""
    common = tmp_path / "pi-mcp-servers.toml"
    common.write_text(render_mcp_servers("applejxd"), encoding="utf-8")
    broken = tmp_path / "mcp.json"
    broken.write_text("{broken", encoding="utf-8")
    assert gen.main(["--target", "pi-mcp", "--common", str(common), "--existing", str(broken)]) == 0
    assert capsys.readouterr().out == "{broken"


# ---------------------------------------------------------------------------
# ラッパー: 使えない機では、失敗せずにツールの無い空のサーバになる
# ---------------------------------------------------------------------------

WRAPPER = ROOT / "home/dot_config/agents/agentcore_websearch_mcp.py"


def _run_wrapper(messages, env_extra=None, args=()):
    env = {
        k: v
        for k, v in __import__("os").environ.items()
        if k != "AGENTCORE_GATEWAY_URL"
    }
    env.update(env_extra or {})
    stdin = "".join(json.dumps(m) + "\n" for m in messages)
    return subprocess.run(
        [sys.executable, "-B", str(WRAPPER), *args],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=30,
        check=False,
    )


INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-03-26"},
}
LIST = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}


@pytest.mark.parametrize(
    "env",
    [
        {},  # URL が無い (家)
        {"AGENTCORE_GATEWAY_URL": "http://insecure.example/mcp"},  # https でない
    ],
    ids=["no-url", "not-https"],
)
def test_wrapper_without_a_usable_gateway_serves_an_empty_mcp_server(env):
    done = _run_wrapper(
        [INIT, {"jsonrpc": "2.0", "method": "notifications/initialized"}, LIST], env
    )
    assert done.returncode == 0, done.stderr
    replies = [json.loads(line) for line in done.stdout.splitlines()]
    assert [r["id"] for r in replies] == [1, 2]
    assert replies[0]["result"]["protocolVersion"] == "2025-03-26"
    assert replies[0]["result"]["capabilities"] == {"tools": {}}
    assert replies[1]["result"] == {"tools": []}
    assert "ツール無しで待機" in done.stderr


def test_wrapper_answers_unknown_methods_with_an_error_and_ignores_garbage():
    done = _run_wrapper([{"jsonrpc": "2.0", "id": 5, "method": "tools/call"}])
    (reply,) = [json.loads(line) for line in done.stdout.splitlines()]
    assert reply["id"] == 5 and reply["error"]["code"] == -32601


@pytest.mark.skipif(sys.platform == "win32", reason="execvp の経路は Unix だけ")
def test_wrapper_with_a_gateway_runs_the_pinned_proxy(tmp_path):
    fake = tmp_path / "uvx"
    fake.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n', encoding="utf-8")
    fake.chmod(0o755)
    env = {"AGENTCORE_GATEWAY_URL": "https://gw.example/mcp", "PATH": f"{tmp_path}:/usr/bin:/bin"}
    done = _run_wrapper([], env, ("--service", "bedrock-agentcore"))
    args = done.stdout.split()
    assert args[:2] == ["mcp-proxy-for-aws-cli==1.7.0", "https://gw.example/mcp"], done
    assert args[2:] == ["--service", "bedrock-agentcore"]
