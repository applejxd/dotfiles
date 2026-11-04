"""bash の確認画面の手順の一覧 (``home/dot_config/pi/harness/explain.ts``) の表試験。

``test/agents/pi/explain_driver.mjs`` が explain.ts と confirm-view.ts を読んで結果を JSON で出す
(node の型除去を使うので、22.18 未満の node では飛ばす)。表示だけの機能で、判定には使わない。

see docs/spec/guard/pi-extensions.md#確認画面の手順の一覧
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

RUNNER = ROOT / "test" / "agents" / "pi" / "explain_driver.mjs"

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")


@pytest.fixture(scope="module")
def table():
    proc = subprocess.run(
        [_node(), str(RUNNER)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-1000:]
    return json.loads(proc.stdout)


def case(table, name):
    return table["cases"][name]


def texts(table, name):
    return [s["text"] for s in case(table, name)["steps"]]


def marks(table, name):
    return {m for s in case(table, name)["steps"] for m in s["marks"]}


def levels(table, name):
    return [s["level"] for s in case(table, name)["steps"]]


# ─── 基本の分割 ─────────────────────────────────────────────


def test_cd_pipe_and_redirect_become_three_steps(table):
    t = texts(table, "pipe_write")
    assert case(table, "pipe_write")["complete"] is True
    assert len(t) == 3
    assert t[0] == "作業場所を `/abs` に変更"
    assert "`git log --oneline`" in t[1] and "出力を次へ渡す" in t[1]
    assert "`head -3`" in t[2] and "標準出力を `/tmp/o` に書き込む（上書き）" in t[2]
    assert marks(table, "pipe_write") == {"ファイルを書き込む"}


def test_delete_and_push_carry_side_effect_marks(table):
    assert len(texts(table, "rm_push")) == 2
    assert marks(table, "rm_push") == {
        "ファイルを削除する",
        "ネットワークに接続する",
        "履歴・参照を書き換える",
    }


def test_semicolon_and_or_split_and_or_is_marked(table):
    assert len(texts(table, "semi")) == 2
    t = texts(table, "or")
    assert len(t) == 2 and t[1].startswith("前が失敗したときだけ")


def test_redirects_are_explained(table):
    t = texts(table, "redir")[0]
    assert "標準エラーを標準出力へ向ける" in t
    assert "`/tmp/l` に書き込む（追記）" in t
    assert "`in.txt` を標準入力にする" in t


def test_env_and_bash_c_are_expanded(table):
    assert texts(table, "env") == ["環境変数 A を設定し、`cmd` を実行"]
    t = texts(table, "bashc")
    assert len(t) == 3 and "`x`" in t[1] and "`y`" in t[2]
    assert levels(table, "bashc") == [0, 1, 1]


def test_wrappers_time_nohup_sudo(table):
    assert (
        "時間を測って" in texts(table, "time_nohup")[0]
        and "切断後も続くように" in texts(table, "time_nohup")[0]
    )
    assert "管理者権限で実行する" in marks(table, "sudo") and "パッケージを入れる" in marks(
        table, "sudo"
    )


def test_separators_inside_quotes_are_not_split(table):
    assert len(texts(table, "quoted_sep")) == 1


# ─── 難しい形は構造化される (原文に倒れない) ─────────────────────


def test_command_substitution_is_nested(table):
    t = texts(table, "subst_assign")
    assert case(table, "subst_assign")["complete"] is True
    assert len(t) == 4 and t[1] == "変数 x を設定"
    assert t[2].startswith("コマンド置換") and "`git rev-parse HEAD`" in t[2]
    assert levels(table, "subst_assign") == [0, 0, 1, 0]
    assert case(table, "subst_arg")["complete"] is True and levels(table, "subst_arg") == [0, 1]
    assert case(table, "backtick")["complete"] is True and "`whoami`" in texts(table, "backtick")[1]


def test_nesting_is_limited_and_falls_back_to_raw(table):
    c = case(table, "nested3")
    assert c["complete"] is False
    assert max(s["level"] for s in c["steps"]) == 4
    assert "入れ子が深いので省略" in c["steps"][-1]["text"]
    assert case(table, "deep_for")["complete"] is False


def test_for_while_if_are_structured(table):
    t = texts(table, "for_loop")
    assert case(table, "for_loop")["complete"] is True
    assert (
        t[0].startswith("繰り返し: f ごとに（対象: a b）")
        and t[1].startswith("本体: ")
        and "`rm $f`" in t[1]
    )
    assert marks(table, "for_loop") == {"ファイルを削除する"}
    t = texts(table, "for_subst")
    assert (
        case(table, "for_subst")["complete"] is True
        and t[1].startswith("対象を作るコマンド置換")
        and t[2].startswith("本体")
    )
    t = texts(table, "while_loop")
    assert case(table, "while_loop")["complete"] is True
    assert t[0].startswith("繰り返し（条件が真の間）") and "< list.txt" in t[0]
    assert t[1].startswith("条件: ") and t[2].startswith("本体: ")
    t = texts(table, "if_else")
    assert case(table, "if_else")["complete"] is True
    assert [x.split(":")[0] for x in t[1:]] == ["条件", "真なら", "偽なら"] and t[0] == "条件分岐"


def test_subshell_and_brace_group_are_structured(table):
    t = texts(table, "subshell")
    assert case(table, "subshell")["complete"] is True
    assert t[0].startswith("サブシェルで次を実行") and t[1] == "作業場所を `/tmp` に変更"
    t = texts(table, "brace")
    assert case(table, "brace")["complete"] is True
    assert t[0].startswith("グループとして次を実行") and "> /tmp/o" in t[0] and len(t) == 3


def test_heredoc_separates_command_and_body(table):
    t = texts(table, "heredoc_py")
    assert case(table, "heredoc_py")["complete"] is True and len(t) == 2
    assert t[0].startswith("`python3 -`") and "本文（5 行）を標準入力として渡す" in t[0]
    assert "本文（5 行）" in t[1] and "Python のスクリプトとして実行される" in t[1]
    assert "「import os」" in t[1] and "「print(3)」" in t[1] and "「print(2)」" not in t[1]
    assert marks(table, "heredoc_py") == {"ファイルを削除する"}
    t = texts(table, "heredoc_cat")
    assert "`f` に書き込む（上書き）" in t[0] and "ファイル `f` の内容になる" in t[1]
    t = texts(table, "heredoc_sh")
    assert (
        "シェルスクリプトとして実行される" in t[1]
        and len(t) == 4
        and levels(table, "heredoc_sh") == [0, 1, 2, 2]
    )
    assert marks(table, "heredoc_sh") == {"ファイルを削除する", "ネットワークに接続する"}
    assert "標準入力にする" in texts(table, "herestring")[0]


def test_find_exec_and_xargs_show_the_executed_command(table):
    t = texts(table, "find_exec")
    assert case(table, "find_exec")["complete"] is True and len(t) == 2
    assert t[1].startswith("各結果に対して: `rm {}`") and "ファイルを削除する" in marks(
        table, "find_exec"
    )
    t = texts(table, "xargs_a")
    assert "ファイル `list` の各行を引数にする" in t[0] and t[1].startswith(
        "各項目に対して: `git worktree remove`"
    )
    t = texts(table, "xargs_pipe")
    assert len(t) == 3 and "`rm`" in t[2] and "ファイルを削除する" in marks(table, "xargs_pipe")


# ─── 原文に倒れる形 ─────────────────────────────────────────


@pytest.mark.parametrize(
    "name", ["procsub", "funcdef", "case_esac", "eval_", "arith", "open_quote"]
)
def test_ambiguous_forms_fall_back_to_raw_without_raising(table, name):
    c = case(table, name)
    assert c["complete"] is False
    assert any(s["text"].startswith("解析できない部分: ") for s in c["steps"])


def test_fallback_keeps_the_raw_text(table):
    assert texts(table, "procsub") == ["解析できない部分: diff <(ls a) <(ls b)"]
    assert texts(table, "eval_") == ['解析できない部分: eval "$cmd"']
    assert texts(table, "open_quote") == ["解析できない部分: echo 'abc"]


def test_representative_fallback_ratio_is_small(table):
    r = table["ratio"]
    assert r["total"] == 30
    assert r["fallback"] <= 3, r["list"]


# ─── 安全・上限・異常な入力 ────────────────────────────────────


def test_control_characters_and_newlines_are_neutralized(table):
    s = case(table, "ctl")["steps"][0]
    assert "\x1b" not in s["text"] + s["raw"] and "\u202e" not in s["text"] + s["raw"]
    assert "\\x1b" in s["text"] and "\\u{202e}" in s["text"]
    for st in case(table, "quoted_nl")["steps"]:
        assert "\n" not in st["text"] + st["raw"] and "\r" not in st["text"] + st["raw"]


def test_step_count_and_length_are_limited(table):
    c = case(table, "many")
    assert len(c["steps"]) == 17 and c["steps"][-1]["text"] == "ほか 14 手順"
    assert all(len(s["text"]) <= 200 and len(s["raw"]) <= 200 for s in case(table, "long")["steps"])


def test_empty_and_odd_inputs_do_not_raise(table):
    assert case(table, "empty") == {"cmd": "", "steps": [], "complete": True}
    for k in ("nul", "undef", "num"):
        assert isinstance(table["misc"][k]["steps"], list)


def test_multiline_commands_split_on_newlines(table):
    assert len(texts(table, "multiline")) == 2 and len(texts(table, "simple")) == 1


def test_hit_marks_only_the_matching_step(table):
    h = table["hit"]
    assert [s["hit"] for s in h["push"]["steps"]] == [False, True]
    assert not any(s["hit"] for s in h["none"]["steps"])
    assert [s["hit"] for s in h["sub"]["steps"]] == [False, False] or any(
        s["hit"] for s in h["sub"]["steps"]
    )


# ─── 表示 (confirm-view.ts) ─────────────────────────────────


def test_simple_command_shows_no_list(table):
    assert table["view"]["lines_simple"] == ""
    body = table["view"]["must_simple"]["body"]
    assert "手順:" in body  # git push は副作用の印があるので出る
    assert "ls -la" not in body


def test_list_lines_have_numbers_marks_hit_and_disclaimer(table):
    v = table["view"]
    assert v["lines_pipe"].startswith("手順:\n  1. 作業場所を `/x` に変更")
    assert "判定には使っていません" in v["lines_pipe"]
    assert "⚠ 解析できない部分があります。原文を確認してください" in v["lines_bad"]
    assert re.search(r"2\. `git push`.*← 確認の理由に当たった箇所", v["lines_hit"])
    assert "← 確認の理由に当たった箇所" not in v["lines_hit"].split("\n")[1]


def test_must_confirm_body_places_list_below_the_raw_command(table):
    body = table["view"]["must_multi"]["body"]
    assert (
        body.index("コマンド (全文):")
        < body.index("cd /x && git push")
        < body.index("手順:")
        < body.index("理由:")
    )
    # 従来の呼び出し (opts なし・explain: false) は変わらない
    assert "手順:" not in table["view"]["must_noexplain"]["body"]
    assert "手順:" not in table["view"]["must_nonbash"]["body"]


# ─── 同梱の mvdan-sh・日本語・読み込み失敗 ─────────────────────────

VENDOR = ROOT / "home" / "dot_config" / "pi" / "harness" / "vendor" / "mvdan-sh"


def test_vendored_parser_matches_readme_hash_and_size():
    """同梱の index.js が README の値 (sha256・大きさ) と一致する (勝手に書き換わっていない)。"""
    readme = (VENDOR / "README.md").read_text(encoding="utf-8")
    sha = re.search(r"sha256 \| `([0-9a-f]{64})`", readme)
    size = re.search(r"（(\d+) バイト）", readme)
    assert sha and size
    data = (VENDOR / "index.js").read_bytes()
    assert hashlib.sha256(data).hexdigest() == sha.group(1)
    assert len(data) == int(size.group(1))
    assert "BSD" in readme and (VENDOR / "LICENSE").is_file()


def test_missing_parser_falls_back_to_one_raw_step_without_raising():
    env = {**os.environ, "PI_EXPLAIN_VENDOR": str(VENDOR / "no-such-dir" / "index.js")}
    proc = subprocess.run(
        [_node(), str(RUNNER), "--fallback"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        env=env,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-1000:]
    out = json.loads(proc.stdout)
    for cmd, r in out.items():
        if cmd == "":
            assert r == {"steps": [], "complete": True}
            continue
        assert r["complete"] is False and len(r["steps"]) == 1
        assert r["steps"][0]["text"] == f"解析できない部分: {cmd}"


def test_japanese_text_is_sliced_by_byte_offsets(table):
    """Offset は UTF-8 のバイト位置。日本語・絵文字・サロゲートペアでも切り出しが壊れない。"""
    assert texts(table, "jp_and") == [
        "`echo 日本語`（文字列を出力） を実行",
        "`ls`（一覧を表示） を実行",
    ]
    t = texts(table, "jp_grep")
    assert t[0].startswith("`grep 'こんにちは' f`") and t[1].startswith("`head`")
    t = texts(table, "jp_heredoc")
    assert len(t) == 2 and "「print('日本語')」" in t[1] and "「os.remove('あ')」" in t[1]
    assert marks(table, "jp_heredoc") == {"ファイルを削除する"}
    t = texts(table, "jp_subst")
    assert len(t) == 4 and "`echo 日本語 $(echo 漢字 | wc -c)`" in t[0]
    assert t[1].startswith("コマンド置換") and "`echo 漢字`" in t[1] and "`wc -c`" in t[2]
    assert t[3] == "`echo 終`（文字列を出力） を実行"
    t = texts(table, "jp_bashc")
    assert len(t) == 3 and "`echo 日`" in t[1] and "`ls`" in t[2]
    t = texts(table, "jp_emoji")
    assert t == ["`echo 😀`（文字列を出力） を実行", "`rm 𠮷野家`（ファイルを削除） を実行"]
    for k in ("jp_and", "jp_grep", "jp_heredoc", "jp_subst", "jp_bashc", "jp_emoji"):
        assert case(table, k)["complete"] is True
