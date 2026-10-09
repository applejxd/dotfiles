"""pi のハーネス (``~/.config/pi/harness``) を、偽のモデル (faux) で通信なしに回す試験。

pi が無い環境では skip する。pi の内部の挙動に頼る点 (``/reload`` で組み込みが同じ名前で
戻ること・``details`` に生の出力が入ることなど) も、ここで検出する。
see docs/spec/pi-harness.md
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from agents_common import ROOT, agents_config_dir, load_common

sys.path.insert(0, str(ROOT / "scripts" / "agents"))
import generate as gen

PI = shutil.which("pi")
pytestmark = pytest.mark.skipif(PI is None, reason="pi is not installed")

HARNESS_SRC = ROOT / "home" / "dot_config" / "pi" / "harness" / "index.ts"
GUIDE_SRC = ROOT / "home" / "dot_config" / "opencode" / "guide-plugin"
COMMIT_MESSAGE_SRC = GUIDE_SRC / "commit-message.js"
DECIDE = ROOT / "home" / "dot_claude" / "hooks" / "executable_decide.py"
FIXTURES = Path(__file__).resolve().parent / "pi"
SECRET = "abc123rawsecret"


@pytest.fixture
def env(tmp_path):
    """ハーネスの置き場 (rules.json 付き)・作業ツリー・使い捨ての agent 置き場を用意する。"""
    # 配備先と同じ並び (ハーネスは ../../opencode/guide-plugin/commit-message.js を取り込む)
    harness = tmp_path / ".config" / "pi" / "harness"
    harness.mkdir(parents=True)
    shutil.copy2(HARNESS_SRC, harness / "index.ts")
    guide = tmp_path / ".config" / "opencode" / "guide-plugin"
    guide.mkdir(parents=True)
    shutil.copy2(COMMIT_MESSAGE_SRC, guide / "commit-message.js")
    rules = gen.build_pi_harness({}, load_common())
    rules["decide"] = str(DECIDE)
    # 子エージェントも偽のモデルで動かす (階層のモデルは認証が要る)
    for agent in rules["agents"].values():
        agent["model"] = None
    (harness / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
    proj = tmp_path / "proj"
    proj.mkdir()
    agent = tmp_path / "agent"
    agent.mkdir()
    base = {
        **os.environ,
        "PI_CODING_AGENT_DIR": str(agent),
        "AGENTS_CONFIG_DIR": str(agents_config_dir()),
        "TMPDIR": str(tmp_path),
    }
    # 作業している環境の変数を持ち込まない (Orca の中で回すと ORCA_* が入っている)
    for key in [k for k in base if k.startswith(("PI_HARNESS_", "ORCA_"))]:
        base.pop(key, None)
    return {"harness": harness, "proj": proj, "env": base, "tmp": tmp_path}


def run_pi(env, calls, *messages, extra=(), mode="print", session=False, **env_extra):
    args = [PI, *(() if session else ("--no-session",)), "--model", "faux/spike"]
    args += ["-nbt", "-ne", "-e", "builtin:mcp", "-e", str(env["harness"])]
    args += [*extra, "-e", str(FIXTURES / "faux.ts")]
    if mode == "json":
        args += ["--mode", "json"]
    else:
        args += ["-p"]
    proc = subprocess.run(
        [*args, *(messages or ("go",))],
        cwd=env["proj"],
        env={**env["env"], "FAUX_TOOL_CALLS": json.dumps(calls), **env_extra},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )
    return proc


def bash_call(command):
    return [{"name": "guarded_bash", "args": {"command": command}}]


def lines(proc):
    return proc.stdout.strip().splitlines()


def test_only_guarded_tools_are_declared(env):
    proc = run_pi(env, [])
    assert proc.returncode == 0, proc.stderr
    tools = json.loads(lines(proc)[0].removeprefix("TOOLS="))
    names = ("bash", "edit", "find", "grep", "ls", "read", "task", "write")
    assert tools == sorted(f"guarded_{t}" for t in names)


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("wc -c /dev/null", "isError=false"),
        ("git push", "isError=true :: `git push` は deny"),
        # UI の無い起動では確認できないので拒否
        ("touch made-by-pi", "isError=true :: not approved:"),
    ],
)
def test_decisions_reach_the_tools(env, command, expected):
    proc = run_pi(env, bash_call(command))
    assert expected in proc.stdout, proc.stdout + proc.stderr
    assert not (env["proj"] / "made-by-pi").exists()


def test_bypass_runs_ask_but_not_deny(env):
    run_pi(env, bash_call("touch made-by-pi"), PI_HARNESS_BYPASS="1")
    assert (env["proj"] / "made-by-pi").exists()
    proc = run_pi(env, bash_call("git push"), PI_HARNESS_BYPASS="1")
    assert "isError=true" in proc.stdout


def test_reader_role_does_not_see_bash(env):
    proc = run_pi(env, bash_call("wc -c /dev/null"), PI_HARNESS_ROLE="reader")
    assert lines(proc)[0] == 'TOOLS=["guarded_find","guarded_grep","guarded_ls","guarded_read"]'
    assert "Tool guarded_bash not found" in proc.stdout


def test_unknown_role_registers_no_tools(env):
    proc = run_pi(env, bash_call("wc -c /dev/null"), PI_HARNESS_ROLE="nobody")
    assert lines(proc)[0] == "TOOLS=[]", proc.stdout


def test_broken_decide_is_denied(env):
    rules = json.loads((env["harness"] / "rules.json").read_text(encoding="utf-8"))
    rules["decide"] = str(env["tmp"] / "missing.py")
    (env["harness"] / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
    proc = run_pi(env, bash_call("wc -c /dev/null"))
    assert "isError=true" in proc.stdout, proc.stdout


def test_missing_rules_stop_startup(env):
    (env["harness"] / "rules.json").unlink()
    proc = run_pi(env, bash_call("wc -c /dev/null"))
    assert proc.returncode != 0


@pytest.mark.parametrize("mode", ["syntax", "delete"])
def test_reload_without_harness_leaves_no_tools(env, mode):
    builtin = {"name": "bash", "args": {"command": "wc -c /dev/null"}}
    calls = [*bash_call("wc -c /dev/null"), builtin]
    proc = run_pi(
        env,
        calls,
        "/spike-reload",
        "go",
        SPIKE_BREAK_MODE=mode,
        SPIKE_BREAK_FILE=str(env["harness"] / "index.ts"),
    )
    assert "TOOLS=[]" in proc.stdout, proc.stdout
    assert "Tool guarded_bash not found" in proc.stdout
    assert "Tool bash not found" in proc.stdout


def test_input_rewritten_after_the_decision_is_rejected(env):
    proc = run_pi(
        env,
        bash_call("wc -c /dev/null"),
        extra=("-e", str(FIXTURES / "mutator.ts")),
        MUTATE_TO=f"touch {env['proj']}/pwned",
    )
    assert "実行前の判定で止めた" in proc.stdout, proc.stdout
    assert not (env["proj"] / "pwned").exists()


def _secret_script(env):
    (env["proj"] / "big.py").write_text(
        "import time\n"
        f'print("password = \\"{SECRET}\\"", flush=True)\n'
        "time.sleep(1.5)\n"
        'for i in range(3000):\n    print(f"line {i} " + "x" * 40)\n'
        f'print("password = \\"{SECRET}\\" tail", flush=True)\n',
        encoding="utf-8",
    )


def test_bash_output_is_redacted_everywhere(env):
    _secret_script(env)
    # python3 は既定で確認になるので bypass で通す (判定ではなく伏字化を見る試験)
    proc = run_pi(env, bash_call("python3 big.py"), mode="json", PI_HARNESS_BYPASS="1")
    assert proc.returncode == 0, proc.stderr
    assert "伏字" in proc.stdout
    assert SECRET not in proc.stdout
    spills = {p for p in env["tmp"].glob("pi-bash-*.log")}
    assert spills, "退避ファイルができていない (出力の量か pi の版を確かめる)"
    for spill in spills:
        assert SECRET not in spill.read_text(encoding="utf-8")
    # details に生の出力が入る pi の挙動 (spike の E3) が前提なので、入っていることも確かめる
    events = [json.loads(line) for line in lines(proc) if line.startswith("{")]
    ends = [e for e in events if e.get("type") == "tool_execution_end"]
    assert any("truncation" in json.dumps(e["result"].get("details") or {}) for e in ends)


def test_output_of_commands_touching_protected_paths_is_withheld(env):
    proc = run_pi(env, bash_call("wc -c ~/.ssh/known_hosts"), PI_HARNESS_BYPASS="1")
    # wc は deny (秘密のパスの読み取り) で止まるか、通っても出力を伏せる
    assert "isError=true" in proc.stdout or "[伏字] 保護対象のパス" in proc.stdout, proc.stdout


# ─── 子エージェント ─────────────────────────────────────────────────


def run_child(env, agent, child_calls, **env_extra):
    calls = [{"name": "guarded_task", "args": {"agent": agent, "task": "do it"}}]
    return run_pi(
        env,
        calls,
        FAUX_CHILD_TOOL_CALLS=json.dumps(child_calls),
        PI_HARNESS_TEST_CHILD_EXT=str(FIXTURES / "faux.ts"),
        **env_extra,
    )


def test_child_cannot_start_another_child(env):
    calls = [{"name": "guarded_task", "args": {"agent": "worker", "task": "x"}}]
    proc = run_child(env, "worker", calls)
    assert "completed" in proc.stdout, proc.stdout
    assert "Tool guarded_task not found" in proc.stdout


def test_reader_child_does_not_get_bash(env):
    proc = run_child(env, "explore", bash_call("wc -c /dev/null"))
    assert "Tool guarded_bash not found" in proc.stdout, proc.stdout


def test_child_ask_is_returned_as_blocked(env):
    proc = run_child(env, "worker", bash_call("touch by-child"))
    assert "child worker: blocked" in proc.stdout, proc.stdout
    assert "needs the user's approval" in proc.stdout
    assert "isError=true" in proc.stdout
    assert not (env["proj"] / "by-child").exists()


def test_parent_bypass_reaches_only_children_that_inherit_it(env):
    proc = run_child(env, "worker", bash_call("touch by-child"), PI_HARNESS_BYPASS="1")
    assert "child worker: completed" in proc.stdout, proc.stdout
    assert (env["proj"] / "by-child").exists()


@pytest.mark.parametrize("agent", ["worker", "commit"])
def test_child_role_denies_git_state_changes_even_with_bypass(env, agent):
    proc = run_child(env, agent, bash_call("git add -- x"), PI_HARNESS_BYPASS="1")
    assert "shell_deny" in proc.stdout, proc.stdout


def test_commit_child_reads_git_without_confirmation(env):
    subprocess.run(["git", "init", "-q"], cwd=env["proj"], check=True)
    proc = run_child(env, "commit", bash_call("git status --short"))
    assert "child commit: completed" in proc.stdout, proc.stdout
    assert "tool error" not in proc.stdout


# ─── MCP ────────────────────────────────────────────────────────────


def test_mcp_servers_are_registered_by_the_harness_and_judged(env):
    rules = json.loads((env["harness"] / "rules.json").read_text(encoding="utf-8"))
    config = {"command": sys.executable, "args": [str(FIXTURES / "mcp_server.py")]}
    rules["mcp"] = [{"name": "spike", "config": {**config, "exposure": "direct"}}]
    (env["harness"] / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
    proc = run_pi(env, [{"name": "mcp__spike__echo_secret", "args": {}}])
    assert "mcp__spike__echo_secret" in lines(proc)[0], proc.stdout
    # 実装役では MCP のツールは既定の扱い (確認)。UI の無い起動では拒否になる
    assert "isError=true :: not approved:" in proc.stdout, proc.stdout
    assert "mcp-raw-secret" not in proc.stdout


def test_guides_point_to_the_tool_to_use(env):
    (env["proj"] / "f.txt").write_text("x\n", encoding="utf-8")
    proc = run_pi(env, bash_call("cat f.txt"), PI_HARNESS_BYPASS="1")
    assert "isError=true" in proc.stdout, proc.stdout
    assert "read ツールを使ってください" in proc.stdout


# ─── 起動の入口 (pis) ───────────────────────────────────────────────

PIS = ROOT / "home" / "dot_local" / "bin" / "executable_pis"


@pytest.fixture
def pis_env(env, tmp_path):
    """pis が読む ~/.config/pi/harness を、一時的な HOME の下に置く。"""
    home = tmp_path / "home"
    shutil.copytree(env["harness"], home / ".config" / "pi" / "harness")
    return {**env, "home": home, "env": {**env["env"], "HOME": str(home)}}


def run_pis(pis_env, *pis_args, calls=(), **env_extra):
    faux = str(FIXTURES / "faux.ts")
    args = [str(PIS), *pis_args, "--model", "faux/spike", "-e", faux, "-p", "go"]
    return subprocess.run(
        ["bash", *args],
        cwd=pis_env["proj"],
        env={**pis_env["env"], "FAUX_TOOL_CALLS": json.dumps(list(calls)), **env_extra},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )


def test_pis_starts_pi_with_the_harness(pis_env):
    proc = run_pis(pis_env, calls=bash_call("touch made-by-pi"), PI_HARNESS_CHILD="1")
    assert proc.returncode == 0, proc.stderr
    assert "guarded_task" in lines(proc)[0], "子の印を外して起動していない"
    assert "isError=true :: not approved:" in proc.stdout


def test_pis_bypass_and_role(pis_env):
    run_pis(pis_env, "--bypass", calls=bash_call("touch made-by-pi"))
    assert (pis_env["proj"] / "made-by-pi").exists()
    proc = run_pis(pis_env, "--role", "reader")
    assert lines(proc)[0] == 'TOOLS=["guarded_find","guarded_grep","guarded_ls","guarded_read"]'


def test_pis_refuses_without_the_harness(pis_env):
    shutil.rmtree(pis_env["home"] / ".config" / "pi" / "harness")
    proc = run_pis(pis_env)
    assert proc.returncode == 1 and "ハーネスが無い" in proc.stderr


def test_pis_refuses_servers_in_the_agent_mcp_json(pis_env):
    agent = Path(pis_env["env"]["PI_CODING_AGENT_DIR"])
    (agent / "mcp.json").write_text('{"mcpServers": {"x": {"command": "true"}}}', encoding="utf-8")
    proc = run_pis(pis_env)
    assert proc.returncode == 1 and "mcp.json" in proc.stderr
    (agent / "mcp.json").write_text('{"mcpServers": {}}', encoding="utf-8")
    assert run_pis(pis_env).returncode == 0


def test_pis_boundary_hands_over_to_ocs(pis_env, tmp_path):
    stub_bin = tmp_path / "stub-bin"
    stub_bin.mkdir()
    log = tmp_path / "ocs.log"
    stub = stub_bin / "ocs"
    script = (
        "#!/bin/sh\n"
        'echo "$*" > "$OCS_LOG"\n'
        'echo "$PI_HARNESS_ROLE:$PI_HARNESS_BYPASS" >> "$OCS_LOG"\n'
    )
    stub.write_text(script, encoding="utf-8")
    stub.chmod(0o755)
    proc = subprocess.run(
        ["bash", str(PIS), "--boundary", "--bypass", "--role", "reader", "-c"],
        cwd=pis_env["proj"],
        env={**pis_env["env"], "PATH": f"{stub_bin}:{os.environ['PATH']}", "OCS_LOG": str(log)},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert log.read_text(encoding="utf-8").splitlines() == ["--harness pi -c", "reader:1"]


# ─── 圧縮・commit の表示・整形・RPC ─────────────────────────────────


def _session_entries(session_dir):
    entries = []
    for path in session_dir.rglob("*.jsonl"):
        entries += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return entries


def test_compaction_carries_the_handover_instructions_and_file_lists(env):
    settings = env["proj"] / ".pi"
    settings.mkdir()
    small = '{"compaction": {"keepRecentTokens": 1}}'
    (settings / "settings.json").write_text(small, encoding="utf-8")
    (env["proj"] / "f.txt").write_text("x\n", encoding="utf-8")
    sessions = env["tmp"] / "sessions"
    calls = [{"name": "guarded_read", "args": {"path": "f.txt"}}]
    proc = run_pi(
        env,
        calls,
        "go",
        "again",  # 履歴の要約 (指示が入る側) が空にならないよう、ターンを複数にする
        "/spike-compact",
        session=True,
        extra=("--approve", "--session-dir", str(sessions), "-e", str(FIXTURES / "compact.ts")),
    )
    assert proc.returncode == 0, proc.stderr
    compactions = [e for e in _session_entries(sessions) if e.get("type") == "compaction"]
    assert compactions, proc.stdout + proc.stderr
    entry = compactions[-1]
    assert "INSTR=yes" in entry["summary"], f"圧縮の指示が要約の依頼に入っていない: {proc.stderr}"
    details = entry.get("details") or {}
    assert "f.txt" in json.dumps(details), "別名のツールで読んだファイルが一覧に無い"


def _rpc(env, calls, answers, timeout=120):
    """pi を RPC モードで動かし、確認の要求 (extension_ui_request) に answers の順に応える。"""
    args = [PI, "--no-session", "--model", "faux/spike", "-nbt", "-ne", "-e", "builtin:mcp"]
    args += ["-e", str(env["harness"]), "-e", str(FIXTURES / "faux.ts"), "--mode", "rpc"]
    proc = subprocess.Popen(
        args,
        cwd=env["proj"],
        env={**env["env"], "FAUX_TOOL_CALLS": json.dumps(calls)},
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    requests = []
    proc.stdin.write(json.dumps({"type": "prompt", "message": "go"}) + "\n")
    proc.stdin.flush()
    deadline = time.time() + timeout
    try:
        for line in proc.stdout:
            if time.time() > deadline:
                break
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("type") == "extension_ui_request" and event.get("method") == "confirm":
                requests.append(event)
                answer = answers[len(requests) - 1] if len(requests) <= len(answers) else False
                reply = {"type": "extension_ui_response", "id": event["id"], "confirmed": answer}
                proc.stdin.write(json.dumps(reply) + "\n")
                proc.stdin.flush()
            if event.get("type") == "agent_end":
                break
    finally:
        proc.kill()
    return requests


def test_git_commit_confirmation_shows_subject_and_body(env):
    subprocess.run(["git", "init", "-q"], cwd=env["proj"], check=True)
    command = "git commit -m 'feat: 件名です' -m '本文の 1 行目'"
    requests = _rpc(env, bash_call(command), [False])
    assert len(requests) == 1, requests
    message = requests[0]["message"]
    assert "件名: feat: 件名です" in message and "本文の 1 行目" in message
    assert "理由:" in message
    # RPC ではクライアントが応えないと永久に待つので、期限が付く
    assert requests[0].get("timeout"), "確認に期限が付いていない"


def test_approved_rpc_confirmation_runs_the_tool(env):
    requests = _rpc(env, bash_call("touch made-via-rpc"), [True])
    assert len(requests) == 1
    assert (env["proj"] / "made-via-rpc").exists()


@pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff is not installed")
def test_python_files_are_formatted_after_a_write(env):
    messy = "x   =   1\nprint( x )\n"
    calls = [{"name": "guarded_write", "args": {"path": "m.py", "content": messy}}]
    run_pi(env, calls)
    assert (env["proj"] / "m.py").read_text(encoding="utf-8") == "x = 1\nprint(x)\n"


@pytest.mark.skipif(shutil.which("markdownlint-cli2") is None, reason="markdownlint-cli2 無し")
def test_markdownlint_warnings_reach_the_model(env):
    body = "# Title\n\n```\ncode without a language\n```\n"
    calls = [{"name": "guarded_write", "args": {"path": "d.md", "content": body}}]
    proc = run_pi(env, calls)
    assert "[markdownlint] issues remain" in proc.stdout, proc.stdout


# ─── プロンプトテンプレート (/fleet)・キーバインド・共通の指示 ──────


def _render(template: Path) -> str:
    chezmoi = shutil.which("chezmoi")
    if chezmoi is None:
        pytest.skip("chezmoi is not installed")
    done = subprocess.run(
        [chezmoi, "--source", str(ROOT), "execute-template"],
        input=template.read_text(encoding="utf-8"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return done.stdout


def test_fleet_prompt_template_expands_under_no_extensions(env):
    prompts = Path(env["env"]["PI_CODING_AGENT_DIR"]) / "prompts"
    prompts.mkdir()
    rendered = _render(ROOT / "home" / "dot_pi" / "agent" / "prompts" / "fleet.md.tmpl")
    (prompts / "fleet.md").write_text(rendered, encoding="utf-8")
    proc = run_pi(env, [], "/fleet README を直す", FAUX_ECHO_USER="1")
    assert proc.returncode == 0, proc.stderr
    # 引数が $ARGUMENTS に入り、テンプレート本文が利用者の発言として届く
    assert "依頼:\nREADME を直す" in proc.stdout, proc.stdout
    assert "guarded_task" in proc.stdout


def test_shared_instructions_are_rendered_for_pi():
    rendered = _render(ROOT / "home" / "dot_pi" / "agent" / "AGENTS.md.tmpl")
    assert rendered.strip(), "共通の指示が空"
    claude = _render(ROOT / "home" / "dot_claude" / "CLAUDE.md.tmpl")
    assert rendered.strip() == claude.strip()


def test_keybindings_are_generated_from_the_declaration():
    out = gen.pi_keybindings({}, load_common())
    assert out["app.interrupt"] == ["escape", "ctrl+c"] and out["app.clear"] == []
    assert out == load_common()["pi"]["keybinds"]


@pytest.mark.parametrize("bad", [{"app.exit": ""}, {"app.exit": [1]}, {"app.exit": None}])
def test_bad_keybindings_stop_generation(bad):
    common = load_common()
    common["pi"]["keybinds"] = bad
    with pytest.raises(SystemExit, match=r"pi\.keybinds"):
        gen.pi_keybindings({}, common)


# ─── Orca のステータス拡張 ──────────────────────────────────────────


def _orca_extension(pis_env, probe, marker=True):
    """Orca が置く拡張の代役。呼ばれたら印のファイルを書く。"""
    agent = Path(pis_env["env"]["PI_CODING_AGENT_DIR"])
    (agent / "extensions").mkdir(exist_ok=True)
    head = "// @orca-managed-pi-extension\n" if marker else "// someone else\n"
    body = (
        head
        + 'import { writeFileSync } from "node:fs";\n'
        + "export default function (pi) {\n"
        + '  pi.registerCommand("orca-probe", { description: "p", handler: async () => {\n'
        + f'    writeFileSync("{probe}", "loaded");\n'
        + "  } });\n}\n"
    )
    (agent / "extensions" / "orca-agent-status.ts").write_text(body, encoding="utf-8")


def _run_pis_probe(pis_env, **env_extra):
    faux = str(FIXTURES / "faux.ts")
    return subprocess.run(
        ["bash", str(PIS), "--model", "faux/spike", "-e", faux, "-p", "/orca-probe"],
        cwd=pis_env["proj"],
        env={**pis_env["env"], "FAUX_TOOL_CALLS": "[]", **env_extra},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )


def test_pis_loads_orcas_status_extension_only_from_orca_with_its_marker(pis_env, tmp_path):
    probe = tmp_path / "probe"
    _orca_extension(pis_env, probe)
    _run_pis_probe(pis_env)
    assert not probe.exists(), "Orca の外で Orca の拡張を読んだ"
    _run_pis_probe(pis_env, ORCA_AGENT_HOOK_PORT="1")
    assert probe.exists(), "Orca の中で Orca の拡張を読んでいない"
    probe.unlink()
    _orca_extension(pis_env, probe, marker=False)
    _run_pis_probe(pis_env, ORCA_AGENT_HOOK_PORT="1")
    assert not probe.exists(), "印の無い拡張を読んだ"
