"""確認表 ``[pi.confirm]`` (bypass でも確認する ask) と、公開・配布の deny。

- TS 版の判定器: ``mustConfirm`` の ask は bypass もサンドボックスの緩和も効かない。
- ``[bash] deny`` に足した公開・配布のコマンド (TS 版・Python 版の両方)。
- ``gh api`` の公開・配布 (``check_gh_api_publish``) が TS 版と Python 版で同じ判定になる。
- 生成器が ``[pi.confirm]`` を検証して rules.json へ出す。

判定器には、正解データではなく現在の common.toml (生成器が出す形) を渡す。
see docs/spec/guard/pi-decide.md#confirm
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest
from agents_common import ROOT, load_common
from check_bash_hook import run_hook
from test_pi_judge_ts import _node

sys.path.insert(0, str(ROOT / "scripts" / "agents"))
import generate as gen

PREFIX = "確認が必要な外部への送信・公開 (bypass でも確認する): "
BLIND = "本文を確認できない形"

needs_node = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")


def _judge(requests, common=None):
    common = common or gen.pi_judge_data(load_common())["common"]
    proc = subprocess.run(
        [_node(), str(ROOT / "test" / "agents" / "pi" / "judge_boundary.mjs")],
        input=json.dumps({"requests": requests, "common": common}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout)


def _bash(command, **extra):
    return {
        "tool": "bash",
        "input": {"command": command},
        "cwd": "/work/proj",
        "role": "implementer",
        **extra,
    }


def _modes(command, role="implementer"):
    """同じコマンドを、通常・bypass・boundary・両方で判定する。"""
    return [
        _bash(command, role=role, **flags)
        for flags in ({}, {"bypass": True}, {"boundary": True}, {"bypass": True, "boundary": True})
    ]


CONFIRM_COMMANDS = [
    "gh pr create --title t --body b",
    "gh pr edit 1 --title t",
    "gh pr review 1 --approve --body ok",
    "gh pr comment 1 --body x",
    "gh pr close 1",
    "gh pr reopen 1",
    "gh pr ready 1",
    "gh issue create --title t --body b",
    "gh issue close 1",
    "gh issue reopen 1",
    "gh issue lock 1",
    "gh issue unlock 1",
    "gh issue transfer 1 o/r",
    "gh issue pin 1",
    "gh issue unpin 1",
    "gh issue delete 1",
    "gh repo fork o/r",
    "gh repo rename new",
    "gh repo archive o/r",
    "gh repo unarchive o/r",
    "gh workflow run ci.yml",
    "gh workflow enable ci.yml",
    "gh workflow disable ci.yml",
    "gh variable set X --body v",
    "gh variable delete X",
    "gh gist edit abc",
    "gh gist delete abc",
]

PREFIXED_FORMS = [
    "cd x && gh pr create --title t --body b",
    "gh -R owner/repo pr create --title t --body b",
    "gh --repo x issue close 1",
    "env gh pr create --title t --body b",
    "bash -c 'gh pr create --title t --body b'",
    "echo hi; gh issue close 1",
]

BLIND_COMMANDS = [
    "gh pr create --title t --body-file -",
    "gh pr comment 1 -F -",
    "gh issue create -b - -t x",
    "gh pr edit 1 --body-file=-",
    'gh pr create --title t --body "$(cat f)"',
    "gh pr edit 1 --body `date`",
    "gh pr review 1 --approve --body-file -",
    "bash -c 'gh pr create --title t --body-file -'",
]

PUBLISH_DENY = [
    "gh repo edit --visibility public",
    "gh repo create foo --public",
    "gh release delete v1",
    "gh release edit v1",
    "npm publish",
    "yarn publish",
    "pnpm publish",
    "uv publish",
    "twine upload dist/*",
    "cargo publish",
    "gem push foo.gem",
    "docker push myimage",
]

API_PUBLISH_DENY = [
    "gh api -X PATCH repos/o/r -f private=false",
    "gh api -X DELETE repos/o/r",
    "gh api -X PUT repos/o/r/contents/a.txt -f message=m",
    "gh api -X DELETE repos/o/r/contents/a.txt -f message=m",
    "gh api -X POST repos/o/r/git/refs -f ref=refs/heads/x",
    "gh api -X PATCH repos/o/r/git/refs/heads/x -f sha=abc",
    "gh api -X DELETE repos/o/r/git/refs/heads/x",
    "gh api -X POST repos/o/r/git/commits -f message=m",
    "gh api -X POST repos/o/r/releases -f tag_name=v1",
    "gh api -X PATCH repos/o/r/releases/1 -f name=n",
    "gh api -X DELETE repos/o/r/releases/1",
    "gh api -X POST user/repos -f name=x",
    "gh api -X POST orgs/acme/repos -f name=x",
    "gh api -X POST repos/o/r/transfer -f new_owner=x",
    "gh api -X POST repos/o/r/pages",
    "gh api -X PUT repos/o/r/pages -f a=b",
    "gh api -X POST repos/o/r/hooks -f name=web",
    "gh api -X DELETE repos/o/r/hooks/1",
    "gh api -X PUT repos/o/r/collaborators/bob",
    "gh api -X DELETE repos/o/r/collaborators/bob",
    "gh api -X POST repos/o/r/dispatches -f event_type=x",
    "gh api -X PUT repos/o/r/actions/secrets/NAME -f a=b",
    "gh api -X DELETE repos/o/r/actions/secrets/NAME",
    "gh api -X POST /repos/o/r/git/refs -f ref=x",
    "gh api --method=POST repos/o/r/releases -f tag_name=v1",
    "gh api graphql -f query='mutation { createRepository(input: {name: \"x\"}) { clientMutationId } }'",
    "gh api graphql -f query='mutation { mergePullRequest(input: {pullRequestId: \"x\"}) { clientMutationId } }'",
    "gh api graphql -F query='mutation { deleteRef(input: {refId: \"x\"}) { clientMutationId } }'",
]

# 公開・配布ではない書き込み (ask。TS では mustConfirm)
API_WRITE_ASK = [
    "gh api -X POST repos/o/r/issues -f title=x",
    "gh api -X PATCH repos/o/r/issues/1 -f state=closed",
    "gh api -X POST repos/o/r/issues/1/comments -f body=x",
    "gh api -X POST repos/o/r -f a=b",
    "gh api --input body.json -X POST repos/o/r/issues",
    "gh api graphql -F query=@q.graphql",
    'gh api graphql -f query=\'mutation { addComment(input: {subjectId: "x", body: "y"}) { clientMutationId } }\'',
]

API_READS = [
    "gh api repos/o/r",
    "gh api -X GET repos/o/r/contents/a.txt",
    "gh api repos/o/r/releases",
    "gh api graphql -f query='query { viewer { login } }'",
]


# ─── mustConfirm: bypass もサンドボックスの緩和も効かない ───────────────────


@needs_node
def test_confirm_table_asks_even_with_bypass_and_boundary():
    for command in CONFIRM_COMMANDS:
        for flags, out in zip(
            ("none", "bypass", "boundary", "both"), _judge(_modes(command)), strict=True
        ):
            assert out["decision"] == "ask", f"{command!r} [{flags}] -> {out}"
            assert out["mustConfirm"] is True, f"{command!r} [{flags}] -> {out}"
            assert out["reason"].startswith(PREFIX), out["reason"]
            assert "bypassed" not in out and "sandboxed" not in out


@needs_node
def test_existing_bash_ask_commands_in_the_table_become_must_confirm():
    # [bash] ask にもある gh pr create / gh issue create|close は、確認表が先に当たる
    # (gh issue comment は implementer では guarded_action へ誘導する deny。test_pi_actions.py)
    for command in (
        "gh pr create --title t --body b",
        "gh issue close 1",
    ):
        out = _judge(_modes(command))
        assert all(o["decision"] == "ask" and o["mustConfirm"] is True for o in out), out


@needs_node
def test_non_table_commands_keep_the_old_bypass_and_boundary_behaviour():
    out = _judge(_modes("touch made-by-pi"))
    assert (out[0]["decision"], out[0]["source"]) == ("ask", "default")
    assert out[1]["decision"] == "allow" and out[1]["bypassed"] is True
    assert out[2]["decision"] == "allow" and out[2]["sandboxed"] is True
    assert out[3]["decision"] == "allow"
    assert all("mustConfirm" not in o for o in out)
    # [bash] ask の通常の確認は bypass で allow のまま
    out = _judge(_modes("git add a"))
    assert out[0]["decision"] == "ask" and "mustConfirm" not in out[0]
    assert out[1]["decision"] == "allow" and out[1]["bypassed"] is True


@needs_node
def test_deny_guide_and_shell_deny_come_before_the_table():
    out = _judge(
        [
            _bash("gh repo edit --visibility public", bypass=True),
            _bash("gh repo create x", bypass=True, boundary=True),
            # 誘導 (pip) は確認表より先
            _bash("pip install x && gh pr create --title t --body b", bypass=True),
            # 役割の shell_deny (worker は git commit を禁じる) は確認表より先
            _bash("git commit -m x && gh pr create --title t --body b", role="worker", bypass=True),
            # [bash] allow / skill_scripts に先取りされない
            _bash("git log && gh pr create --title t --body b", bypass=True),
        ]
    )
    assert [o["decision"] for o in out[:4]] == ["deny"] * 4
    assert all("mustConfirm" not in o for o in out[:4])
    assert out[4]["decision"] == "ask" and out[4]["mustConfirm"] is True


@needs_node
@pytest.mark.parametrize("command", PREFIXED_FORMS)
def test_confirm_table_matches_prefixed_and_nested_forms(command):
    out = _judge(_modes(command))
    assert all(o["decision"] == "ask" and o["mustConfirm"] is True for o in out), out


@needs_node
def test_sudo_prefix_is_still_denied():
    out = _judge([_bash("sudo gh pr create --title t --body b", bypass=True)])
    assert out[0]["decision"] == "deny"


# ─── 本文を確認できない形は deny ──────────────────────────────────────


@needs_node
@pytest.mark.parametrize("command", BLIND_COMMANDS)
def test_unverifiable_body_is_denied(command):
    out = _judge(_modes(command))
    for o in out:
        assert o["decision"] == "deny" and BLIND in o["reason"], (command, o)
        assert "mustConfirm" not in o


@needs_node
def test_body_from_a_file_or_inline_is_confirmed_not_denied():
    for command in (
        "gh pr create --title t --body-file body.md",
        "gh pr create --title t --body 'hello world'",
        "gh pr close 1 --comment x",
    ):
        out = _judge(_modes(command))
        assert all(o["decision"] == "ask" and o["mustConfirm"] is True for o in out), (command, out)


# ─── [bash] deny の追加 ─────────────────────────────────────────────


@needs_node
@pytest.mark.parametrize("command", PUBLISH_DENY)
def test_ts_publish_commands_are_denied(command):
    out = _judge(_modes(command))
    assert all(o["decision"] == "deny" for o in out), (command, out)


@pytest.mark.parametrize("command", PUBLISH_DENY)
def test_python_publish_commands_are_denied(command):
    decision, reason = run_hook(command)
    assert decision == "deny", f"{command!r} -> {decision} ({reason})"


def test_docker_push_moved_from_ask_to_deny():
    bash = load_common()["bash"]
    assert "docker push" in bash["deny"] and "docker push" not in bash["ask"]
    assert "docker push" in bash["deny_guide"]["user_only"]


def test_every_new_deny_is_classified_in_deny_guide():
    bash = load_common()["bash"]
    patterns = [
        "gh repo edit",
        "gh repo create",
        "gh release delete",
        "gh release edit",
        "npm publish",
        "yarn publish",
        "pnpm publish",
        "uv publish",
        "twine upload",
        "cargo publish",
        "gem push",
        "docker push",
    ]
    assert len(patterns) == len(PUBLISH_DENY)
    for pattern in patterns:
        assert pattern in bash["deny"], pattern
        assert pattern in bash["deny_guide"]["user_only"], pattern


# ─── gh api の公開・配布 (TS と Python で同じ) ─────────────────────────


@needs_node
def test_ts_gh_api_publish_is_denied_and_other_writes_are_confirmed():
    deny = _judge([_bash(c, bypass=True) for c in API_PUBLISH_DENY])
    for command, out in zip(API_PUBLISH_DENY, deny, strict=True):
        assert out["decision"] == "deny" and out.get("check") == "check_gh_api_publish", (
            command,
            out,
        )
        assert "公開・配布に当たる API 操作" in out["reason"]
    ask = _judge([_bash(c, bypass=True, boundary=True) for c in API_WRITE_ASK])
    for command, out in zip(API_WRITE_ASK, ask, strict=True):
        assert out["decision"] == "ask" and out["mustConfirm"] is True, (command, out)
        assert out["reason"].startswith(PREFIX) and out.get("check") == "check_gh_api_mutation"
    reads = _judge([_bash(c, bypass=True) for c in API_READS])
    for command, out in zip(API_READS, reads, strict=True):
        assert out["decision"] == "allow" and "mustConfirm" not in out, (command, out)


@pytest.mark.parametrize("command", API_PUBLISH_DENY)
def test_python_gh_api_publish_is_denied(command):
    decision, reason = run_hook(command)
    assert decision == "deny" and "公開・配布に当たる API 操作" in reason, (decision, reason)


@pytest.mark.parametrize("command", API_WRITE_ASK)
def test_python_gh_api_other_writes_still_ask(command):
    decision, reason = run_hook(command)
    assert decision == "ask", f"{command!r} -> {decision} ({reason})"


@pytest.mark.parametrize("command", API_READS)
def test_python_gh_api_reads_are_not_blocked(command):
    decision, reason = run_hook(command)
    assert decision is None, f"{command!r} -> {decision} ({reason})"


# ─── ask の優先順位 (現状の順序を保つ) ─────────────────────────────────


@needs_node
def test_confirm_checks_come_before_the_other_asks():
    # [bash] ask の git commit (check_policy_ask) と複合しても、gh api の書き込みは bypass でも確認する
    out = _judge([_bash("git add a && gh api -X POST repos/o/r/issues -f title=x", bypass=True)])
    assert out[0]["decision"] == "ask" and out[0]["mustConfirm"] is True
    assert "bypassed" not in out[0]


# ─── 生成器: [pi.confirm] の検証 ──────────────────────────────────────


def _with_confirm(section):
    common = load_common()
    if section is None:
        common["pi"].pop("confirm", None)
    else:
        common["pi"]["confirm"] = section
    return common


def _confirm_of(common):
    return gen.build_pi_harness({}, common)["judge"]["common"]["pi"]["confirm"]


def test_rules_json_carries_the_confirm_table():
    confirm = _confirm_of(load_common())
    assert confirm["timeout_seconds"] == 300
    assert confirm["checks"] == ["check_gh_api_mutation"]
    assert "gh pr create" in confirm["bash"] and "gh workflow run" in confirm["bash"]
    assert all(isinstance(c, str) for c in confirm["bash"])


def test_confirm_defaults_when_omitted():
    assert _confirm_of(_with_confirm(None)) == {
        "bash": [],
        "checks": [],
        "timeout_seconds": 300,
        "local_git": False,
    }
    assert _confirm_of(_with_confirm({"bash": ["gh pr create"]})) == {
        "bash": ["gh pr create"],
        "checks": [],
        "timeout_seconds": 300,
        "local_git": False,
    }


@pytest.mark.parametrize("seconds", [10, 300, 3600])
def test_confirm_timeout_accepts_the_range(seconds):
    assert _confirm_of(_with_confirm({"timeout_seconds": seconds}))["timeout_seconds"] == seconds


@pytest.mark.parametrize("seconds", [9, 3601, 0, -1, 1.5, "300", True, False, None])
def test_confirm_timeout_rejects_bad_values(seconds):
    with pytest.raises(SystemExit):
        _confirm_of(_with_confirm({"timeout_seconds": seconds}))


@pytest.mark.parametrize(
    "section",
    [
        {"checks": ["check_nonexistent"]},
        # DENY の検査は確認表に載せられない (ASK_NAMES に無い)
        {"checks": ["check_gh_api_publish"]},
        {"checks": "check_gh_api_mutation"},
        {"checks": [1]},
        {"bash": "gh pr create"},
        {"bash": [1]},
        {"bash": [""]},
    ],
)
def test_confirm_rejects_bad_lists(section):
    with pytest.raises(SystemExit):
        _confirm_of(_with_confirm(section))


def test_confirm_rejects_unknown_keys_and_non_tables():
    with pytest.raises(ValueError, match="未知のキー"):
        _confirm_of(_with_confirm({"bsh": ["gh pr create"]}))
    with pytest.raises(SystemExit):
        _confirm_of(_with_confirm(["gh pr create"]))
