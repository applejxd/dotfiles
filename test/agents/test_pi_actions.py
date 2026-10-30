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
COMMIT_EXAMPLE = '{"action":"git_commit","params":{"message":"<件名と本文>"}}'
COMMIT = (
    HEAD
    + COMMIT_EXAMPLE
    + "。任意の引数: dir は、cwd 配下にある別の git リポジトリ (最上位) の相対パス。省略すると cwd のリポジトリ"
)


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


def test_rules_json_carries_the_actions():
    actions = _actions_of(load_common())
    assert [a["id"] for a in actions] == [
        "gh_issue_comment",
        "gh_issue_edit_body",
        "gh_issue_edit_title",
        "git_commit",
        "gitflow_feature_start",
        "gitflow_feature_commit",
        "gitflow_feature_finish",
        "gitflow_feature_discard",
    ]
    comment, edit_body, edit_title, commit, gf_start, gf_commit, gf_finish, gf_discard = actions
    assert edit_body["argv"] == [
        "gh",
        "issue",
        "edit",
        "{number}",
        "-R",
        "{repo}",
        "--body-file",
        "{body_file}",
    ]
    assert edit_body["replaces"] == ["gh issue edit"] and edit_body["preview"] == "none"
    assert edit_title["argv"] == [
        "gh",
        "issue",
        "edit",
        "{number}",
        "-R",
        "{repo}",
        "--title",
        "{title}",
    ]
    assert edit_title["fields"]["title"] == {"type": "line", "content": True, "max_chars": 256}
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
        "message": {"type": "text", "file": True, "content": True, "max_chars": 1200},
        "dir": {"type": "dir", "optional": True},
    }
    # git flow: 固定の引数。ネットワークと push に触れない。確認の省略は start だけ
    assert gf_start["argv"] == [
        "git",
        "flow",
        "feature",
        "start",
        "{name}",
        "--worktree",
        "--no-fetch",
    ]
    assert gf_start["confirm"] == "gitflow_start" and gf_start["preview"] == "gitflow_start"
    assert gf_start["fields"] == {"name": {"type": "featurename"}}
    assert gf_finish["confirm"] == "ask" and gf_finish["preview"] == "gitflow_finish"
    assert gf_commit["confirm"] == "gitflow_wip" and gf_commit["preview"] == "gitflow_commit"
    assert gf_commit["argv"] == ["git", "commit", "--message={message}"]
    assert set(gf_commit["fields"]) == {"name", "message"}
    for flag in ("--squash", "--keepremote", "--no-fetch", "--no-push", "--no-pushtag", "--notag"):
        assert flag in gf_finish["argv"]
    for argv in (gf_start["argv"], gf_finish["argv"]):
        assert not any(a in argv for a in ("--push", "--fetch", "--force", "--no-keepremote"))
    assert all(a["confirm"] == "ask" for a in (comment, edit_body, edit_title, commit))
    # 破棄: 確認あり、リモートに触れない、未コミットの worktree を強制しない
    assert gf_discard["confirm"] == "ask" and gf_discard["preview"] == "gitflow_discard"
    assert gf_discard["argv"] == [
        "git",
        "flow",
        "feature",
        "delete",
        "{name}",
        "--force",
        "--no-fetch",
        "--no-remote",
    ]
    assert not any(a in gf_discard["argv"] for a in ("--remote", "--fetch", "--force-worktree"))


def test_only_the_parent_roles_get_the_action_tool():
    # 子の役割は持たない。orchestrator は親の絞り込み（コミット・承認は親が行う）
    profiles = load_common()["pi"]["profiles"]
    assert "action" in profiles["implementer"]["tools"]
    assert [n for n, p in profiles.items() if "action" in p["tools"]] == [
        "implementer",
        "orchestrator",
    ]


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


def _gf_entry(**over) -> dict:
    base = {
        "id": "gf_demo",
        "label": "demo",
        "argv": ["git", "flow", "feature", "start", "{name}"],
        "fields": {"name": {"type": "featurename"}},
        "replaces": ["git flow feature start"],
        "preview": "gitflow_start",
        "confirm": "gitflow_start",
    }
    return {**base, **over}


def test_skipping_the_confirmation_is_limited_to_a_name_only_gitflow_start():
    assert _actions_of(_common_with(_gf_entry()))[0]["confirm"] == "gitflow_start"
    for bad in (
        _gf_entry(confirm="never"),  # 未知の値
        _gf_entry(confirm="gitflow_start", preview="gitflow_finish"),  # preview が合わない
        _gf_entry(preview="none"),
        _gf_entry(
            argv=["git", "flow", "feature", "start", "{name}", "{note}"],
            fields={"name": {"type": "featurename"}, "note": {"type": "line", "max_chars": 20}},
        ),  # 名前以外の引数がある
    ):
        with pytest.raises(SystemExit):
            _actions_of(_common_with(bad))
    # confirm を省略した項目は ask
    assert _actions_of(_common_with(_entry()))[0]["confirm"] == "ask"


def test_a_text_field_that_is_not_a_file_is_passed_as_one_argv_element():
    entry = _entry(
        argv=["demo", "{repo}", "{number}", "--m={body}"],
        fields={
            "repo": {"type": "repo"},
            "number": {"type": "int"},
            "body": {"type": "text", "content": True, "max_chars": 100},
        },
    )
    action = _actions_of(_common_with(entry))[0]
    assert action["argv"][-1] == "--m={body}" and "file" not in action["fields"]["body"]


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
    example = COMMIT_EXAMPLE
    assert json.loads(example)["params"] == {"message": "<件名と本文>"}


# ─── line (1 行の短い文字列) ─────────────────────────────────────────


def _line_entry(**field):
    spec = {"type": "line", "content": True, "max_chars": 100}
    spec.update(field)
    return {
        "id": "demo_title",
        "label": "デモ",
        "argv": ["demo", "run", "--title", "{title}"],
        "fields": {"title": spec},
        "replaces": ["demo run"],
        "preview": "none",
    }


def test_a_line_field_is_accepted_and_passed_through():
    actions = _actions_of(_common_with(_line_entry()))
    assert actions[0]["fields"]["title"] == {"type": "line", "content": True, "max_chars": 100}


@pytest.mark.parametrize(
    "field",
    [
        {"max_chars": 0},
        {"max_chars": 1001},
        {"max_chars": True},
        {"max_chars": None},
        {"content": "yes"},
        {"file": True},  # line は本文ファイルにしない
    ],
)
def test_a_broken_line_field_stops_generation(field):
    entry = _line_entry()
    if field.get("max_chars", ...) is None:
        del entry["fields"]["title"]["max_chars"]
    else:
        entry["fields"]["title"].update(field)
    with pytest.raises(SystemExit):
        _actions_of(_common_with(entry))


# ─── dir (実行するリポジトリを選ぶ。argv に現れない任意の引数) ───────────────────────────


def _dir_entry(**field):
    spec = {"type": "dir", "optional": True}
    spec.update(field)
    return {
        "id": "demo_commit",
        "label": "デモ",
        "argv": ["git", "commit", "-F", "{message_file}"],
        "fields": {
            "message": {"type": "text", "file": True, "content": True, "max_chars": 100},
            "dir": spec,
        },
        "replaces": ["demo commit"],
        "preview": "git_staged",
    }


def test_a_dir_field_is_accepted_without_appearing_in_argv():
    actions = _actions_of(_common_with(_dir_entry()))
    assert actions[0]["fields"]["dir"] == {"type": "dir", "optional": True}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda e: e["fields"]["dir"].update({"optional": "yes"}),
        lambda e: e["fields"]["dir"].update({"file": True}),
        lambda e: e.update({"preview": "none"}),  # dir を持てるのは git_staged だけ
        lambda e: e["fields"].update({"where": e["fields"].pop("dir")}),  # 名前は dir に固定
    ],
)
def test_a_broken_dir_field_stops_generation(mutate):
    entry = _dir_entry()
    mutate(entry)
    with pytest.raises(SystemExit):
        _actions_of(_common_with(entry))
