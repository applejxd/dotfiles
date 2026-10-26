"""pi を Fence で囲って起動する (``pis`` の標準) の試験。

- 生成: ``[pi.sandbox]`` の追加分が共有の境界の素材に足される
- 準備: 境界用の agent 置き場 (認証の写し・設定の凍結・古いものの掃除)
- 認証: 境界の内側で更新された認証だけを本物へ戻す
- セッション: 外の ``pi -c`` と同じ置き場
- 実機: 実際の Fence で境界チェックが通る (Fence・bwrap・pi が無ければ skip)

see docs/spec/guard/pi-sandbox.md#サンドボックス
"""

from __future__ import annotations

import http.server
import importlib
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import threading
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
MODULES = ("common", "boundary", "check", "backup", "config", "pi", "cli", "pis")


def _ocs() -> SimpleNamespace:
    """ランチャーの本体を source state から読み込む (配備先は読まない)。"""
    namespace: dict = {"__name__": "probe"}
    exec(compile(LAUNCHER.read_text(encoding="utf-8"), "launcher", "exec"), namespace)
    saved, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        namespace["load"](LIB)
        importlib.import_module("ocs_lib.pis")  # ocs の cli は pis を読み込まない
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


def test_pi_sandbox_hides_the_search_keys_inside_the_open_config_dir():
    # ~/.config/agents は判定器のために開けるが、その中の検索 API の鍵は内側へ見せない
    pi = gen.pi_sandbox(load_common())
    assert pi is not None
    home = os.path.expanduser("~")
    assert f"{home}/.config/agents" in pi["base"]["read"]
    assert f"{home}/.config/agents/websearch-keys.json" in pi["base"]["deny_read"]


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
    frozen = ("settings.json", "trust.json", "mcp.json", "AGENTS.md", "keybindings.json")
    expected = {str(agent / n) for n in (*frozen, "extensions", "prompts")}
    assert set(pi.frozen_paths(agent)) == expected
    # 本物の置き場は触らない
    assert not (real / "trust.json").exists() and not (real / "mcp.json").exists()


def test_agent_dir_carries_the_instructions_keybindings_and_prompts(tmp_path):
    """共通の指示・キーバインド・/fleet は、内側でも同じに読めて、書き換えられない。"""
    pi = _ocs().pi
    real = tmp_path / "real"
    (real / "prompts").mkdir(parents=True)
    (real / "AGENTS.md").write_text("# 個人用カスタム指示\n", encoding="utf-8")
    (real / "keybindings.json").write_text('{"a": 1}', encoding="utf-8")
    (real / "prompts" / "fleet.md").write_text("fleet", encoding="utf-8")
    agent = pi.prepare_agent_dir(real, tmp_path / "home")
    assert (agent / "AGENTS.md").read_text(encoding="utf-8") == "# 個人用カスタム指示\n"
    assert (agent / "keybindings.json").read_text(encoding="utf-8") == '{"a": 1}'
    assert (agent / "prompts" / "fleet.md").read_text(encoding="utf-8") == "fleet"
    for name in ("AGENTS.md", "keybindings.json", "prompts"):
        assert str(agent / name) in pi.frozen_paths(agent)
    # fd・rg は本物の bin を指すリンク (毎回ダウンロードさせない)。本物に bin が無ければ作らない
    assert (agent / "bin").is_symlink() is False
    (real / "bin").mkdir()
    (real / "bin" / "fd").write_text("fd", encoding="utf-8")
    linked = pi.prepare_agent_dir(real, tmp_path / "home3")
    assert (linked / "bin").is_symlink()
    assert (linked / "bin" / "fd").read_text(encoding="utf-8") == "fd"
    # 本物に無いときも、書き込みを塞ぐ場所が空で在る (denyWrite は無いパスに効かない)
    bare = pi.prepare_agent_dir(tmp_path / "none", tmp_path / "home2")
    assert (bare / "AGENTS.md").read_text(encoding="utf-8") == ""
    assert (bare / "prompts").is_dir() and (bare / "keybindings.json").exists()


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
    config_ = {"filesystem": {"allowRead": ["/a"], "allowWrite": ["/b"]}}
    monkeypatch.setenv("PI_HARNESS_ALLOWED", "outer")
    for name in ("ORCA_AGENT_HOOK_TOKEN", "ORCA_PANE_KEY", "MY_SERVICE_SECRET", "db_password"):
        monkeypatch.setenv(name, "x")
    monkeypatch.setenv("ORCA_AGENT_HOOK_PORT", "1234")  # ポートは資格情報ではない
    monkeypatch.setenv("PIS_EXTRA_READ", "/data2")  # 起動前に外側が読む入力
    monkeypatch.setenv("PIS_EXTRA_DEVICES", "/dev/dxg")  # 同上
    monkeypatch.setattr(pi.check, "ensure_canary", lambda: None)
    env = pi.inner_env(tmp_path / "agent", config_)
    assert "GH_TOKEN" not in env and "PI_HARNESS_CHILD" not in env
    assert "PIS_EXTRA_READ" not in env
    assert "PIS_EXTRA_DEVICES" not in env
    # 名前から資格情報と分かるものは、固定の一覧に無くても渡さない
    for name in ("ORCA_AGENT_HOOK_TOKEN", "ORCA_PANE_KEY", "MY_SERVICE_SECRET", "db_password"):
        assert name not in env, name
    assert env["ORCA_AGENT_HOOK_PORT"] == "1234"
    assert env["PI_HARNESS_BOUNDARY"] == "1"
    # 内側ではネイティブのクリップボード経路が塞がれるので、OSC 52 を強制する
    assert env["PI_CLIPBOARD_OSC52"] == "1"
    # プロキシ越しの取得の印。ホスト側の値ではなく pis が付ける
    assert env["PIS_FETCH_VIA_PROXY"] == "1"
    # 外から入った値は捨て、実際に開けた場所を渡す。カナリアは内側から見えない状態領域に置く
    assert json.loads(env["PI_HARNESS_ALLOWED"]) == {"read": ["/a"], "write": ["/b"]}
    assert env["PI_HARNESS_CANARY_READ"].endswith(pi.check.CANARY_REL)
    assert env["PI_HARNESS_CANARY_WRITE"].startswith(str(pi.STATE))
    assert env["PI_CODING_AGENT_DIR"] == str(tmp_path / "agent")
    assert env["PI_HARNESS_ROLE"] == "reader"
    rules = tmp_path / "rules.json"
    rules.write_text(json.dumps({"extensions": []}), encoding="utf-8")
    monkeypatch.setattr(pi, "RULES", rules)
    command = pi.inner_command(["-c"], "/usr/bin", tmp_path / "sessions")
    for flag in ("--no-approve", "-nbt", "-ne", "builtin:mcp", str(pi.HARNESS), "--session-dir"):
        assert flag in command
    assert command[-1] == "-c"


def test_inner_command_adds_only_the_extensions_that_exist(tmp_path):
    pi = _ocs().pi
    real = tmp_path / "real"
    for name in ("todo", "btw", "orca-agent-status"):
        (real / "extensions" / name).mkdir(parents=True)
        (real / "extensions" / name / "index.ts").write_text("", encoding="utf-8")
    # 一覧にあって未配布のもの (plan) と、一覧に無いもの (orca-agent-status) は足さない
    args = pi.extension_args(real, ["todo", "plan", "btw"])
    expected = ["-e", str(real / "extensions/todo/index.ts")]
    expected += ["-e", str(real / "extensions/btw/index.ts")]
    assert args == expected


def test_own_extensions_come_from_rules_json(tmp_path):
    pi = _ocs().pi
    rules = tmp_path / "rules.json"
    rules.write_text(json.dumps({"extensions": ["todo", "plan"]}), encoding="utf-8")
    assert pi.own_extensions(rules) == ["todo", "plan"]


@pytest.mark.parametrize("body", [None, "{}", '{"extensions": "todo"}', '{"extensions": [1]}'])
def test_own_extensions_refuse_a_stale_or_broken_rules_json(tmp_path, body):
    pi = _ocs().pi
    rules = tmp_path / "rules.json"
    if body is not None:
        rules.write_text(body, encoding="utf-8")
    with pytest.raises(SystemExit):
        pi.own_extensions(rules)


def test_the_extension_list_is_declared_once_and_drives_the_read_allowance():
    """拡張を足すのは [pi] own_extensions の 1 か所。rules.json と読み取りの許可は生成される。"""
    common = load_common()
    names = gen.pi_own_extensions(common)
    assert names and gen.build_pi_harness({}, common)["extensions"] == names
    home = os.path.expanduser("~")
    read = gen.pi_sandbox(common)["base"]["read"]
    for name in names:
        assert f"{home}/.pi/agent/extensions/{name}" in read
    # [pi.sandbox] read に拡張を手で書いていない (二重の宣言にしない)
    assert not [p for p in common["pi"]["sandbox"]["read"] if ".pi/agent/extensions" in p]


@pytest.mark.parametrize("bad", [["../x"], ["a/b"], ["Todo"], [""], ["todo", "todo"], "todo"])
def test_own_extensions_rejects_unsafe_names(bad):
    common = load_common()
    common["pi"]["own_extensions"] = bad
    with pytest.raises(SystemExit):
        gen.pi_own_extensions(common)


def _stub_pis(monkeypatch, ocs):
    monkeypatch.setattr(ocs.pis, "check_installed", lambda: None)
    monkeypatch.setattr(ocs.pis, "check_mcp_json", lambda _agent: None)
    seen = {}

    def fake_main(argv):
        seen["argv"] = argv
        seen["env"] = (os.environ.get("PI_HARNESS_ROLE"), os.environ.get("PI_HARNESS_BYPASS"))
        return 7

    monkeypatch.setattr(ocs.pi, "run_sandboxed", fake_main)
    return seen


def test_pis_defaults_to_the_sandbox(monkeypatch):
    """pis は標準でサンドボックスの中。役割・bypass の環境を整えて引き継ぐ (--boundary は互換)。"""
    ocs = _ocs()
    seen = _stub_pis(monkeypatch, ocs)
    monkeypatch.setenv("PI_HARNESS_CHILD", "1")
    monkeypatch.setenv("PI_HARNESS_ALLOWED", "outer")
    assert ocs.pis.main(["--bypass", "--role", "reader", "-c"]) == 7
    assert seen["argv"] == ["-c"]
    assert seen["env"] == ("reader", "1")
    assert "PI_HARNESS_CHILD" not in os.environ and "PI_HARNESS_ALLOWED" not in os.environ
    assert ocs.pis.main(["--boundary", "-c"]) == 7 and seen["argv"] == ["-c"]


def test_pis_refuses_the_sandbox_where_it_cannot_be_built(monkeypatch, capsys):
    ocs = _ocs()
    _stub_pis(monkeypatch, ocs)
    monkeypatch.setattr(ocs.pis.sys, "platform", "darwin")
    with pytest.raises(SystemExit):
        ocs.pis.main(["-c"])
    assert "--no-sandbox" in capsys.readouterr().err


def test_pis_no_sandbox_marks_the_environment_and_warns(monkeypatch, capsys):
    ocs = _ocs()
    _stub_pis(monkeypatch, ocs)
    monkeypatch.setattr(ocs.pis.shutil, "which", lambda *_a, **_k: "/usr/bin/pi")
    # 配備済みの rules.json (~/.config/pi/harness) に依存しない
    monkeypatch.setattr(ocs.pi, "own_extensions", lambda *_a, **_k: [])
    captured = {}
    monkeypatch.setattr(ocs.pis.os, "execvpe", lambda f, a, e: captured.update(file=f, env=e))
    monkeypatch.setenv("PI_HARNESS_BOUNDARY", "1")  # 外から入った期待は捨てる
    ocs.pis.main(["--no-sandbox", "-c"])
    assert captured["env"]["PI_HARNESS_NO_SANDBOX"] == "1"
    assert "PI_HARNESS_BOUNDARY" not in captured["env"]
    assert "サンドボックス無し" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        ocs.pis.parse(["--no-sandbox", "--boundary"])


def test_pis_plain_command_shares_the_flags_and_the_extension_list(monkeypatch, tmp_path):
    ocs = _ocs()
    rules = tmp_path / "rules.json"
    rules.write_text(json.dumps({"extensions": ["todo"]}), encoding="utf-8")
    monkeypatch.setattr(ocs.pi, "RULES", rules)
    agent = tmp_path / "agent"
    (agent / "extensions" / "todo").mkdir(parents=True)
    (agent / "extensions" / "todo" / "index.ts").write_text("", encoding="utf-8")
    command = ocs.pis.plain_command(ocs.pis.parse(["--model", "x"]), agent)
    assert command[0] == "pi"
    assert tuple(command[1 : 1 + len(ocs.pi.BASE_FLAGS)]) == ocs.pi.BASE_FLAGS
    assert ["-e", str(agent / "extensions/todo/index.ts")] == command[6:8]
    assert command[-4:] == ["-e", str(ocs.pi.HARNESS), "--model", "x"]
    # サンドボックスの内側の起動も、同じフラグと一覧から作る
    inner = ocs.pi.inner_command([], "/usr/bin", tmp_path / "sessions")
    start = inner.index(str(ocs.pi.PI)) + 1
    assert tuple(inner[start : start + len(ocs.pi.BASE_FLAGS)]) == ocs.pi.BASE_FLAGS


def _repo(tmp_path, *skills):
    """git ルートを作る。skills は ``ルートからの相対パス`` (そこに .agents/skills を置く)。"""
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    for rel in skills:
        (root / rel / ".agents" / "skills").mkdir(parents=True)
    return root


def test_skill_args_adds_the_worktree_skills_up_to_the_git_root(tmp_path):
    pi = _ocs().pi
    root = _repo(tmp_path, ".", "sub")
    (root / "sub" / "deep").mkdir()
    # 作業先から git ルートまでの .agents/skills を、近い順に足す (pi の発見の範囲と同じ)
    assert pi.skill_args(root / "sub" / "deep") == [
        "--skill",
        str(root / "sub/.agents/skills"),
        "--skill",
        str(root / ".agents/skills"),
    ]
    assert pi.skill_args(root) == ["--skill", str(root / ".agents/skills")]


def test_skill_args_adds_nothing_without_a_git_root_or_skills(tmp_path, monkeypatch):
    pi = _ocs().pi
    # git ルートが無いと足さない (.agents/skills があっても)。tmp が別の git の中にあっても動くように差し替える
    loose = tmp_path / "loose"
    (loose / ".agents" / "skills").mkdir(parents=True)
    monkeypatch.setattr(pi, "_git_root", lambda _start: None)
    assert pi.skill_args(loose) == []
    monkeypatch.undo()
    # git ルートより上の .agents/skills は足さない
    root = tmp_path / "outer" / "repo"
    (root / ".git").mkdir(parents=True)
    (tmp_path / "outer" / ".agents" / "skills").mkdir(parents=True)
    assert pi.skill_args(root) == []


def test_skill_args_skips_the_user_level_skills(tmp_path, monkeypatch):
    pi = _ocs().pi
    # $HOME 自体が git リポジトリでも、~/.agents/skills (pi が元から読む) は重ねない
    home = _repo(tmp_path, ".")
    monkeypatch.setattr(pi, "HOME", home)
    assert pi.skill_args(home) == []


def test_skill_args_reaches_both_launch_commands(tmp_path, monkeypatch):
    ocs = _ocs()
    root = _repo(tmp_path, ".")
    rules = tmp_path / "rules.json"
    rules.write_text(json.dumps({"extensions": []}), encoding="utf-8")
    monkeypatch.setattr(ocs.pi, "RULES", rules)
    monkeypatch.chdir(root)
    skill = ["--skill", str(root / ".agents/skills")]
    inner = ocs.pi.inner_command([], "/usr/bin", tmp_path / "sessions")
    plain = ocs.pis.plain_command(ocs.pis.parse([]), tmp_path / "agent")
    for command in (inner, plain):
        # 信頼を緩めず (--no-approve のまま)、スキルだけ明示で足す。フルガードより前
        assert "--no-approve" in command
        at = command.index("--skill")
        assert command[at : at + 2] == skill
        assert at < command.index(str(ocs.pi.HARNESS))


def test_pis_parse_takes_only_the_leading_options():
    ocs = _ocs()
    options = ocs.pis.parse(["--bypass", "--role", "reader", "--", "--bypass", "x"])
    assert (options.bypass, options.sandbox, options.role, options.rest) == (
        True,
        True,
        "reader",
        ["--bypass", "x"],
    )
    assert ocs.pis.parse(["-c", "--bypass"]).rest == ["-c", "--bypass"]
    with pytest.raises(SystemExit):
        ocs.pis.parse(["--role"])


def test_bypass_defaults_on_in_the_sandbox_and_off_without_it():
    pis = _ocs().pis
    assert pis.parse([]).bypass is True  # サンドボックスでの起動が既定
    assert pis.parse(["--no-bypass"]).bypass is False
    assert pis.parse(["--no-sandbox"]).bypass is False  # 守りがガードだけのときは確認を残す
    assert pis.parse(["--no-sandbox", "--bypass"]).bypass is True  # 明示すれば勝つ
    assert pis.parse(["--bypass", "--no-bypass"]).bypass is False  # 後の指定が勝つ
    assert pis.parse(["-c", "--no-bypass"]).rest == ["-c", "--no-bypass"]  # pi の引数は解釈しない


def _preflight_setup(monkeypatch, tmp_path, codes):
    ocs = _ocs()
    monkeypatch.setattr(ocs.check, "PREFLIGHT_DIR", tmp_path / "preflight")
    fake = tmp_path / "fence"
    fake.write_text("#!/bin/sh\necho fence-1.0\n", encoding="utf-8")
    fake.chmod(0o755)
    check_script = tmp_path / "ocs-boundary-check"
    check_script.write_text("v1", encoding="utf-8")
    monkeypatch.setattr(ocs.check, "CHECK", check_script)
    calls = []

    def run_check(*_args):
        calls.append(1)
        return codes.pop(0)

    monkeypatch.setattr(ocs.check, "run_check", run_check)
    return ocs, fake, check_script, calls


def _project(agent, extra=None):
    config = {"filesystem": {"allowWrite": [agent, "/w"], "denyWrite": [f"{agent}/settings.json"]}}
    config.update(extra or {})
    return {"workspace": "/w", "config": config}


def test_preflight_remembers_only_a_pass_and_rekeys_on_any_change(monkeypatch, tmp_path):
    ocs, fence, script, calls = _preflight_setup(monkeypatch, tmp_path, [1, 0, 0])
    run = lambda agent, **kw: ocs.check.preflight(  # noqa: E731
        fence, "b.json", _project(agent, **kw), {}, tmp_path, volatile=[agent]
    )
    assert run("/agent-aaa") == 1 and len(calls) == 1  # 不合格は覚えない
    assert run("/agent-bbb") == 0 and len(calls) == 2  # 合格を覚える
    assert run("/agent-ccc") == 0 and len(calls) == 2  # 起動ごとに変わる置き場は鍵に影響しない
    assert run("/agent-ddd", extra={"network": {"allowedDomains": ["x"]}}) == 0 and len(calls) == 3
    script.write_text("v2", encoding="utf-8")  # 検査スクリプトが変わったら再検査する
    monkeypatch.setattr(ocs.check, "run_check", lambda *_a: (calls.append(1), 0)[1])
    assert run("/agent-eee") == 0 and len(calls) == 4


def test_preflight_forgets_after_the_max_age(monkeypatch, tmp_path):
    ocs, fence, _script, calls = _preflight_setup(monkeypatch, tmp_path, [0, 0])
    args = (fence, "b.json", _project("/a"), {}, tmp_path, ["/a"])
    assert ocs.check.preflight(*args) == 0 and len(calls) == 1
    marker = next((tmp_path / "preflight").iterdir())
    old = time.time() - ocs.check.PREFLIGHT_MAX_AGE_SECONDS - 10
    os.utime(marker, (old, old))
    assert ocs.check.preflight(*args) == 0 and len(calls) == 2


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


# ─── Copilot ブローカーモード ───────────────────────────────────────


def _broker_real(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    auth = _auth(openai=100, **{"github-copilot": 500})
    (real / "auth.json").write_text(json.dumps(auth), encoding="utf-8")
    os.chmod(real / "auth.json", 0o600)
    return real, auth


def test_broker_unset_keeps_the_current_behaviour(tmp_path, monkeypatch):
    pi = _ocs().pi
    assert pi.parse_broker(None) is None and pi.parse_broker("") is None
    real, auth = _broker_real(tmp_path)
    agent = pi.prepare_agent_dir(real, tmp_path / "home")
    assert json.loads((agent / "auth.json").read_text(encoding="utf-8")) == auth
    assert not (agent / "models.json").exists()
    monkeypatch.setenv("COPILOT_GITHUB_TOKEN", "host-secret")
    monkeypatch.setattr(pi.check, "ensure_canary", lambda: None)
    env = pi.inner_env(agent, {"filesystem": {}})
    assert "COPILOT_GITHUB_TOKEN" not in env


@pytest.mark.parametrize(
    "bad",
    [
        "https://127.0.0.1:18080",
        "http://example.com:18080",
        "http://localhost:18080",
        "http://127.0.0.1:80",
        "http://127.0.0.1:65536",
        "http://127.0.0.1",
        "http://127.0.0.1:18080/v1",
        "http://127.0.0.1:18080/?a=1",
        "http://127.0.0.1:18080?",
        "http://127.0.0.1:18080/#x",
        "http://user:pw@127.0.0.1:18080",
        "http://user@127.0.0.1:18080",
        " http://127.0.0.1:18080",
        "http://127.0.0.1:abc",
    ],
)
def test_broker_rejects_invalid_values(bad, capsys):
    pi = _ocs().pi
    with pytest.raises(SystemExit):
        pi.parse_broker(bad)
    assert "broker.copilot" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["http://127.0.0.1:18080", "http://127.0.0.1:18080/"])
def test_broker_accepts_a_loopback_url(value):
    pi = _ocs().pi
    assert pi.parse_broker(value) == ("http://127.0.0.1:18080", 18080)


def test_broker_opens_only_its_port_in_the_fence_config():
    pi = _ocs().pi
    config_ = {"network": {"allowLocalBinding": False, "allowedDomains": ["x"]}}
    pi.apply_broker_network(config_, 18080)
    assert config_["network"] == {
        "allowLocalBinding": False,
        "allowedDomains": ["x"],
        "allowLocalOutbound": True,
        "allowLocalOutboundPorts": [18080],
    }


def test_broker_agent_dir_drops_only_the_copilot_auth(tmp_path):
    pi = _ocs().pi
    real, auth = _broker_real(tmp_path)
    agent = pi.prepare_agent_dir(real, tmp_path / "home", "http://127.0.0.1:18080")
    copied = json.loads((agent / "auth.json").read_text(encoding="utf-8"))
    assert "github-copilot" not in copied and copied["openai"] == auth["openai"]
    assert stat.S_IMODE((agent / "auth.json").stat().st_mode) == 0o600
    # 本物は触らない
    assert json.loads((real / "auth.json").read_text(encoding="utf-8")) == auth


def test_broker_agent_dir_writes_models_json(tmp_path):
    pi = _ocs().pi
    real, _ = _broker_real(tmp_path)
    agent = pi.prepare_agent_dir(real, tmp_path / "home", "http://127.0.0.1:18080/")
    models = json.loads((agent / "models.json").read_text(encoding="utf-8"))
    assert models == {"providers": {"github-copilot": {"baseUrl": "http://127.0.0.1:18080"}}}
    # 既にあれば (他のプロバイダや項目を残して) マージする
    (agent / "models.json").write_text(
        json.dumps({"providers": {"x": {"a": 1}, "github-copilot": {"b": 2}}}), encoding="utf-8"
    )
    pi._write_broker_models(agent, "http://127.0.0.1:18080")
    merged = json.loads((agent / "models.json").read_text(encoding="utf-8"))
    assert merged["providers"]["x"] == {"a": 1}
    assert merged["providers"]["github-copilot"] == {"b": 2, "baseUrl": "http://127.0.0.1:18080"}


def test_agent_dir_gets_only_the_provider_compat_from_models_json(tmp_path):
    # 本物の models.json から写すのは providers.*.compat だけ (apiKey ・ baseUrl ・ headers ・ models は写さない)
    pi = _ocs().pi
    real, _ = _broker_real(tmp_path)
    (real / "models.json").write_text(
        json.dumps(
            {
                "providers": {
                    "github-copilot": {
                        "compat": {"supportsEagerToolInputStreaming": False},
                        "headers": {"x": "y"},
                    },
                    "custom": {
                        "apiKey": "SECRET-KEY",
                        "baseUrl": "http://h",
                        "models": [{"id": "m"}],
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    agent = pi.prepare_agent_dir(real, tmp_path / "home")
    text = (agent / "models.json").read_text(encoding="utf-8")
    assert json.loads(text) == {
        "providers": {"github-copilot": {"compat": {"supportsEagerToolInputStreaming": False}}}
    }
    assert "SECRET-KEY" not in text and "headers" not in text


def test_agent_dir_compat_merges_with_the_broker_base_url(tmp_path):
    pi = _ocs().pi
    real, _ = _broker_real(tmp_path)
    (real / "models.json").write_text(
        json.dumps(
            {
                "providers": {
                    "github-copilot": {"compat": {"supportsEagerToolInputStreaming": False}}
                }
            }
        ),
        encoding="utf-8",
    )
    agent = pi.prepare_agent_dir(real, tmp_path / "home", "http://127.0.0.1:18080")
    models = json.loads((agent / "models.json").read_text(encoding="utf-8"))
    assert models["providers"]["github-copilot"] == {
        "compat": {"supportsEagerToolInputStreaming": False},
        "baseUrl": "http://127.0.0.1:18080",
    }


@pytest.mark.parametrize(
    "body", [None, "not json", "[]", '{"providers": 3}', '{"providers": {"x": {"compat": 1}}}']
)
def test_agent_dir_ignores_a_missing_or_odd_models_json(tmp_path, body):
    pi = _ocs().pi
    real, _ = _broker_real(tmp_path)
    if body is not None:
        (real / "models.json").write_text(body, encoding="utf-8")
    agent = pi.prepare_agent_dir(real, tmp_path / "home")
    assert not (agent / "models.json").exists()


def test_shipped_models_json_turns_off_eager_tool_input_streaming():
    # 配布する models.json: Copilot のツール引数を、検証なしの細粒度ストリーミングで送らせない
    data = json.loads((ROOT / "home/dot_pi/agent/models.json").read_text(encoding="utf-8"))
    assert data == {
        "providers": {"github-copilot": {"compat": {"supportsEagerToolInputStreaming": False}}}
    }


def test_broker_env_has_the_dummy_and_never_the_host_value(tmp_path, monkeypatch):
    pi = _ocs().pi
    monkeypatch.setenv("COPILOT_GITHUB_TOKEN", "host-secret")
    monkeypatch.setenv("GH_TOKEN", "host-secret")
    monkeypatch.setattr(pi.check, "ensure_canary", lambda: None)
    env = pi.inner_env(tmp_path / "agent", {"filesystem": {}}, broker=True)
    assert env["COPILOT_GITHUB_TOKEN"] == "dummy-not-a-real-token"
    assert "GH_TOKEN" not in env and "host-secret" not in env.values()


def test_broker_sync_does_not_write_the_copilot_entry_back(tmp_path, monkeypatch):
    pi = _ocs().pi
    real_auth = _auth(openai=100, **{"github-copilot": 500})
    copy_auth = _auth(openai=200, **{"github-copilot": 900})  # 内側で作られた (新しい) 分
    real, agent = _setup_auth(tmp_path, real_auth, copy_auth)
    monkeypatch.setattr(pi, "REAL_AGENT", real)
    pi.cleanup(agent, broker=True)
    merged = json.loads((real / "auth.json").read_text(encoding="utf-8"))
    assert merged["openai"] == copy_auth["openai"]  # 他は現行どおり戻る
    assert merged["github-copilot"] == real_auth["github-copilot"]


def test_broker_sync_does_not_create_a_missing_copilot_entry(tmp_path):
    pi = _ocs().pi
    copy_auth = _auth(openai=200, **{"github-copilot": 900})
    real, agent = _setup_auth(tmp_path, _auth(openai=100), copy_auth)
    assert pi.sync_auth_back(agent, real, skip=("github-copilot",)) is True
    assert "github-copilot" not in json.loads((real / "auth.json").read_text(encoding="utf-8"))


class _Handler(http.server.BaseHTTPRequestHandler):
    status = 200
    body = b"pis-broker-copilot"
    paths: list[str] = []  # noqa: RUF012

    def do_GET(self):
        type(self).paths.append(self.path)
        self.send_response(type(self).status)
        self.send_header("Content-Length", str(len(type(self).body)))
        self.end_headers()
        self.wfile.write(type(self).body)

    def log_message(self, *_args):
        pass


def _serve(status, body):
    handler = type("H", (_Handler,), {"status": status, "body": body, "paths": []})
    server = http.server.HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, handler, thread


def test_broker_identity_check_accepts_the_real_broker(monkeypatch):
    pi = _ocs().pi
    # 環境のプロキシ設定があっても使わない
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    server, handler, thread = _serve(200, b"pis-broker-copilot\n")
    try:
        pi.verify_broker(f"http://127.0.0.1:{server.server_port}")
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert handler.paths == ["/__pis_broker"]


@pytest.mark.parametrize(("status", "body"), [(200, b"hello"), (404, b"pis-broker-copilot")])
def test_broker_identity_check_refuses_another_service(status, body, capsys):
    pi = _ocs().pi
    server, _handler, thread = _serve(status, body)
    try:
        with pytest.raises(SystemExit):
            pi.verify_broker(f"http://127.0.0.1:{server.server_port}")
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert "別のサービス" in capsys.readouterr().err


def test_broker_identity_check_refuses_when_unreachable(capsys):
    pi = _ocs().pi
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()  # 閉じた直後のポートは誰も聞いていない
    with pytest.raises(SystemExit):
        pi.verify_broker(f"http://127.0.0.1:{port}")
    assert "動いていない" in capsys.readouterr().err


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
        # 生成した rules.json の broker (auto の機では Envoy を起動してしまう) を使わない
        code = ocs.pi.run_sandboxed(["--check", "--no-backup", "--no-broker"])
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
    assert code == 0
    # 差し替えが効いて (本物の ~/.pi/agent を使わず)、境界用の置き場は終わったら消える
    assert (tmp_path / "pi-sandbox").is_dir(), "AGENT_HOME の差し替えが効いていない"
    assert not list((tmp_path / "pi-sandbox").glob("agent-*")), "境界用の置き場が残っている"
    assert (real / "sessions").is_dir(), "REAL_AGENT の差し替えが効いていない"
