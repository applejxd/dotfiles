"""OpenCode の global config (``~/.config/opencode/opencode.json``) 生成の test.

OpenCode には hook 機構も sandbox も無く、3 層のうち permission 層しか使えない。
つまり ``common.toml`` の意図が **permission リストだけで** 表現できているか、
そして OpenCode 固有の照合規則 (後勝ち・``**`` 記法が無い) に合わせた変換が
できているかが、そのまま防御の有無になる。

Run with: ``uv run --with pytest --no-project pytest test/agents/ -q``
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "agents"))

import generate as gen  # noqa: E402
from agents_common import load_common  # noqa: E402

COMMON = load_common()
MODIFIER = ROOT / "home/dot_config/opencode/modify_opencode.json.py.tmpl"
INSTRUCTIONS = ROOT / "home/dot_config/opencode/AGENTS.md.tmpl"
SHARED_INSTRUCTIONS = ROOT / "home/.chezmoitemplates/agent-instructions.md"


def generated(common: dict | None = None) -> dict:
    return gen.merge_opencode_config({}, common if common is not None else COMMON)


def rules(action: str, effect: str, config: dict | None = None) -> list[str]:
    config = config or generated()
    return [
        rule["resource"]
        for rule in config["permissions"]
        if rule["action"] == action and rule["effect"] == effect
    ]


# ---------------------------------------------------------------------------
# 配線 (chezmoi 側)
# ---------------------------------------------------------------------------

def test_target_is_registered_and_wired():
    assert gen.TARGETS["opencode-config"] is gen.merge_opencode_config
    source = MODIFIER.read_text(encoding="utf-8")
    assert '"target" "opencode-config"' in source
    assert 'includeTemplate "dot_config/agents/common.toml.tmpl"' in source
    # 生成物を source state に置かない (置くと単一ソースが二重化する)
    assert not (ROOT / "home/dot_config/opencode/opencode.json").exists()


def test_global_instructions_reuse_the_shared_template():
    """Claude / Codex / Copilot と同じ本文を配る (指示を CLI ごとに写さない)。

    OpenCode V2 が読む global 指示は ``~/.config/opencode/AGENTS.md`` だけで、
    ``CLAUDE.md`` へのフォールバックは無い (公式 Instructions ガイド)。
    """
    source = INSTRUCTIONS.read_text(encoding="utf-8")
    assert 'includeTemplate "agent-instructions.md"' in source
    # 本文をここに写していないこと
    assert "## 検証" not in source
    assert SHARED_INSTRUCTIONS.is_file()


# ---------------------------------------------------------------------------
# 形 (公式スキーマ)
# ---------------------------------------------------------------------------

def test_schema_and_update_policy():
    config = generated()
    assert config["$schema"] == gen.OPENCODE_SCHEMA
    assert next(iter(config)) == "$schema", "エディタ補完のため先頭に置く"
    # CLI 本体は公式インストーラーで入れるので自動更新はしない
    assert config["update"] == "disable"


def test_rules_use_only_the_three_required_fields():
    for rule in generated()["permissions"]:
        assert set(rule) == {"action", "resource", "effect"}
        assert rule["effect"] in {"allow", "deny", "ask"}


def test_unmanaged_keys_survive():
    existing = {"model": "anthropic/claude-sonnet-4-5", "theme": "custom"}
    before = copy.deepcopy(existing)
    merged = gen.merge_opencode_config(existing, COMMON)

    assert merged["model"] == before["model"]
    assert merged["theme"] == before["theme"]
    assert existing == before, "入力を破壊しない"
    assert gen.merge_opencode_config(merged, COMMON) == merged


# ---------------------------------------------------------------------------
# 後勝ち (OpenCode 固有の照合規則)
# ---------------------------------------------------------------------------

def test_effects_are_ordered_allow_then_ask_then_deny():
    """OpenCode は **最後に一致した規則** が勝つ。

    Claude の deny > ask > allow と逆なので、並び順が優先順位そのものになる。
    崩れると ``git reset --hard`` の deny を ``git reset`` の ask が上書きする。
    """
    order = {"allow": 0, "ask": 1, "deny": 2}
    for action in ("shell", "read", "edit"):
        seen = [order[r["effect"]] for r in generated()["permissions"] if r["action"] == action]
        assert seen == sorted(seen), f"{action} の effect 並びが崩れている"


@pytest.mark.parametrize(
    ("general", "specific"),
    [("git reset *", "git reset --hard *"), ("git config *", "git config --global *")],
)
def test_specific_deny_comes_after_the_general_ask(general: str, specific: str):
    resources = [rule["resource"] for rule in generated()["permissions"]]
    assert resources.index(specific) > resources.index(general)


# ---------------------------------------------------------------------------
# shell
# ---------------------------------------------------------------------------

def test_shell_rules_cover_every_declared_command():
    for effect in ("allow", "ask", "deny"):
        expected = [f"{cmd} *" for cmd in COMMON["bash"][effect]]
        assert rules("shell", effect) == expected


def test_hook_owned_ask_is_still_emitted():
    """``ask_hook_owned`` は OpenCode では除外しない。

    Claude では静的 ask を出すと hook の exemption が無効化されるので外すが、
    OpenCode に hook は無い。除外すると委譲先が無いまま素通りになる。
    """
    hook_owned = COMMON["bash"]["ask_hook_owned"]
    assert hook_owned, "前提: hook に委ねる ask がある"
    for cmd in hook_owned:
        assert f"{cmd} *" in rules("shell", "ask")
    # Claude 側では従来どおり外れていること (非対称が意図であることの固定)
    assert f"Bash({hook_owned[0]}:*)" not in gen.build_claude_permissions(COMMON)["ask"]


# ---------------------------------------------------------------------------
# glob の記法差
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("glob", "expected"),
    [
        # `**/` は「0 段以上」なので、ルート直下と入れ子の 2 本に割る
        ("**/.netrc", [".netrc", "*/.netrc"]),
        ("**/.ssh/**", [".ssh/*", "*/.ssh/*"]),
        ("**/secrets/**", ["secrets/*", "*/secrets/*"]),
        ("**/id_rsa*", ["id_rsa*", "*/id_rsa*"]),
        # `*` は `/` も跨ぐので、`*` 始まりなら入れ子側は要らない
        ("**/*.pem", ["*.pem"]),
        ("**/*secret*", ["*secret*"]),
        # `**` を含まないものはそのまま
        (".env", [".env"]),
        (".env.*", [".env.*"]),
        ("~/.claude.json", ["~/.claude.json"]),
    ],
)
def test_glob_conversion(glob: str, expected: list[str]):
    assert gen.opencode_path_patterns(glob) == expected


def test_no_double_star_reaches_the_generated_rules():
    """``**`` を渡すと ``*`` 2 つとして読まれ、意図より広く当たる。"""
    for rule in generated()["permissions"]:
        assert "**" not in rule["resource"], rule


@pytest.mark.parametrize("key", ["claude_read_deny_globs", "claude_write_deny_globs"])
def test_every_file_deny_glob_is_converted(key: str):
    action = "read" if "read" in key else "edit"
    emitted = set(rules(action, "deny"))
    for glob in COMMON["file"][key]:
        assert set(gen.opencode_path_patterns(glob)) <= emitted, glob


def test_allow_side_file_globs_are_not_emitted():
    """OpenCode は allow が既定なので、allow の写しを増やさない。"""
    assert rules("read", "allow") == []
    assert rules("edit", "allow") == []


# ---------------------------------------------------------------------------
# 整形 (formatter)
# ---------------------------------------------------------------------------

def test_formatter_is_generated_from_common():
    """PostToolUse hook (format-file.sh / markdownlint.sh) の代替。"""
    formatter = generated()["formatter"]
    assert formatter == COMMON["opencode"]["formatter"]


def test_markdown_is_covered_because_it_has_no_builtin():
    """組み込みに markdownlint は無いので、ここが唯一の .md 整形経路。"""
    markdown = generated()["formatter"]["markdownlint"]
    assert markdown["command"][0] == "markdownlint-cli2"
    assert "$FILE" in markdown["command"]
    assert set(markdown["extensions"]) == {".md", ".markdown"}


@pytest.mark.parametrize("name", ["ruff", "clang-format", "prettier", "shfmt"])
def test_builtin_covered_formatters_are_not_redeclared(name: str):
    """組み込みがあるものを書くと、更新が二重管理になる。

    テーブルを 1 つでも書けば組み込みは全部有効になる (公式 Formatters
    ガイド) ので、``format-file.sh`` が呼んでいた ruff / clang-format /
    prettier は宣言せずに済む。
    """
    assert name in gen.OPENCODE_BUILTIN_FORMATTERS
    assert name not in COMMON["opencode"]["formatter"]


def test_formatter_is_omitted_when_common_has_none():
    """キーが無ければ既存値に触らない (auto_update と同じ約束)。"""
    assert "formatter" not in gen.merge_opencode_config({}, {})
    kept = gen.merge_opencode_config({"formatter": {"mine": {}}}, {})
    assert kept["formatter"] == {"mine": {}}


@pytest.mark.parametrize(
    "entry",
    [
        # 組み込みに無い名前は command と extensions の両方が要る
        {"command": ["x", "$FILE"]},
        {"extensions": [".x"]},
        {},
        # 綴り間違い
        {"command": ["x"], "extensions": [".x"], "exts": [".y"]},
        # argv 配列でないもの (シェル文字列と取り違えた形)
        {"command": "x --fix $FILE", "extensions": [".x"]},
        {"command": [], "extensions": [".x"]},
        {"command": ["x", 1], "extensions": [".x"]},
        # 先頭のドットが無い拡張子は一致しない
        {"command": ["x"], "extensions": ["md"]},
        {"command": ["x"], "extensions": "md"},
    ],
)
def test_broken_formatter_declaration_stops_generation(entry: dict):
    """整形されないだけで表に出ないので、apply を止める。"""
    with pytest.raises(ValueError):
        gen.build_opencode_formatter({"opencode": {"formatter": {"custom": entry}}})


def test_builtin_entry_may_omit_command_and_extensions():
    """組み込みの上書きは省略した値を継承する。"""
    common = {"opencode": {"formatter": {"prettier": {"extensions": [".ts"]}}}}
    assert gen.build_opencode_formatter(common) == {"prettier": {"extensions": [".ts"]}}


def test_disabling_a_custom_entry_needs_nothing_else():
    common = {"opencode": {"formatter": {"custom": {"disabled": True}}}}
    assert gen.build_opencode_formatter(common) == {"custom": {"disabled": True}}


# ---------------------------------------------------------------------------
# 自分の設定を書き換えられないこと
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "path", ["~/.config/opencode/opencode.json", "~/.config/opencode/service.json"]
)
def test_opencode_cannot_rewrite_its_own_runtime_config(path: str):
    """permission の正本を自分で緩められると、他の層が無い分そのまま穴になる。"""
    assert path in rules("edit", "deny")


def test_service_credentials_are_not_readable():
    """service.json には background service の password が平文で入る。"""
    assert "~/.config/opencode/service.json" in rules("read", "deny")
    assert "~/.config/opencode/service.json" in COMMON["sandbox"]["deny"]


# ---------------------------------------------------------------------------
# OpenCode へ渡さないもの (意図的な非対称)
# ---------------------------------------------------------------------------

def test_web_domains_are_not_translated_into_webfetch_rules():
    """ドメイン許可は OpenCode の資源表現 (URL) では正しく書けない。

    ``*`` が ``/`` を跨ぐため ``*://*.example.com/*`` は
    ``https://evil.test/x.example.com/y`` にも当たる。過大な allowlist を
    出すくらいなら出さない、という判断を固定する。
    """
    assert COMMON["web"]["allow_domains"], "前提: 許可ドメインがある"
    assert [r for r in generated()["permissions"] if r["action"] == "webfetch"] == []


def test_claude_mcp_deny_names_are_not_copied():
    """``mcp__<server>__<tool>`` は OpenCode の ``<server>_<tool>`` と別体系。"""
    for name in COMMON["claude"]["mcp_deny"]:
        assert name not in json.dumps(generated(), ensure_ascii=False)


# ---------------------------------------------------------------------------
# MCP
# ---------------------------------------------------------------------------

def opencode_entry(server: dict) -> dict:
    if server["transport"] == "http":
        return {"type": "remote", "url": server["url"]}
    return {"type": "local", "command": [server["command"], *server["args"]]}


@pytest.mark.parametrize("username", ["applejxd", "tester"])
def test_mcp_servers_come_from_common(username: str):
    common = load_common(username)
    merged = gen.merge_opencode_config({}, common)
    assert merged["mcp"]["servers"] == {
        name: opencode_entry(server) for name, server in gen.mcp_servers(common)
    }


def test_mcp_covers_stdio():
    servers = gen.merge_opencode_config({}, load_common("tester"))["mcp"]["servers"]
    assert any(entry["type"] == "local" for entry in servers.values())


def test_mcp_keeps_servers_and_secret_fields_it_does_not_own():
    name = COMMON["mcp"][0]["id"]
    existing = {
        "mcp": {
            "timeout": {"startup": 45000},
            "servers": {
                "added-by-cli": {"type": "remote", "url": "https://example.com/mcp"},
                name: {
                    "type": "remote",
                    "url": "https://stale.example.com/mcp",
                    "headers": {"Authorization": "Bearer {env:EXAMPLE_TOKEN}"},
                },
            },
        }
    }
    merged = gen.merge_opencode_config(existing, COMMON)
    servers = merged["mcp"]["servers"]

    assert merged["mcp"]["timeout"] == {"startup": 45000}
    assert servers["added-by-cli"] == existing["mcp"]["servers"]["added-by-cli"]
    assert servers[name]["headers"] == {"Authorization": "Bearer {env:EXAMPLE_TOKEN}"}
    # url は common.toml が正本
    assert servers[name]["url"] == COMMON["mcp"][0]["url"]


def test_mcp_drops_keys_of_the_previous_transport():
    existing = {"mcp": {"servers": {"x": {"type": "remote", "url": "https://old.test/mcp"}}}}
    stdio = {"id": "x", "transport": "stdio", "command": "uvx", "args": ["demo"]}
    merged = gen.merge_opencode_config(existing, {"mcp": [stdio]})
    assert merged["mcp"]["servers"]["x"] == opencode_entry(stdio)


def test_source_does_not_hardcode_servers_or_users():
    source = MODIFIER.read_text(encoding="utf-8")
    for server in load_common("tester")["mcp"]:
        for value in (server.get("url"), server.get("command"), server["id"]):
            assert value is None or value not in source
    assert "applejxd" not in source
