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
import re
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

def test_default_is_ask_and_the_catch_all_comes_first():
    """未掲載のコマンドを無条件許可にしない。

    OpenCode に classifier は無いので、``[bash]`` の「未掲載は auto / assisted
    へ委ねる」設計がそのままだと無条件実行になる。``*`` は最も一般的な規則
    なので **先頭**に無ければならない。後ろにあると全部を ask で塗り潰す。
    """
    shell = [r for r in generated()["permissions"] if r["action"] == "shell"]
    assert shell[0] == {"action": "shell", "resource": "*", "effect": "ask"}
    assert [r["resource"] for r in shell[1:]].count("*") == 0


def test_effects_are_ordered_allow_then_ask_then_deny():
    """OpenCode は **最後に一致した規則** が勝つ。

    Claude の deny > ask > allow と逆なので、並び順が優先順位そのものになる。
    崩れると ``git reset --hard`` の deny を ``git reset`` の ask が上書きする。

    shell だけは先頭の ``*`` (既定 ask) を除いてから見る。これは最も一般的な
    規則で、allow より前に来るのが正しい。
    """
    order = {"allow": 0, "ask": 1, "deny": 2}
    for action in ("shell", "read", "edit"):
        found = [r for r in generated()["permissions"] if r["action"] == action]
        if action == "shell":
            found = found[1:]
        seen = [order[r["effect"]] for r in found]
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

def test_shell_allow_comes_from_the_opencode_section():
    """allow だけ ``[opencode.shell]`` から取る (``[bash]`` と共有しない)。

    ``[bash] allow`` は Claude / Copilot と共有しており、未掲載を classifier
    へ委ねる前提で組まれている。OpenCode は既定 ask なので前提が違う。
    """
    expected = [f"{cmd} *" for cmd in COMMON["opencode"]["shell"]["allow"]]
    assert rules("shell", "allow") == expected


def test_shell_ask_and_deny_still_come_from_bash():
    for effect in ("ask", "deny"):
        expected = [f"{cmd} *" for cmd in COMMON["bash"][effect]]
        # 先頭の catch-all (既定 ask) は [bash] 由来ではないので外す
        assert [r for r in rules("shell", effect) if r != "*"] == expected


# 実行するコードを呼び出し側が決められるもの。allow に載ると、そのコマンドが
# 無確認で任意コード実行の入口になる。
# - find     -exec / -delete / -fprintf
# - gcc/g++  -B や specs ファイルで任意プログラムを起動できる
# - cmake    CMakeLists.txt がそのまま実行される
# - uv sync  依存のビルドフックが走る
# - mise run タスク定義が走る
ARBITRARY_CODE_EXECUTION = ("find", "gcc", "g++", "cmake", "uv sync", "mise run")


@pytest.mark.parametrize("command", ARBITRARY_CODE_EXECUTION)
def test_allow_has_no_arbitrary_code_execution(command: str):
    """段階 1 の受入条件。

    これらは実測で ``find`` 以外のヒットが 0 件だった。確認を増やさずに
    落とせるので、allow に戻す理由があるなら測り直してからにする。
    """
    for resource in rules("shell", "allow"):
        assert not resource.startswith(command), f"{resource} は任意コード実行を含む"


def test_bypass_agent_is_declared():
    """全ツールを無確認で実行するカスタムエージェント。

    ``permission = "allow"`` は OpenCode が
    ``{action:"*", resource:"*", effect:"allow"}`` へ展開する (実測)。
    V1 の ``mode`` は非推奨なので ``agent`` で出す。
    """
    agent = generated()["agent"]["bypass"]
    assert agent["permission"] == "allow"
    assert agent["description"]


def test_agents_not_declared_in_common_are_kept():
    """``/agents`` などが同じファイルへ書くので、宣言した名前だけ差し替える。"""
    existing = {"agent": {"mine": {"description": "手で足したもの"}}}
    merged = gen.merge_opencode_config(existing, COMMON)["agent"]
    assert merged["mine"] == {"description": "手で足したもの"}
    assert "bypass" in merged


def test_bypass_is_the_only_agent_from_common():
    """権限を緩めるエージェントが黙って増えないようにする。"""
    assert set(generated()["agent"]) == {"bypass"}


# --- 誘導 plugin ---------------------------------------------------------
# 明示指定は絶対パスのディレクトリでないと解決されない。相対でも ``~`` でも
# 単一ファイルでも、OpenCode は**黙って無視する**。
# see docs/research/opencode/plugin/loading.md


def test_guide_plugin_is_registered_as_absolute_directory():
    entries = generated()["plugins"]
    assert gen.opencode_guide_plugin_path() in entries
    for entry in entries:
        assert not entry.startswith("~"), f"{entry}: ~ は展開されない"


def test_guide_plugin_directory_name_is_not_auto_discovered():
    """``plugin`` / ``plugins`` は設定ディレクトリ直下で自動探索される。

    その名前にすると明示指定と合わせて二重にロードされる。
    """
    assert Path(gen.OPENCODE_GUIDE_PLUGIN).name not in {"plugin", "plugins"}


def test_guide_plugin_files_exist():
    source = ROOT / "home/dot_config/opencode/guide-plugin"
    assert (source / "index.js").is_file()
    assert (source / "modify_rules.json.py.tmpl").is_file()


def test_plugins_not_declared_in_common_are_kept():
    existing = {"plugins": ["opencode-acme-plugin"]}
    merged = gen.merge_opencode_config(existing, COMMON)["plugins"]
    assert merged[0] == "opencode-acme-plugin"
    assert gen.opencode_guide_plugin_path() in merged


def test_guide_plugin_is_not_registered_twice():
    existing = {"plugins": [gen.opencode_guide_plugin_path()]}
    merged = gen.merge_opencode_config(existing, COMMON)["plugins"]
    assert merged.count(gen.opencode_guide_plugin_path()) == 1


def test_guide_rules_are_generated():
    rules_json = gen.build_opencode_guide({}, COMMON)["guide"]
    assert rules_json, "誘導規則が 1 件も無い"
    for rule in rules_json:
        assert set(rule) == {"pattern", "message"}
        re.compile(rule["pattern"])


def test_cd_is_guided_to_workdir():
    """最も件数の多い誘導。実機で deny とメッセージの到達を確認済み。

    区切りの後ろの ``cd`` も見る。先頭だけを見る形では実履歴で 15 件
    取りこぼした。
    see docs/change/0002-opencode-ask-by-default.md
    """
    rules_json = gen.build_opencode_guide({}, COMMON)["guide"]
    for command in ("cd sub && cat x", 'ls -la; echo "---"; cd /tmp && ls'):
        hit = [r for r in rules_json if re.search(r["pattern"], command)]
        assert len(hit) == 1, command
        assert "workdir" in hit[0]["message"]


def test_separator_echo_is_not_guided():
    """区切り用途の ``echo`` は誘導しない。

    確認が 1 件も減らないうえ、deny は 1 往復を捨てさせるので差し引き
    マイナスだった（実履歴 466 呼び出しで実測）。
    see docs/change/0002-opencode-ask-by-default.md 「誘導（優先度を下げる）」
    """
    rules_json = gen.build_opencode_guide({}, COMMON)["guide"]
    assert not [r for r in rules_json if re.search(r["pattern"], 'echo "--- env ---"')]


@pytest.mark.parametrize("broken", [{"pattern": "x"}, {"message": "y"}, {}])
def test_guide_rule_without_pattern_or_message_is_rejected(broken: dict):
    common = copy.deepcopy(COMMON)
    common["opencode"]["shell"]["guide"] = [broken]
    with pytest.raises(SystemExit):
        gen.build_opencode_guide({}, common)


def test_guide_target_is_fully_generated():
    """壊れた rules.json でも apply でやり直せるようにする。"""
    assert "opencode-guide" in gen.TARGETS
    assert "opencode-guide" in gen.FULL_GENERATION_TARGETS


def test_allow_is_not_widened_silently():
    """allow が増えたら気付けるようにする。

    ここを更新するときは docs/change/0002-opencode-ask-by-default.md の
    「段階 1 の詳細」と、その根拠になった実測も一緒に見直すこと。
    """
    assert rules("shell", "allow") == [
        "git log *",
        "wc *",
        "grep -n *",
        "uv pip list *",
        "docker ps *",
    ]


# `.git/config` へ書けると diff.<name>.command / core.fsmonitor に任意コマンドを
# 仕込めて、git diff / git status が実行手段になる (実測)。
# see docs/research/opencode/permission/allow-list-audit.md
@pytest.mark.parametrize(
    "resource", ["*/.git/config", "*/.git/hooks/*", "~/.gitconfig"]
)
def test_git_config_is_write_denied(resource: str):
    assert resource in rules("edit", "deny")


# プロジェクト側の設定に書いた permission はグローバルの deny に勝つ (実測)。
# 書けるとエージェントが自分で権限を広げられる。
# see docs/research/opencode/permission/gaps.md
@pytest.mark.parametrize(
    "resource", ["*/.opencode/opencode.json", "*/.opencode/opencode.jsonc"]
)
def test_project_config_is_write_denied(resource: str):
    assert resource in rules("edit", "deny")


@pytest.mark.parametrize("command", ["git diff", "git status"])
def test_git_commands_that_execute_are_not_allowed(command: str):
    """`git diff` は外部 diff、`git status` は fsmonitor で任意コマンドを起動する。

    どちらも実測済み。`.git/config` を write deny にしても、shell の
    リダイレクトはその deny を通らないので、allow に戻してはいけない。
    """
    for resource in rules("shell", "allow"):
        assert not resource.startswith(command), f"{resource} は任意コード実行を含む"


def test_bash_allow_is_untouched_so_other_clis_do_not_move():
    """``[bash] allow`` は Claude / Copilot 用に残す (段階 1 の非目的)。

    ここが縮むと他 CLI の確認回数が変わり、OpenCode 側の効果を切り分け
    られなくなる。撤退も ``[opencode.shell]`` の削除だけでは済まなくなる。
    """
    bash_allow = COMMON["bash"]["allow"]
    for command in ARBITRARY_CODE_EXECUTION:
        assert any(cmd.startswith(command) for cmd in bash_allow), (
            f"{command} が [bash] allow から消えている。"
            "OpenCode 側だけを絞るのが段階 1 の前提"
        )


def test_dropping_them_from_opencode_does_not_reach_copilot():
    """Copilot の commandIdentifiers は ``[bash] allow`` 由来のまま。

    段階 1 の受入条件「他 CLI の生成物に diff が出ない」の機械的な固定。
    """
    approvals = gen.build_copilot_locations(COMMON)["locations"]
    names = {
        command
        for location in approvals.values()
        for approval in location["tool_approvals"]
        if approval.get("kind") == "commands"
        for command in approval["commandIdentifiers"]
    }
    assert {"find", "gcc", "cmake"} <= names
    # OpenCode 専用の allow は Copilot へ漏れない
    assert "docker" in names or "docker ps" not in names


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
