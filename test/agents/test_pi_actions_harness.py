"""``guarded_action`` (``home/dot_config/pi/harness/actions.ts``) の統合試験。

RPC + faux プロバイダーで、承認つきの git commit・gh issue comment を通しで確かめる。
``pi.actions`` の表は試験が rules.json へ自分で書く (生成器には依存しない)。
判定器がまだ ``action`` を allow しない間は飛ばす (test_pi_harness.py の needs_must_confirm と同じ流儀)。
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import time

import pytest
import test_pi_harness as H

pytestmark = pytest.mark.skipif(H.PI is None, reason="pi is not installed")

env = H.env  # 使い捨ての作業ツリーと rules.json (fixture を再利用)

ACTIONS = [
    {
        "id": "gh_issue_comment",
        "label": "issue にコメントを投稿",
        "argv": [
            "gh",
            "issue",
            "comment",
            "{number}",
            "-R",
            "{repo}",
            "--body-file",
            "{body_file}",
        ],
        "fields": {
            "repo": {"type": "repo"},
            "number": {"type": "int"},
            "body": {"type": "text", "file": True, "content": True, "max_chars": 8000},
        },
        "replaces": ["gh issue comment"],
        "preview": "none",
    },
    {
        "id": "gh_issue_edit_body",
        "label": "issue の本文を編集",
        "argv": ["gh", "issue", "edit", "{number}", "-R", "{repo}", "--body-file", "{body_file}"],
        "fields": {
            "repo": {"type": "repo"},
            "number": {"type": "int"},
            "body": {"type": "text", "file": True, "content": True, "max_chars": 8000},
        },
        "replaces": ["gh issue edit"],
        "preview": "none",
    },
    {
        "id": "gh_issue_edit_title",
        "label": "issue のタイトルを編集",
        "argv": ["gh", "issue", "edit", "{number}", "-R", "{repo}", "--title", "{title}"],
        "fields": {
            "repo": {"type": "repo"},
            "number": {"type": "int"},
            "title": {"type": "line", "content": True, "max_chars": 256},
        },
        "replaces": ["gh issue edit --title"],
        "preview": "none",
    },
    {
        "id": "git_commit",
        "label": "コミット",
        "argv": ["git", "commit", "-F", "{message_file}"],
        "fields": {"message": {"type": "text", "file": True, "content": True, "max_chars": 8000}},
        "replaces": ["git commit"],
        "preview": "git_staged",
    },
]


def _judge_allows_action():
    judge = H.HARNESS_SRC.parent / "judge"
    return any('"action"' in p.read_text(encoding="utf-8") for p in judge.glob("*.ts"))


needs_action = pytest.mark.skipif(
    not _judge_allows_action(), reason="判定器がまだ action を扱わない"
)

APPROVE, EDIT, REJECT = "承認して実行", "編集して承認", "拒否"


def _prepare(env, timeout_seconds=300):
    """rules.json に表・役割の action・確認の期限を書き、偽の gh と作業用の git リポジトリを用意する。"""
    path = env["harness"] / "rules.json"
    rules = json.loads(path.read_text(encoding="utf-8"))
    pi = rules["judge"]["common"].setdefault("pi", {})
    pi["actions"] = ACTIONS
    pi["confirm"] = {"timeout_seconds": timeout_seconds, "bash": []}
    for role in ("implementer", "worker"):
        tools = rules["profile_tools"].setdefault(role, [])
        if "action" not in tools:
            tools.append("action")
    path.write_text(json.dumps(rules), encoding="utf-8")
    tmp = env["tmp"]
    bindir = tmp / "fakebin"
    bindir.mkdir()
    gh = bindir / "gh"
    gh.write_text(
        "#!/bin/sh\n"
        'for a in "$@"; do printf "%s\\n" "$a"; done > "$FAKE_GH_DIR/args"\n'
        'prev=""\n'
        'for a in "$@"; do\n'
        '  if [ "$prev" = "--body-file" ]; then\n'
        '    cp "$a" "$FAKE_GH_DIR/body"; stat -c %a "$a" > "$FAKE_GH_DIR/mode"; printf "%s" "$a" > "$FAKE_GH_DIR/path"\n'
        "  fi\n"
        '  prev="$a"\n'
        "done\n"
        "echo https://example.test/o/r/issues/3#issuecomment-1\n",
        encoding="utf-8",
    )
    gh.chmod(0o755)
    ghdir = tmp / "ghlog"
    ghdir.mkdir()
    env["ghdir"] = ghdir
    env["env"]["PATH"] = f"{bindir}{os.pathsep}{env['env']['PATH']}"
    env["env"]["FAKE_GH_DIR"] = str(ghdir)
    env["env"]["PI_HARNESS_ROLE"] = "implementer"
    proj = env["proj"]
    _git(proj, "init", "-q")
    _git(proj, "config", "user.name", "t")
    _git(proj, "config", "user.email", "t@example.test")
    _git(proj, "config", "commit.gpgsign", "false")
    _git(proj, "config", "core.hooksPath", ".git/hooks")
    (proj / "base.txt").write_text("base\n", encoding="utf-8")
    _git(proj, "add", "base.txt")
    _git(proj, "commit", "-q", "-m", "base")


def _git(proj, *args):
    return subprocess.run(
        ["git", *args], cwd=proj, check=True, capture_output=True, text=True, encoding="utf-8"
    ).stdout


def _head(proj):
    return _git(proj, "rev-parse", "HEAD").strip()


def _stage(proj, name="new.txt", text="new\n"):
    (proj / name).write_text(text, encoding="utf-8")
    _git(proj, "add", name)


def _call(action, **params):
    return [{"name": "guarded_action", "args": {"action": action, "params": params}}]


def _rpc(env, calls, handler, timeout=60, **env_extra):
    """RPC で 1 回呼ぶ。handler(request) は応答の dict (confirmed / value / cancelled) か None (応えない)。

    返すのは (UI の要求の一覧, [(isError, 本文)])。
    """
    args = [H.PI, "--no-session", "--model", "faux/spike", "-nbt", "-ne", "-e", "builtin:mcp"]
    args += ["-e", str(env["harness"]), "-e", str(H.FIXTURES / "faux.ts"), "--mode", "rpc"]
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
    requests, results = [], []
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
                "confirm",
                "editor",
                "input",
            ):
                requests.append(event)
                answer = handler(event)
                if answer is not None:
                    proc.stdin.write(
                        json.dumps({"type": "extension_ui_response", "id": event["id"], **answer})
                        + "\n"
                    )
                    proc.stdin.flush()
            if event.get("type") == "tool_execution_end":
                res = event.get("result") or {}
                text = "".join(c.get("text", "") for c in res.get("content") or [])
                results.append((event.get("isError"), text))
            if event.get("type") == "agent_end":
                break
    finally:
        proc.kill()
    return requests, results


def _choose(choice, **others):
    """select に choice で応え、editor・input には others (editor= / input=) で応える。"""

    def handler(req):
        if req["method"] == "select":
            return {"value": choice}
        if req["method"] == "editor":
            return (
                {"value": others["editor"]}
                if others.get("editor") is not None
                else {"cancelled": True}
            )
        if req["method"] == "input":
            return {"value": others.get("input", "")}
        return {"confirmed": False}

    return handler


def _methods(requests):
    return [r["method"] for r in requests]


@needs_action
def test_approved_commit_runs_once_with_a_single_confirmation(env):
    _prepare(env)
    _stage(env["proj"])
    before = _head(env["proj"])
    requests, results = _rpc(
        env, _call("git_commit", message="feat: add new\n\n本文です"), _choose(APPROVE)
    )
    assert _methods(requests) == ["select"], requests  # 汎用の confirm は出ない
    title = requests[0]["title"]
    assert "コミット" in title and "feat: add new" in title and "new.txt" in title, title
    assert requests[0]["options"] == [APPROVE, EDIT, REJECT]
    assert requests[0].get("timeout") == 300 * 1000 + 3000  # 自前の期限 (300 秒) の 3 秒後の保険
    assert results and results[0][0] is False, results
    assert "実際に使った最終の内容" in results[0][1] and "本文です" in results[0][1]
    assert _head(env["proj"]) != before
    assert _git(env["proj"], "log", "-1", "--format=%B").strip() == "feat: add new\n\n本文です"
    assert not list(env["tmp"].glob("pi-action-*"))  # 本文ファイルのディレクトリが消える


@needs_action
def test_approved_issue_comment_passes_the_approved_argv_and_cleans_up(env):
    _prepare(env)
    body = "コメント本文\n2 行目 $(touch pwned) `x`"
    requests, results = _rpc(
        env, _call("gh_issue_comment", repo="o/r", number=3, body=body), _choose(APPROVE)
    )
    assert _methods(requests) == ["select"], requests
    title = requests[0]["title"]
    assert (
        "コメント本文" in title
        and "o/r" in title
        and '"gh","issue","comment","3","-R","o/r"' in title
    )
    assert (
        results and results[0][0] is False and "https://example.test/o/r/issues/3" in results[0][1]
    ), results
    args = (env["ghdir"] / "args").read_text(encoding="utf-8").splitlines()
    assert args[:6] == ["issue", "comment", "3", "-R", "o/r", "--body-file"], args
    assert (env["ghdir"] / "body").read_text(encoding="utf-8") == body
    assert (env["ghdir"] / "mode").read_text(encoding="utf-8").strip() == "600"
    path = (env["ghdir"] / "path").read_text(encoding="utf-8")
    assert path == args[6] and path.startswith("/")
    assert not os.path.exists(path) and not os.path.exists(os.path.dirname(path))
    assert not (env["proj"] / "pwned").exists()
    # 表示した argv と実行した argv が同じ (本文ファイルの絶対パスを含めて)
    assert json.dumps(["gh", *args], ensure_ascii=False, separators=(",", ":")) in title


@needs_action
def test_rejection_returns_the_reason_and_runs_nothing(env):
    _prepare(env)
    _stage(env["proj"])
    before = _head(env["proj"])
    requests, results = _rpc(
        env, _call("git_commit", message="x"), _choose(REJECT, input="件名が長い")
    )
    assert _methods(requests) == ["select", "input"], requests
    assert results[0][0] is True and "not approved:" in results[0][1], results
    assert "利用者が拒否した" in results[0][1] and "件名が長い" in results[0][1]
    assert _head(env["proj"]) == before


def _refs(proj):
    return [
        r
        for r in _git(proj, "for-each-ref", "--format=%(refname)", "refs/pi/pending/").split()
        if r
    ]


@needs_action
def test_no_answer_defers_the_commit_and_runs_nothing(env):
    _prepare(env, timeout_seconds=1)
    _stage(env["proj"])
    before = _head(env["proj"])
    requests, results = _rpc(env, _call("git_commit", message="feat: later"), lambda req: None)
    assert _methods(requests) == ["select"] and requests[0].get("timeout") == 4000, requests
    assert "応答が無ければ、実行せず内容を退避" in requests[0]["title"]
    ok, text = results[0]
    assert ok is True and text.startswith("not approved:"), results
    assert "元の操作は未実行" in text and "refs/pi/pending/" in text and "再試行しない" in text, (
        text
    )
    assert _head(env["proj"]) == before
    refs = _refs(env["proj"])
    assert len(refs) == 1
    assert _git(env["proj"], "show", "-s", "--format=%B", refs[0]).startswith("feat: later")
    assert "new.txt" in _git(env["proj"], "ls-tree", "-r", "--name-only", refs[0])


@needs_action
def test_the_deferred_commit_is_what_was_shown_even_if_the_index_changes_while_waiting(env):
    _prepare(env, timeout_seconds=1)
    _stage(env["proj"])

    def handler(req):
        # 待つ間に別のファイルをステージする
        _stage(env["proj"], name="later.txt", text="later\n")
        return None

    _requests, results = _rpc(env, _call("git_commit", message="m"), handler)
    assert results and results[0][0] is True and "refs/pi/pending/" in results[0][1], results
    refs = _refs(env["proj"])
    assert len(refs) == 1
    files = _git(env["proj"], "ls-tree", "-r", "--name-only", refs[0]).split()
    assert "new.txt" in files and "later.txt" not in files, files


@needs_action
def test_after_a_timeout_the_next_commit_is_deferred_without_waiting(env):
    _prepare(env, timeout_seconds=1)
    _stage(env["proj"])
    calls = _call("git_commit", message="one") + _call("git_commit", message="two")
    requests, results = _rpc(env, calls, lambda req: None)
    # 2 つ目は確認を出さず (不在)、退避する
    assert _methods(requests) == ["select"], requests
    assert len(results) == 2 and all(
        r[0] is True and "refs/pi/pending/" in r[1] for r in results
    ), results
    assert len(_refs(env["proj"])) == 2


@needs_action
@pytest.mark.parametrize(
    "answer", [{"cancelled": True}, {"value": REJECT}], ids=["cancel", "reject"]
)
def test_a_cancel_or_a_refusal_does_not_defer(env, answer):
    _prepare(env)
    _stage(env["proj"])
    before = _head(env["proj"])
    _requests, results = _rpc(env, _call("git_commit", message="x"), lambda req: answer)
    assert results and results[0][0] is True and "not approved:" in results[0][1], results
    assert "退避した" not in results[0][1], results
    assert _head(env["proj"]) == before
    assert _refs(env["proj"]) == []


@needs_action
def test_other_actions_are_still_refused_on_timeout(env):
    _prepare(env, timeout_seconds=1)
    requests, results = _rpc(
        env, _call("gh_issue_comment", repo="o/r", number=3, body="b"), lambda req: None
    )
    assert (
        results[0][0] is True and "not approved:" in results[0][1] and "再試行せず" in results[0][1]
    ), results
    assert "退避" not in requests[0]["title"]
    assert not (env["ghdir"] / "args").exists()


@needs_action
def test_without_a_ui_the_commit_is_deferred_and_nothing_runs(env):
    _prepare(env)
    _stage(env["proj"])
    before = _head(env["proj"])
    proc = H.run_pi(env, _call("git_commit", message="x"))
    assert "isError=true :: not approved:" in proc.stdout, proc.stdout + proc.stderr
    assert "refs/pi/pending/" in proc.stdout
    assert _head(env["proj"]) == before
    assert len(_refs(env["proj"])) == 1


@needs_action
def test_a_child_cannot_use_the_action_tool(env):
    _prepare(env)
    _stage(env["proj"])
    before = _head(env["proj"])
    proc = H.run_child(env, "worker", _call("git_commit", message="x"))
    assert proc.returncode == 0, proc.stderr
    assert _head(env["proj"]) == before
    assert not (env["ghdir"] / "args").exists()


@needs_action
def test_action_tool_is_registered_only_for_a_role_that_has_it(env):
    _prepare(env)
    proc = H.run_pi(env, [])
    assert "guarded_action" in H.lines(proc)[0], proc.stdout
    proc = H.run_pi(env, [], PI_HARNESS_ROLE="reader")
    assert "guarded_action" not in H.lines(proc)[0], proc.stdout


@needs_action
@pytest.mark.parametrize(
    ("call", "expected"),
    [
        (_call("nope"), "unknown action"),
        (_call("gh_issue_comment", repo="o/r", number=1), "params.body: 必須"),
        (_call("gh_issue_comment", repo="o/r", number="x", body="b"), "params.number"),
        (_call("gh_issue_comment", repo="o/r", number=0, body="b"), "params.number"),
        (_call("gh_issue_comment", repo="o/r", number=-1, body="b"), "params.number"),
        (_call("gh_issue_comment", repo="-o/r", number=1, body="b"), "params.repo"),
        (_call("gh_issue_comment", repo="o/r --x", number=1, body="b"), "params.repo"),
        (
            _call("gh_issue_comment", repo="o/r", number=1, body="x" * 8001),
            "params.body: 8000 字以下",
        ),
        (_call("gh_issue_comment", repo="o/r", number=1, body="a\0b"), "NUL"),
        (_call("gh_issue_comment", repo="o/r", number=1, body=""), "params.body: 空にできない"),
        (
            _call("gh_issue_comment", repo="o/r", number=1, body="b", extra="x"),
            "params.extra: 未知のキー",
        ),
        (_call("git_commit", message=3), "params.message: 文字列"),
    ],
)
def test_invalid_calls_are_errors_without_a_confirmation(env, call, expected):
    if not _judge_allows_action():
        pytest.skip("判定器がまだ action を扱わない")
    _prepare(env)
    requests, results = _rpc(env, call, _choose(APPROVE))
    assert requests == [], requests
    assert results and results[0][0] is True and expected in results[0][1], results
    assert not (env["ghdir"] / "args").exists()


@needs_action
def test_commit_with_nothing_staged_is_an_error_without_a_confirmation(env):
    _prepare(env)
    before = _head(env["proj"])
    requests, results = _rpc(env, _call("git_commit", message="x"), _choose(APPROVE))
    assert requests == [], requests
    assert results[0][0] is True and "ステージ済み" in results[0][1], results
    assert _head(env["proj"]) == before


@needs_action
def test_index_change_after_approval_requires_a_new_call(env):
    _prepare(env)
    _stage(env["proj"])
    before = _head(env["proj"])

    def handler(req):
        # 確認に応える間に、別のファイルをステージする
        _stage(env["proj"], "sneaky.txt", "sneaky\n")
        return {"value": APPROVE}

    requests, results = _rpc(env, _call("git_commit", message="x"), handler)
    assert _methods(requests) == ["select"], requests
    assert results[0][0] is True and "状態が変わった" in results[0][1], results
    assert _head(env["proj"]) == before


@needs_action
def test_failing_hook_output_is_returned_as_an_error(env):
    _prepare(env)
    hook = env["proj"] / ".git" / "hooks" / "pre-commit"
    hook.write_text(
        "#!/bin/sh\necho hook-says-no\necho hook-stderr >&2\nexit 1\n", encoding="utf-8"
    )
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
    _stage(env["proj"])
    before = _head(env["proj"])
    _, results = _rpc(env, _call("git_commit", message="x"), _choose(APPROVE))
    assert results[0][0] is True, results
    assert (
        "hook-says-no" in results[0][1]
        and "hook-stderr" in results[0][1]
        and "終了コード 1" in results[0][1]
    )
    assert _head(env["proj"]) == before


@needs_action
def test_edit_and_approve_uses_the_edited_text_and_returns_it(env):
    _prepare(env)
    _stage(env["proj"])
    requests, results = _rpc(
        env, _call("git_commit", message="before"), _choose(EDIT, editor="fix: edited message")
    )
    assert _methods(requests) == ["select", "editor"], requests
    assert requests[1]["prefill"] == "before"
    assert results[0][0] is False and "fix: edited message" in results[0][1], results
    assert "before" not in results[0][1]
    assert _git(env["proj"], "log", "-1", "--format=%B").strip() == "fix: edited message"


@needs_action
def test_edit_cancelled_or_emptied_is_a_rejection(env):
    _prepare(env)
    _stage(env["proj"])
    before = _head(env["proj"])
    for handler in (_choose(EDIT), _choose(EDIT, editor="  \n")):
        _, results = _rpc(env, _call("git_commit", message="before"), handler)
        assert results[0][0] is True and "not approved:" in results[0][1], results
        assert _head(env["proj"]) == before


@needs_action
def test_the_approval_is_for_one_run_only(env):
    _prepare(env)
    _stage(env["proj"])
    calls = _call("git_commit", message="once")
    rounds = [calls, _call("git_commit", message="twice")]
    requests, results = _rpc(env, calls, _choose(APPROVE), FAUX_TOOL_ROUNDS=json.dumps(rounds))
    # 2 回目は、ステージ済みが無いので確認なしのエラー (承認は再利用されない)
    assert _methods(requests) == ["select"], requests
    assert [r[0] for r in results] == [False, True], results


@needs_action
def test_approved_issue_title_edit_passes_the_title_as_one_argv_element(env):
    _prepare(env)
    title = "新しい題 $(touch pwned) `x` --body injected"
    requests, results = _rpc(
        env, _call("gh_issue_edit_title", repo="o/r", number=7, title=title), _choose(APPROVE)
    )
    assert _methods(requests) == ["select"], requests
    shown = requests[0]["title"]
    assert "新しい題" in shown and "o/r" in shown and '"--title"' in shown
    assert results and results[0][0] is False, results
    args = (env["ghdir"] / "args").read_text(encoding="utf-8").splitlines()
    assert args == ["issue", "edit", "7", "-R", "o/r", "--title", title], args
    assert not (env["proj"] / "pwned").exists()


@needs_action
def test_approved_issue_body_edit_writes_the_body_file(env):
    _prepare(env)
    body = "更新した本文\n- [ ] 項目"
    requests, results = _rpc(
        env, _call("gh_issue_edit_body", repo="o/r", number=7, body=body), _choose(APPROVE)
    )
    assert _methods(requests) == ["select"], requests
    assert results and results[0][0] is False, results
    args = (env["ghdir"] / "args").read_text(encoding="utf-8").splitlines()
    assert args[:6] == ["issue", "edit", "7", "-R", "o/r", "--body-file"], args
    assert (env["ghdir"] / "body").read_text(encoding="utf-8") == body


@needs_action
@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("1 行目\n2 行目", "改行・制御文字"),
        ("tab\tinside", "改行・制御文字"),
        ("nul\0inside", "改行・制御文字"),
        ("   ", "空にできない"),
        ("x" * 257, "256 字以下"),
    ],
)
def test_an_invalid_issue_title_is_refused_before_any_confirmation(env, title, expected):
    _prepare(env)
    requests, results = _rpc(
        env, _call("gh_issue_edit_title", repo="o/r", number=7, title=title), _choose(APPROVE)
    )
    assert requests == [], requests
    assert results and results[0][0] is True and expected in results[0][1], results
    assert not (env["ghdir"] / "args").exists()


@needs_action
def test_the_rpc_confirmation_is_compact_for_a_long_message_and_many_files(env):
    """RPC (Orca・Zed) の select は title しか持たない。全部を詰めると chat UI で巨大になるので縮める。"""
    _prepare(env)
    proj = env["proj"]
    for i in range(30):
        _stage(proj, name=f"f{i:02d}.txt", text=f"{i}\n")
    body = "\n".join(f"line {i}" for i in range(60))
    requests, _ = _rpc(env, _call("git_commit", message="feat: many\n\n" + body), _choose(REJECT))
    title = requests[0]["title"]
    assert "feat: many" in title and "line 0" in title
    assert "line 59" not in title  # 本文は先頭だけ
    assert "他 20 ファイル" in title and "30 files changed" in title  # 統計は先頭 10 件と要約
    assert EDIT in title  # 全文の見方を案内する
    assert len(title) < 1800, len(title)


@needs_action
def test_the_edit_dialog_still_shows_the_full_message_when_the_view_is_compact(env):
    """縮めるのは確認の表示だけ。『編集して承認』のエディタには全文が出る。"""
    _prepare(env)
    _stage(env["proj"])
    body = "\n".join(f"line {i}" for i in range(60))
    requests, _ = _rpc(env, _call("git_commit", message="feat: long\n\n" + body), _choose(EDIT))
    editors = [r for r in requests if r["method"] == "editor"]
    assert editors, _methods(requests)
    assert "line 59" in editors[0]["prefill"]
