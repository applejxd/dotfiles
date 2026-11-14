"""pi の設定 (stock) の描画を検証する。

除外 (.chezmoiignore.tmpl)・撤去 (.chezmoiremove)・settings.json の変換・MCP・plan mode・
permission-system・AGENTS.md・プロンプトの中身を、chezmoi execute-template で描画して確かめる。
実機の chezmoi apply は行わない。
see docs/spec/agent-config-generation.md#pi-の設定
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
HARNESS_WORDS = ("guarded_", "フルガード", "worktree", "pis", "kcage", "feature-orchestration")  # stock の AGENTS.md に出さない語


def chezmoi_bin() -> str:
    found = shutil.which("chezmoi")
    if found is None:
        pytest.skip("chezmoi is not installed")
    return found


def render(
    template: str,
    home: Path,
    *,
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




def lines(text: str) -> set[str]:
    return {line.strip() for line in text.splitlines()}




# --- 判定 -------------------------------------------------------------
















# --- 除外と撤去 -------------------------------------------------------




















# --- settings.json ----------------------------------------------------


def stock_settings_script(tmp_path: Path, os_name: str = "linux") -> Path:
    script = tmp_path / "modify_settings.py"
    script.write_text(
        render_file(
            "dot_pi/agent/modify_settings.json.py.tmpl",
            tmp_path,
            os_name=os_name,
        ),
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
    assert out == {
        "defaultTools": ["+grep", "+find", "+ls"],
        "packages": stock_packages(tmp_path),
        "shellPath": str(tmp_path / ".local" / "bin" / "pib-shell"),  # Linux だけ (下の試験)
    }


def test_stock_settings_points_the_shell_at_pib_shell_only_on_linux(tmp_path):
    """pi のシェルは、コマンド実行の囲い (pib-shell) を指す。bwrap は Linux 専用なので、他の OS には入れない。"""
    linux = json.loads(run_script(stock_settings_script(tmp_path, "linux"), "{}"))
    assert linux["shellPath"] == str(tmp_path / ".local" / "bin" / "pib-shell")
    for os_name in ("darwin", "windows"):
        assert "shellPath" not in json.loads(run_script(stock_settings_script(tmp_path, os_name), "{}"))


def test_stock_settings_keeps_a_shell_the_user_chose(tmp_path):
    """利用者が別のシェルを書いていれば触らない (pib が、囲いを指していないと知らせる)。"""
    script = stock_settings_script(tmp_path)
    out = json.loads(run_script(script, json.dumps({"shellPath": "/usr/bin/zsh"})))
    assert out["shellPath"] == "/usr/bin/zsh"


def test_stock_settings_keeps_user_incremental_default_tools(tmp_path):
    script = stock_settings_script(tmp_path)
    src = {**CUSTOM_SETTINGS, "defaultTools": ["+grep", "-ls"]}
    first = run_script(script, json.dumps(src))
    assert json.loads(first)["defaultTools"] == ["+grep", "-ls"]  # 利用者の増分指定は保つ
    assert run_script(script, first) == first


def test_stock_settings_leaves_broken_input_alone(tmp_path):
    assert run_script(stock_settings_script(tmp_path), "{broken") == "{broken"






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
            username=username,
        ),
        encoding="utf-8",
    )
    return script




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


# --- pi-mcp-adapter の設定 (~/.pi/agent/mcp-adapter.json。会社 PC の stock だけ) ---

MCP_ADAPTER_MODIFY = HOME_SRC / "dot_pi" / "agent" / "modify_mcp-adapter.json.py.tmpl"
MCP_ADAPTER_TARGET = ".pi/agent/mcp-adapter.json"




def test_mcp_adapter_json_has_the_search_server_of_the_work_pc(tmp_path):
    script = tmp_path / "modify_mcp_adapter.py"
    script.write_text(
        render(
            MCP_ADAPTER_MODIFY.read_text(encoding="utf-8"),
            tmp_path,
            username="tester",
        ),
        encoding="utf-8",
    )
    existing = {"mcpServers": {"mine": {"command": "x"}}, "settings": {"toolPrefix": "none"}}
    out = json.loads(run_script(script, json.dumps(existing)))
    assert out["mcpServers"]["mine"] == {"command": "x"}
    assert out["settings"] == {"toolPrefix": "none"}
    server = out["mcpServers"]["agentcore-websearch"]
    assert server["command"] == "uv"
    assert "exposure" not in server  # pi 組み込みの MCP の概念
    mcp_json = json.loads(run_script(mcp_script(tmp_path, "tester"), ""))["mcpServers"]
    assert {k: v for k, v in mcp_json["agentcore-websearch"].items() if k != "exposure"} == server
    assert json.loads(run_script(script, json.dumps(out))) == out


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
        render(PLAN_MODE_MODIFY.read_text(encoding="utf-8"), tmp_path),
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
    text = render_file("dot_pi/agent/AGENTS.md.tmpl", tmp_path)
    assert "日本語" in text
    for word in HARNESS_WORDS:
        assert word not in text, word


def test_stock_agents_md_asks_for_absolute_cd_until_upstream_fix(tmp_path):
    """TEMP-REMOVE: pi-permission-system が cd 先の ~・変数を解決しない間の一時対処。上流が直ったら削除する。

    理由・撤去の条件は docs/spec/temporary-workarounds.md#pi-permission-system-の-cd-先の誤判定
    """
    text = render_file("dot_pi/agent/AGENTS.md.tmpl", tmp_path)
    assert "`cd` は絶対パスで書く" in text
    assert "TEMP-REMOVE" in text
    doc = (ROOT / "docs" / "spec" / "temporary-workarounds.md").read_text(encoding="utf-8")
    assert "## pi-permission-system の cd 先の誤判定" in doc




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
        render((PERMISSION_MODIFY).read_text(encoding="utf-8"), tmp_path),
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
    assert out["promptTimeoutMs"] == 300000  # 誰も答えない確認は、5 分で拒否して先へ進む (離席中に止まらない)


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
    # YOLO を切る前提。bash は既定 allow で、止めるものだけを後ろの規則で決める (個別の判定は test_pi_permission_decisions.py の表)
    assert perm["bash"]["*"] == "allow"
    assert next(iter(perm["bash"])) == "*"  # 後勝ち: 既定を先頭に置く
    assert perm["external_directory"] == {"*": "ask", "/tmp/*": "allow"}  # /tmp の読み書きだけ事前許可
    # 読み取りだけの許可リスト (pi 自身のディレクトリと Orca の貼り付け画像)。広い許可 ("*": allow) にはしない
    read = perm["external_directory_read"]
    assert "*" not in read and "~/.pi/agent/extensions/*" in read
    keys = list(read)
    for logs in ("~/.pi/agent/extensions/*/logs", "~/.pi/agent/extensions/*/logs/*"):
        assert read[logs] == "ask" and keys.index(logs) > keys.index("~/.pi/agent/extensions/*")  # 後勝ち: logs は許可の後で ask
    assert perm["mcp"]["*"] == "ask"
    assert perm["skill"]["*"] == "allow"

    def action(value):
        return value["action"] if isinstance(value, dict) else value

    bash = {k: action(v) for k, v in perm["bash"].items()}
    for denied in ("sudo *", "git push*", "sh", "bash", "printenv", "gh *auth token*", "bw get*", "op read*"):
        assert bash[denied] == "deny", denied
    # rm -rf の一律 deny は置かない (cc-safety-net が対象で判定する。2.0% の誤 deny を避ける)
    assert not any(k.startswith("rm ") for k in bash)
    for asked in ("gh *pr create*", "chezmoi *apply*", "git rebase*", "git -C * rebase*", "npm publish*", "ssh *"):
        assert bash[asked] == "ask", asked
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
        assert action(path[denied]) == "deny", denied
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
        "subagent_launch",  # ワークフローの子の起動 (当面は allow。docs の「subagent_launch は allow」)
        "contact_supervisor",
        "intercom",
        "structured_output",
        "subagent_command",
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


def test_every_deny_rule_carries_a_reason():
    """deny は、エージェントが「なぜ拒否され、代わりに何をすべきか」を読めるよう、理由をつける (ask には理由の仕組みが無い)。"""
    missing = []
    for surface, value in policy()["permission"].items():
        if isinstance(value, str):
            assert value != "deny", f"{surface} が理由のない単一の deny"
            continue
        for pattern, act in value.items():
            denied = act == "deny" or (isinstance(act, dict) and act.get("action") == "deny")
            if denied and not (isinstance(act, dict) and act.get("reason", "").strip()):
                missing.append((surface, pattern))
    assert not missing, f"理由のない deny: {missing}"


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


# --- プロンプトテンプレート (/fleet・/stepback) と静的な設定 --------------------------

PROMPTS = HOME_SRC / "dot_pi" / "agent" / "prompts"
# stock の pi に無いもの (自作ハーネスのツール・役割・起動)。/fleet・/stepback が指示してはならない
HARNESS_ONLY = ("guarded_task", "guarded_", "pis ", "--role", "フルガード", "kcage", "bypass")

# stock の /fleet が、利用者の待ち時間の 3 つの原因 (書き手の衝突・前の作業の完了待ち・長い検査の待ち) への
# 手順を持つこと。(節の番号, 手順を担う句)。方針の説明や frontmatter に同じ語があっても通らないよう、節ごとに探す
FLEET_STRATEGY = {
    "分けない判断": ("1", "分けずに自分で進める"),
    "共有ファイルの担当": ("2", "共有されやすいファイル"),
    "境界の契約を先に決める": ("2", "契約に対して同時に実装"),
    "todo に登録する": ("2", "todo に登録"),
    "書き手ごとの専用の枝と worktree": ("3", "書き手 1 人につき、専用の枝と worktree"),
    "統合用の枝を先に切る": ("3", "統合用の枝を先に"),
    "完了した順に取り込む": ("3", "完了した順に 1 件ずつ"),
    "取り込む前に clean を確かめる": ("3", "統合用の worktree が clean"),
    "衝突は merge --abort で戻す": ("3", "git merge --abort"),
    "履歴を書き換えない": ("3", "rebase など履歴を書き換える操作"),
    "見込み実装 (前の完了を待たない)": ("3", "前の完了を待たずに始める"),
    "管理 worktree の成果の採用": ("3", "handoff と patch を確認"),
    "完了ごとに次を起動 (上限 4)": ("4", "進行中は 4 件まで"),
    "子に全体の検査を回させない": ("5", "子には全体の検査を回させない"),
    "全体の検査は 1 回だけ": ("5", "1 回だけ回す"),
    "長い検査は背景へ": ("5", "bg_run"),
    "失敗で途中でも起きる": ("5", "wake_on"),
}


def fleet_sections(text: str) -> dict[str, str]:
    """/fleet を、「## <番号>. 」の見出しごとの本文に分ける (番号の無い節は含めない)。"""
    sections: dict[str, str] = {}
    current = None
    for line in text.splitlines():
        match = re.match(r"## (\d+)\. ", line)
        if match:
            current = match.group(1)
            sections[current] = ""
        elif line.startswith("## "):
            current = None
        elif current is not None:
            sections[current] += line + "\n"
    return sections


def test_fleet_prompt_instructs_the_subagent_tool_not_the_harness():
    """pi の道具は subagent (pi-subagents)。自作ハーネスの guarded_task・pis の指示が残ると、存在しない道具を呼ばせる。"""
    text = (PROMPTS / "fleet.md").read_text(encoding="utf-8")
    assert "$ARGUMENTS" in text and text.startswith("---\n")
    assert "subagent" in text and "worktree" in text  # 書き手ごとの作業ディレクトリ (git worktree) の隔離
    for word in HARNESS_ONLY:
        assert word not in text, word


@pytest.mark.parametrize(("what", "where"), FLEET_STRATEGY.items())
def test_fleet_prompt_has_the_isolation_merge_and_verification_strategy(what, where):
    number, phrase = where
    sections = fleet_sections((PROMPTS / "fleet.md").read_text(encoding="utf-8"))
    assert number in sections, f"節 {number} が無い"
    assert phrase in sections[number], what


def test_fleet_sections_ignores_text_outside_the_numbered_sections():
    text = "---\nx: 1\n---\n## 方針\n衝突\n## 1. 分ける\nあ\n## 2. 契約\nい\n"
    assert fleet_sections(text) == {"1": "あ\n", "2": "い\n"}


def test_stepback_prompt_is_a_stock_prompt():
    text = (PROMPTS / "stepback.md").read_text(encoding="utf-8")
    assert "$ARGUMENTS" in text and "ステップバック" in text
    for word in HARNESS_ONLY:
        assert word not in text, word
    assert "尽ねて" not in text  # 誤字 (尋ねて)


def test_keybindings_free_ctrl_c_for_interrupt():
    """app.clear (既定は Ctrl+C) を外さないと、Ctrl+C を app.interrupt へ足しても入力の消去が先に効く。"""
    keys = json.loads((HOME_SRC / "dot_pi" / "agent" / "keybindings.json").read_text(encoding="utf-8"))
    assert keys["app.interrupt"] == ["escape", "ctrl+c"]
    assert keys["app.clear"] == []


# --- 除外と撤去 -------------------------------------------------------


def test_ignore_keeps_the_pi_configs_deployed(tmp_path):
    """plan mode・compaction・prompts など、pi の設定は除外しない (Windows の prompts だけ除く)。"""
    ignore = lines(render_file(".chezmoiignore.tmpl", tmp_path))
    for target in (".pi/agent/pi-plan-mode.json", ".pi/agent/compaction.json", ".pi/agent/agents"):
        assert target not in ignore, target
    assert ".pi/agent/prompts/" not in ignore


def test_ignore_never_unignores_config_pi(tmp_path):
    """.chezmoiremove が .config/pi を消すので、除外を外すと apply が inconsistent state で止まる。"""
    for os_name in ("linux", "windows", "darwin"):
        ignore = lines(render_file(".chezmoiignore.tmpl", tmp_path, os_name=os_name))
        assert "!.config/pi/" not in ignore


def test_remove_lists_the_retired_custom_assets(tmp_path):
    remove = lines(render_file(".chezmoiremove", tmp_path))
    for target in (
        ".config/pi",
        ".pi/agent/models.json",
        ".pi/agent/extensions/subagents",
        ".pi/agent/extensions/todo",
        ".local/bin/pis",
        ".local/share/ocs",
    ):
        assert target in remove, target
    # package の設定と利用者の拡張が入る親は消さない
    assert ".pi/agent/extensions" not in remove
    assert PERMISSION_DIR not in remove


def test_source_has_no_target_that_remove_deletes(tmp_path):
    """ソースに同名が残ると、chezmoi apply が inconsistent state で失敗する。"""
    remove = lines(render_file(".chezmoiremove", tmp_path))
    deployed = set()
    for path in HOME_SRC.rglob("*"):
        if path.is_file():
            deployed.add(path.relative_to(HOME_SRC).as_posix())
    for target in remove:
        if not target or target.startswith("#"):
            continue
        source_name = "/".join(
            ("dot_" + part[1:]) if part.startswith(".") else part for part in target.split("/")
        )
        assert not any(d == source_name or d.startswith(source_name + "/") for d in deployed), target
