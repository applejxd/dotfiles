"""pi を Fence で囲って起動する (``ocs --harness pi``) の試験。

- 生成: ``[pi.sandbox]`` の追加分が共有の境界の素材に足される
- 準備: 境界用の agent 置き場 (認証の写し・設定の凍結・古いものの掃除)
- 認証: 境界の内側で更新された認証だけを本物へ戻す
- セッション: 外の ``pi -c`` と同じ置き場
- 実機: 実際の Fence で境界チェックが通る (Fence・bwrap・pi が無ければ skip)

see docs/spec/pi-harness.md#境界
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from agents_common import ROOT, agents_config_dir, load_common

sys.path.insert(0, str(ROOT / "scripts" / "agents"))
import generate as gen

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="境界は Linux 専用")

LIB = ROOT / "home" / "dot_local" / "share" / "ocs"
LAUNCHER = ROOT / "home" / "dot_local" / "bin" / "executable_ocs"
BOUNDARY_CHECK = ROOT / "home" / "dot_local" / "bin" / "executable_ocs-boundary-check"
HARNESS_SRC = ROOT / "home" / "dot_config" / "pi" / "harness" / "index.ts"
MODULES = ("common", "boundary", "check", "backup", "config", "pi", "cli")


def _ocs() -> SimpleNamespace:
    """ランチャーの本体を source state から読み込む (配備先は読まない)。"""
    namespace: dict = {"__name__": "probe"}
    exec(compile(LAUNCHER.read_text(encoding="utf-8"), "launcher", "exec"), namespace)
    saved, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        namespace["load"](LIB)
    finally:
        sys.dont_write_bytecode = saved
    return SimpleNamespace(**{n: sys.modules[f"ocs_lib.{n}"] for n in MODULES})


def _auth(**expires: int) -> dict:
    return {
        name: {"type": "oauth", "access": f"a-{name}", "refresh": f"r-{name}-{exp}", "expires": exp}
        for name, exp in expires.items()
    }


# ─── 生成 ───────────────────────────────────────────────────────────


def test_pi_sandbox_adds_pi_paths_to_the_shared_material():
    common = load_common()
    shared = gen.opencode_sandbox(common)
    pi = gen.pi_sandbox(common)
    assert pi is not None and shared is not None
    home = os.path.expanduser("~")
    wanted = (".pi/agent/install", "bin", ".config/pi/harness", ".config/agents", ".claude/hooks")
    for path in wanted:
        assert f"{home}/{path}" in pi["base"]["read"]
    assert f"{home}/.local/share/pi-sandbox" in pi["base"]["control_dirs"]
    # 共有の項目は残る。OpenCode だけのキー (permissions / plugins / config_dir) は出さない
    assert set(shared["base"]["read"]) <= set(pi["base"]["read"])
    assert set(pi) == {"runtime_path", "base"}
    # 書き込みは増やさない (セッションと境界用の agent 置き場はランチャーが足す)
    assert pi["base"]["write"] == shared["base"]["write"]


def test_pi_sandbox_rejects_unknown_keys():
    common = load_common()
    common["pi"]["sandbox"]["wirte"] = ["~/x"]
    with pytest.raises(ValueError, match=r"pi\.sandbox"):
        gen.pi_sandbox(common)


def test_the_harness_rules_carry_the_boundary():
    rules = gen.build_pi_harness({}, load_common())
    assert rules["sandbox"] == gen.pi_sandbox(load_common())


# ─── 境界用の agent 置き場 ──────────────────────────────────────────


def test_agent_dir_copies_credentials_and_freezes_settings(tmp_path):
    pi = _ocs().pi
    real = tmp_path / "real"
    real.mkdir()
    (real / "auth.json").write_text("{}", encoding="utf-8")
    os.chmod(real / "auth.json", 0o600)
    (real / "models-store.json").write_text("[]", encoding="utf-8")
    (real / "settings.json").write_text('{"defaultModel": "m"}', encoding="utf-8")
    (real / "extensions").mkdir()
    (real / "extensions" / "evil.ts").write_text("x", encoding="utf-8")

    agent = pi.prepare_agent_dir(real, tmp_path / "home")

    assert (agent / "settings.json").read_text(encoding="utf-8") == '{"defaultModel": "m"}'
    assert stat.S_IMODE((agent / "auth.json").stat().st_mode) == 0o600
    # 本物の拡張は写さない。凍結する場所は空で作る (denyWrite は無いパスに効かない)
    assert list((agent / "extensions").iterdir()) == []
    assert (agent / "trust.json").exists() and (agent / "mcp.json").exists()
    assert set(pi.frozen_paths(agent)) == {
        str(agent / n) for n in ("settings.json", "trust.json", "mcp.json", "extensions")
    }
    # 本物の置き場は触らない
    assert not (real / "trust.json").exists() and not (real / "mcp.json").exists()


def test_old_agent_dirs_are_pruned_but_fresh_ones_stay(tmp_path):
    pi = _ocs().pi
    home = tmp_path / "home"
    home.mkdir()
    old, fresh = home / "agent-old", home / "agent-fresh"
    for path in (old, fresh):
        path.mkdir()
    stale = time.time() - pi.AGENT_MAX_AGE_SECONDS - 60
    os.utime(old, (stale, stale))
    pi.prepare_agent_dir(tmp_path / "real", home)
    assert not old.exists() and fresh.exists()


@pytest.mark.parametrize(
    ("workspace", "name"),
    [
        ("/home/a/.local/share/x", "--home-a-.local-share-x--"),
        ("/home/a/src/tmp.Bcz9", "--home-a-src-tmp.Bcz9--"),
    ],
)
def test_sessions_dir_matches_the_one_pi_uses_outside(tmp_path, workspace, name):
    """pi の ``getDefaultSessionDirPath`` と同じ置き場 (外の ``pi -c`` で再開できる)。"""
    pi = _ocs().pi
    path = pi.sessions_dir(Path(workspace), tmp_path)
    assert path.relative_to(tmp_path / "sessions").name == name


def test_inner_command_and_environment(tmp_path, monkeypatch):
    pi = _ocs().pi
    monkeypatch.setenv("GH_TOKEN", "secret")
    monkeypatch.setenv("PI_HARNESS_CHILD", "1")
    monkeypatch.setenv("PI_HARNESS_ROLE", "reader")
    env = pi.inner_env(tmp_path / "agent")
    assert "GH_TOKEN" not in env and "PI_HARNESS_CHILD" not in env
    assert env["PI_HARNESS_BOUNDARY"] == "1"
    assert env["PI_CODING_AGENT_DIR"] == str(tmp_path / "agent")
    assert env["PI_HARNESS_ROLE"] == "reader"
    command = pi.inner_command(["-c"], "/usr/bin", tmp_path / "sessions")
    for flag in ("--no-approve", "-nbt", "-ne", "builtin:mcp", str(pi.HARNESS), "--session-dir"):
        assert flag in command
    assert command[-1] == "-c"


# ─── 認証を本物へ戻す ───────────────────────────────────────────────


def _setup_auth(tmp_path, real_auth, copy_auth):
    real, agent = tmp_path / "real", tmp_path / "agent"
    real.mkdir()
    agent.mkdir()
    (real / "auth.json").write_text(json.dumps(real_auth), encoding="utf-8")
    (agent / "auth.json").write_text(json.dumps(copy_auth), encoding="utf-8")
    return real, agent


def test_newer_credentials_are_written_back_and_others_are_kept(tmp_path):
    pi = _ocs().pi
    real_auth = _auth(openai=100, copilot=900)
    copy_auth = _auth(openai=200, copilot=900)  # openai だけが更新された
    real, agent = _setup_auth(tmp_path, real_auth, copy_auth)
    assert pi.sync_auth_back(agent, real) is True
    merged = json.loads((real / "auth.json").read_text(encoding="utf-8"))
    assert merged["openai"] == copy_auth["openai"] and merged["copilot"] == real_auth["copilot"]
    assert stat.S_IMODE((real / "auth.json").stat().st_mode) == 0o600
    assert not (real / "auth.json.lock").exists() and not (real / "auth.json.ocs-tmp").exists()


def test_older_or_unchanged_credentials_are_not_written_back(tmp_path):
    pi = _ocs().pi
    real, agent = _setup_auth(tmp_path, _auth(openai=300), _auth(openai=200))
    before = (real / "auth.json").read_text(encoding="utf-8")
    assert pi.sync_auth_back(agent, real) is False
    assert (real / "auth.json").read_text(encoding="utf-8") == before


def test_credentials_are_not_written_back_while_pi_holds_the_lock(tmp_path, monkeypatch):
    pi = _ocs().pi
    real, agent = _setup_auth(tmp_path, _auth(openai=100), _auth(openai=200))
    (real / "auth.json.lock").mkdir()
    monkeypatch.setattr(pi.time, "sleep", lambda _s: None)
    assert pi.sync_auth_back(agent, real) is False
    assert json.loads((real / "auth.json").read_text(encoding="utf-8")) == _auth(openai=100)
    assert (real / "auth.json.lock").exists(), "他者のロックを消してはいけない"


def test_broken_copy_is_ignored(tmp_path):
    pi = _ocs().pi
    real, agent = _setup_auth(tmp_path, _auth(openai=100), {})
    (agent / "auth.json").write_text("{not json", encoding="utf-8")
    assert pi.sync_auth_back(agent, real) is False


def test_cleanup_removes_the_copy_after_syncing(tmp_path, monkeypatch):
    pi = _ocs().pi
    real, agent = _setup_auth(tmp_path, _auth(openai=100), _auth(openai=200))
    monkeypatch.setattr(pi, "REAL_AGENT", real)
    pi.cleanup(agent)
    assert not agent.exists()
    assert json.loads((real / "auth.json").read_text(encoding="utf-8"))["openai"]["expires"] == 200


# ─── 実際の Fence ───────────────────────────────────────────────────


def _real_boundary_ready() -> str | None:
    fence = Path(gen.expand_user(gen.opencode_sandbox(load_common())["runtime_path"]))
    if not fence.is_file():
        return "Fence が無い"
    if shutil.which("bwrap") is None:
        return "bwrap が無い"
    if not (Path.home() / "bin/pi").is_file():
        return "pi が入っていない"
    return None


def test_real_fence_boundary_check_passes_for_pi(tmp_path, monkeypatch):
    """実際の Fence で、境界チェック (読めない・書けない・通信できない) が通る。"""
    reason = _real_boundary_ready()
    if reason:
        pytest.skip(reason)
    ocs = _ocs()
    harness = tmp_path / "harness"
    harness.mkdir()
    shutil.copy2(HARNESS_SRC, harness / "index.ts")
    rules = gen.build_pi_harness({}, load_common())
    (harness / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
    real = tmp_path / "real-agent"
    real.mkdir()
    (real / "auth.json").write_text("{}", encoding="utf-8")
    workspace = Path.home() / "src" / f"pi-boundary-test-{os.getpid()}"
    workspace.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
    try:
        monkeypatch.chdir(workspace)
        monkeypatch.setattr(ocs.pi, "HARNESS", harness)
        monkeypatch.setattr(ocs.pi, "RULES", harness / "rules.json")
        monkeypatch.setattr(ocs.pi, "REAL_AGENT", real)
        monkeypatch.setattr(ocs.pi, "AGENT_HOME", tmp_path / "pi-sandbox")
        monkeypatch.setattr(ocs.check, "CHECK", BOUNDARY_CHECK)
        monkeypatch.setenv("AGENTS_CONFIG_DIR", str(agents_config_dir()))
        code = ocs.cli.main(["--harness", "pi", "--check", "--no-backup"])
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
    assert code == 0
    # 差し替えが効いて (本物の ~/.pi/agent を使わず)、境界用の置き場は終わったら消える
    assert (tmp_path / "pi-sandbox").is_dir(), "AGENT_HOME の差し替えが効いていない"
    assert not list((tmp_path / "pi-sandbox").glob("agent-*")), "境界用の置き場が残っている"
    assert (real / "sessions").is_dir(), "REAL_AGENT の差し替えが効いていない"
