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
    ".pi/agent/extensions",
    ".pi/agent/prompts",
    ".pi/agent/models.json",
    ".config/pi",
    ".config/pi/**",
)
STOCK_REMOVES = (".pi/agent/extensions", ".pi/agent/prompts", ".pi/agent/models.json", ".config/pi")
# stock の AGENTS.md に出してはならない自作ハーネスの語
HARNESS_WORDS = ("guarded_", "フルガード", "worktree", "pis", "kcage", "feature-orchestration")


def chezmoi_bin() -> str:
    found = shutil.which("chezmoi")
    if found is None:
        pytest.skip("chezmoi is not installed")
    return found


def render(
    template: str, home: Path, *, profile_env: str | None = None, os_name: str = "linux"
) -> str:
    context = {
        "chezmoi": {
            "os": os_name,
            "username": "tester",
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


def test_custom_ignore_has_no_stock_entries(tmp_path):
    rendered = lines(render_file(".chezmoiignore.tmpl", tmp_path))
    for entry in STOCK_ONLY_IGNORES:
        assert entry not in rendered, entry


def test_stock_ignore_excludes_own_pi_assets(tmp_path):
    rendered = lines(render_file(".chezmoiignore.tmpl", tmp_path, profile_env="stock"))
    for entry in STOCK_ONLY_IGNORES:
        assert entry in rendered, entry
    # pi 以外の設定・実行ファイルは除外しない
    for other in (".claude/settings.json", ".local/bin/pis", ".config/opencode", ".codex"):
        assert other not in rendered


def test_custom_remove_is_unchanged(tmp_path):
    rendered = lines(render_file(".chezmoiremove", tmp_path))
    for entry in STOCK_REMOVES:
        assert entry not in rendered, entry
    # 従来の項目は残る
    assert ".config/agents/critical_deny.py" in rendered


def test_stock_remove_lists_own_pi_assets(tmp_path):
    rendered = lines(render_file(".chezmoiremove", tmp_path, profile_env="stock"))
    for entry in STOCK_REMOVES:
        assert entry in rendered, entry
    # ディレクトリの配下を並べない
    assert not any(e.startswith(".pi/agent/extensions/") for e in rendered)
    assert ".config/agents/critical_deny.py" in rendered


def test_remove_has_no_stock_target_that_source_still_deploys_in_custom(tmp_path):
    """stock の撤去対象は、stock では除外されている (同名が管理対象に残ると apply が失敗する)。"""
    ignore = lines(render_file(".chezmoiignore.tmpl", tmp_path, profile_env="stock"))
    remove = lines(render_file(".chezmoiremove", tmp_path, profile_env="stock"))
    for entry in STOCK_REMOVES:
        assert entry in ignore and entry in remove


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


def stock_packages() -> list[str]:
    text = (HOME_SRC / ".chezmoitemplates" / "pi-stock-packages").read_text(encoding="utf-8")
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
    for key in ("defaultTools", "extensions", "skills"):
        assert key not in out, key
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
    assert out["packages"] == stock_packages()


def test_stock_settings_keeps_user_extension_and_is_idempotent(tmp_path):
    script = stock_settings_script(tmp_path)
    src = {**CUSTOM_SETTINGS, "extensions": [*CUSTOM_SETTINGS["extensions"], "~/mine/index.ts"]}
    first = run_script(script, json.dumps(src))
    assert json.loads(first)["extensions"] == ["~/mine/index.ts"]
    assert run_script(script, first) == first


def test_stock_settings_from_empty_input(tmp_path):
    out = json.loads(run_script(stock_settings_script(tmp_path), ""))
    assert out == {"packages": stock_packages()}


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


def test_stock_packages_are_pinned_npm():
    pkgs = stock_packages()
    assert len(pkgs) == len(set(pkgs)) > 0
    for pkg in pkgs:
        assert re.fullmatch(r"npm:(@[a-z0-9._-]+/)?[a-z0-9._-]+@\d+\.\d+\.\d+", pkg), pkg


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
