"""judge/plan.ts の ExecSite の試験: ラッパー・入れ子・``cmd``・``cwd``・``tails``・``denyViews``・``varsVisible``・ANSI-C の頭。

- ``tails`` と ``denyViews`` は**拒否側専用**の view。許可の被覆 (``argv``) には混ぜない (argv は旧の追加セグメントを含まない)。
- ``cwd`` は caller / chain / unknown。chain に積むのは無条件に実行される単純な ``cd <lit|tilde>`` だけ。
- ANSI-C 引用の頭 (``$'sudo' ls``) は復号せず ``unk(ansi-c)``。後段 (S2) が deny にする印。

see docs/spec/guard/pi-decide.md#解析結果-plan-g1a
"""

from __future__ import annotations

import json
from functools import cache

import pytest
from plan_helper import argv_of, cwd_of, needs_node, run_cases, tok

pytestmark = needs_node

SSH = ["sbx@sandbox-gpu"]


@cache
def _plan(cmd: str, ssh: tuple = ()) -> str:
    return json.dumps(run_cases([{"cmd": cmd, "ssh": list(ssh)}])[0])


def plan(cmd: str, ssh=SSH) -> dict:
    r = json.loads(_plan(cmd, tuple(ssh)))
    assert r["ok"] is True, r
    return r


def sites(cmd: str, ssh=SSH) -> list[dict]:
    return plan(cmd, ssh)["sites"]


def via_names(site):
    return [v["name"] for v in site["via"]]


def tails_of(site):
    return [[tok(w) for w in t] for t in site["tails"]]


def views_of(site):
    return [[tok(w) for w in t] for t in site["denyViews"]]


# ─── ラッパー (表 V)


def test_plain_command_has_no_via():
    s = sites("git log")[0]
    assert argv_of(s) == ["git", "log"] and s["via"] == [] and s["cmd"] == "git"
    assert [tok(w) for w in s["rawArgv"]] == ["git", "log"]


def test_env_is_transparent_without_options_and_assigns_move_to_assigns():
    s = sites("env FOO=1 git log")[0]
    assert argv_of(s) == ["git", "log"]
    assert via_names(s) == ["env"] and s["via"][0]["transparent"] is True
    assert [a["name"] for a in s["assigns"]] == ["FOO"]
    assert [tok(w) for w in s["rawArgv"]][:2] == ["env", "FOO=1"]


def test_env_with_option_is_not_transparent():
    s = sites("env -i FOO=1 git log")[0]
    assert argv_of(s) == ["git", "log"]
    assert s["via"][0]["transparent"] is False and s["via"][0]["opts"] == ["-i"]


def test_nice_is_stripped_but_not_transparent():
    s = sites("nice -n 5 git log")[0]
    assert argv_of(s) == ["git", "log"] and via_names(s) == ["nice"]
    assert s["via"][0]["transparent"] is False


def test_timeout_with_literal_duration_is_transparent():
    s = sites("timeout 10 git log")[0]
    assert argv_of(s) == ["git", "log"] and s["via"][0]["transparent"] is True


def test_timeout_with_unknown_duration_is_not_transparent():
    s = sites("timeout $d git log")[0]
    assert argv_of(s) == ["git", "log"] and s["via"][0]["transparent"] is False


@pytest.mark.parametrize(
    ("cmd", "transparent"),
    [("nohup git log", True), ("time git log", True), ("time -p git log", False)],
)
def test_nohup_and_time_transparency(cmd, transparent):
    s = sites(cmd)[0]
    assert argv_of(s) == ["git", "log"] and s["via"][0]["transparent"] is transparent


def test_command_v_is_not_transparent():
    s = sites("command -v git")[0]
    assert s["via"][0]["name"] == "command" and s["via"][0]["transparent"] is False


def test_sudo_is_stripped_and_raw_argv_keeps_it():
    s = sites("sudo git push")[0]
    assert (
        argv_of(s) == ["git", "push"]
        and via_names(s) == ["sudo"]
        and s["via"][0]["transparent"] is False
    )
    assert [tok(w) for w in s["rawArgv"]] == ["sudo", "git", "push"]
    assert s["cmd"] == "git"


def test_nested_wrappers_are_peeled_in_order():
    s = sites("sudo env FOO=1 nice git log")[0]
    assert argv_of(s) == ["git", "log"] and via_names(s) == ["sudo", "env", "nice"]


def test_wrapper_without_command_stays_as_command():
    s = sites("sudo")[0]
    assert argv_of(s) == ["sudo"] and s["via"] == []


def test_unknown_head_is_not_peeled():
    s = sites("$w git log")[0]
    assert s["via"] == [] and s["cmd"] is None


# ─── ssh (許可宛先だけ展開)


def test_ssh_allowed_target_becomes_nested_site_and_outer_argv_is_empty():
    ss = sites("ssh sbx@sandbox-gpu git log")
    assert len(ss) == 2
    outer, inner = ss
    assert (
        outer["argv"] == []
        and outer["via"][0]["name"] == "ssh"
        and outer["via"][0]["target"] == "sbx@sandbox-gpu"
    )
    assert outer["via"][0]["transparent"] is True
    assert [tok(w) for w in outer["rawArgv"]][:2] == ["ssh", "sbx@sandbox-gpu"]
    assert (
        inner["parent"] == outer["id"]
        and inner["ctl"]["sub"] == "ssh"
        and argv_of(inner) == ["git", "log"]
    )


def test_ssh_remote_with_semicolon_splits_into_sites():
    ss = sites("ssh sbx@sandbox-gpu 'git log; ls'")
    assert [argv_of(s) for s in ss[1:]] == [["git", "log"], ["ls"]]


def test_ssh_other_target_stays_a_plain_site():
    ss = sites("ssh other git log")
    assert len(ss) == 1 and argv_of(ss[0]) == ["ssh", "other", "git", "log"]


def test_ssh_with_option_before_target_stays_plain():
    ss = sites("ssh -o StrictHostKeyChecking=no sbx@sandbox-gpu git log")
    assert len(ss) == 1 and ss[0]["cmd"] == "ssh"


def test_ssh_with_non_literal_remote_stays_plain():
    ss = sites('ssh sbx@sandbox-gpu "git $x"')
    assert len(ss) == 1 and ss[0]["cmd"] == "ssh"


def test_ssh_without_allowed_targets_is_never_expanded():
    assert len(sites("ssh sbx@sandbox-gpu git log", ssh=())) == 1


def test_ssh_remote_syntax_error_is_not_expanded_and_not_fatal():
    ss = sites("ssh sbx@sandbox-gpu 'echo \"x'")
    assert len(ss) == 1 and ss[0]["cmd"] == "ssh"


# ─── xargs・parallel・find -exec (外側を残し、後ろを入れ子の site にする)


def test_xargs_keeps_outer_and_adds_nested_site():
    ss = sites("xargs git log --")
    assert argv_of(ss[0])[:2] == ["xargs", "git"]
    inner = ss[1]
    assert (
        inner["parent"] == 0
        and inner["ctl"]["sub"] == "xargs"
        and inner["via"][0]["appendsArgs"] is True
    )
    assert argv_of(inner) == ["git", "log", "--"]


def test_xargs_with_options_skips_option_values():
    ss = sites("xargs -n 1 -I {} git push")
    assert argv_of(ss[1])[:2] == ["git", "push"]


def test_parallel_cuts_at_triple_colon():
    ss = sites("parallel git log ::: a b")
    assert argv_of(ss[1]) == ["git", "log"] and ss[1]["via"][0]["name"] == "parallel"


def test_find_exec_terminated_by_semicolon():
    ss = sites("find . -exec git push \\;")
    assert ss[1]["ctl"]["sub"] == "find-exec" and argv_of(ss[1]) == ["git", "push"]
    assert ss[1]["via"][0]["appendsArgs"] is True


def test_find_exec_without_terminator_still_nested():
    ss = sites("find . -exec git push")
    assert argv_of(ss[1]) == ["git", "push"]


def test_find_exec_plus_keeps_brace_as_pattern():
    ss = sites("find . -exec rm {} +")
    assert [w["k"] for w in ss[1]["argv"]] == ["lit", "pat"]


def test_find_multiple_exec_make_multiple_sites():
    ss = sites("find . -exec a \\; -execdir b \\;")
    assert [argv_of(s) for s in ss[1:]] == [["a"], ["b"]]


# ─── bash -c・heredoc・here-string・置換


def test_bash_c_literal_body_becomes_nested_sites():
    ss = sites("bash -c 'git push; ls'")
    assert [argv_of(s) for s in ss] == [["bash", "-c", "git push; ls"], ["git", "push"], ["ls"]]
    assert (
        [s["ctl"]["sub"] for s in ss] == [None, "-c", "-c"]
        and ss[1]["parent"] == 0
        and ss[1]["depth"] == 1
    )


@pytest.mark.parametrize("cmd", ["bash -lc 'git push'", "sh -c 'git push'", "zsh -c 'git push'"])
def test_shell_flag_forms_with_c(cmd):
    assert argv_of(sites(cmd)[1]) == ["git", "push"]


def test_bash_c_non_literal_body_is_opaque_and_adds_no_site():
    p = plan('bash -c "$x"')
    assert len(p["sites"]) == 1 and [o["kind"] for o in p["opaque"]] == ["nonlit-c"]


def test_heredoc_to_shell_is_nested_site():
    ss = sites("bash <<EOF\ngit push\nEOF")
    assert ss[0]["redirs"][0]["hdoc"] == {"body": "git push", "quoted": False}
    assert ss[1]["ctl"]["sub"] == "hdoc" and argv_of(ss[1]) == ["git", "push"]


def test_heredoc_to_cat_is_data_not_a_site():
    ss = sites("cat <<'EOF'\ngit push\nEOF")
    assert len(ss) == 1 and ss[0]["redirs"][0]["hdoc"] == {"body": "git push", "quoted": True}


def test_heredoc_to_interpreter_is_opaque():
    p = plan("python3 <<EOF\nimport os\nEOF")
    assert [o["kind"] for o in p["opaque"]] == ["hdoc-to-interp"] and len(p["sites"]) == 1


def test_here_string_body_is_nested_and_tail():
    ss = sites("cat <<< 'git push'")
    assert ss[1]["ctl"]["sub"] == "herestr" and argv_of(ss[1]) == ["git", "push"]
    assert tails_of(ss[0]) == [["git", "push"]]
    assert argv_of(ss[0]) == ["cat"]


def test_here_string_with_syntax_error_is_tolerated():
    ss = sites("cat <<< 'echo \"x'")
    assert len(ss) == 1 and ss[0]["redirs"][0]["op"] == "<<<"


def test_command_and_process_substitution_are_nested_with_parent():
    ss = sites("echo $(git push) `ls` <(cat x)")
    assert [s["ctl"]["sub"] for s in ss] == [None, "cmdsubst", "cmdsubst", "procsubst"]
    assert all(s["parent"] == 0 for s in ss[1:]) and ss[1]["depth"] == 1


def test_substitution_in_assignment_and_redirect_target():
    ss = sites("x=$(a) > $(b)")
    assert [s["ctl"]["sub"] for s in ss] == [None, "cmdsubst", "cmdsubst"]


def test_eval_source_python_alias_are_opaque_and_not_sites():
    assert [o["kind"] for o in plan("eval git push")["opaque"]] == ["eval"]
    assert [o["kind"] for o in plan("source ./x.sh")["opaque"]] == ["source"]
    assert [o["kind"] for o in plan("python -c 'import os'")["opaque"]] == ["interp-body"]
    assert [o["kind"] for o in plan("alias g='git push'")["opaque"]] == ["alias"]
    assert plan("eval git push")["opaque"][0]["text"] == "git push"


def test_function_definition_is_complex_and_opaque():
    p = plan("f() { git push; }; f")
    assert p["complex"] is True and "func" in [o["kind"] for o in p["opaque"]]
    assert ["git", "push"] in [argv_of(s) for s in p["sites"]]


# ─── complex (許可しない形) と ctl・redirs・assigns・cmd


@pytest.mark.parametrize(
    "cmd",
    [
        "echo hi # c",
        "f() { a; }",
        "if a; then b; fi",
        "for i in 1; do a; done",
        "while a; do b; done",
        "case x in y) a;; esac",
        "declare x=1",
        "export X=1",
        "let x=1",
        "(( x = 1 ))",
        "[[ -f x ]]",
        "coproc a",
    ],
)
def test_complex_forms(cmd):
    assert plan(cmd)["complex"] is True


@pytest.mark.parametrize(
    "cmd",
    ["git log", "a && b || c", "a | b", "(a)", "{ a; }", "x=1 a", "a > f", "time a", "a $(b)"],
)
def test_plain_forms_are_not_complex(cmd):
    assert plan(cmd)["complex"] is False


def test_compound_bodies_still_produce_sites():
    ss = sites("if true; then git push; fi")
    assert ["git", "push"] in [argv_of(s) for s in ss]
    assert all(s["cwd"]["k"] == "unknown" for s in ss)


def test_ctl_pipe_bg_neg():
    a, b = sites("a | b")
    assert a["ctl"]["pipe"] is True and b["ctl"]["pipe"] is True
    assert sites("a &")[0]["ctl"]["bg"] is True
    assert sites("! a")[0]["ctl"]["neg"] is True
    assert sites("a && b")[0]["ctl"] == {"pipe": False, "bg": False, "neg": False, "sub": None}


def test_redirects_and_assigns_are_separate_from_argv():
    s = sites("A=1 B= git log 2>&1 >> out")[0]
    assert argv_of(s) == ["git", "log"]
    assert [(a["name"], tok(a["value"])) for a in s["assigns"]] == [("A", "1"), ("B", "")]
    assert [(r["fd"], r["op"], tok(r["target"])) for r in s["redirs"]] == [
        ("2", ">&", "1"),
        ("", ">>", "out"),
    ]


def test_assignment_only_and_redirect_only_have_empty_argv():
    assert sites("x=1")[0]["argv"] == [] and sites("> out")[0]["argv"] == []
    assert sites("x=1")[0]["cmd"] is None


def test_redirect_on_compound_command_is_kept_on_its_own_site():
    ss = sites("(a) > out")
    assert any(s["argv"] == [] and s["redirs"] for s in ss)


@pytest.mark.parametrize(
    ("cmd", "cmd_name"),
    [
        ("/usr/bin/git log", "git"),
        ("~/bin/git log", "git"),
        ("$d/git log", "git"),
        ("$x log", None),
        ("git log", "git"),
        ("./a.sh", "a.sh"),
    ],
)
def test_cmd_is_basename_of_head(cmd, cmd_name):
    assert sites(cmd)[0]["cmd"] == cmd_name


def test_site_span_is_utf8_byte_range_of_each_statement():
    ss = sites("echo あ; ls")
    assert ss[1]["span"] == [10, 12]


# ─── ANSI-C 引用の頭 (S2 で deny にする印)


@pytest.mark.parametrize("cmd", ["$'sudo' ls", "$'git' push", "$'printf' x", "$'g\\x69t' push"])
def test_ansi_c_head_is_unknown_with_why(cmd):
    s = sites(cmd)[0]
    assert s["argv"][0]["k"] == "unk" and s["argv"][0]["why"] == "ansi-c"
    assert s["cmd"] is None


def test_variable_head_is_unknown_param_with_refs():
    s = sites("s=sudo; $s ls")[1]
    assert (
        s["argv"][0]["k"] == "unk"
        and s["argv"][0]["why"] == "param"
        and s["argv"][0]["refs"] == ["s"]
    )


# ─── cwd

CWD_CASES = [
    ("git log", [("git", "caller")]),
    (
        "cd ..; cd sibling; echo x > out",
        [("cd", "caller"), ("cd", "chain:.."), ("echo", "chain:..,sibling")],
    ),
    ("cd sub && echo x", [("cd", "caller"), ("echo", "chain:sub")]),
    ("cd ~; echo", [("cd", "caller"), ("echo", "chain:~")]),
    ("cd a/b; echo", [("cd", "caller"), ("echo", "chain:a/b")]),
    ("false && cd ..; echo x", [("false", "caller"), ("cd", "caller"), ("echo", "unknown")]),
    ("cd a || echo x", [("cd", "caller"), ("echo", "unknown")]),
    (
        "cd a && foo || bar; baz",
        [("cd", "caller"), ("foo", "unknown"), ("bar", "unknown"), ("baz", "unknown")],
    ),
    ("cd a && cd b && echo", [("cd", "caller"), ("cd", "chain:a"), ("echo", "unknown")]),
    ("cd a & echo", [("cd", "caller"), ("echo", "unknown")]),
    ("cd .. | tee out", [("cd", "caller"), ("tee", "unknown")]),
    ("(cd ..; echo x)", [("cd", "caller"), ("echo", "unknown")]),
    ("cd ..; (echo x)", [("cd", "caller"), ("echo", "chain:..")]),
    ("cd a; (cd b; echo)", [("cd", "caller"), ("cd", "chain:a"), ("echo", "unknown")]),
    ("{ cd ..; }; echo", [("cd", "caller"), ("echo", "unknown")]),
    ("if t; then cd ..; fi; echo", [("t", "unknown"), ("cd", "unknown"), ("echo", "unknown")]),
    ("pushd ..; echo", [("pushd", "caller"), ("echo", "unknown")]),
    ("popd; echo", [("popd", "caller"), ("echo", "unknown")]),
    ("chdir a; echo", [("chdir", "caller"), ("echo", "unknown")]),
    ("cd -; echo", [("cd", "caller"), ("echo", "unknown")]),
    ("cd; echo", [("cd", "caller"), ("echo", "unknown")]),
    ("cd a b; echo", [("cd", "caller"), ("echo", "unknown")]),
    ("cd $x; echo", [("cd", "caller"), ("echo", "unknown")]),
    ("cd *; echo", [("cd", "caller"), ("echo", "unknown")]),
    ("cd -P a; echo", [("cd", "caller"), ("echo", "unknown")]),
    ("cd ~root; echo", [("cd", "caller"), ("echo", "unknown")]),
    ("builtin cd ..; echo", [("cd", "caller"), ("echo", "unknown")]),
    ("command cd ..; echo", [("cd", "caller"), ("echo", "unknown")]),
    ("FOO=1 cd a; echo", [("cd", "caller"), ("echo", "unknown")]),
    ("CDPATH=/x cd a; echo", [("cd", "caller"), ("echo", "unknown")]),
    ("export CDPATH=/x; cd a; echo", [("export", "caller"), ("cd", "caller"), ("echo", "unknown")]),
    ("cd a > f; echo", [("cd", "caller"), ("echo", "unknown")]),
    ("f() { cd ..; }; cd x; echo", [("cd", "unknown"), ("cd", "unknown"), ("echo", "unknown")]),
    ("f() { :; }; cd x; echo", [(":", "unknown"), ("cd", "caller"), ("echo", "unknown")]),
    ("alias cd=ls; cd x; echo", [("alias", "caller"), ("cd", "caller"), ("echo", "unknown")]),
    ("cd a; bash -c 'echo x'", [("cd", "caller"), ("bash", "chain:a"), ("echo", "chain:a")]),
    (
        "cd a; bash -c 'cd b; echo'",
        [("cd", "caller"), ("bash", "chain:a"), ("cd", "chain:a"), ("echo", "chain:a,b")],
    ),
    ("cd a; echo $(pwd)", [("cd", "caller"), ("echo", "chain:a"), ("pwd", "chain:a")]),
    ("echo $(cd ..; pwd)", [("echo", "caller"), ("cd", "caller"), ("pwd", "unknown")]),
    ("cd a\ncd b\necho", [("cd", "caller"), ("cd", "chain:a"), ("echo", "chain:a,b")]),
]


@pytest.mark.parametrize("cmd", [c for c, _ in CWD_CASES], ids=[c for c, _ in CWD_CASES])
def test_cwd(cmd):
    expected = dict(CWD_CASES)[cmd]
    got = [(s["cmd"], cwd_of(s)) for s in sites(cmd)]
    assert got == expected


def test_failed_cd_chain_is_resolved_later_not_here():
    """``cd nosuch`` が実在しないかどうかは paths.ts (G5) が chain を解くときに決める。Plan は chain のまま持つ。"""
    assert cwd_of(sites("cd nosuch; echo x > out")[1]) == "chain:nosuch"


def test_cwd_chain_steps_are_words():
    c = sites("cd ..; cd ~/x; echo")[2]["cwd"]
    assert (
        c["k"] == "chain"
        and [w["k"] for w in c["steps"]] == ["lit", "tilde"]
        and c["steps"][1]["v"] == "x"
    )


# ─── tails (拒否側専用。旧の埋め込み抽出と同じ範囲)


@pytest.mark.parametrize(
    ("cmd", "expected"),
    [
        ("cargo run -- git push", [["git", "push"]]),
        ("uv run git push", [["git", "push"]]),
        ("npm exec git push", [["git", "push"]]),
        ("pnpm dlx git push", [["git", "push"]]),
        ("docker run img git push", [["git", "push"]]),
        ("docker exec -it c git push", [["git", "push"]]),
        ("git submodule foreach git push", [["git", "push"]]),
        ("tmux send-keys 'git push' Enter", [["git push", "Enter"]]),
        ("screen -dm git push", [["git", "push"]]),
        ("eval git push", [["git", "push"]]),
        ("source ./x.sh", [["./x.sh"]]),
        ("trap 'git push' EXIT", [["git push"]]),
        ("cat <<< 'git push'", [["git", "push"]]),
        ("echo $(echo git) push", [["git"]]),
    ],
)
def test_tails(cmd, expected):
    assert tails_of(sites(cmd)[0]) == expected


def test_process_substitution_echo_payload_is_a_tail():
    assert ["git", "push"] in tails_of(sites("source <(echo git push)")[0])


def test_tails_are_empty_for_plain_commands_and_git_double_dash():
    assert sites("git log")[0]["tails"] == []
    assert sites("git log -- file")[0]["tails"] == []
    assert sites("ls -l")[0]["tails"] == []


def test_tails_do_not_change_argv():
    s = sites("cargo run -- git push")[0]
    assert argv_of(s) == ["cargo", "run", "--", "git", "push"]


def test_double_dash_tail_for_non_git_head():
    assert tails_of(sites("make -- git push")[0]) == [["git", "push"]]


def test_tails_are_deduplicated():
    assert len(sites("cargo run -- git push")[0]["tails"]) == 1


def test_tail_through_wrapper_uses_stripped_and_raw_views():
    s = sites("sudo cargo run -- git push")[0]
    assert ["git", "push"] in tails_of(s)


# ─── denyViews (git などのグローバル引数を除いた view)


def test_deny_view_without_globals_is_single():
    assert views_of(sites("git push")[0]) == [["git", "push"]]
    assert views_of(sites("ls -l")[0]) == [["ls", "-l"]]


@pytest.mark.parametrize(
    ("cmd", "view"),
    [
        ("git -C $d push", ["git", "push"]),
        ("git -C /x push origin", ["git", "push", "origin"]),
        ("git --no-pager log", ["git", "log"]),
        ("git --no-pager -C /x push", ["git", "push"]),
        ("git -c a=b push", ["git", "push"]),
        ("git --git-dir=/x push", ["git", "push"]),
        ("git --git-dir /x push", ["git", "push"]),
        ("git -C $a -C $b push", ["git", "push"]),
        ("gh -R x/y pr create", ["gh", "pr", "create"]),
        ("sudo git -C x push", ["git", "push"]),
    ],
)
def test_deny_view_strips_global_options(cmd, view):
    vs = views_of(sites(cmd)[0])
    assert vs[0] == argv_of(sites(cmd)[0]) and vs[-1] == view and len(vs) == 2


def test_deny_view_is_absent_when_only_options_follow():
    assert len(views_of(sites("git -C x")[0])) == 1
    assert len(views_of(sites("git")[0])) == 1


def test_deny_view_is_empty_for_empty_argv_site():
    assert sites("x=1")[0]["denyViews"] == []


def test_deny_view_keeps_unknown_value_as_unknown_word_in_original():
    vs = sites("git -C $d push")[0]["denyViews"]
    assert vs[0][2]["k"] == "unk" and vs[1][1]["k"] == "lit"


# ─── varsVisible (旧の字句上の条件と同じ範囲)


@pytest.mark.parametrize(
    ("cmd", "names"),
    [
        ("p=push; git $p", ["p"]),
        ("FOO=1 git log", ["FOO"]),
        ("a=1;b=2", ["a", "b"]),
        ("echo a=b", ["a"]),
        ('echo "x=1"', ["x"]),
        ("export A=1", ["A"]),
        ("x= git log", []),
        ("git log", []),
        ("echo $(p=1; ls)", ["p"]),
        ("env A=1 B=2 ls", ["A", "B"]),
    ],
)
def test_vars_visible(cmd, names):
    assert plan(cmd)["varsVisible"] == names


# ─── legacy


def test_legacy_cmd_without_tables_is_the_source_and_remote_false():
    p = plan("git log")
    assert (
        p["legacy"]["cmd"] == "git log"
        and p["legacy"]["remote"] is False
        and p["legacy"]["cdVariant"] is not None
    )


def test_plan_is_deterministic():
    cmd = "cd a; git -C $d push && ssh sbx@sandbox-gpu ls"
    assert plan(cmd) == json.loads(json.dumps(plan(cmd)))
