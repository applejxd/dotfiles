"""素の pi 向けの補助 (home/dot_config/pi/commit-confirm) を、本物の pi と偽のモデルで動かす試験。

settings.json の ``extensions`` から読ませ、push の拒否・commit の確認・時間切れの退避を見る。
解釈・表示・退避の細部は test_pi_commit_parse.py。
see docs/spec/guard/pi-extensions.md#commit-の確認-素の-pi
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
from agents_common import ROOT

PI = shutil.which("pi")
pytestmark = pytest.mark.skipif(PI is None, reason="pi is not installed")

EXT_SRC = ROOT / "home" / "dot_config" / "pi" / "commit-confirm"
FIXTURES = Path(__file__).resolve().parent / "pi"
HARNESS_SRC = ROOT / "home" / "dot_config" / "pi" / "harness" / "index.ts"
TIMEOUT_MS = "1500"  # 時間切れの試験が長引かないよう縮める (本番は TUI 15 分・RPC 5 分)


@pytest.fixture
def env(tmp_path):
    ext = tmp_path / ".config" / "pi" / "commit-confirm"
    ext.mkdir(parents=True)
    for src in EXT_SRC.glob("*.ts"):
        shutil.copy2(src, ext / src.name)
    agent = tmp_path / "agent"
    agent.mkdir()
    (agent / "settings.json").write_text(json.dumps({"extensions": [str(ext)]}), encoding="utf-8")
    proj = tmp_path / "proj"
    proj.mkdir()
    git_env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    base = {
        **os.environ,
        **git_env,
        "PI_CODING_AGENT_DIR": str(agent),
        "TMPDIR": str(tmp_path),
        "PI_COMMIT_CONFIRM_TIMEOUT_MS": TIMEOUT_MS,
    }
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=proj, check=True)
    (proj / "a.txt").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt"], cwd=proj, check=True)
    return {"proj": proj, "env": base, "tmp": tmp_path}


def bash_call(command):
    return [{"name": "bash", "args": {"command": command}}]


def git_out(env, *args):
    done = subprocess.run(
        ["git", *args],
        cwd=env["proj"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return done.stdout


def commits(env):
    return git_out(env, "log", "--format=%s").splitlines()


def pending_refs(env):
    return git_out(
        env, "for-each-ref", "--sort=refname", "--format=%(refname)", "refs/pi/pending/"
    ).split()


def _args(*extra, mode):
    faux = str(FIXTURES / "faux.ts")
    return [PI, "--no-session", "--model", "faux/spike", *extra, "-e", faux, "--mode", mode]


class Rpc(list):
    """確認の要求の一覧。raw は pi の出力全部 (ツールの結果の文章を探すのに使う)。"""

    raw: str = ""


def _rpc(env, calls, answers, extra=(), prompts=("go",)):
    """RPC で動かし、確認の要求に answers の順に応える。None は応えない (時間切れを待つ)。"""
    proc = subprocess.Popen(
        _args(*extra, mode="rpc"),
        cwd=env["proj"],
        env={**env["env"], "FAUX_TOOL_CALLS": json.dumps(calls)},
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    result = Rpc()
    lines = []
    remaining = list(prompts)
    proc.stdin.write(json.dumps({"type": "prompt", "message": remaining.pop(0)}) + "\n")
    proc.stdin.flush()
    deadline = time.time() + 120
    try:
        for line in proc.stdout:
            lines.append(line)
            if time.time() > deadline:
                break
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("type") == "extension_ui_request" and event.get("method") == "confirm":
                result.append(event)
                answer = answers[len(result) - 1] if len(result) <= len(answers) else False
                if answer is not None:
                    reply = {
                        "type": "extension_ui_response",
                        "id": event["id"],
                        "confirmed": answer,
                    }
                    proc.stdin.write(json.dumps(reply) + "\n")
                    proc.stdin.flush()
            if event.get("type") == "agent_end":
                if not remaining:
                    break
                proc.stdin.write(json.dumps({"type": "prompt", "message": remaining.pop(0)}) + "\n")
                proc.stdin.flush()
    finally:
        proc.kill()
    result.raw = "".join(lines)
    return result


def _print(env, command):
    return subprocess.run(
        [*_args(mode="text"), "-p", "go"],
        cwd=env["proj"],
        env={**env["env"], "FAUX_TOOL_CALLS": json.dumps(bash_call(command))},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )


COMMIT = "git commit -m 'feat: 件名です' -m '本文の 1 行目'"
HEREDOC = "git commit -m \"$(cat <<'EOF'\nfeat: ヒアドキュメント\n\n本文 A\nEOF\n)\""


# ─── 確認 ────────────────────────────────────────────────────────────


def test_commit_confirmation_is_structured_and_has_a_deadline(env):
    requests = _rpc(env, bash_call(COMMIT), [False])
    assert len(requests) == 1, requests
    message = requests[0]["message"]
    assert message.startswith("リポジトリ: (origin なし) ")
    assert "\n\n対象:       1 ファイル  +1 −0\n  A a.txt (+1 −0)\n\nメッセージ:\n" in message
    assert "  feat: 件名です\n  本文の 1 行目" in message
    assert "git commit" not in message.split("応答が無ければ")[0], "生のコマンドを出している"
    assert requests[0].get("timeout") == int(TIMEOUT_MS), "確認に期限が付いていない"


def test_a_heredoc_message_is_shown_structured(env):
    requests = _rpc(env, bash_call(HEREDOC), [False])
    assert "メッセージ:\n  feat: ヒアドキュメント\n  本文 A" in requests[0]["message"]


def test_refusal_blocks_the_commit_and_saves_nothing(env):
    requests = _rpc(env, bash_call(COMMIT), [False])
    assert commits(env) == []
    assert pending_refs(env) == [], requests.raw[-1500:]
    assert "利用者が git commit を拒否した" in requests.raw


def test_approval_runs_the_commit(env):
    requests = _rpc(env, bash_call(COMMIT), [True])
    assert len(requests) == 1
    assert commits(env) == ["feat: 件名です"]
    assert pending_refs(env) == []


@pytest.mark.parametrize(
    "command", ["git status --short", "echo git commit is only text", "git log --oneline -1"]
)
def test_other_commands_pass_without_confirmation(env, command):
    assert _rpc(env, bash_call(command), [False]) == []


@pytest.mark.parametrize(
    "command",
    [
        "git -C . commit -m x",
        "cd . && git commit -m x",
        "git -c core.x=1 commit -m x",
        "git commit -m x | cat",
    ],
)
def test_commit_variants_are_confirmed(env, command):
    assert len(_rpc(env, bash_call(command), [False])) == 1


def test_an_unreadable_command_is_shown_raw_with_a_warning(env):
    requests = _rpc(env, bash_call("git commit -m x | cat"), [False])
    assert requests[0]["message"].startswith(
        "解釈できない形のコマンドです。次がそのまま実行されます:"
    )


# ─── push ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "command", ["git push origin main", "git commit -m x && git push", "git -C . push"]
)
def test_push_is_denied_without_asking(env, command):
    requests = _rpc(env, bash_call(command), [True])
    assert requests == [], "push は確認を出さずに拒否する"
    assert "git push は完全手動" in requests.raw
    assert commits(env) == [], "push と連結された commit も実行しない"


def test_push_is_denied_without_a_screen_too(env):
    done = _print(env, "git push origin main")
    assert "git push は完全手動" in done.stdout + done.stderr


# ─── 時間切れ・不在 ──────────────────────────────────────────────────


def test_a_timeout_saves_the_commit_and_tells_the_model_to_continue(env):
    before = git_out(env, "status", "--porcelain=v1")
    requests = _rpc(env, bash_call(COMMIT), [None])
    assert len(requests) == 1
    assert commits(env) == [], "時間切れでコミットしてはいけない"
    [ref] = pending_refs(env)
    assert git_out(env, "log", "-1", "--format=%s", ref).strip() == "feat: 件名です"
    assert git_out(env, "status", "--porcelain=v1") == before, (
        "退避が作業ツリー・インデックスを変えた"
    )
    assert (
        "git commit は実行していない: 確認が" in requests.raw and "時間切れになった" in requests.raw
    )
    assert (
        ref in requests.raw
        and "再試行しない" in requests.raw
        and "保留したコミット" in requests.raw
    )


def test_after_a_timeout_later_commits_in_the_same_run_are_not_asked(env):
    calls = bash_call(COMMIT) + bash_call("git add -- b.txt && git commit -m 'second'")
    (env["proj"] / "b.txt").write_text("b\n", encoding="utf-8")
    requests = _rpc(env, calls, [None, None])
    assert len(requests) == 1, "不在と分かった後の確認を待った"
    first, second = pending_refs(env)
    assert git_out(env, "rev-parse", f"{second}^") == git_out(env, "rev-parse", first)
    assert git_out(env, "diff", "--name-only", first, second).split() == ["b.txt"]
    assert "不在のため確認せずに退避した" in requests.raw


def test_a_new_user_input_ends_the_absence(env):
    requests = _rpc(env, bash_call(COMMIT), [None, False], prompts=("go", "もう一度"))
    assert len(requests) == 2, "利用者の入力の後も確認を出さなかった"


def test_without_a_screen_the_commit_is_saved_not_run(env):
    done = _print(env, COMMIT)
    assert commits(env) == [], done.stdout + done.stderr
    assert len(pending_refs(env)) == 1
    assert "確認できる画面が無い" in done.stdout + done.stderr


def test_a_chained_commit_is_blocked_whole_and_saved_as_an_approximation(env):
    """モデルがよく書く連結 (実機で確認)。全体を止め、最初の commit から近似して退避する。"""
    requests = _rpc(env, bash_call("git commit -m 'feat: chained' && touch made-after"), [None])
    assert commits(env) == [] and not (env["proj"] / "made-after").exists(), (
        "連結した操作が実行された"
    )
    [ref] = pending_refs(env)
    assert git_out(env, "log", "-1", "--format=%s", ref).strip() == "feat: chained"
    assert "近似" in requests.raw and "commit と分けて実行し直す" in requests.raw


def test_an_unreadable_commit_cannot_be_saved_but_still_does_not_run(env):
    requests = _rpc(env, bash_call('git commit -m "fix: $MSG"'), [None])
    assert commits(env) == [] and pending_refs(env) == []
    assert "退避できなかった" in requests.raw


# ─── TUI ─────────────────────────────────────────────────────────────


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux が無い")
def test_the_tui_shows_the_structure_and_a_countdown_then_saves_on_timeout(env):
    session = f"cc-{os.getpid()}"
    tmp = env["tmp"]
    script = tmp / "start.sh"
    exports = " ".join(
        f"{k}={json.dumps(v)}"
        for k, v in env["env"].items()
        if k.startswith(("PI_", "GIT_", "TMPDIR"))
    )
    script.write_text(
        f"cd {env['proj']}\nexport {exports} PI_COMMIT_CONFIRM_TIMEOUT_MS=6000\n"
        f"export FAUX_TOOL_CALLS={json.dumps(json.dumps(bash_call(COMMIT)))}\n"
        f"exec {PI} --no-approve --no-session --model faux/spike -e {FIXTURES / 'faux.ts'}\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["tmux", "new-session", "-d", "-s", session, "-x", "110", "-y", "36", f"bash {script}"],
        check=True,
    )

    def capture() -> str:
        return subprocess.run(
            ["tmux", "capture-pane", "-t", session, "-p"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        ).stdout

    def wait_for(predicate, seconds: float) -> str:
        # 負荷で起動や描画が遅れると固定の sleep では落ちるので、画面を見ながら待つ
        deadline = time.monotonic() + seconds
        screen = capture()
        while not predicate(screen) and time.monotonic() < deadline:
            time.sleep(0.3)
            screen = capture()
        return screen

    try:
        # pi は起動時に fd をダウンロードすることがあり、連続実行の負荷では長引く。入力欄 (フッター) が出てから送る。
        # 「Startup is still in progress」などの通知は消えずに残るので、待つ条件にしない
        wait_for(lambda s: "/100k" in s, 90)
        time.sleep(2)
        subprocess.run(["tmux", "send-keys", "-t", session, "go", "Enter"], check=True)
        screen = wait_for(lambda s: "メッセージ:" in s and "s)" in s, 8)
        for _ in range(4):
            if "メッセージ:" in screen:
                break
            # 起動直後に送った Enter が取りこぼされていることがある。入力欄に `go` が残っていれば Enter をやり直す
            subprocess.run(["tmux", "send-keys", "-t", session, "Enter"], check=True)
            screen = wait_for(lambda s: "メッセージ:" in s and "s)" in s, 8)
        assert (
            "リポジトリ: (origin なし)" in screen and "対象:" in screen and "メッセージ:" in screen
        ), screen
        assert "feat: 件名です" in screen and "(" in screen and "s)" in screen, (
            "残り時間が出ていない"
        )
        # 期限切れの保存 (git の ref 作成) も負荷で遅れる。固定の sleep ではなく、保存されるまで待つ
        time.sleep(6)
        deadline = time.monotonic() + 30
        while not pending_refs(env) and time.monotonic() < deadline:
            time.sleep(0.5)
    finally:
        subprocess.run(["tmux", "kill-session", "-t", session], check=False)
    assert commits(env) == [] and len(pending_refs(env)) == 1


# ─── フルガードとの関係 ────────────────────────────────────────────────


def test_the_harness_replaces_it_instead_of_doubling(env):
    """pis (-ne -e harness) では settings.json の extensions が外れ、確認は 1 回だけ。"""
    sys.path.insert(0, str(ROOT / "scripts" / "agents"))
    import generate as gen
    from agents_common import agents_config_dir, load_common

    harness = env["tmp"] / ".config" / "pi" / "harness"
    harness.mkdir(parents=True)
    shutil.copy2(HARNESS_SRC, harness / "index.ts")
    shutil.copytree(HARNESS_SRC.parent / "judge", harness / "judge")
    shutil.copy2(HARNESS_SRC.parent / "redact.ts", harness / "redact.ts")
    shutil.copy2(HARNESS_SRC.parent / "canary.ts", harness / "canary.ts")
    shutil.copy2(HARNESS_SRC.parent / "children.ts", harness / "children.ts")
    shutil.copy2(HARNESS_SRC.parent / "audit.ts", harness / "audit.ts")
    shutil.copy2(HARNESS_SRC.parent / "tools-ext.ts", harness / "tools-ext.ts")
    shutil.copy2(HARNESS_SRC.parent / "confirm-view.ts", harness / "confirm-view.ts")
    shutil.copy2(HARNESS_SRC.parent / "actions.ts", harness / "actions.ts")
    shutil.copy2(HARNESS_SRC.parent / "worktree.ts", harness / "worktree.ts")
    shutil.copy2(HARNESS_SRC.parent / "worktrees-command.ts", harness / "worktrees-command.ts")
    shutil.copy2(HARNESS_SRC.parent / "unguarded.ts", harness / "unguarded.ts")
    shutil.copy2(HARNESS_SRC.parent / "session-tmp.ts", harness / "session-tmp.ts")
    shutil.copy2(HARNESS_SRC.parent / "platform.ts", harness / "platform.ts")
    shutil.copy2(HARNESS_SRC.parent / "landlock_exec.py", harness / "landlock_exec.py")
    shutil.copy2(HARNESS_SRC.parent / "commit-message.js", harness / "commit-message.js")
    rules = gen.build_pi_harness({}, load_common())
    for agent in rules["agents"].values():
        agent["model"] = None
    # action を持たない役割では、bash の git commit は従来どおり確認を出す (この試験は「確認が 1 回だけ」を見る)
    for tools in rules["profile_tools"].values():
        if "action" in tools:
            tools.remove("action")
    for profile in (rules["judge"]["common"].get("pi") or {}).get("profiles", {}).values():
        if "action" in (profile.get("tools") or []):
            profile["tools"].remove("action")
    (harness / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
    env["env"]["AGENTS_CONFIG_DIR"] = str(agents_config_dir())
    calls = [{"name": "guarded_bash", "args": {"command": COMMIT}}]
    requests = _rpc(env, calls, [False], extra=("-nbt", "-ne", "-e", str(harness)))
    assert len(requests) == 1, requests


def test_a_commit_whose_structure_cannot_be_read_is_shown_raw_with_the_reason(env):
    requests = _rpc(env, bash_call("git commit -F missing-message.txt"), [False])
    assert requests[0]["message"].startswith(
        "構造を取得できなかったので、生のコマンドを表示します。"
    )
    assert "git commit -F missing-message.txt" in requests[0]["message"]


def test_a_later_confirmation_shows_the_state_before_the_earlier_commit_runs(env):
    """並んだ 2 件目の表示は、1 件目の確認が済んだ後に組むが、1 件目のコミットはまだ入っていない。

    pi は同じ応答の全呼び出しの tool_call を終えてから実行を始める (実行の終わりを待つと、
    安全弁の時間まで止まる)。そのため 2 件目は、1 件目が入る前の状態 (a.txt も対象) を見せる。
    既知の限界 (docs/spec/guard/pi-extensions.md#commit-の確認-素の-pi)。
    """
    (env["proj"] / "b.txt").write_text("b\n", encoding="utf-8")
    calls = bash_call(COMMIT) + bash_call("git add -- b.txt && git commit -m 'second'")
    requests = _rpc(env, calls, [True, False])
    assert len(requests) == 2
    assert "A a.txt" in requests[0]["message"]
    assert "A a.txt" in requests[1]["message"], requests[1]["message"]
    assert "A b.txt" in requests[1]["message"]


def test_commit_message_copy_for_opencode_is_identical():
    """OpenCode の guide plugin の写しと、フルガードの本体が一致する (撤去で写しを消す)。"""
    pi = ROOT / "home" / "dot_config" / "pi" / "harness" / "commit-message.js"
    copy = ROOT / "home" / "dot_config" / "opencode" / "guide-plugin" / "commit-message.js"

    def body(path):
        lines = path.read_text(encoding="utf-8").splitlines()
        return "\n".join(line for line in lines if not line.startswith("//"))

    assert body(pi) == body(copy)
