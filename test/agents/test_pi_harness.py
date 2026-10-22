"""pi のフルガード (``~/.config/pi/harness``) を、偽のモデル (faux) で通信なしに回す試験。

pi が無い環境では skip する。pi の内部の挙動に頼る点 (``/reload`` で組み込みが同じ名前で
戻ること・``details`` に生の出力が入ることなど) も、ここで検出する。
see docs/spec/pi-guard.md
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
TODO_EXT = ROOT / "home" / "dot_pi" / "agent" / "extensions" / "todo" / "index.ts"
COMMIT_MESSAGE_SRC = ROOT / "home" / "dot_config" / "pi" / "harness" / "commit-message.js"
FIXTURES = Path(__file__).resolve().parent / "pi"
SECRET = "abc123rawsecret"


@pytest.fixture
def env(tmp_path):
    """フルガードの置き場 (rules.json 付き)・作業ツリー・使い捨ての agent 置き場を用意する。"""
    harness = tmp_path / ".config" / "pi" / "harness"
    harness.mkdir(parents=True)
    shutil.copy2(HARNESS_SRC, harness / "index.ts")
    shutil.copytree(HARNESS_SRC.parent / "judge", harness / "judge")
    shutil.copy2(HARNESS_SRC.parent / "redact.ts", harness / "redact.ts")
    shutil.copy2(HARNESS_SRC.parent / "canary.ts", harness / "canary.ts")
    shutil.copy2(HARNESS_SRC.parent / "children.ts", harness / "children.ts")
    shutil.copy2(HARNESS_SRC.parent / "audit.ts", harness / "audit.ts")
    shutil.copy2(COMMIT_MESSAGE_SRC, harness / "commit-message.js")
    rules = gen.build_pi_harness({}, load_common())
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


# ─── サンドボックスのゲート (カナリアで実測できたときだけ緩和する) ───────────────


def _boundary_env(env, *, read=None, write=None, allowed=True):
    """サンドボックスの内側のつもりの環境変数。カナリアの既定は「読めない・書けない」(存在しない場所)。"""
    tmp = env["tmp"]
    out = {
        "PI_HARNESS_BOUNDARY": "1",
        "PI_HARNESS_CANARY_READ": str(read or tmp / "hidden" / "canary-read"),
        "PI_HARNESS_CANARY_WRITE": str(write or tmp / "hidden" / "canary-write"),
    }
    if allowed:
        root = str(env["proj"])
        out["PI_HARNESS_ALLOWED"] = json.dumps({"read": [root], "write": [root]})
    return out


def test_boundary_expected_but_canary_readable_refuses_to_start(env):
    readable = env["tmp"] / "readable"
    readable.write_text("secret", encoding="utf-8")
    proc = run_pi(env, bash_call("touch made-by-pi"), **_boundary_env(env, read=readable))
    assert proc.returncode != 0 and "サンドボックスを確認できない" in proc.stdout + proc.stderr
    assert not (env["proj"] / "made-by-pi").exists()


def test_boundary_expected_but_canary_writable_refuses_to_start(env):
    writable = env["tmp"] / "writable"
    proc = run_pi(env, [], **_boundary_env(env, write=writable))
    assert proc.returncode != 0 and "サンドボックスを確認できない" in proc.stdout + proc.stderr
    assert not writable.exists(), "カナリアの書き込みの跡を残している"
    existing = env["tmp"] / "existing"
    existing.write_text("x", encoding="utf-8")
    proc = run_pi(env, [], **_boundary_env(env, write=existing))
    assert proc.returncode != 0, "既にあるパスへの書き込みの失敗は、拒否の証明にならない"


def test_boundary_env_alone_never_relaxes(env):
    # 一覧・カナリアの場所が無い自己申告だけでは、起動しない (緩和もしない)
    proc = run_pi(env, bash_call("touch made-by-pi"), PI_HARNESS_BOUNDARY="1")
    assert proc.returncode != 0 and not (env["proj"] / "made-by-pi").exists()
    proc = run_pi(env, bash_call("touch made-by-pi"), **_boundary_env(env, allowed=False))
    assert proc.returncode != 0 and not (env["proj"] / "made-by-pi").exists()


def test_proven_boundary_drops_the_plain_shell_ask_and_explains_outside_access(env):
    proven = _boundary_env(env)
    proc = run_pi(env, bash_call("touch made-by-pi"), **proven)
    assert proc.returncode == 0, proc.stderr
    assert (env["proj"] / "made-by-pi").exists(), "証明できたのに日常の shell を確認した"
    # 規則に当たる deny は変わらない
    proc = run_pi(env, bash_call("git push"), **proven)
    assert "isError=true :: `git push` は deny" in proc.stdout
    # 許可の外は、確認ではなく理由つきの deny
    proc = run_pi(env, [{"name": "guarded_read", "args": {"path": "/etc/hostname"}}], **proven)
    assert "サンドボックスの外" in proc.stdout, proc.stdout + proc.stderr


def test_reader_role_does_not_see_bash(env):
    proc = run_pi(env, bash_call("wc -c /dev/null"), PI_HARNESS_ROLE="reader")
    assert lines(proc)[0] == 'TOOLS=["guarded_find","guarded_grep","guarded_ls","guarded_read"]'
    assert "Tool guarded_bash not found" in proc.stdout


def test_the_default_role_comes_from_the_rules_and_the_environment_overrides_it(env):
    path = env["harness"] / "rules.json"
    rules = json.loads(path.read_text(encoding="utf-8"))
    rules["default_role"] = "reader"
    path.write_text(json.dumps(rules), encoding="utf-8")
    proc = run_pi(env, bash_call("wc -c /dev/null"))
    assert lines(proc)[0] == 'TOOLS=["guarded_find","guarded_grep","guarded_ls","guarded_read"]'
    proc = run_pi(env, bash_call("wc -c /dev/null"), PI_HARNESS_ROLE="implementer")
    assert "guarded_bash" in lines(proc)[0]


def test_unknown_role_registers_no_tools(env):
    proc = run_pi(env, bash_call("wc -c /dev/null"), PI_HARNESS_ROLE="nobody")
    assert lines(proc)[0] == "TOOLS=[]", proc.stdout


def test_broken_judge_settings_are_denied(env):
    rules = json.loads((env["harness"] / "rules.json").read_text(encoding="utf-8"))
    rules["judge"]["common"] = {}  # [pi] が無い設定は、判定が失敗して deny になる
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


def _skill_dir(tmp, name, description, group=None):
    """``<tmp>/skills-<group>/<name>/SKILL.md`` を作り、スキル群のディレクトリを返す。本文は description と同じ印。"""
    base = tmp / f"skills-{group or name}"
    (base / name).mkdir(parents=True)
    (base / name / "SKILL.md").write_text(
        f'---\nname: {name}\ndescription: "{description}"\n---\n# {name}\n{description}\n',
        encoding="utf-8",
    )
    return base


# ★フルガードの下では組み込みの read / bash が無いので、pi 自身はスキルの一覧をシステムプロンプトへ入れない。
#   フルガードが同じ形で足す (下の test_the_harness_adds_the_skill_list...)。読まれたかは /skill:<名前> の展開でも見る
def test_explicit_skill_loads_under_no_approve_and_global_wins_on_a_name_clash(env):
    # pis は --no-approve のまま、作業先のスキルだけを --skill で足す。同名ならグローバルが勝つ (乗っ取られない)
    project = _skill_dir(env["tmp"], "projonly", "PROJECT-ONLY-DESC")
    clash = _skill_dir(env["tmp"], "clash", "PROJECT-CLASH-DESC", group="project-clash")
    global_dir = _skill_dir(env["tmp"], "clash", "GLOBAL-CLASH-DESC", group="global-clash")
    (env["tmp"] / "agent" / "settings.json").write_text(
        json.dumps({"skills": [str(global_dir)]}), encoding="utf-8"
    )
    extra = ("--no-approve", "--skill", str(project), "--skill", str(clash))
    proc = run_pi(env, [], "/skill:projonly go", extra=extra, FAUX_ECHO_USER="1")
    assert proc.returncode == 0, proc.stderr
    assert "PROJECT-ONLY-DESC" in proc.stdout, proc.stdout
    proc = run_pi(env, [], "/skill:clash go", extra=extra, FAUX_ECHO_USER="1")
    assert "GLOBAL-CLASH-DESC" in proc.stdout and "PROJECT-CLASH-DESC" not in proc.stdout, (
        proc.stdout
    )


def test_the_harness_adds_the_skill_list_to_the_system_prompt(env):
    # pi は宣言されたツールに read / bash が無いと一覧を入れない。フルガードが guarded_* を読むツールとして足す
    shown = _skill_dir(env["tmp"], "shown", "SHOWN-SKILL-DESC")
    hidden = _skill_dir(env["tmp"], "hidden", "HIDDEN-SKILL-DESC")
    (hidden / "hidden" / "SKILL.md").write_text(
        '---\nname: hidden\ndescription: "HIDDEN-SKILL-DESC"\ndisable-model-invocation: true\n---\n# h\n',
        encoding="utf-8",
    )
    extra = ("--no-approve", "--skill", str(shown), "--skill", str(hidden))
    proc = run_pi(env, [], extra=extra, FAUX_DUMP_PROMPT="1")
    assert proc.returncode == 0, proc.stderr
    prompt = proc.stdout
    assert "<available_skills>" in prompt and "<name>shown</name>" in prompt, prompt
    assert "SHOWN-SKILL-DESC" in prompt
    assert "Use the guarded_read tool to load a skill's file" in prompt
    # モデルが自動で選ばないように指定したスキルは載せない (pi の標準と同じ)
    assert "HIDDEN-SKILL-DESC" not in prompt
    # bypass でも同じ
    proc = run_pi(env, [], extra=extra, FAUX_DUMP_PROMPT="1", PI_HARNESS_BYPASS="1")
    assert "<name>shown</name>" in proc.stdout


def test_the_child_also_gets_the_skill_list(env):
    project = _skill_dir(env["tmp"], "childlist", "CHILD-LIST-DESC")
    calls = [{"name": "guarded_task", "args": {"agent": "worker", "task": "list skills"}}]
    common = dict(FAUX_CHILD_SKILLS="1", PI_HARNESS_TEST_CHILD_EXT=str(FIXTURES / "faux.ts"))
    proc = run_pi(env, calls, extra=("--skill", str(project)), **common)
    assert proc.returncode == 0, proc.stderr
    assert "SKILLS=[" in proc.stdout and '"childlist"' in proc.stdout, proc.stdout


def test_child_inherits_the_parents_explicit_skills(env):
    project = _skill_dir(env["tmp"], "childskill", "CHILD-SKILL-DESC")
    calls = [{"name": "guarded_task", "args": {"agent": "worker", "task": "/skill:childskill go"}}]
    common = dict(FAUX_CHILD_ECHO_USER="1", PI_HARNESS_TEST_CHILD_EXT=str(FIXTURES / "faux.ts"))
    proc = run_pi(env, calls, extra=("--skill", str(project)), **common)
    assert proc.returncode == 0, proc.stderr
    assert '<skill name="childskill"' in proc.stdout, proc.stdout
    # 親が足していなければ、子にも入らない
    proc = run_pi(env, calls, **common)
    assert '<skill name="childskill"' not in proc.stdout, proc.stdout


def test_task_tool_is_listed_in_the_system_prompt(env):
    # promptSnippet が無い自作ツールは Available tools に出ず、モデルが気付けない
    proc = run_pi(env, [], FAUX_DUMP_PROMPT="1")
    assert proc.returncode == 0, proc.stderr
    prompt = proc.stdout
    assert "- guarded_task:" in prompt, prompt
    assert 'guarded_task with agent "review"' in prompt, prompt


def test_todo_and_activity_tools_are_listed_in_the_system_prompt(env):
    # promptSnippet が無い自作ツールは Available tools に出ず、モデルが気付けない
    activity = TODO_EXT.parent.parent / "activity" / "index.ts"
    extra = ("-e", str(TODO_EXT), "-e", str(activity))
    proc = run_pi(env, [], extra=extra, FAUX_DUMP_PROMPT="1")
    assert proc.returncode == 0, proc.stderr
    prompt = proc.stdout
    for tool in ("todo", "bg_run", "bg_log", "bg_kill"):
        assert f"- {tool}:" in prompt, prompt


def test_child_cannot_start_another_child(env):
    calls = [{"name": "guarded_task", "args": {"agent": "worker", "task": "x"}}]
    proc = run_child(env, "worker", calls)
    assert "completed" in proc.stdout, proc.stdout
    assert "Tool guarded_task not found" in proc.stdout


def test_review_child_reads_with_the_same_read_only_commands_as_explore(env):
    # review は差分を自分で取りに行けるよう explorer 役。それ以外の shell は拒否
    proc = run_child(env, "review", bash_call("wc -c /dev/null"))
    assert "0 /dev/null" in proc.stdout and "child review: completed" in proc.stdout, proc.stdout
    proc = run_child(env, "review", bash_call("touch made-by-review"))
    assert "tool error: guarded_bash" in proc.stdout, proc.stdout
    assert not (env["proj"] / "made-by-review").exists()


# see docs/spec/pi-guard.md#review-への依頼の書き方
@pytest.mark.parametrize(
    "command",
    [
        "git log --oneline -5",
        "git show HEAD",
        "git show HEAD --stat",
        "git diff",
        "git diff HEAD~1",
        "git diff HEAD",
        "git status --short",
        "git show HEAD -- file.txt",
        "git diff HEAD~1 -- file.txt",
        "git diff -- file.txt",
        "git log -- file.txt",
    ],
)
def test_review_child_may_read_a_revision_with_git(env, command):
    # review は差分を自分で読む。リビジョンを付けた形も、判定で「どの規則にも当たらない」と拒まれない
    proc = run_child(env, "review", bash_call(command))
    assert "どの規則にも当たらない" not in proc.stdout, proc.stdout


def test_explore_child_gets_only_the_read_only_commands(env):
    # wc と読み取り専用の git だけ確認なしで通る。それ以外の shell は拒否 (子は承認できないところで止まる)
    proc = run_child(env, "explore", bash_call("wc -c /dev/null"))
    assert "0 /dev/null" in proc.stdout and "child explore: completed" in proc.stdout, proc.stdout
    proc = run_child(env, "explore", bash_call("touch made-by-explore"))
    assert "tool error: guarded_bash" in proc.stdout, proc.stdout
    assert not (env["proj"] / "made-by-explore").exists()
    proc = run_child(env, "explore", bash_call("git commit -m x"))
    assert "tool error: guarded_bash" in proc.stdout, proc.stdout


ASK_READ_CHILD = FIXTURES / "ask_read_child.ts"
BTW_EXT = ROOT / "home" / "dot_pi" / "agent" / "extensions" / "btw" / "index.ts"
CHILD_ECHO = dict(FAUX_CHILD_ECHO_USER="1", PI_HARNESS_TEST_CHILD_EXT=str(FIXTURES / "faux.ts"))


def test_ask_read_child_entry_runs_only_read_only_agents(env):
    # btw が使う入口。利用者のコマンドなので判定は通さないかわりに、読み取り専用の役割だけを許す
    proc = run_pi(
        env, [], "/askchild explore hello-child", extra=("-e", str(ASK_READ_CHILD)), **CHILD_ECHO
    )
    out = proc.stdout + proc.stderr
    assert "ASKCHILD ok=true" in out and "CHILD_USER=hello-child" in out, out
    for agent in ("worker", "commit"):
        proc = run_pi(
            env,
            [],
            f"/askchild {agent} hello-child",
            extra=("-e", str(ASK_READ_CHILD)),
            **CHILD_ECHO,
        )
        out = proc.stdout + proc.stderr
        assert "ASKCHILD ok=false not a read-only agent" in out, out
        assert "CHILD_USER=" not in out


def test_btw_asks_an_explore_child_by_default_and_plain_does_not(env):
    # 子の入口を記録するものに差し替えて、btw が渡すものを見る (print モードでは答えの表示が見えない)
    extra = ("-e", str(ASK_READ_CHILD), "-e", str(BTW_EXT))
    proc = run_pi(env, [], "/btw where-is-x", extra=extra, ASKCHILD_STUB="1")
    out = proc.stdout + proc.stderr
    assert (
        "STUB agent=explore" in out
        and "ついでの質問: where-is-x" in out
        and "<conversation>" in out
    ), out
    proc = run_pi(env, [], "/btw --plain where-is-x", extra=extra, ASKCHILD_STUB="1")
    assert proc.returncode == 0 and "STUB" not in proc.stdout + proc.stderr, (
        proc.stdout + proc.stderr
    )


def test_child_ask_is_returned_as_blocked(env):
    proc = run_child(env, "worker", bash_call("touch by-child"))
    assert "child worker: blocked" in proc.stdout, proc.stdout
    assert "needs the user's approval" in proc.stdout
    assert "isError=true" in proc.stdout
    assert not (env["proj"] / "by-child").exists()


def _rounds(env, rounds, **env_extra):
    """親が複数ターンで guarded_task を呼ぶ。子は受けた利用者の発言の数を返す (履歴が続いているかが分かる)。"""
    return run_pi(
        env,
        [],
        FAUX_TOOL_ROUNDS=json.dumps(rounds),
        FAUX_CHILD_TOOL_CALLS="[]",
        FAUX_COUNT_USER="1",
        PI_HARNESS_TEST_CHILD_EXT=str(FIXTURES / "faux.ts"),
        **env_extra,
    )


def _task(**args):
    return {"name": "guarded_task", "args": args}


def test_kept_child_remembers_the_conversation_until_closed(env):
    proc = _rounds(
        env,
        [
            [_task(agent="worker", task="first", keep=True)],
            [_task(jobId="{{JOB}}", task="second")],
            [_task(jobId="{{JOB}}", close=True)],
        ],
    )
    assert proc.returncode == 0, proc.stderr
    assert "USERS=1" in proc.stdout and "USERS=2" in proc.stdout, proc.stdout
    assert "idle; follow up with" in proc.stdout, proc.stdout
    assert "closed" in proc.stdout.split("USERS=2", 1)[1], proc.stdout


def test_child_is_stopped_after_the_answer_unless_kept(env):
    proc = _rounds(env, [[_task(agent="worker", task="once")]])
    assert "child worker: completed" in proc.stdout, proc.stdout
    assert "- job:" not in proc.stdout, proc.stdout


def test_task_input_forms_are_exclusive(env):
    bad = [
        _task(jobId="job-x", agent="worker", task="t"),
        _task(close=True),
        _task(jobId="job-x", task="t", close=True),
        _task(agent="worker"),
        _task(jobId="job-x", keep=True, task="t"),
    ]
    proc = _rounds(env, [bad])
    assert proc.stdout.count("invalid guarded_task input") == len(bad), proc.stdout
    # スキーマにない項目は実行前に拒否される
    proc = _rounds(env, [[_task(agent="worker", task="t", bogus=1)]])
    assert "isError=true" in proc.stdout and "USERS=" not in proc.stdout, proc.stdout


def test_task_input_ignores_unused_arguments_filled_with_empty_values(env):
    """厳格なスキーマのモデル (gpt-6-sol) は、使わない引数も false / \"\" / [] で埋める (B1 の F5)。"""
    filled = {
        "list": False,
        "close": False,
        "status": False,
        "abort": False,
        "steer": "",
        "tasks": [],
    }
    filled |= {"jobId": "", "background": False, "keep": False, "model": "", "todo": 0}
    proc = _rounds(env, [[_task(agent="worker", task="t", **filled)]])
    assert "invalid guarded_task input" not in proc.stdout, proc.stdout
    assert "child worker: completed" in proc.stdout, proc.stdout


def test_task_input_forms_accept_empty_fillers_but_still_reject_real_conflicts(env):
    """全形式で、埋め草 (空の値) は無視し、実質の値同士の衝突は拒む。"""
    empty = {
        "list": False,
        "status": False,
        "abort": False,
        "close": False,
        "steer": "",
        "tasks": [],
    }
    empty |= {"agent": "", "task": "", "model": "", "todo": 0, "keep": False, "background": False}
    only = lambda **keep: {**empty, **keep}  # noqa: E731
    proc = _rounds(
        env,
        [
            [_task(**only(agent="worker", task="first", keep=True))],
            [_task(**only(jobId="{{JOB}}", task="second"))],
            [_task(**only(jobId="{{JOB}}", status=True))],
            [_task(**only(jobId="{{JOB}}", close=True))],
            [_task(**only(list=True))],
            [_task(**only(tasks=[{"agent": "worker", "task": "b"}]))],
        ],
    )
    assert "invalid guarded_task input" not in proc.stdout, proc.stdout
    assert "USERS=2" in proc.stdout and "closed" in proc.stdout, proc.stdout
    # 実質の値どうしは拒む (埋め草で拒むようにはなっていない)
    bad = [
        _task(**only(jobId="job-x", close=True, status=True)),
        _task(**only(list=True, agent="worker", task="t")),
        _task(**only(jobId="job-x")),
    ]
    proc = _rounds(env, [bad])
    assert proc.stdout.count("invalid guarded_task input") == len(bad), proc.stdout


def test_follow_up_to_a_missing_job_says_to_start_over(env):
    proc = _rounds(env, [[_task(jobId="job-0000000000000000", task="x")]])
    assert "does not exist" in proc.stdout and "include a summary" in proc.stdout, proc.stdout


def test_live_jobs_are_capped_and_the_error_lists_them(env):
    proc = _rounds(env, [[_task(agent="worker", task=f"t{i}", keep=True) for i in range(5)]])
    assert proc.stdout.count("too many live child jobs") == 1, proc.stdout
    assert proc.stdout.count("USERS=1") == 4, proc.stdout


def test_second_request_to_a_busy_job_is_refused(env):
    proc = _rounds(
        env,
        [
            [_task(agent="worker", task="first", keep=True)],
            [_task(jobId="{{JOB}}", task="a"), _task(jobId="{{JOB}}", task="b")],
        ],
        FAUX_DELAY_MS="1500",
    )
    assert proc.stdout.count("is busy with another request") == 1, proc.stdout


def test_child_result_is_split_into_status_stats_warnings_and_answer(env):
    proc = run_child(env, "worker", bash_call("touch by-child"), PI_HARNESS_BYPASS="1")
    import re

    # 見出し行に使用量、あとは承認待ち・警告・job・答えの順に分ける
    assert re.search(r"child worker: \w+ \[\d+s, \d+ calls, [\d.]+k? tokens", proc.stdout), (
        proc.stdout
    )
    assert "answer:" in proc.stdout, proc.stdout


def test_child_result_warns_when_the_answer_lacks_the_standard_sections(env):
    proc = run_child(env, "worker", bash_call("echo hi"), PI_HARNESS_BYPASS="1")
    assert "child worker: completed" in proc.stdout, proc.stdout
    assert "format check (the answer lacks the standard sections" in proc.stdout, proc.stdout
    assert "- missing: 結論, 根拠, 未確認, 次の候補" in proc.stdout, proc.stdout
    assert "- calls: bash×1" in proc.stdout, proc.stdout


def test_child_result_has_no_format_check_for_a_standard_answer(env):
    # 子は受けた依頼をそのまま答える (CHILD_USER=...)。先頭行は見出しにしない
    task = "x\n## 結論\nok\n## 根拠\na\n## 未確認\nnone\n## 次の候補\nnone"
    proc = run_pi(
        env,
        [{"name": "guarded_task", "args": {"agent": "worker", "task": task}}],
        FAUX_CHILD_TOOL_CALLS="[]",
        FAUX_CHILD_ECHO_USER="1",
        PI_HARNESS_TEST_CHILD_EXT=str(FIXTURES / "faux.ts"),
    )
    assert "child worker: completed" in proc.stdout, proc.stdout
    assert "- calls: none" in proc.stdout, proc.stdout
    assert "format check" not in proc.stdout, proc.stdout


def test_task_input_new_forms_are_exclusive(env):
    bad = [
        _task(list=True, agent="worker"),
        _task(jobId="job-x", status=True, task="t"),
        _task(jobId="job-x", steer=""),
        _task(steer="x"),
        _task(tasks=[]),
        _task(tasks=[{"agent": "worker", "task": "t", "keep": True}]),
        _task(tasks=[{"agent": "worker", "task": "t"}], agent="worker"),
        _task(jobId="job-x", abort=True, background=True),
        _task(agent="worker", task="t", todo=1.5),
    ]
    proc = _rounds(env, [bad])
    # どれも子を起動せずに拒否される (スキーマで拒むものと、execute() の排他で拒むもの)
    assert proc.stdout.count("isError=true") == len(bad), proc.stdout
    assert "USERS=" not in proc.stdout, proc.stdout


def test_background_child_reports_status_and_notifies_on_completion(env):
    proc = _rounds(
        env,
        [
            [_task(agent="worker", task="slow", background=True)],
            [_task(jobId="{{JOB}}", status=True), _task(list=True)],
        ],
        FAUX_DELAY_MS="1500",
        FAUX_FINAL_DELAY_MS="3000",
        FAUX_ECHO_CHILD_FINISHED="1",
    )
    assert proc.returncode == 0, proc.stderr
    assert "in the background as job-" in proc.stdout, proc.stdout
    # 状態の問い合わせと一覧（動いている間）
    assert "running" in proc.stdout and "calls" in proc.stdout, proc.stdout
    # 完了は followUp で親へ届く (ターンが再開する)
    assert "FINISHED=バックグラウンドの子" in proc.stdout and "USERS=1" in proc.stdout, proc.stdout


def test_finished_result_can_be_read_with_status_until_the_job_is_closed(env):
    proc = _rounds(
        env,
        [
            [_task(agent="worker", task="once", keep=True)],
            [_task(jobId="{{JOB}}", status=True)],
            [_task(jobId="{{JOB}}", close=True)],
            [_task(jobId="{{JOB}}", status=True)],
        ],
        FAUX_RESULT_CHARS="2000",
    )
    assert proc.returncode == 0, proc.stderr
    # 完了後の status は直近の結果の全文を返し、close した後は結果を返さない (状態だけが closed と出る)
    assert proc.stdout.count("last result (done") == 1, proc.stdout
    assert "(worker): closed" in proc.stdout, proc.stdout


def test_background_notification_has_sequence_and_times_and_the_result_is_saved(env):
    import re

    proc = _rounds(
        env,
        [[_task(agent="worker", task="slow", background=True)]],
        FAUX_DELAY_MS="500",
        FAUX_FINAL_DELAY_MS="3000",
        FAUX_ECHO_CHILD_FINISHED="1",
    )
    assert proc.returncode == 0, proc.stderr
    m = re.search(r"\(#1 起動 \d\d:\d\d:\d\d / 完了 \d\d:\d\d:\d\d\)", proc.stdout)
    assert m, proc.stdout
    saved = list((env["proj"] / ".tmp" / "subagents").glob("1-job-*.md"))
    assert len(saved) == 1, proc.stdout
    assert f"結果の全文: .tmp/subagents/{saved[0].name}" in proc.stdout, proc.stdout
    body = saved[0].read_text(encoding="utf-8")
    assert "#1 起動" in body and "answer:" in body, body


def test_batch_heading_and_saved_file_do_not_leak_a_secret_in_the_task(env):
    task = f'password = "{SECRET}" を使って調べる'
    proc = _rounds(
        env,
        [[_task(tasks=[{"agent": "worker", "task": task}], background=True)]],
        FAUX_DELAY_MS="500",
        FAUX_FINAL_DELAY_MS="3000",
        FAUX_ECHO_CHILD_FINISHED="1",
    )
    assert proc.returncode == 0, proc.stderr
    assert "FINISHED=バックグラウンドの 1 件の子" in proc.stdout, proc.stdout
    assert SECRET not in proc.stdout, proc.stdout
    saved = list((env["proj"] / ".tmp" / "subagents").glob("1-batch-*.md"))
    assert len(saved) == 1, proc.stdout
    assert SECRET not in saved[0].read_text(encoding="utf-8")


def test_symlinked_save_dir_is_not_written_but_the_notification_still_arrives(env):
    outside = env["tmp"] / "outside"
    outside.mkdir()
    (env["proj"] / ".tmp").mkdir()
    (env["proj"] / ".tmp" / "subagents").symlink_to(outside, target_is_directory=True)
    proc = _rounds(
        env,
        [[_task(agent="worker", task="slow", background=True)]],
        FAUX_DELAY_MS="500",
        FAUX_FINAL_DELAY_MS="3000",
        FAUX_ECHO_CHILD_FINISHED="1",
    )
    assert proc.returncode == 0, proc.stderr
    assert "FINISHED=バックグラウンドの子" in proc.stdout, proc.stdout
    assert "結果の全文" not in proc.stdout, proc.stdout
    assert list(outside.iterdir()) == []
    assert "シンボリックリンク" in proc.stderr, proc.stderr


def test_steer_reaches_a_running_child(env):
    proc = _rounds(
        env,
        [
            [_task(agent="worker", task="slow", background=True)],
            [_task(jobId="{{JOB}}", steer="change course")],
        ],
        FAUX_DELAY_MS="1500",
        FAUX_FINAL_DELAY_MS="4500",
        FAUX_ECHO_CHILD_FINISHED="1",
    )
    assert "steer queued" in proc.stdout, proc.stdout
    # 子は追加の指示を受けてもう 1 回答える (利用者の発言が 2 つ)
    assert "USERS=2" in proc.stdout, proc.stdout


def test_steer_and_abort_say_so_when_the_job_is_not_running(env):
    proc = _rounds(
        env,
        [
            [_task(agent="worker", task="first", keep=True)],
            [_task(jobId="{{JOB}}", steer="x"), _task(jobId="{{JOB}}", abort=True)],
            [_task(jobId="{{JOB}}", close=True)],
        ],
    )
    assert "is not running; nothing to steer" in proc.stdout, proc.stdout
    assert "is not running; nothing to abort" in proc.stdout, proc.stdout


def test_abort_stops_only_the_round_and_keeps_the_child(env):
    proc = _rounds(
        env,
        [
            [_task(agent="worker", task="slow", keep=True, background=True)],
            [_task(jobId="{{JOB}}", abort=True)],
        ],
        FAUX_DELAY_MS="1500",
        FAUX_FINAL_DELAY_MS="4000",
        FAUX_ECHO_CHILD_FINISHED="1",
    )
    assert "abort sent to job-" in proc.stdout, proc.stdout
    assert "aborted" in proc.stdout.split("FINISHED=", 1)[-1], proc.stdout
    # keep していた子は残る (job の案内が付く)
    assert "idle; follow up with" in proc.stdout.split("FINISHED=", 1)[-1], proc.stdout


def test_tasks_run_in_parallel_and_wait_for_free_slots(env):
    items = [{"agent": "worker", "task": f"t{i}"} for i in range(6)]
    proc = _rounds(env, [[_task(tasks=items)]], FAUX_DELAY_MS="300", FAUX_RESULT_CHARS="20000")
    assert proc.returncode == 0, proc.stderr
    # 上限 4 を超える 2 件も断らず、待ってすべて実行する
    assert proc.stdout.count("USERS=1") == 6, proc.stdout
    assert "too many live child jobs" not in proc.stdout, proc.stdout
    for i in range(1, 7):
        assert f"### {i}/6 worker" in proc.stdout, proc.stdout


def test_tasks_unknown_agent_is_refused_before_anything_starts(env):
    proc = _rounds(
        env, [[_task(tasks=[{"agent": "worker", "task": "a"}, {"agent": "nobody", "task": "b"}])]]
    )
    assert "unknown agent: nobody" in proc.stdout or "isError=true" in proc.stdout, proc.stdout
    assert "USERS=" not in proc.stdout, proc.stdout


def test_model_override_is_limited_to_models_already_in_use(env):
    proc = _rounds(
        env,
        [
            [_task(agent="worker", task="x", model="nowhere/unknown")],
            [_task(agent="worker", task="y", model="faux/spike")],
        ],
    )
    assert "model not allowed: nowhere/unknown" in proc.stdout, proc.stdout
    # 親と同じモデルは指定できる
    assert "child worker: completed" in proc.stdout, proc.stdout


def test_child_result_updates_the_assigned_todo(env):
    rounds = [
        [{"name": "todo", "args": {"action": "add", "text": "investigate"}}],
        [_task(agent="worker", task="t", todo=1)],
        [{"name": "todo", "args": {"action": "list", "all": True}}],
    ]
    proc = run_pi(
        env,
        [],
        extra=("-e", str(TODO_EXT)),
        FAUX_TOOL_ROUNDS=json.dumps(rounds),
        FAUX_CHILD_TOOL_CALLS="[]",
        FAUX_COUNT_USER="1",
        PI_HARNESS_TEST_CHILD_EXT=str(FIXTURES / "faux.ts"),
    )
    assert proc.returncode == 0, proc.stderr
    # 完了した子を割り当てた項目は done になり、メモに結果が残る
    assert "[x] #1: investigate — child worker: done" in proc.stdout, proc.stdout


def _run_task_with_todo_ext(env, rounds):
    return run_pi(
        env,
        [],
        extra=("-e", str(TODO_EXT)),
        FAUX_TOOL_ROUNDS=json.dumps(rounds),
        FAUX_CHILD_TOOL_CALLS="[]",
        FAUX_COUNT_USER="1",
        PI_HARNESS_TEST_CHILD_EXT=str(FIXTURES / "faux.ts"),
    )


def test_task_requires_todo_for_worker_when_todo_tool_is_active(env):
    proc = _run_task_with_todo_ext(env, [[_task(agent="worker", task="t")]])
    assert "todo is required for worker" in proc.stdout, proc.stdout
    assert "isError=true" in proc.stdout and "USERS=" not in proc.stdout, proc.stdout


def test_task_todo_is_optional_for_commit_agent(env):
    proc = _run_task_with_todo_ext(env, [[_task(agent="commit", task="t")]])
    assert "todo is required" not in proc.stdout, proc.stdout
    assert "child commit: completed" in proc.stdout, proc.stdout


def test_task_follow_up_and_status_do_not_need_todo(env):
    rounds = [
        [{"name": "todo", "args": {"action": "add", "text": "x"}}],
        [_task(agent="worker", task="first", keep=True, todo=1)],
        [_task(jobId="{{JOB}}", task="second")],
        [_task(jobId="{{JOB}}", status=True)],
        [_task(jobId="{{JOB}}", close=True)],
    ]
    proc = _run_task_with_todo_ext(env, rounds)
    assert proc.returncode == 0, proc.stderr
    assert "todo is required" not in proc.stdout, proc.stdout
    assert "USERS=2" in proc.stdout, proc.stdout


def test_round_time_limit_stops_the_child(env):
    proc = _rounds(
        env,
        [[_task(agent="worker", task="slow", keep=True)], [_task(jobId="{{JOB}}", task="again")]],
        FAUX_DELAY_MS="5000",
        PI_HARNESS_TEST_ROUND_MS="500",
    )
    assert "child worker: limit" in proc.stdout, proc.stdout
    assert "does not exist" in proc.stdout, proc.stdout


def _live_children(agent_dir):
    """環境変数が試験の agent 置き場で、子の印が付いたプロセスの数 (Linux の /proc だけ)。"""
    count = 0
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            environ = (entry / "environ").read_bytes().split(b"\0")
        except OSError:
            continue
        if (
            f"PI_CODING_AGENT_DIR={agent_dir}".encode() in environ
            and b"PI_HARNESS_CHILD=1" in environ
        ):
            count += 1
    return count


@pytest.mark.skipif(not Path("/proc/self/environ").exists(), reason="/proc が無い")
def test_kept_children_do_not_outlive_the_parent(env):
    proc = _rounds(env, [[_task(agent="worker", task="keep me", keep=True)]])
    assert "USERS=1" in proc.stdout, proc.stdout
    agent_dir = env["env"]["PI_CODING_AGENT_DIR"]
    deadline = time.time() + 10
    while time.time() < deadline and _live_children(agent_dir):
        time.sleep(0.2)
    assert _live_children(agent_dir) == 0


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
OCS_LIB = ROOT / "home" / "dot_local" / "share" / "ocs"


@pytest.fixture
def pis_env(env, tmp_path):
    """pis が読む ~/.config/pi/harness を、一時的な HOME の下に置く。"""
    home = tmp_path / "home"
    shutil.copytree(env["harness"], home / ".config" / "pi" / "harness")
    # pis は ~/.local/share/ocs の本体を読み込む (配備先と同じ置き場)
    ignore = shutil.ignore_patterns("__pycache__")
    shutil.copytree(OCS_LIB, home / ".local" / "share" / "ocs", ignore=ignore)
    return {**env, "home": home, "env": {**env["env"], "HOME": str(home)}}


def run_pis(pis_env, *pis_args, calls=(), **env_extra):
    faux = str(FIXTURES / "faux.ts")
    # 標準はサンドボックスの中。この試験は素の起動 (フルガードだけ) を見るので --no-sandbox を付ける
    sandbox = () if "--boundary" in pis_args else ("--no-sandbox",)
    args = [str(PIS), *sandbox, *pis_args, "--model", "faux/spike", "-e", faux, "-p", "go"]
    return subprocess.run(
        [sys.executable, *args],
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
    assert proc.returncode == 1 and "フルガードが無い" in proc.stderr


def _set_rules(pis_env, **changes):
    path = pis_env["home"] / ".config" / "pi" / "harness" / "rules.json"
    rules = json.loads(path.read_text(encoding="utf-8"))
    for key, value in changes.items():
        if value is None:
            rules.pop(key, None)
        else:
            rules[key] = value
    path.write_text(json.dumps(rules), encoding="utf-8")


def test_pis_loads_exactly_the_own_extensions_listed_in_rules_json(pis_env):
    agent = Path(pis_env["env"]["PI_CODING_AGENT_DIR"])
    for name in ("own-demo", "unlisted"):
        (agent / "extensions" / name).mkdir(parents=True)
        shutil.copy2(FIXTURES / "ext_tool.ts", agent / "extensions" / name / "index.ts")
    # 一覧にあって配られていないもの (missing) は足さず、一覧に無いもの (unlisted) は読まない
    _set_rules(pis_env, extensions=["own-demo", "missing"])
    marker = pis_env["tmp"] / "loaded"
    proc = run_pis(pis_env, EXT_LOADED_FILE=str(marker))
    assert proc.returncode == 0, proc.stderr
    assert "ext_search" in lines(proc)[0] and marker.exists()
    _set_rules(pis_env, extensions=[])
    marker.unlink()
    proc = run_pis(pis_env, EXT_LOADED_FILE=str(marker))
    assert proc.returncode == 0, proc.stderr
    assert "ext_search" not in lines(proc)[0] and not marker.exists()


def test_pis_refuses_a_rules_json_without_the_extension_list(pis_env):
    _set_rules(pis_env, extensions=None)
    proc = run_pis(pis_env)
    assert proc.returncode == 1 and "拡張の一覧" in proc.stderr


def test_pis_refuses_servers_in_the_agent_mcp_json(pis_env):
    agent = Path(pis_env["env"]["PI_CODING_AGENT_DIR"])
    (agent / "mcp.json").write_text('{"mcpServers": {"x": {"command": "true"}}}', encoding="utf-8")
    proc = run_pis(pis_env)
    assert proc.returncode == 1 and "mcp.json" in proc.stderr
    (agent / "mcp.json").write_text('{"mcpServers": {}}', encoding="utf-8")
    assert run_pis(pis_env).returncode == 0


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
    assert "圧縮の指示を付けられなかった" not in proc.stderr, (
        proc.stderr
    )  # 既定の圧縮へ落ちていない
    details = entry.get("details") or {}
    assert "f.txt" in json.dumps(details), "別名のツールで読んだファイルが一覧に無い"


def test_compaction_retries_once_when_the_summary_hits_the_output_cap(env):
    settings = env["proj"] / ".pi"
    settings.mkdir()
    small = '{"compaction": {"keepRecentTokens": 1}}'
    (settings / "settings.json").write_text(small, encoding="utf-8")
    (env["proj"] / "f.txt").write_text("x\n", encoding="utf-8")
    sessions = env["tmp"] / "sessions"
    calls = [{"name": "guarded_read", "args": {"path": "f.txt"}}]
    env["env"]["FAUX_SUMMARY_LENGTH_ONCE"] = "1"
    proc = run_pi(
        env,
        calls,
        "go",
        "again",
        "/spike-compact",
        session=True,
        extra=("--approve", "--session-dir", str(sessions), "-e", str(FIXTURES / "compact.ts")),
    )
    assert proc.returncode == 0, proc.stderr
    compactions = [e for e in _session_entries(sessions) if e.get("type") == "compaction"]
    assert compactions, proc.stdout + proc.stderr
    # やり直しが効けば、指示つきの要約が保存される (既定の圧縮に落ちれば INSTR=no になる)
    assert "INSTR=yes" in compactions[-1]["summary"], proc.stderr
    assert "圧縮の指示を付けられなかった" not in proc.stderr, proc.stderr


def test_compaction_sends_the_session_thinking_level(env):
    """思考レベルを渡さないと「thinking: disabled」で送られ、受け付けないモデルで指示つきの圧縮が失敗して既定に落ちる。"""
    settings = env["proj"] / ".pi"
    settings.mkdir()
    small = '{"compaction": {"keepRecentTokens": 1}}'
    (settings / "settings.json").write_text(small, encoding="utf-8")
    (env["proj"] / "f.txt").write_text("x\n", encoding="utf-8")
    sessions = env["tmp"] / "sessions"
    calls = [{"name": "guarded_read", "args": {"path": "f.txt"}}]
    env["env"]["FAUX_REASONING"] = "1"
    proc = run_pi(
        env,
        calls,
        "go",
        "again",
        "/spike-compact",
        session=True,
        extra=(
            "--approve",
            "--thinking",
            "medium",
            "--session-dir",
            str(sessions),
            "-e",
            str(FIXTURES / "compact.ts"),
        ),
    )
    assert proc.returncode == 0, proc.stderr
    compactions = [e for e in _session_entries(sessions) if e.get("type") == "compaction"]
    assert compactions, proc.stdout + proc.stderr
    summary = compactions[-1]["summary"]
    assert "INSTR=yes" in summary, (
        proc.stderr
    )  # 指示つきの圧縮が保存された (既定に落ちたら INSTR=no)
    assert "THINK=medium" in summary, summary
    assert "圧縮の指示を付けられなかった" not in proc.stderr, proc.stderr


def test_compaction_retries_with_minimal_thinking_when_disabled_is_rejected(env):
    """思考「なし」を拒むモデルでも、指示つきの圧縮を保存する (pi 既定の圧縮は同じ 400 で失敗する)。"""
    settings = env["proj"] / ".pi"
    settings.mkdir()
    small = '{"compaction": {"keepRecentTokens": 1}}'
    (settings / "settings.json").write_text(small, encoding="utf-8")
    (env["proj"] / "f.txt").write_text("x\n", encoding="utf-8")
    sessions = env["tmp"] / "sessions"
    calls = [{"name": "guarded_read", "args": {"path": "f.txt"}}]
    env["env"]["FAUX_REASONING"] = "1"
    env["env"]["FAUX_REJECT_NO_THINKING"] = "1"
    proc = run_pi(
        env,
        calls,
        "go",
        "again",
        "/spike-compact",
        session=True,
        extra=(
            "--approve",
            "--thinking",
            "off",
            "--session-dir",
            str(sessions),
            "-e",
            str(FIXTURES / "compact.ts"),
        ),
    )
    assert proc.returncode == 0, proc.stderr
    compactions = [e for e in _session_entries(sessions) if e.get("type") == "compaction"]
    assert compactions, proc.stdout + proc.stderr
    summary = compactions[-1]["summary"]
    assert "INSTR=yes" in summary and "THINK=minimal" in summary, summary
    assert "圧縮の指示を付けられなかった" not in proc.stderr, proc.stderr


def test_compaction_keeps_the_users_compact_arguments(env):
    """/compact の引数 (利用者の指定した焦点) を、自作の圧縮が捨てない。"""
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
        "again",
        "/spike-compact APIの変更点に絞って",
        session=True,
        extra=("--approve", "--session-dir", str(sessions), "-e", str(FIXTURES / "compact.ts")),
    )
    assert proc.returncode == 0, proc.stderr
    compactions = [e for e in _session_entries(sessions) if e.get("type") == "compaction"]
    assert compactions, proc.stdout + proc.stderr
    summary = compactions[-1]["summary"]
    assert "INSTR=yes" in summary and "CUSTOM=yes" in summary, summary


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


def _rpc_script(
    env, calls, messages, answers, timeout=120, status_key="bypass", extra=(), notices=None
):
    """RPC で messages を順に送る。確認 (confirm) には answers の順に応え、尽きたら拒否する。

    各メッセージは、応答 (response) を待ち、実行が始まったもの (started) は agent_end まで待つ。
    返すのは、確認の要求と、status_key の表示 (setStatus) の履歴。
    """
    args = [PI, "--no-session", "--model", "faux/spike", "-nbt", "-ne", "-e", "builtin:mcp"]
    args += ["-e", str(env["harness"]), *extra, "-e", str(FIXTURES / "faux.ts"), "--mode", "rpc"]
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
    requests, statuses = [], []
    deadline = time.time() + timeout
    try:
        for index, message in enumerate(messages):
            command = {"id": f"m{index}", "type": "prompt", "message": message}
            proc.stdin.write(json.dumps(command) + "\n")
            proc.stdin.flush()
            responded, started, ended = False, False, False
            for line in proc.stdout:
                if time.time() > deadline:
                    raise TimeoutError(f"{message!r}: {requests} {statuses}")
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get("type") == "extension_ui_request":
                    if event.get("method") == "confirm":
                        requests.append(event)
                        n = len(requests)
                        answer = answers[n - 1] if n <= len(answers) else False
                        reply = {"type": "extension_ui_response", "id": event["id"]}
                        proc.stdin.write(json.dumps({**reply, "confirmed": answer}) + "\n")
                        proc.stdin.flush()
                    elif event.get("method") == "notify" and notices is not None:
                        notices.append(event.get("message"))
                    elif (
                        event.get("method") == "setStatus" and event.get("statusKey") == status_key
                    ):
                        statuses.append(event.get("statusText"))
                if event.get("type") == "response" and event.get("id") == f"m{index}":
                    responded = True
                    started = (event.get("data") or {}).get("disposition") == "started"
                if event.get("type") == "agent_end":
                    ended = True
                if responded and (ended or not started):
                    break
    finally:
        proc.kill()
    return requests, statuses


def test_bypass_command_turns_on_after_confirmation_and_shows_the_status(env):
    # /bypass on の確認に応じると、次の ask が確認なしで通る
    calls = bash_call("touch made-by-pi")
    requests, statuses = _rpc_script(env, calls, ["/bypass on", "go"], [True])
    assert len(requests) == 1 and "bypass" in requests[0]["title"], requests
    # 先頭の None は起動時の消去。ON で表示が出る
    assert statuses[0] is None and "bypass" in statuses[-1], statuses
    assert (env["proj"] / "made-by-pi").exists()


def test_bypass_command_declined_keeps_asking(env):
    calls = bash_call("touch made-by-pi")
    requests, statuses = _rpc_script(env, calls, ["/bypass on", "go"], [False, False])
    assert len(requests) == 2, requests  # bypass の確認と、touch の確認
    assert statuses == [] or all(s is None for s in statuses)
    assert not (env["proj"] / "made-by-pi").exists()


def test_bypass_command_off_restores_asking_and_clears_the_status(env):
    messages = ["/bypass on", "/bypass off", "go"]
    requests, statuses = _rpc_script(env, bash_call("touch made-by-pi"), messages, [True, False])
    assert len(requests) == 2, requests  # bypass の確認 (OFF は確認なし) と、touch の確認
    assert statuses[0] is None and "bypass" in statuses[1] and statuses[-1] is None, statuses
    assert not (env["proj"] / "made-by-pi").exists()


def test_bypass_command_does_not_lift_deny(env):
    requests, _ = _rpc_script(env, bash_call("git push"), ["/bypass on", "go"], [True])
    assert len(requests) == 1, requests  # git push は確認も出ずに拒否される
    assert not (env["proj"] / "pushed").exists()


def test_bypass_starting_value_is_shown_and_can_be_turned_off(env):
    env["env"]["PI_HARNESS_BYPASS"] = "1"
    calls = bash_call("touch made-by-pi")
    requests, statuses = _rpc_script(env, calls, ["/bypass off", "go"], [False])
    assert statuses and statuses[-1] is None, statuses
    assert len(requests) == 1, requests  # touch の確認だけ
    assert not (env["proj"] / "made-by-pi").exists()


def _todo(**args):
    return {"name": "todo", "args": args}


def _last_todo_result(stdout):
    """偽のモデルが書き出した、最後の todo の結果 (`todo: isError=… :: 本文`) の本文。"""
    return stdout.split("todo: isError=")[-1]


def _run_todo(env, calls, *messages, **kwargs):
    # 試験の偶のモデルは「続行」で同じ呼び出しをやり直すので、リマインドは切る (専用の試験で確かめる)
    kwargs.setdefault("PI_TODO_NO_REMINDER", "1")
    extra = ("-e", str(TODO_EXT), *kwargs.pop("extra", ()))
    return run_pi(env, calls, *messages, extra=extra, **kwargs)


def test_todo_adds_many_sets_states_and_folds_finished_items(env):
    calls = [
        _todo(action="add", texts=["a", "b", "c"]),
        _todo(action="set", id=1, status="done"),
        _todo(action="set", id=2, status="in_progress"),
        _todo(action="list"),
    ]
    proc = _run_todo(env, calls)
    assert proc.returncode == 0, proc.stderr
    assert "追加: #1 a / #2 b / #3 c" in proc.stdout, proc.stdout
    # 畳んだ一覧: 未完了だけ出し、完了は件数にする
    tail = _last_todo_result(proc.stdout)
    assert "[>] #2: b" in tail and "[ ] #3: c" in tail and "完了 1 件" in tail, proc.stdout
    assert "[x] #1: a" not in tail, proc.stdout


def test_todo_list_all_shows_finished_and_cancelled(env):
    calls = [
        _todo(action="add", texts=["a", "b"]),
        _todo(action="set", id=1, status="done"),
        _todo(action="set", id=2, status="cancelled"),
        _todo(action="list", all=True),
    ]
    proc = _run_todo(env, calls)
    assert "[x] #1: a" in proc.stdout and "[-] #2: b" in proc.stdout, proc.stdout


def test_todo_set_is_idempotent_unlike_toggle(env):
    calls = [
        _todo(action="add", text="a"),
        _todo(action="set", id=1, status="done"),
        _todo(action="set", id=1, status="done"),
        _todo(action="list", all=True),
    ]
    proc = _run_todo(env, calls)
    assert "[x] #1: a" in _last_todo_result(proc.stdout), proc.stdout


def test_todo_warns_on_several_in_progress_and_rejects_bad_input(env):
    calls = [
        _todo(action="add", texts=["a", "b"]),
        _todo(action="set", id=1, status="in_progress"),
        _todo(action="set", id=2, status="in_progress"),
        _todo(action="set", id=99, status="done"),
        _todo(action="update", id=1),
        _todo(action="add"),
    ]
    proc = _run_todo(env, calls)
    assert "in_progress が 2 件" in proc.stdout, proc.stdout
    assert "#99 が無い" in proc.stdout, proc.stdout
    assert "update には text か note が要る" in proc.stdout, proc.stdout
    assert "add には text か texts が要る" in proc.stdout, proc.stdout


def test_todo_batch_applies_many_operations_in_one_call(env):
    calls = [
        _todo(action="add", texts=["a", "b", "c", "d"]),
        _todo(
            action="batch",
            ops=[
                {"action": "set", "id": 1, "status": "done"},
                {"action": "set", "id": 2, "status": "in_progress"},
                {"action": "update", "id": 3, "text": "c2"},
                {"action": "remove", "id": 4},
                {"action": "add", "text": "e"},
            ],
        ),
        _todo(action="list", all=True),
    ]
    proc = _run_todo(env, calls)
    last = _last_todo_result(proc.stdout)
    assert "[x] #1: a" in last and "[>] #2: b" in last and "[ ] #3: c2" in last, proc.stdout
    assert "#4" not in last and "[ ] #5: e" in last, proc.stdout


def test_todo_batch_is_atomic_and_names_the_failing_operation(env):
    calls = [
        _todo(action="add", texts=["a", "b"]),
        _todo(
            action="batch",
            ops=[
                {"action": "set", "id": 1, "status": "done"},
                {"action": "set", "id": 99, "status": "done"},
            ],
        ),
        _todo(action="list", all=True),
    ]
    proc = _run_todo(env, calls)
    assert "ops[1]: #99 が無い" in proc.stdout, proc.stdout
    # 1 件目も適用されていない
    assert "[ ] #1: a" in _last_todo_result(proc.stdout), proc.stdout


def test_todo_replace_rewrites_the_list_and_keeps_ids_on_request(env):
    calls = [
        _todo(action="add", texts=["a", "b", "c"]),
        _todo(
            action="replace",
            items=[
                {"id": 2, "text": "b2", "status": "in_progress"},
                {"text": "new"},
            ],
        ),
        _todo(action="list", all=True),
    ]
    proc = _run_todo(env, calls)
    assert "置き換えた: 2 件 (消えた既存の項目 2 件)" in proc.stdout, proc.stdout
    last = _last_todo_result(proc.stdout)
    # id を付けた項目は引き継ぎ、無い項目は新しい ID (次の番号) を振る
    assert "[>] #2: b2" in last and "[ ] #4: new" in last, proc.stdout
    assert "#1" not in last and "#3" not in last, proc.stdout


def test_todo_replace_rejects_bad_items(env):
    calls = [
        _todo(action="add", text="a"),
        _todo(action="replace", items=[{"text": " "}]),
        _todo(action="replace", items=[{"id": 1, "text": "x"}, {"id": 1, "text": "y"}]),
        _todo(action="list"),
    ]
    proc = _run_todo(env, calls)
    assert "text は空にできない" in proc.stdout and "id が重複している" in proc.stdout, proc.stdout
    assert "[ ] #1: a" in _last_todo_result(proc.stdout), proc.stdout


def test_todo_note_is_kept_shown_and_cleared(env):
    calls = [
        _todo(action="add", text="a", note="初期のメモ"),
        _todo(action="set", id=1, status="done", note="pytest 3 passed"),
        _todo(action="list", all=True),
        _todo(action="update", id=1, note=""),
        _todo(action="list", all=True),
    ]
    proc = _run_todo(env, calls)
    _first, second = proc.stdout.split("todo: isError=")[-2:]
    assert "[x] #1: a — pytest 3 passed" in proc.stdout, proc.stdout
    assert "—" not in second, proc.stdout
    assert "pytest 3 passed" not in second


def test_todo_changes_return_a_compact_summary_not_the_whole_list(env):
    texts = [f"item{i}" for i in range(1, 8)]
    proc = _run_todo(env, [_todo(action="add", texts=texts)])
    body = _last_todo_result(proc.stdout)
    # 変更の結果は、未完了の先頭 3 件と件数だけ (全件は list)
    assert "#1: item1" in body and "#3: item3" in body and "#4: item4" not in body, proc.stdout
    assert "… 他 4 件" in body and "未完了 7 件" in body, proc.stdout
    # list は全件
    proc = _run_todo(env, [_todo(action="add", texts=texts), _todo(action="list")])
    assert "#7: item7" in _last_todo_result(proc.stdout), proc.stdout


def test_todo_reminds_once_when_the_answer_ends_with_work_in_progress(env):
    rounds = [
        [
            _todo(action="add", texts=["a", "b"]),
            _todo(action="set", id=1, status="in_progress"),
        ]
    ]
    proc = run_pi(
        env,
        [],
        extra=("-e", str(TODO_EXT)),
        FAUX_TOOL_ROUNDS=json.dumps(rounds),
        FAUX_ECHO_REMINDER="1",
    )
    assert proc.returncode == 0, proc.stderr
    # 作業中の項目が残るので、終わろうとしたところで 1 回だけ促す
    assert "REMINDER=" in proc.stdout and "#1 a" in proc.stdout, proc.stdout
    assert proc.stdout.count("REMINDER=") == 1, proc.stdout


def test_todo_does_not_remind_when_nothing_is_in_progress(env):
    rounds = [
        [
            _todo(action="add", texts=["a"]),
            _todo(action="set", id=1, status="done"),
        ]
    ]
    proc = run_pi(
        env,
        [],
        extra=("-e", str(TODO_EXT)),
        FAUX_TOOL_ROUNDS=json.dumps(rounds),
        FAUX_ECHO_REMINDER="1",
    )
    assert proc.returncode == 0, proc.stderr
    assert "REMINDER=" not in proc.stdout, proc.stdout


def test_todo_update_and_remove(env):
    calls = [
        _todo(action="add", texts=["a", "b"]),
        _todo(action="update", id=1, text="a2"),
        _todo(action="remove", id=2),
        _todo(action="list", all=True),
    ]
    proc = _run_todo(env, calls)
    last = _last_todo_result(proc.stdout)
    assert "[ ] #1: a2" in last and "#2" not in last, proc.stdout


def _todo_states(sessions):
    """セッションに残った todo の状態を、古い順に返す。

    ツール結果の details と、利用者の操作の custom エントリ (todo-state) の両方。
    """
    states = []
    for e in _session_entries(sessions):
        if e.get("type") == "message" and e["message"].get("toolName") == "todo":
            states.append(e["message"]["details"])
        elif e.get("type") == "custom" and e.get("customType") == "todo-state":
            states.append(e["data"])
    return states


def _resume_todo(env, sessions, calls, *messages, **kwargs):
    extra = ("--approve", "--session-dir", str(sessions), "-c", *kwargs.pop("extra", ()))
    return _run_todo(env, calls, *messages, session=True, extra=extra, **kwargs)


def test_todo_state_survives_resume_and_reads_the_old_format(env):
    sessions = env["tmp"] / "sessions"
    first = [_todo(action="add", texts=["a", "b"]), _todo(action="set", id=1, status="done")]
    proc = _run_todo(env, first, session=True, extra=("--approve", "--session-dir", str(sessions)))
    assert proc.returncode == 0, proc.stderr
    # 旧形式 ({ id, text, done }) に戻す
    for path in sessions.rglob("*.jsonl"):
        text = path.read_text(encoding="utf-8")
        text = text.replace('"status":"done"', '"done":true').replace(
            '"status":"pending"', '"done":false'
        )
        path.write_text(text, encoding="utf-8")
    proc = _resume_todo(
        env, sessions, [_todo(action="add", text="c"), _todo(action="list", all=True)]
    )
    assert proc.returncode == 0, proc.stderr
    last = _last_todo_result(proc.stdout)
    # 旧形式の done が完了として読まれ、ID は続き (#3) から振られる
    assert "[x] #1: a" in last and "[ ] #2: b" in last and "[ ] #3: c" in last, proc.stdout


def test_todos_tidy_and_clear_are_user_commands_that_persist(env):
    sessions = env["tmp"] / "sessions"
    calls = [_todo(action="add", texts=["a", "b"]), _todo(action="set", id=1, status="done")]
    extra = ("--approve", "--session-dir", str(sessions))
    proc = _run_todo(env, calls, "go", "/todos tidy", session=True, extra=extra)
    assert proc.returncode == 0, proc.stderr
    # 利用者の操作は custom エントリで残り、完了だけが片付いている
    last = _todo_states(sessions)[-1]
    assert [t["id"] for t in last["todos"]] == [2], last
    # 再開しても片付いたまま。モデルが呼べるのはツールだけで、/todos は呼べない
    proc = _resume_todo(env, sessions, [_todo(action="list", all=True)])
    tail = _last_todo_result(proc.stdout)
    assert "#1" not in tail and "[ ] #2: b" in tail, proc.stdout


def test_todo_state_survives_compaction(env):
    settings = env["proj"] / ".pi"
    settings.mkdir()
    (settings / "settings.json").write_text(
        '{"compaction": {"keepRecentTokens": 1}}', encoding="utf-8"
    )
    sessions = env["tmp"] / "sessions"
    extra = ("--approve", "--session-dir", str(sessions), "-e", str(FIXTURES / "compact.ts"))
    calls = [_todo(action="add", text="x")]
    proc = _run_todo(env, calls, "go", "again", "/spike-compact", session=True, extra=extra)
    assert proc.returncode == 0, proc.stderr
    assert any(e.get("type") == "compaction" for e in _session_entries(sessions)), (
        proc.stdout + proc.stderr
    )
    proc = _resume_todo(
        env, sessions, [_todo(action="list", all=True)], extra=("-e", str(FIXTURES / "compact.ts"))
    )
    # 圧縮の前に足した項目 (2 ターン分) が、圧縮のあとも復元される
    assert "#1: x" in proc.stdout and "#2: x" in proc.stdout, proc.stdout


def test_todo_footer_shows_progress_the_active_item_and_clears_on_tidy(env):
    calls = [
        _todo(action="add", texts=["first step", "second"]),
        _todo(action="set", id=1, status="in_progress"),
        _todo(action="set", id=1, status="done"),
        _todo(action="set", id=2, status="done"),
    ]
    extra = (str(TODO_EXT),)
    _, statuses = _rpc_script(
        env, calls, ["go", "/todos tidy"], [], status_key="todo", extra=("-e", *extra)
    )
    assert any(s and "📋 0/2 ▶ first step" in s for s in statuses), statuses
    assert any(s and "✅ 2/2" in s for s in statuses), statuses
    assert statuses[-1] is None, statuses  # 片付けて空になったら表示を消す


def test_agent_commands_start_a_child_and_list_children(env):
    env["env"].update(
        FAUX_CHILD_TOOL_CALLS="[]",
        FAUX_COUNT_USER="1",
        FAUX_DELAY_MS="1500",
        PI_HARNESS_TEST_CHILD_EXT=str(FIXTURES / "faux.ts"),
    )
    notices: list = []
    messages = ["/agent worker investigate", "/agents", "/agent nobody x", "/agent"]
    _rpc_script(env, [], messages, [], notices=notices)
    joined = "\n".join(str(n) for n in notices)
    assert "worker を起動しました" in joined, notices
    # 動いている間の一覧
    assert "worker running" in joined and "calls" in joined, notices
    assert joined.count("使い方: /agent") == 2, notices


def test_activity_footer_names_the_running_children_with_elapsed_time(env):
    # 3 件以下なら名前と経過時間 (子は遅くして、フッターの 1 秒ごとの更新を見る)
    env["env"].update(
        FAUX_CHILD_TOOL_CALLS="[]",
        FAUX_COUNT_USER="1",
        FAUX_DELAY_MS="2500",
        PI_HARNESS_TEST_CHILD_EXT=str(FIXTURES / "faux.ts"),
    )
    activity = ROOT / "home" / "dot_pi" / "agent" / "extensions" / "activity" / "index.ts"
    calls = [{"name": "guarded_task", "args": {"agent": "worker", "task": "slow"}}]
    _, statuses = _rpc_script(
        env, calls, ["go"], [], status_key="activity", extra=("-e", str(activity))
    )
    assert any(s and s.startswith("🤖 worker ") for s in statuses), statuses


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


def test_stepback_prompt_template_expands_the_question_and_asks_for_a_step_back(env):
    prompts = Path(env["env"]["PI_CODING_AGENT_DIR"]) / "prompts"
    prompts.mkdir()
    rendered = _render(ROOT / "home" / "dot_pi" / "agent" / "prompts" / "stepback.md.tmpl")
    (prompts / "stepback.md").write_text(rendered, encoding="utf-8")
    proc = run_pi(env, [], "/stepback なぜ cron が動かない", FAUX_ECHO_USER="1")
    assert proc.returncode == 0, proc.stderr
    assert "質問:\nなぜ cron が動かない" in proc.stdout, proc.stdout
    assert "ステップバック質問" in proc.stdout
    # 読み取りだけで確かめる指示 (状態を変えない) と、ツール名に依らない文面であること
    assert "状態を変えない" in proc.stdout
    assert "guarded_" not in proc.stdout


def test_stepback_without_an_argument_targets_the_previous_exchange(env):
    prompts = Path(env["env"]["PI_CODING_AGENT_DIR"]) / "prompts"
    prompts.mkdir()
    rendered = _render(ROOT / "home" / "dot_pi" / "agent" / "prompts" / "stepback.md.tmpl")
    (prompts / "stepback.md").write_text(rendered, encoding="utf-8")
    proc = run_pi(env, [], "/stepback", FAUX_ECHO_USER="1")
    assert proc.returncode == 0, proc.stderr
    # 引数が空でも展開され、「質問:」が空のときは直前のやり取りを対象にする指示が届く
    assert "質問:\n\n" in proc.stdout, proc.stdout
    assert "直前の利用者の質問" in proc.stdout
    assert "$ARGUMENTS" not in proc.stdout


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
    probe = ["-p", "/orca-probe"]
    return subprocess.run(
        [sys.executable, str(PIS), "--no-sandbox", "--model", "faux/spike", "-e", faux, *probe],
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


# ─── ask (利用者への質問) ───────────────────────────────────────────

ASK_EXT = ROOT / "home" / "dot_pi" / "agent" / "extensions" / "ask" / "index.ts"


def _ask_q(question, *labels, mark=True, **extra):
    """mark=True は最初の選択肢の label に推奨の印を付ける (推奨の検査を通すため)。"""
    labels = [f"{labels[0]} (推奨)", *labels[1:]] if mark else list(labels)
    options = [{"label": label, "description": f"d-{label}"} for label in labels]
    return {"question": question, "options": options, **extra}


def _ask_rpc(env, questions, replies, timeout=120, **env_extra):
    """ask を RPC で呼び、select / input の要求に replies の順に応える (None は中断)。返すのは (要求, 結果の本文)。"""
    calls = [{"name": "ask", "args": {"questions": questions}}]
    args = [PI, "--no-session", "--model", "faux/spike", "-nbt", "-ne", "-e", "builtin:mcp"]
    args += [
        "-e",
        str(env["harness"]),
        "-e",
        str(ASK_EXT),
        "-e",
        str(FIXTURES / "faux.ts"),
        "--mode",
        "rpc",
    ]
    proc = subprocess.Popen(
        args,
        cwd=env["proj"],
        env={**env["env"], "FAUX_TOOL_CALLS": json.dumps(calls), **env_extra},
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    requests, result = [], ""
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
            if event.get("type") == "extension_ui_request" and event.get("method") in (
                "select",
                "input",
            ):
                requests.append(event)
                n = len(requests)
                value = replies[n - 1] if n <= len(replies) else None
                reply = {"type": "extension_ui_response", "id": event["id"]}
                reply |= {"cancelled": True} if value is None else {"value": value}
                proc.stdin.write(json.dumps(reply) + "\n")
                proc.stdin.flush()
            if event.get("type") == "tool_execution_end" and event.get("toolName") == "ask":
                content = (event.get("result") or {}).get("content") or []
                result = "".join(c.get("text", "") for c in content)
            if event.get("type") == "agent_end":
                break
    finally:
        proc.kill()
    return requests, result


def test_ask_is_removed_from_the_tools_without_a_ui(env):
    # print モードは UI が無いので、ask はモデルに見せない
    proc = run_pi(env, [], extra=("-e", str(ASK_EXT)), FAUX_DUMP_PROMPT="1")
    assert proc.returncode == 0, proc.stderr
    assert "- ask:" not in proc.stdout, proc.stdout


def test_ask_returns_the_chosen_option_label(env):
    qs = [_ask_q("Which?", "A", "B")]
    requests, result = _ask_rpc(env, qs, ["2. B"])
    assert [r["method"] for r in requests] == ["select"], requests
    assert "Type something." in requests[0]["options"], requests
    # 行はラベルだけ、説明は質問文の一覧に出る
    assert requests[0]["options"][:2] == ["1. A (推奨)", "2. B"], requests
    assert "d-A" in requests[0]["title"] and "d-B" in requests[0]["title"], requests
    assert "→ B" in result, result


def test_ask_wraps_long_descriptions_with_a_hanging_indent_and_blank_lines(env):
    long = "とても長い説明文。" * 12
    q = {
        "question": "Which?",
        "options": [
            {"label": "A (推奨)", "description": long},
            {"label": "B", "description": "short"},
        ],
    }
    requests, _ = _ask_rpc(env, [q], ["1. A (推奨)"])
    title = requests[0]["title"]
    body = [line for line in title.splitlines() if line.startswith(" " * 7)]
    assert len(body) >= 3, title  # 長い説明は複数行になり、どの行も字下げが付く
    assert all(len(line) <= 7 + 33 for line in body), body  # 全角 32 文字 (64 カラム) まで
    assert "\n\n  2. B" in title, title  # 選択肢の間に空行


def test_ask_asks_several_questions_in_one_call(env):
    qs = [_ask_q("First?", "A", "B"), _ask_q("Second?", "C", "D")]
    requests, result = _ask_rpc(env, qs, ["1. A (推奨)", "2. D"])
    assert len(requests) == 2, requests
    assert "→ A (推奨)" in result and "→ D" in result, result


def test_ask_takes_free_text_and_returns_to_options_on_an_empty_answer(env):
    qs = [_ask_q("Which?", "A", "B")]
    # 空の自由記述は記録せず、選択肢へ戻る
    requests, result = _ask_rpc(env, qs, ["Type something.", "  ", "Type something.", "mine"])
    assert [r["method"] for r in requests] == ["select", "input", "select", "input"], requests
    assert "→ mine" in result, result


def test_ask_multi_select_collects_checked_options_and_free_text(env):
    qs = [_ask_q("Which?", "A", "B", "C", multi=True)]
    replies = ["[ ] 1. A (推奨)", "[ ] 3. C", "Type something.", "extra", "Next"]
    requests, result = _ask_rpc(env, qs, replies)
    assert "[x] 1. A (推奨)" in requests[1]["options"], requests
    assert "→ A (推奨), C, 自由記述: extra" in result, result


def test_ask_reports_unanswered_questions_when_dismissed_midway(env):
    qs = [_ask_q("First?", "A", "B"), _ask_q("Second?", "C", "D")]
    _, result = _ask_rpc(env, qs, ["1. A (推奨)", None])
    assert "未回答の問: Q2" in result and "→ A (推奨)" in result, result


def test_ask_dismissed_at_once_is_a_cancellation(env):
    _, result = _ask_rpc(env, [_ask_q("Which?", "A", "B")], [None])
    assert "答えなかった" in result and "→" not in result, result


@pytest.mark.parametrize(
    ("questions", "code"),
    [
        ([_ask_q("Q?", "A", "Other")], "reserved_label"),
        ([_ask_q("Q?", "A", "Type something.")], "reserved_label"),
        ([_ask_q("Q?", "A", "A", mark=False)], "duplicate_option_label"),
        ([_ask_q("Q?", "A", "B"), _ask_q("Q?", "C", "D")], "duplicate_question"),
        # 推奨の検査。直し方 (末尾に ` (推奨)` を付ける) もエラー文に出る
        ([_ask_q("Q?", "A", "B", mark=False)], "missing_recommended"),
        ([_ask_q("Q?", "A", "B (推奨)", mark=False)], "recommended_not_first"),
        ([_ask_q("Q?", "A (推奨)", "B (推奨)", mark=False)], "multiple_recommended"),
    ],
)
def test_ask_rejects_a_malformed_questionnaire_without_asking(env, questions, code):
    # 選択肢の個数の上限はスキーマが先に弾く (ここは実行時の検査だけ)
    requests, result = _ask_rpc(env, questions, [])
    assert requests == [], requests
    assert code in result, result
    if code.endswith("_recommended") or code == "recommended_not_first":
        assert "末尾に ` (推奨)` を付けて呼び直す" in result and "最も安全な選択肢" in result, (
            result
        )


def test_ask_reports_every_violating_question_in_one_error(env):
    qs = [
        _ask_q("First question?", "A", "B", mark=False),
        _ask_q("Fine?", "C", "D"),
        _ask_q("Third question?", "E", "F (推奨)", mark=False),
    ]
    requests, result = _ask_rpc(env, qs, [])
    assert requests == [], requests
    assert "missing_recommended" in result and "Q1 (First question?)" in result, result
    assert "Q3 (Third question?)" in result and "先頭にない" in result, result
    assert "Q2" not in result, result


def test_ask_allows_several_recommended_options_when_multi(env):
    qs = [_ask_q("Which?", "A (推奨)", "B (推奨)", "C", multi=True, mark=False)]
    requests, result = _ask_rpc(env, qs, ["[ ] 2. B (推奨)", "Next"])
    assert [r["method"] for r in requests] == ["select", "select"], requests
    assert "→ B (推奨)" in result, result


@pytest.mark.parametrize("mark", ["(recommended)", "（推奨）", "(Recommended)"])
def test_ask_recognises_the_other_recommended_marks(env, mark):
    qs = [_ask_q("Which?", f"A {mark}", "B", mark=False)]
    requests, result = _ask_rpc(env, qs, [f"1. A {mark}"])
    assert [r["method"] for r in requests] == ["select"], requests
    assert f"→ A {mark}" in result, result
