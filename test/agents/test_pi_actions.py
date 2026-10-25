"""``[[pi.actions]]`` (guarded_action の操作表) の判定器と生成器の試験。

- 生成器: 表の検証 (正常・各種の不正) と rules.json への出力。
- 判定器 (TS 版・Python 版): action ツールの allow / deny、役割に action があるときだけ bash の
  ``git commit`` / ``gh issue comment`` を deny + 呼び出し例の案内。理由の文字列は両方で同一。
- action を持たない役割の従来の挙動は変わらない。

see docs/spec/guard/pi-decide.md
"""

from __future__ import annotations

import copy
import json
import sys

import pytest
from agents_common import ROOT, load_common
from test_decide import bash as py_bash
from test_decide import decide as py_decide
from test_pi_confirm import _judge  # 判定器 (TS 版) へ common を渡す口
from test_pi_judge_ts import _node

sys.path.insert(0, str(ROOT / "scripts" / "agents"))
import generate as gen

needs_node = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")

HEAD = (
    "投稿・コミットは guarded_action で行う（承認はそのツールが 1 回だけ取る。"
    "事前に ask やチャットで承認を取らない）。"
    "呼び出し例（値は候補。実際の値を確認する）: guarded_action "
)
COMMIT = HEAD + '{"action":"git_commit","params":{"message":"<件名と本文>"}}'


def _comment(repo: str = "<owner/name>", number: str = "<N>") -> str:
    r = f'"{repo}"'
    return (
        HEAD
        + '{"action":"gh_issue_comment","params":{"repo":'
        + r
        + ',"number":'
        + number
        + ',"body":"<本文>"}}'
    )


# (コマンド, 期待する理由。None は action の deny にならない)
CASES = [
    ("git commit -m x", COMMIT),
    ("git commit", COMMIT),
    ("git -C d commit -m x", COMMIT),
    ("cd x && git commit -m x", COMMIT),
    ("git add a && git commit -m x", COMMIT),
    ("bash -c 'git commit -m x'", COMMIT),
    ("env git commit -m x", COMMIT),
    ("gh issue comment 1 -R o/r --body x", _comment("o/r", "1")),
    ("gh issue comment 12 --repo o/r --body x", _comment("o/r", "12")),
    ("gh issue comment 12 --repo=o/r -b x", _comment("o/r", "12")),
    ("gh -R o/r issue comment 3 --body x", _comment("o/r", "3")),
    ("cd x && gh issue comment 7 -R o/r -b x", _comment("o/r", "7")),
    ("bash -c 'gh -R o/r issue comment 9 --body x'", _comment("o/r", "9")),
    # 値が分からなければプレースホルダーのまま
    ("gh issue comment 5 --body x", _comment(number="5")),
    ("gh issue comment --body x", _comment()),
    ("gh issue comment 1 -R bad --body x", _comment(number="1")),
    ("gh issue comment https://example.com/o/r/issues/1 -b x", _comment()),
    ("gh issue comment", _comment()),
    # 当たらない
    ("echo git commit", None),
    ("git commit-tree HEAD", None),
    ("gh issue view 1", None),
    ("git log", None),
]


def _pi_common() -> dict:
    return gen.pi_judge_data(load_common())["common"]


def _with(common: dict, *, actions=..., implementer_tools=None) -> dict:
    out = copy.deepcopy(common)
    if actions is not ...:
        out["pi"]["actions"] = actions
    if implementer_tools is not None:
        out["pi"]["profiles"]["implementer"]["tools"] = implementer_tools
    return out


def _bash(command: str, role: str = "implementer", **extra) -> dict:
    return {
        "tool": "bash",
        "input": {"command": command},
        "cwd": "/work/proj",
        "role": role,
        **extra,
    }


def _action(role: str = "implementer", **extra) -> dict:
    return {
        "tool": "action",
        "input": {"action": "git_commit", "params": {"message": "x"}},
        "cwd": "/work/proj",
        "role": role,
        **extra,
    }


# ─── 生成器 ────────────────────────────────────────────────────────────


def _actions_of(common: dict) -> list:
    return gen.build_pi_harness({}, common)["judge"]["common"]["pi"]["actions"]


def _entry(**over) -> dict:
    base = {
        "id": "demo",
        "label": "デモ",
        "argv": ["demo", "{repo}", "{number}", "-F", "{body_file}"],
        "fields": {
            "repo": {"type": "repo"},
            "number": {"type": "int"},
            "body": {"type": "text", "file": True, "content": True, "max_chars": 100},
        },
        "replaces": ["demo run"],
        "preview": "none",
    }
    return {**base, **over}


def _common_with(*entries) -> dict:
    common = copy.deepcopy(load_common())
    common["pi"]["actions"] = list(entries)
    return common


def test_rules_json_carries_the_two_actions():
    actions = _actions_of(load_common())
    assert [a["id"] for a in actions] == ["gh_issue_comment", "git_commit"]
    comment, commit = actions
    assert comment["argv"] == [
        "gh",
        "issue",
        "comment",
        "{number}",
        "-R",
        "{repo}",
        "--body-file",
        "{body_file}",
    ]
    assert comment["replaces"] == ["gh issue comment"] and comment["preview"] == "none"
    assert commit["argv"] == ["git", "commit", "-F", "{message_file}"]
    assert commit["replaces"] == ["git commit"] and commit["preview"] == "git_staged"
    assert commit["fields"] == {
        "message": {"type": "text", "file": True, "content": True, "max_chars": 8000}
    }


def test_only_the_implementer_gets_the_action_tool():
    profiles = load_common()["pi"]["profiles"]
    assert "action" in profiles["implementer"]["tools"]
    assert [n for n, p in profiles.items() if "action" in p["tools"]] == ["implementer"]


def test_no_table_means_an_empty_array():
    common = copy.deepcopy(load_common())
    common["pi"].pop("actions", None)
    assert _actions_of(common) == []
    assert _actions_of(_common_with()) == []


def test_a_valid_extra_entry_is_accepted():
    actions = _actions_of(_common_with(_entry()))
    assert actions[0]["id"] == "demo" and actions[0]["fields"]["repo"] == {"type": "repo"}


@pytest.mark.parametrize(
    "bad",
    [
        _entry(id="Bad-Id"),
        _entry(id="1x"),
        _entry(label=""),
        _entry(preview="shell"),
        _entry(preview=None),
        _entry(replaces=[]),
        _entry(replaces=[""]),
        _entry(replaces="demo run"),
        _entry(argv=[]),
        _entry(argv="demo"),
        _entry(argv=["{repo}", "{number}", "{body_file}"]),  # 先頭に置換点
        _entry(argv=["demo", "{repo}", "{number}", "{body_file}", "{nope}"]),  # 未知の置換点
        _entry(argv=["demo", "{repo}", "{body_file}"]),  # number が argv に無い
        _entry(argv=["demo", "{repo}", "{number}", "{body}"]),  # text は _file でだけ使える
        _entry(argv=["demo", "{repo}", "{number}", "{body_file", "x"]),
        _entry(fields={}),
        _entry(fields={"repo": {"type": "shell"}}),
        _entry(fields={"repo": {"type": "repo", "max_chars": 3}}),
        _entry(
            fields={
                "repo": {"type": "repo"},
                "number": {"type": "int"},
                "body": {"type": "text", "file": True, "content": True},  # max_chars が無い
            }
        ),
        _entry(
            fields={
                "repo": {"type": "repo"},
                "number": {"type": "int"},
                "body": {"type": "text", "file": False, "max_chars": 10},  # file でない text
            }
        ),
        _entry(
            fields={
                "repo": {"type": "repo"},
                "number": {"type": "int"},
                "body": {"type": "text", "file": True, "max_chars": 0},
            }
        ),
        _entry(extra=1),
    ],
)
def test_bad_entries_are_rejected_before_startup(bad):
    with pytest.raises((SystemExit, ValueError)):
        _actions_of(_common_with(bad))


def test_duplicate_ids_are_rejected():
    with pytest.raises(SystemExit):
        _actions_of(_common_with(_entry(), _entry()))


def test_a_non_array_table_is_rejected():
    common = copy.deepcopy(load_common())
    common["pi"]["actions"] = {"id": "x"}
    with pytest.raises(SystemExit):
        _actions_of(common)


# ─── 判定器: action ツール ───────────────────────────────────────────────


@needs_node
def test_ts_action_tool_is_allowed_only_for_roles_with_it():
    common = _pi_common()
    reqs = [
        _action(role=r, bypass=b)
        for r in ("implementer", "explorer", "reader")
        for b in (False, True)
    ]
    out = _judge(reqs, common)
    assert [o["decision"] for o in out] == ["allow", "allow", "deny", "deny", "deny", "deny"]
    assert all(o["source"] == "rule" for o in out)
    assert all("mustConfirm" not in o and "bypassed" not in o for o in out)
    # boundary でも変わらない (確認は execute() が 1 回だけ取る)
    assert _judge([_action(boundary=True)], common)[0]["decision"] == "allow"


def test_python_action_tool_is_allowed_only_for_roles_with_it():
    out = [
        py_decide(_action(role=r, bypass=b) | {"cwd": str(ROOT)})
        for r in ("implementer", "explorer")
        for b in (False, True)
    ]
    assert [o["decision"] for o in out] == ["allow", "allow", "deny", "deny"]
    assert all(o["source"] == "rule" and "bypassed" not in o for o in out)


# ─── 判定器: bash の deny + 呼び出し例 ───────────────────────────────────────


@needs_node
@pytest.mark.parametrize(("command", "reason"), CASES)
def test_ts_bash_replaced_commands_are_denied_with_an_example(command, reason):
    for extra in ({}, {"bypass": True}, {"boundary": True}, {"bypass": True, "boundary": True}):
        out = _judge([_bash(command, **extra)], _pi_common())[0]
        if reason is None:
            assert out["reason"] != "" and not out["reason"].startswith(HEAD[:20]), out
        else:
            assert (out["decision"], out["source"], out["reason"]) == ("deny", "rule", reason), out


@pytest.mark.parametrize(("command", "reason"), CASES)
def test_python_bash_replaced_commands_are_denied_with_an_example(command, reason):
    out = py_bash(command)
    if reason is None:
        assert not out["reason"].startswith(HEAD[:20]), out
    else:
        assert (out["decision"], out["source"], out["reason"]) == ("deny", "rule", reason), out
        assert py_bash(command, bypass=True)["reason"] == reason


@needs_node
def test_ts_and_python_agree_on_the_reason():
    out = _judge([_bash(c) for c, _ in CASES], _pi_common())
    for (command, _), ts in zip(CASES, out, strict=True):
        py = py_bash(command)
        if ts["reason"].startswith(HEAD[:20]) or py["reason"].startswith(HEAD[:20]):
            assert ts["reason"] == py["reason"], command


@needs_node
def test_the_deny_is_placed_after_the_guide_and_before_shell_deny_and_confirm():
    common = _pi_common()
    out = _judge(
        [
            # 誘導 (pip) が先
            _bash("pip install x && git commit -m x"),
            # 確認表 ([pi.confirm] bash) の gh issue comment より先に、action の deny が当たる
            _bash("gh issue comment 1 -R o/r --body x"),
            # 共通の deny が先
            _bash("git push && git commit -m x"),
        ],
        common,
    )
    # 誘導・共通の deny が先 (action の案内にならない)
    assert out[0]["decision"] == "deny" and not out[0]["reason"].startswith(HEAD[:20])
    assert out[1]["reason"] == _comment("o/r", "1") and "mustConfirm" not in out[1]
    assert out[2]["decision"] == "deny" and not out[2]["reason"].startswith(HEAD[:20])
    # action を持たない役割 (worker) は従来どおり shell_deny
    shell_deny = _judge([_bash("git commit -m x", role="worker")], common)[0]
    assert "shell_deny" in shell_deny["reason"]


# ─── action を持たない役割・表が無いときは変わらない ─────────────────────────────


@needs_node
def test_roles_without_the_action_tool_behave_as_before():
    common = _pi_common()
    without_table = _with(common, actions=[])
    commands = [c for c, _ in CASES] + [
        "gh pr create --title t --body b",
        "git add a",
        "ls",
        "git status",
        "gh issue close 1",
    ]
    for role in ("reader", "explorer", "committer", "worker"):
        for extra in ({}, {"bypass": True}, {"boundary": True}):
            reqs = [_bash(c, role=role, **extra) for c in commands]
            assert _judge(reqs, common) == _judge(reqs, without_table), role
    # implementer でも、tools から action を外せば従来どおり (表があっても deny にならない)
    plain_tools = [t for t in common["pi"]["profiles"]["implementer"]["tools"] if t != "action"]
    plain = _with(common, implementer_tools=plain_tools)
    reqs = [_bash(c) for c in commands]
    assert _judge(reqs, plain) == _judge(reqs, _with(plain, actions=[]))
    out = _judge([_bash("git commit -m x"), _bash("gh issue comment 1 --body x")], plain)
    assert out[0]["decision"] == "ask" and out[1]["mustConfirm"] is True


@needs_node
def test_an_empty_table_denies_nothing_extra_for_the_implementer():
    common = _with(_pi_common(), actions=[])
    out = _judge([_bash("git commit -m x"), _bash("gh issue comment 1 --body x")], common)
    assert out[0]["decision"] == "ask"
    assert out[1]["decision"] == "ask" and out[1]["mustConfirm"] is True


@needs_node
def test_a_table_entry_added_by_config_is_enforced_without_code_changes():
    extra = {
        "id": "demo_run",
        "label": "デモ",
        "argv": ["demo", "{repo}", "{n}", "{body_file}"],
        "fields": {
            "repo": {"type": "repo"},
            "n": {"type": "int"},
            "body": {"type": "text", "file": True, "content": True, "max_chars": 10},
        },
        "replaces": ["demo run"],
        "preview": "none",
    }
    common = _pi_common()
    common = _with(common, actions=[*common["pi"]["actions"], extra])
    out = _judge([_bash("demo run -R o/r 4 x")], common)[0]
    assert out["decision"] == "deny" and out["source"] == "rule"
    assert out["reason"].startswith(HEAD)
    assert out["reason"].endswith(
        '{"action":"demo_run","params":{"repo":"o/r","n":4,"body":"<本文>"}}'
    )


@needs_node
def test_a_broken_table_fails_closed_for_roles_with_the_action_tool():
    common = _with(_pi_common(), actions=[{"id": "x", "replaces": "git commit", "fields": {}}])
    out = _judge([_bash("ls"), _bash("ls", role="worker")], common)
    assert out[0]["decision"] == "deny" and out[0]["source"] == "error"
    assert out[1]["decision"] != "deny" or out[1]["source"] != "error"


def test_decide_dump_is_json_serializable():
    # 理由に使う JSON の例は、そのまま JSON として読める (呼び出し例の形)
    example = COMMIT[len(HEAD) :]
    assert json.loads(example)["params"] == {"message": "<件名と本文>"}
