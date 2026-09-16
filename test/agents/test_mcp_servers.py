"""MCP サーバ定義が common.toml の単一ソースから生成されることを固定する。

生成先は Claude Code / Copilot CLI / Codex CLI の 3 つ。
Gemini CLI と Antigravity は使わないので対象外。

ユーザ・OS による出し分けは common.toml 側の chezmoi テンプレートが行うので、
生成側 (generate.py / Codex / Claude) には条件が無い。ここでは
「描画結果が生成先 3 つへそのまま伝わること」を確かめる。

Run with: ``uv run --with pytest --no-project pytest test/agents/ -q``
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "agents"))

import generate as gen  # noqa: E402
from agents_common import load_common, render_common  # noqa: E402

COMMON = load_common()
CLAUDE_SCRIPT = ROOT / "home/.chezmoiscripts/400_unix/run_onchange_after_410_claude_mcp.sh.tmpl"
CLAUDE_WINDOWS_SCRIPT = (
    ROOT / "home/.chezmoiscripts/300_windows/run_onchange_after_346_claude_mcp.ps1.tmpl"
)
CODEX_CONFIG = ROOT / "home/dot_codex/modify_config.toml"
COPILOT_MODIFIER = ROOT / "home/dot_copilot/modify_mcp-config.json.py.tmpl"
TEMPLATE = ROOT / "home/dot_config/agents/common.toml.tmpl"
# applejxd では除外されるサーバがあるので、両方のユーザで確かめる
USERS = ["applejxd", "tester"]

HTTP = {"id": "x", "transport": "http", "url": "https://example.com/mcp"}
STDIO = {"id": "x", "transport": "stdio", "command": "uvx", "args": ["demo"]}


def render(path: Path, username: str | None = None, stdin: str | None = None) -> str:
    """テンプレートを描画する。

    ``username`` を渡すと ``.chezmoi.username`` を差し替える。
    ``stdin`` を渡すと modify-template の既存ファイル内容として扱う。
    """
    chezmoi = shutil.which("chezmoi")
    if chezmoi is None:
        pytest.skip("chezmoi is not installed")
    template = path.read_text(encoding="utf-8")
    if username is not None:
        context = {
            "chezmoi": {
                "username": username,
                "homeDir": "/test-home",
                "stdin": stdin or "",
            }
        }
        template = (
            f"{{{{ with {json.dumps(json.dumps(context))} | fromJson }}}}\n"
            f"{template}\n{{{{ end }}}}"
        )
        stdin = None

    command = [chezmoi, "--source", str(ROOT), "execute-template"]
    if stdin is None:
        command_input = template
    else:
        command += ["--with-stdin", template]
        command_input = stdin
    result = subprocess.run(
        command, input=command_input, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def servers_for(username):
    return gen.mcp_servers(load_common(username))


# ---------------------------------------------------------------------------
# common.toml 側の健全性
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("username", USERS)
def test_rendered_common_is_valid_toml(username):
    """テンプレート化で check-toml が効かなくなる分をここで担保する。"""
    rendered = tomllib.loads(render_common(username))
    assert rendered["mcp"], "[[mcp]] が無い"
    assert rendered["bash"]["deny"], "描画で他の節が壊れていない"


def test_common_declares_mcp_servers():
    for server in COMMON["mcp"]:
        assert server["purpose"], f"{server['id']}: purpose が空"
        allowed = gen.MCP_COMMON_KEYS | gen.MCP_TRANSPORT_KEYS[server["transport"]]
        assert set(server) <= allowed


def test_declared_servers_pass_validation():
    assert [name for name, _ in gen.mcp_servers(COMMON)] == [s["id"] for s in COMMON["mcp"]]


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
    ],
)
def test_broken_declaration_stops_generation(server):
    """未対応・壊れた宣言は、黙って書き出さず apply を止める。"""
    with pytest.raises(ValueError):
        gen.mcp_servers({"mcp": [server]})


def test_duplicate_id_stops_generation():
    with pytest.raises(ValueError):
        gen.mcp_servers({"mcp": [HTTP, dict(HTTP)]})


# ---------------------------------------------------------------------------
# ユーザによる出し分け (common.toml のテンプレート側)
# ---------------------------------------------------------------------------

def test_personal_only_server_is_filtered_in_the_source():
    personal = {name for name, _ in servers_for("applejxd")}
    other = {name for name, _ in servers_for("tester")}

    assert personal < other, "applejxd だけ減る想定"
    assert "ddgs" in other - personal


@pytest.mark.parametrize("username", ["applejxd", "APPLEJXD", "CORP\\applejxd"])
def test_exclusion_covers_case_and_domain_forms(username):
    assert {name for name, _ in servers_for(username)} == {
        name for name, _ in servers_for("applejxd")
    }


# ---------------------------------------------------------------------------
# Copilot 生成 (~/.copilot/mcp-config.json)
# ---------------------------------------------------------------------------

def copilot_entry(server):
    if server["transport"] == "http":
        return {"type": "http", "url": server["url"], "headers": {}, "tools": ["*"]}
    # Copilot は stdio を "local" と呼ぶ (実測: `copilot mcp add` の出力)
    return {
        "type": "local",
        "command": server["command"],
        "args": server["args"],
        "tools": ["*"],
    }


@pytest.mark.parametrize("username", USERS)
def test_copilot_mcp_is_generated_from_common(username):
    common = load_common(username)
    merged = gen.merge_copilot_mcp({}, common)
    assert merged["mcpServers"] == {
        name: copilot_entry(server) for name, server in gen.mcp_servers(common)
    }


def test_copilot_mcp_covers_stdio():
    merged = gen.merge_copilot_mcp({}, load_common("tester"))
    assert any(entry["type"] == "local" for entry in merged["mcpServers"].values())


def test_copilot_mcp_keeps_servers_and_fields_it_does_not_own():
    name = COMMON["mcp"][0]["id"]
    existing = {
        "mcpServers": {
            # CLI 側で足したサーバは消さない
            "added-by-cli": {"type": "http", "url": "https://example.com/mcp"},
            # 同じサーバでも headers (秘密) と tools (公開範囲) は触らない
            name: {
                "type": "http",
                "url": "https://stale.example.com/mcp",
                "headers": {"Authorization": "${EXAMPLE_TOKEN}"},
                "tools": ["search"],
            },
        },
        "unmanaged": True,
    }
    before = copy.deepcopy(existing)
    merged = gen.merge_copilot_mcp(existing, COMMON)

    assert merged["unmanaged"] is True
    assert merged["mcpServers"]["added-by-cli"] == before["mcpServers"]["added-by-cli"]
    kept = merged["mcpServers"][name]
    assert kept["headers"] == {"Authorization": "${EXAMPLE_TOKEN}"}
    assert kept["tools"] == ["search"]
    # url は common.toml が正本なので更新する
    assert kept["url"] == COMMON["mcp"][0]["url"]
    assert existing == before
    assert gen.merge_copilot_mcp(merged, COMMON) == merged


def test_copilot_mcp_drops_keys_of_the_previous_transport():
    """http から stdio へ変えたとき、url と headers を残さない。"""
    existing = {
        "mcpServers": {
            "x": {"type": "http", "url": "https://old.example.com/mcp", "headers": {}}
        }
    }
    merged = gen.merge_copilot_mcp(existing, {"mcp": [STDIO]})
    assert merged["mcpServers"]["x"] == copilot_entry(STDIO)


def test_copilot_mcp_target_is_registered():
    assert gen.TARGETS["copilot-mcp"] is gen.merge_copilot_mcp
    assert '"target" "copilot-mcp"' in COPILOT_MODIFIER.read_text(encoding="utf-8")
    assert not (ROOT / "home/dot_copilot/mcp-config.json").exists()


# ---------------------------------------------------------------------------
# Codex 生成 (~/.codex/config.toml の mcp_servers)
# ---------------------------------------------------------------------------

def codex_entry(server):
    if server["transport"] == "http":
        return {"enabled": True, "url": server["url"]}
    return {"enabled": True, "command": server["command"], "args": server["args"]}


@pytest.mark.parametrize("username", USERS)
def test_codex_config_renders_the_servers_for_this_user(username):
    rendered = tomllib.loads(render(CODEX_CONFIG, username=username))
    assert rendered["mcp_servers"] == {
        name: codex_entry(server) for name, server in servers_for(username)
    }
    # 既存の手書き設定を壊していないこと
    assert rendered["approval_policy"] == "untrusted"
    assert rendered["sandbox_mode"] == "read-only"


def test_codex_config_keeps_the_users_own_settings():
    user_block = '[profiles.mine]\nmodel = "gpt-5"\n'
    existing = f"# chezmoi-managed:start\nstale = true\n# chezmoi-managed:end\n\n{user_block}"
    rendered = render(CODEX_CONFIG, username="tester", stdin=existing)

    assert user_block in rendered
    assert "stale = true" not in rendered
    assert tomllib.loads(rendered)["profiles"]["mine"] == {"model": "gpt-5"}


# ---------------------------------------------------------------------------
# Claude 登録スクリプト (~/.claude.json は管理外なので CLI 経由)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("username", USERS)
def test_claude_script_embeds_only_this_users_servers(username):
    rendered = render(CLAUDE_SCRIPT, username=username)
    assert "mcp add-json -s user" in rendered

    embedded = json.loads(rendered.split("json.loads(r'''", 1)[1].split("''')", 1)[0])
    assert [server["id"] for server in embedded] == [
        name for name, _ in servers_for(username)
    ]


def test_windows_claude_script_covers_the_same_servers():
    """Windows の Claude にも登録する (mise は非 applejxd へ claude を入れる)。"""
    source = CLAUDE_WINDOWS_SCRIPT.read_bytes()
    # WinPS 5.1 は BOM が無いと CP932 として読む
    assert source.startswith(b"\xef\xbb\xbf")

    rendered = render(CLAUDE_WINDOWS_SCRIPT, username="tester")
    assert "mcp add-json -s user" in rendered
    embedded = json.loads(rendered.split("@'", 1)[1].split("'@", 1)[0])
    assert [server["id"] for server in embedded] == [
        name for name, _ in servers_for("tester")
    ]
    # 自動変数 $args と衝突する名前を使っていないこと
    assert "$args" not in rendered
    assert "$serverArgs" in rendered


def test_windows_claude_script_is_skipped_without_claude():
    """applejxd の Windows には claude を入れないので、中身を出さない。

    BOM だけは残る (Windows PowerShell 5.1 対策で先頭に置いているため)。
    空のスクリプトを実行しても何も起きない。
    """
    rendered = render(CLAUDE_WINDOWS_SCRIPT, username="applejxd")
    assert rendered.replace("\ufeff", "").strip() == ""


# ---------------------------------------------------------------------------
# 単一ソース性
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [CLAUDE_SCRIPT, CODEX_CONFIG, COPILOT_MODIFIER])
def test_cli_sources_do_not_hardcode_servers(path):
    """各 CLI 側のソースに定義を書かない (書くと 3 つが静かに食い違う)。"""
    source = path.read_text(encoding="utf-8")
    for server in load_common("tester")["mcp"]:
        for value in (server.get("url"), server.get("command"), server["id"]):
            assert value is None or value not in source, f"{path.name} が定義を直書き"
    assert 'includeTemplate "dot_config/agents/common.toml.tmpl"' in source


def test_cli_sources_do_not_filter_by_user():
    """出し分けは common.toml 側だけ。生成側に規則を複製しない。"""
    sources = (CLAUDE_SCRIPT, CODEX_CONFIG, COPILOT_MODIFIER, ROOT / "scripts/agents/generate.py")
    for path in sources:
        source = path.read_text(encoding="utf-8")
        assert "exclude_users" not in source
        assert "applejxd" not in source, f"{path.name} にユーザ名が書かれている"
    assert "applejxd" in TEMPLATE.read_text(encoding="utf-8")


def test_codex_stops_when_an_unmanaged_table_would_collide():
    """管理ブロック外の同名 MCP を放置すると TOML が重複宣言になる。"""
    conflict = (
        "# chezmoi-managed:start\nstale = true\n# chezmoi-managed:end\n\n"
        '[mcp_servers.ddgs]\ncommand = "old"\n'
    )
    with pytest.raises(AssertionError, match=r"mcp_servers\.ddgs"):
        render(CODEX_CONFIG, username="tester", stdin=conflict)


def test_rendered_policy_is_validated_by_a_hook():
    """check-toml を外した分を機械で埋めていること。"""
    config = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert "scripts/agents/validate_common.py" in config
    assert (ROOT / "scripts/agents/validate_common.py").is_file()
