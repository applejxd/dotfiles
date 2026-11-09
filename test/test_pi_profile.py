"""pi のプロファイル (custom / stock) の描画を検証する。

判定 (pi-profile)・除外 (.chezmoiignore.tmpl)・撤去 (.chezmoiremove)・
settings.json の変換・AGENTS.md の中身を、chezmoi execute-template で描画して確かめる。
実機の chezmoi apply は行わない。
see docs/spec/agent-config-generation.md#pi-のプロファイルcustom-と-stock
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOME_SRC = ROOT / "home"
STOCK_ONLY_IGNORES = (
    ".pi/agent/prompts",
    ".pi/agent/models.json",
    ".config/pi",
    ".config/pi/**",
)
STOCK_REMOVES = (".pi/agent/prompts", ".pi/agent/models.json", ".config/pi")
PERMISSION_DIR = ".pi/agent/extensions/pi-permission-system"
PLAN_MODE_CONFIG = ".pi/agent/pi-plan-mode.json"
PLAN_MODE_MODIFY = HOME_SRC / "dot_pi" / "agent" / "modify_pi-plan-mode.json.py.tmpl"
NEW_PACKAGES = (
    "npm:pi-background@",
    "npm:@narumitw/pi-plan-mode@",
    "npm:@narumitw/pi-goal@",
    "npm:@narumitw/pi-btw@",
    "npm:pi-show-token-rate@",
    "npm:@ayulab/pi-rewind@",
)
# stock の AGENTS.md に出してはならない自作ハーネスの語
HARNESS_WORDS = ("guarded_", "フルガード", "worktree", "pis", "kcage", "feature-orchestration")


def chezmoi_bin() -> str:
    found = shutil.which("chezmoi")
    if found is None:
        pytest.skip("chezmoi is not installed")
    return found


def render(
    template: str,
    home: Path,
    *,
    profile_env: str | None = None,
    os_name: str = "linux",
    username: str = "tester",
) -> str:
    context = {
        "chezmoi": {
            "os": os_name,
            "username": username,
            "kernel": {"osrelease": "Linux"},
            "homeDir": str(home),
            "workingTree": str(ROOT),
        }
    }
    wrapped = (
        "{{ with " + json.dumps(json.dumps(context)) + " | fromJson }}" + template + "{{ end }}"
    )
    env = dict(os.environ)
    env.pop("CHEZMOI_PI_PROFILE", None)
    if profile_env is not None:
        env["CHEZMOI_PI_PROFILE"] = profile_env
    result = subprocess.run(
        [chezmoi_bin(), "--source", str(ROOT), "execute-template"],
        input=wrapped,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def render_file(name: str, home: Path, **kw) -> str:
    return render((HOME_SRC / name).read_text(encoding="utf-8"), home, **kw)


def profile(home: Path, **kw) -> str:
    return render('{{ includeTemplate "pi-profile" . }}', home, **kw)


def lines(text: str) -> set[str]:
    return {line.strip() for line in text.splitlines()}


def write_profile(home: Path, content: str) -> None:
    path = home / ".config" / "chezmoi" / "pi-profile"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# --- 判定 -------------------------------------------------------------


def test_profile_defaults_to_custom(tmp_path):
    assert profile(tmp_path) == "custom"


def test_profile_from_env(tmp_path):
    assert profile(tmp_path, profile_env="stock") == "stock"


@pytest.mark.parametrize("content", ["stock\n", "  stock  \n\n", "stock"])
def test_profile_from_file(tmp_path, content):
    write_profile(tmp_path, content)
    assert profile(tmp_path) == "stock"


@pytest.mark.parametrize("content", ["", "\n", "Stock", "custom\n", "stock2", "foo"])
def test_profile_invalid_file_is_custom(tmp_path, content):
    write_profile(tmp_path, content)
    assert profile(tmp_path) == "custom"


def test_profile_invalid_env_is_custom(tmp_path):
    assert profile(tmp_path, profile_env="nonsense") == "custom"


def test_profile_env_wins_over_file_only_when_set(tmp_path):
    write_profile(tmp_path, "stock\n")
    # 環境変数が空なら、ファイルを見る
    assert profile(tmp_path, profile_env="") == "stock"


def test_profile_on_windows_without_file_is_custom(tmp_path):
    assert profile(tmp_path, os_name="windows") == "custom"


# --- 除外と撤去 -------------------------------------------------------


def own_extensions() -> list[str]:
    """pi-own-extensions (自作の拡張ディレクトリ名の一覧)。"""
    text = (HOME_SRC / ".chezmoitemplates" / "pi-own-extensions").read_text(encoding="utf-8")
    return [x.strip() for x in text.splitlines() if x.strip() and not x.startswith("#")]


def test_own_extensions_match_source_directories():
    """一覧は dot_pi/agent/extensions/ の直下の自作ディレクトリと一致する (permission-system は package の設定)。"""
    src = HOME_SRC / "dot_pi" / "agent" / "extensions"
    # pi-permission-system / subagent は package の設定 (自作の拡張ではない)
    actual = sorted(
        p.name
        for p in src.iterdir()
        if p.is_dir() and p.name not in ("pi-permission-system", "subagent")
    )
    assert sorted(own_extensions()) == actual
    assert actual, "自作の拡張が 1 つも無い"


def test_custom_ignore_has_no_stock_entries(tmp_path):
    rendered = lines(render_file(".chezmoiignore.tmpl", tmp_path))
    for entry in STOCK_ONLY_IGNORES:
        assert entry not in rendered, entry
    # 自作の拡張は custom では配る (除外しない)
    for name in own_extensions():
        if name != "subagents":  # subagents は Unix の custom でも別の理由で除外
            assert f".pi/agent/extensions/{name}" not in rendered, name


def test_custom_ignore_skips_permission_system_config(tmp_path):
    rendered = lines(render_file(".chezmoiignore.tmpl", tmp_path))
    assert PERMISSION_DIR in rendered
    assert f"{PERMISSION_DIR}/**" in rendered
    assert PLAN_MODE_CONFIG in rendered  # plan mode の設定も stock だけ


def test_stock_ignore_keeps_plan_mode_config(tmp_path):
    rendered = lines(render_file(".chezmoiignore.tmpl", tmp_path, profile_env="stock"))
    assert PLAN_MODE_CONFIG not in rendered


def test_stock_ignore_excludes_own_pi_assets(tmp_path):
    rendered = lines(render_file(".chezmoiignore.tmpl", tmp_path, profile_env="stock"))
    for entry in STOCK_ONLY_IGNORES:
        assert entry in rendered, entry
    # 自作の拡張のディレクトリは、ディレクトリとその配下を除外する
    for name in own_extensions():
        assert f".pi/agent/extensions/{name}" in rendered, name
        assert f".pi/agent/extensions/{name}/**" in rendered, name
    # 拡張ディレクトリを丸ごと除外しない・permission-system の設定は除外しない
    assert ".pi/agent/extensions" not in rendered
    assert ".pi/agent/extensions/**" not in rendered
    assert not any(e.startswith(PERMISSION_DIR) for e in rendered)
    # pi 以外の設定・実行ファイルは除外しない
    for other in (".claude/settings.json", ".local/bin/pis", ".config/opencode", ".codex"):
        assert other not in rendered


def test_custom_remove_is_unchanged(tmp_path):
    rendered = lines(render_file(".chezmoiremove", tmp_path))
    for entry in STOCK_REMOVES:
        assert entry not in rendered, entry
    assert not any(e.startswith(".pi/agent/extensions") for e in rendered)
    # 従来の項目は残る
    assert ".config/agents/critical_deny.py" in rendered


def test_stock_remove_lists_own_pi_assets(tmp_path):
    rendered = lines(render_file(".chezmoiremove", tmp_path, profile_env="stock"))
    for entry in STOCK_REMOVES:
        assert entry in rendered, entry
    # 自作の拡張のディレクトリを 1 つずつ消す。配下のファイルは並べない
    for name in own_extensions():
        assert f".pi/agent/extensions/{name}" in rendered, name
    assert not any(e.startswith(".pi/agent/extensions/") and e.count("/") > 3 for e in rendered)
    # 拡張ディレクトリを丸ごと消さない・permission-system と利用者の拡張は消さない
    assert ".pi/agent/extensions" not in rendered
    assert not any(e.startswith(PERMISSION_DIR) for e in rendered)
    assert ".config/agents/critical_deny.py" in rendered


def test_remove_has_no_stock_target_that_source_still_deploys_in_custom(tmp_path):
    """stock の撤去対象は、stock では除外されている (同名が管理対象に残ると apply が失敗する)。"""
    ignore = lines(render_file(".chezmoiignore.tmpl", tmp_path, profile_env="stock"))
    remove = lines(render_file(".chezmoiremove", tmp_path, profile_env="stock"))
    for entry in (*STOCK_REMOVES, *(f".pi/agent/extensions/{n}" for n in own_extensions())):
        assert entry in ignore and entry in remove, entry


# --- settings.json ----------------------------------------------------


def stock_settings_script(tmp_path: Path) -> Path:
    script = tmp_path / "modify_settings.py"
    script.write_text(
        render_file("dot_pi/agent/modify_settings.json.py.tmpl", tmp_path, profile_env="stock"),
        encoding="utf-8",
    )
    return script


def run_script(script: Path, stdin: str) -> str:
    result = subprocess.run(
        [sys.executable, str(script)],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return result.stdout


def stock_packages(home: Path, username: str = "tester") -> list[str]:
    """描画した pi-stock-packages。tester は会社 PC (is-work)、applejxd は家の機。"""
    text = render(
        '{{ includeTemplate "pi-stock-packages" . }}',
        home,
        profile_env="stock",
        username=username,
    )
    return [x.strip() for x in text.splitlines() if x.strip() and not x.startswith("#")]


CUSTOM_SETTINGS = {
    "theme": "dark",
    "defaultProvider": "p",
    "defaultModel": "m",
    "defaultThinkingLevel": "high",
    "defaultTools": ["read"],
    "hideThinkingBlock": True,
    "extensions": [
        "~/.config/pi/harness",
        "!extensions/**",
        "+extensions/ask/index.ts",
        "+extensions/orca-agent-status.ts",
        "-builtin:codemode",
    ],
    "skills": ["~/.claude/skills", "-~/.agents/skills/orca-cli", "-~/.claude/skills/herdr"],
    "lastChangelogVersion": "0.1",
}


def test_stock_settings_removes_harness_keys_and_sets_packages(tmp_path):
    out = json.loads(run_script(stock_settings_script(tmp_path), json.dumps(CUSTOM_SETTINGS)))
    for key in ("extensions", "skills"):
        assert key not in out, key
    # 自作ハーネスの全置換の defaultTools (["read"]) は、読み取り専用の探索ツールの増分に置き換わる
    assert out["defaultTools"] == ["+grep", "+find", "+ls"]
    # 利用者のキーと pi 自身のキーは残る
    for key in (
        "theme",
        "defaultProvider",
        "defaultModel",
        "defaultThinkingLevel",
        "hideThinkingBlock",
        "lastChangelogVersion",
    ):
        assert out[key] == CUSTOM_SETTINGS[key], key
    assert out["packages"] == stock_packages(tmp_path)


def test_stock_settings_keeps_user_extension_and_is_idempotent(tmp_path):
    script = stock_settings_script(tmp_path)
    src = {**CUSTOM_SETTINGS, "extensions": [*CUSTOM_SETTINGS["extensions"], "~/mine/index.ts"]}
    first = run_script(script, json.dumps(src))
    assert json.loads(first)["extensions"] == ["~/mine/index.ts"]
    assert run_script(script, first) == first


def test_stock_settings_from_empty_input(tmp_path):
    out = json.loads(run_script(stock_settings_script(tmp_path), ""))
    out.pop("subagents")  # agentOverrides は test_pi_subagents_config.py で検査
    out.pop("compaction")  # modelOverrides は test_pi_compaction_config.py で検査
    assert out == {"defaultTools": ["+grep", "+find", "+ls"], "packages": stock_packages(tmp_path)}


def test_stock_settings_keeps_user_incremental_default_tools(tmp_path):
    script = stock_settings_script(tmp_path)
    src = {**CUSTOM_SETTINGS, "defaultTools": ["+grep", "-ls"]}
    first = run_script(script, json.dumps(src))
    assert json.loads(first)["defaultTools"] == ["+grep", "-ls"]  # 利用者の増分指定は保つ
    assert run_script(script, first) == first


def test_stock_settings_leaves_broken_input_alone(tmp_path):
    assert run_script(stock_settings_script(tmp_path), "{broken") == "{broken"


def test_stock_removal_covers_every_key_generator_owns_except_user_preferences():
    """生成器が持つキーを増やしたら、stock で扱いを決める (取り除くか、利用者のキーとして残すか)。"""
    sys.path.insert(0, str(ROOT / "scripts" / "agents"))
    try:
        import generate  # type: ignore[import-not-found]
    finally:
        sys.path.pop(0)
    removed = {"extensions", "skills", "defaultTools"}
    kept_as_user_preferences = {
        "defaultThinkingLevel",
        "enabledModels",
        "hideThinkingBlock",
        "defaultProvider",
        "defaultModel",
    }
    assert set(generate.PI_SETTINGS_OWNED) == removed | kept_as_user_preferences


def test_custom_settings_script_uses_generator(tmp_path):
    custom = render_file("dot_pi/agent/modify_settings.json.py.tmpl", tmp_path)
    assert '"pi-settings"' in custom
    assert "pi-stock-packages" not in custom


# --- packages ---------------------------------------------------------


def test_stock_packages_are_pinned_npm(tmp_path):
    pkgs = stock_packages(tmp_path)
    assert len(pkgs) == len(set(pkgs)) > 0
    for pkg in pkgs:
        assert re.fullmatch(r"npm:(@[a-z0-9._-]+/)?[a-z0-9._-]+@\d+\.\d+\.\d+", pkg), pkg


def test_stock_packages_include_background_plan_goal_btw_rewind(tmp_path):
    pkgs = stock_packages(tmp_path)
    for prefix in NEW_PACKAGES:
        assert any(p.startswith(prefix) for p in pkgs), prefix


def test_stock_packages_pi_btw_is_pinned_once_on_every_machine(tmp_path):
    """pi-btw は版固定で 1 回だけ入る。is-work の真偽（tester=会社 PC・applejxd=家の機）に依らない。"""
    for user in ("applejxd", "tester"):
        hits = [p for p in stock_packages(tmp_path, user) if "pi-btw" in p]
        assert hits == ["npm:@narumitw/pi-btw@0.63.5"], (user, hits)


def test_stock_packages_pi_show_token_rate_is_pinned_once_on_every_machine(tmp_path):
    """pi-show-token-rate は版固定で 1 回だけ入る。is-work の真偽（tester=会社 PC・applejxd=家の機）に依らない。"""
    for user in ("applejxd", "tester"):
        hits = [p for p in stock_packages(tmp_path, user) if "pi-show-token-rate" in p]
        assert hits == ["npm:pi-show-token-rate@0.3.0"], (user, hits)


def test_pi_btw_config_is_not_deployed():
    """pi-btw の設定 (pi-btw.json) は配らない。拡張の既定のままにする。"""
    assert not list(HOME_SRC.rglob("*pi-btw.json*"))


def test_stock_packages_never_include_pi_web_access(tmp_path):
    """家の検索は自作の MCP (websearch) に揃えた。どの機でも pi-web-access は入れない。"""
    for user in ("applejxd", "tester"):
        assert not any("pi-web-access" in p for p in stock_packages(tmp_path, user)), user


def test_stock_packages_pi_mcp_adapter_is_work_pc_only(tmp_path):
    """pi-mcp-adapter は会社 PC (is-work) だけ。家の機は pi 組み込みの MCP を使う。"""
    assert any(p.startswith("npm:pi-mcp-adapter@") for p in stock_packages(tmp_path, "tester"))
    assert not any("pi-mcp-adapter" in p for p in stock_packages(tmp_path, "applejxd"))


# --- MCP 設定 (~/.pi/agent/mcp.json) ---------------------------------------

MCP_MODIFY = HOME_SRC / "dot_pi" / "agent" / "modify_mcp.json.py.tmpl"
MCP_TARGET = ".pi/agent/mcp.json"


def mcp_script(tmp_path: Path, username: str) -> Path:
    script = tmp_path / f"modify_mcp_{username}.py"
    script.write_text(
        render(
            MCP_MODIFY.read_text(encoding="utf-8"),
            tmp_path,
            profile_env="stock",
            username=username,
        ),
        encoding="utf-8",
    )
    return script


def test_mcp_json_is_stock_only(tmp_path):
    assert MCP_TARGET in lines(render_file(".chezmoiignore.tmpl", tmp_path))
    stock = lines(render_file(".chezmoiignore.tmpl", tmp_path, profile_env="stock"))
    assert MCP_TARGET not in stock


def test_mcp_json_home_declares_websearch_and_keeps_user_servers(tmp_path):
    script = mcp_script(tmp_path, "applejxd")
    existing = {"mcpServers": {"mine": {"command": "x"}}, "autoEnableCodemode": False}
    out = json.loads(run_script(script, json.dumps(existing)))
    servers = out["mcpServers"]
    assert servers["mine"] == {"command": "x"}
    assert out["autoEnableCodemode"] is False
    web = servers["websearch"]
    assert web["command"] == "uv"
    assert web["args"][:3] == ["run", "--no-project", "--quiet"]
    assert web["args"][3].endswith("/.config/agents/websearch/mcp_server.py")
    assert not {"requires_env", "transport", "purpose", "clis", "pi_exposure"} & set(web)
    assert web["exposure"] == "direct"  # plan mode の許可リストに具体名を足すため
    again = run_script(script, json.dumps(out))
    assert json.loads(again) == out


def test_mcp_json_work_pc_has_no_websearch(tmp_path):
    out = json.loads(run_script(mcp_script(tmp_path, "tester"), ""))
    assert "websearch" not in out["mcpServers"]
    assert "agentcore-websearch" in out["mcpServers"]


def test_mcp_json_keeps_user_keys_of_declared_server_and_broken_input(tmp_path):
    script = mcp_script(tmp_path, "applejxd")
    existing = {
        "mcpServers": {
            "websearch": {"command": "old", "args": [], "env": {"A": "1"}, "exposure": "deferred"}
        }
    }
    web = json.loads(run_script(script, json.dumps(existing)))["mcpServers"]["websearch"]
    assert web["command"] == "uv"
    assert web["env"] == {"A": "1"}
    assert web["exposure"] == "deferred"
    assert run_script(script, "{broken") == "{broken"


# --- plan mode の設定 ------------------------------------------------


def plan_mode_script(tmp_path: Path) -> Path:
    script = tmp_path / "modify_plan_mode.py"
    script.write_text(
        render(PLAN_MODE_MODIFY.read_text(encoding="utf-8"), tmp_path, profile_env="stock"),
        encoding="utf-8",
    )
    return script


SEARCH_TOOLS = [
    "mcp__websearch__web_search",
    "mcp__websearch__fetch_page",
    "mcp__websearch__search_papers",
    "mcp__agentcore_websearch__web_search_tool__WebSearch",
]


def test_plan_mode_config_from_empty_input_has_defaults(tmp_path):
    out = json.loads(run_script(plan_mode_script(tmp_path), ""))
    base = ["read", "bash", "grep", "find", "ls", "ask_user_question"]
    assert out["defaultPlanTools"] == base + SEARCH_TOOLS
    assert "subagent" not in out["defaultPlanTools"]
    assert out["defaultPlanExportPath"] == ".tmp/keep/plan/"


def test_plan_mode_config_keeps_existing_values(tmp_path):
    existing = {"defaultPlanExportPath": "x/", "thinkingLevel": "high", "safeSubcommands": {}}
    out = json.loads(run_script(plan_mode_script(tmp_path), json.dumps(existing)))
    assert out["defaultPlanExportPath"] == "x/"
    assert out["thinkingLevel"] == "high"
    assert out["safeSubcommands"] == {}
    assert "defaultPlanTools" in out


def test_plan_mode_config_appends_search_tools_to_existing_list(tmp_path):
    script = plan_mode_script(tmp_path)
    existing = {"defaultPlanTools": ["read", "my_tool", SEARCH_TOOLS[1]]}
    first = run_script(script, json.dumps(existing))
    tools = json.loads(first)["defaultPlanTools"]
    # 利用者の順序と名前を保ち、無い名前だけ末尾へ足す (重複しない)
    assert tools == ["read", "my_tool", SEARCH_TOOLS[1], SEARCH_TOOLS[0], *SEARCH_TOOLS[2:]]
    assert run_script(script, first) == first


def test_plan_mode_config_leaves_non_list_tools(tmp_path):
    out = json.loads(run_script(plan_mode_script(tmp_path), '{"defaultPlanTools": "read"}'))
    assert out["defaultPlanTools"] == "read"


def test_plan_mode_config_is_idempotent_and_leaves_broken_input(tmp_path):
    script = plan_mode_script(tmp_path)
    first = run_script(script, "")
    assert run_script(script, first) == first
    assert run_script(script, "{broken") == "{broken"
    assert run_script(script, "[1]") == "[1]"


# --- AGENTS.md --------------------------------------------------------


def test_stock_agents_md_has_no_harness_words(tmp_path):
    text = render_file("dot_pi/agent/AGENTS.md.tmpl", tmp_path, profile_env="stock")
    assert "日本語" in text
    for word in HARNESS_WORDS:
        assert word not in text, word


def test_custom_agents_md_is_the_full_instructions(tmp_path):
    text = render_file("dot_pi/agent/AGENTS.md.tmpl", tmp_path)
    full = (HOME_SRC / ".chezmoitemplates" / "agent-instructions.md").read_text(encoding="utf-8")
    assert text.rstrip("\n") == full.rstrip("\n")


# --- permission-system の設定 ------------------------------------------

PERMISSION_POLICY = HOME_SRC / ".chezmoitemplates" / "pi-permission-policy.json"
PERMISSION_MODIFY = (
    HOME_SRC
    / "dot_pi"
    / "agent"
    / "extensions"
    / "pi-permission-system"
    / "modify_config.json.py.tmpl"
)
RUNTIME_KEYS = (
    "debugLog",
    "permissionReviewLog",
    "yoloMode",
    "doublePressToConfirm",
    "promptNotifications",
)


def permission_script(tmp_path: Path) -> Path:
    script = tmp_path / "modify_permission.py"
    script.write_text(
        render((PERMISSION_MODIFY).read_text(encoding="utf-8"), tmp_path, profile_env="stock"),
        encoding="utf-8",
    )
    return script


def policy() -> dict:
    return json.loads(PERMISSION_POLICY.read_text(encoding="utf-8"))


def test_permission_config_from_empty_input_has_policy_and_runtime_defaults(tmp_path):
    out = json.loads(run_script(permission_script(tmp_path), ""))
    assert out["permission"] == policy()["permission"]
    assert out["commandEffects"] == policy()["commandEffects"]
    assert out["yoloMode"] is False
    assert out["debugLog"] is False
    assert out["permissionReviewLog"] is True
    assert out["doublePressToConfirm"] is True
    assert out["promptNotifications"] == ["bell"]  # 承認待ちの BEL (Zed・Orca の通知)


def test_permission_config_keeps_runtime_values_and_replaces_policy(tmp_path):
    script = permission_script(tmp_path)
    existing = {
        "yoloMode": True,
        "debugLog": True,
        "permissionReviewLog": False,
        "doublePressToConfirm": False,
        "promptNotifications": ["osc777"],
        "promptTimeoutMs": 60000,
        "shellTools": {"exec_command": {"commandArgument": "cmd"}},
        "permission": {"*": "allow", "bash": "allow"},
    }
    out = json.loads(run_script(script, json.dumps(existing)))
    for key in (*RUNTIME_KEYS, "promptTimeoutMs"):
        assert out[key] == existing[key], key
    # shellTools はマージ: 利用者が足した項目を保ち、リポジトリの bg_run を入れる
    assert out["shellTools"] == {**existing["shellTools"], **policy()["shellTools"]}
    assert out["permission"] == policy()["permission"]  # 手で緩めた値は戻る


def test_permission_config_shell_tools_bg_run_replaces_hand_edit(tmp_path):
    existing = {"shellTools": {"bg_run": {"commandArgument": "cmd"}}}
    out = json.loads(run_script(permission_script(tmp_path), json.dumps(existing)))
    assert out["shellTools"]["bg_run"] == {"commandArgument": "command", "workdirArgument": "cwd"}


def test_permission_config_from_empty_input_has_shell_tools(tmp_path):
    out = json.loads(run_script(permission_script(tmp_path), ""))
    assert out["shellTools"] == policy()["shellTools"]
    assert out["shellTools"]["bg_run"] == {"commandArgument": "command", "workdirArgument": "cwd"}


def test_permission_config_is_idempotent(tmp_path):
    script = permission_script(tmp_path)
    first = run_script(script, "")
    assert run_script(script, first) == first


def test_permission_config_leaves_broken_input_alone(tmp_path):
    script = permission_script(tmp_path)
    assert run_script(script, "{broken") == "{broken"
    assert run_script(script, "[1]") == "[1]"


def test_permission_policy_does_not_carry_runtime_keys():
    """実行時の値 (yoloMode など) は拡張が書き換える。リポジトリは方針だけを持つ。"""
    assert set(policy()) <= {"permission", "shellTools", "commandEffects"}


def test_permission_policy_matches_the_contract():
    perm = policy()["permission"]
    for tool in ("read", "write", "edit", "grep", "find", "ls"):
        assert perm[tool] == "allow", tool
    assert perm["bash"]["*"] == "ask"
    assert perm["external_directory"] == "ask"
    assert perm["mcp"]["*"] == "ask"
    assert perm["skill"]["*"] == "allow"

    def action(value):
        return value["action"] if isinstance(value, dict) else value

    bash = {k: action(v) for k, v in perm["bash"].items()}
    for denied in ("rm -rf *", "sudo *", "git push*", "sh", "bash"):
        assert bash[denied] == "deny", denied
    for allowed in ("git status *", "git diff *", "mise run *", "uv run *", "pytest *", "rg *"):
        assert bash[allowed] == "allow", allowed
    path = perm["path"]
    assert next(iter(path)) == "*" and path["*"] == "allow"  # 後勝ち: 全許可を先頭に置く
    keys = list(path)
    for denied in (
        "*.env",
        "*.env.*",
        "~/.ssh/*",
        "~/.aws/*",
        "~/.gnupg/*",
        "~/.netrc",
        "~/.config/gh/*",
        "~/.config/agents/websearch-keys.json",
        "*.pem",
    ):
        assert path[denied] == "deny", denied
    # 入れる拡張の自分のツールは、毎回の確認を出さない (子の起動・ToDo・利用者への質問)
    for tool in (
        "todo",
        "ask_user_question",
        "subagent",
        "subagents_enable",
        "bg_wait",
        "bg_status",
        "bg_kill",
        "plan_mode_question",
        "plan_mode_complete",
        "goal_complete",
        "goal_blocked",
        "goal_wait",
    ):
        assert perm[tool] == "allow", tool
    assert "bg_run" not in perm  # bg_run は shellTools で bash と同じ判定に通す (allow にしない)
    assert path["*.env.example"] == "allow"
    assert keys.index("*.env.example") > keys.index("*.env.*")  # 例外は deny より後


def _check_state_map(value, where: str) -> None:
    states = {"allow", "deny", "ask"}
    if isinstance(value, str):
        assert value in states, where
        return
    assert isinstance(value, dict) and value, where
    for pattern, act in value.items():
        assert pattern, where
        if isinstance(act, dict):
            assert set(act) <= {"action", "reason"} and act.get("action") == "deny", (
                where,
                pattern,
            )
            assert isinstance(act.get("reason", ""), str) and len(act.get("reason", "")) <= 500
        else:
            assert act in states, (where, pattern)


def test_permission_policy_structure():
    """同梱のスキーマ (permissions.schema.json) の要点を、外部の依存なしで検査する。"""
    data = policy()
    for key, value in data["permission"].items():
        _check_state_map(value, key)
    for cmd, entry in data["commandEffects"].items():
        assert "/" not in cmd and "\\" not in cmd and " " not in cmd
        assert set(entry) <= {"effects", "unlessOption", "subcommands"}
        for stem in entry.get("unlessOption", []):
            assert re.fullmatch(r"-{1,2}[^-=\s][^=\s]*", stem), stem
        for eff in entry.get("subcommands", {}).values():
            assert eff in ("read", "write")


def test_permission_policy_validates_against_bundled_schema(tmp_path):
    """環境変数 PI_PERMISSION_SCHEMA に permissions.schema.json のパスがあり、jsonschema が使えるときだけ全検査する。"""
    schema_path = os.environ.get("PI_PERMISSION_SCHEMA")
    if not schema_path:
        pytest.skip("PI_PERMISSION_SCHEMA is not set")
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    out = json.loads(run_script(permission_script(tmp_path), ""))
    jsonschema.validate(out, schema)
