"""作業台帳の pi への登録 (``home/dot_config/pi/harness/work/register.ts``) の試験。

``test/agents/pi/work_register_driver.mjs`` に偽の pi・偽の ctx を渡し、実の runtime を tmp ディレクトリで動かして見る
(node の型除去を使うので、22.18 未満の node では飛ばす)。

see docs/spec/work/register.md
"""

from __future__ import annotations

import json
import subprocess

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

DRIVER = ROOT / "test" / "agents" / "pi" / "work_register_driver.mjs"
REGISTER = ROOT / "home" / "dot_config" / "pi" / "harness" / "work" / "register.ts"
INDEX = ROOT / "home" / "dot_config" / "pi" / "harness" / "index.ts"

needs_node = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")

ON = {"PI_WORK_TOOL": "1"}


def run(tmp_path, steps, **kw):
    scenario = {"dir": str(tmp_path), "steps": steps, **kw}
    proc = subprocess.run(
        [_node(), str(DRIVER)],
        input=json.dumps(scenario),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=90,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-1500:]
    return json.loads(proc.stdout)


def start(pi="a", sid=None, **kw):
    s = {"pi": pi, "ev": "session_start", **kw}
    if sid:
        s["sid"] = sid
    return s


def shutdown(pi="a", **kw):
    return {"pi": pi, "ev": "session_shutdown", **kw}


def tool(args, pi="a", **kw):
    return {"pi": pi, "tool": args, **kw}


def text(res):
    return res["content"][0]["text"]


# ── 旗・子・無効 ──


@needs_node
@pytest.mark.parametrize(
    "env, child",
    [
        ({}, False),
        ({"PI_WORK_TOOL": "0"}, False),
        ({"PI_WORK_TOOL": "true"}, False),
        ({"PI_WORK_TOOL": "1", "PI_WORK": "0"}, False),
        ({"PI_WORK_TOOL": "1", "PI_HARNESS_CHILD": "1"}, False),
        ({"PI_WORK_TOOL": "1"}, True),
    ],
)
def test_旗なし_無効_子では何も登録しない(tmp_path, env, child):
    r = run(tmp_path, [start(), tool({"op": "list"})], env=env, child=child)
    reg = r["registered"]["a"]
    assert reg["tools"] == [] and reg["commands"] == [] and reg["handlers"] == []
    assert r["files"] == [] and r["journal"] == []


@needs_node
def test_旗ありでツール_コマンド_ハンドラを登録する(tmp_path):
    r = run(tmp_path, [])
    reg = r["registered"]["a"]
    assert reg["tools"] == ["work"]
    assert reg["commands"] == ["work"]
    assert set(reg["handlers"]) == {"session_start", "session_shutdown"}


@needs_node
def test_ツールの引数の型は_oneof_で_op_ごと(tmp_path):
    r = run(tmp_path, [])
    p = r["registered"]["a"]["parameters"]
    assert p["type"] == "object" and len(p["oneOf"]) == 6


# ── べき等 ──


@needs_node
def test_session_start_が複数回来ても_runtime_は_1_つ(tmp_path):
    r = run(
        tmp_path,
        [
            start(),
            start(reason="resume"),
            start(reason="fork"),
            tool({"op": "add", "title": "一つ"}),
            tool({"op": "list"}),
        ],
    )
    starts = [j for j in r["journal"] if j["type"] == "session.start"]
    assert len(starts) == 1
    assert "n2" in text(r["results"][-1]) and "n3" not in text(r["results"][-1])


@needs_node
def test_複数回の_start_でも_lease_は壊れず_書ける(tmp_path):
    r = run(tmp_path, [start(), start(), tool({"op": "add", "title": "x"})])
    assert "追加 n2" in text(r["results"][-1])


@needs_node
def test_start_前のツール呼び出しは拒否される(tmp_path):
    r = run(tmp_path, [tool({"op": "list"})])
    assert "開いていない" in text(r["results"][0])


@needs_node
def test_別の会話_id_へ変わると開き直す(tmp_path):
    r = run(
        tmp_path,
        [start(sid="s1"), tool({"op": "add", "title": "x"}), start(sid="s2"), tool({"op": "list"})],
    )
    assert len([j for j in r["journal"] if j["type"] == "session.start"]) == 2
    assert "n2" in text(r["results"][-1])


# ── 永続 ──


@needs_node
def test_add_list_set_done_が永続し_再_open_で一致する(tmp_path):
    r = run(
        tmp_path,
        [
            start(),
            tool({"op": "add", "title": "調べる"}),
            tool({"op": "add", "title": "直す"}),
            tool({"op": "set", "id": "n2", "status": "done"}),
            tool({"op": "list"}),
            shutdown(),
            start(sid="again"),
            tool({"op": "list"}),
        ],
    )
    before, after = text(r["results"][4]), text(r["results"][-1])
    assert before == after
    assert "n2" in after
    assert "調べる" in after and "直す" in after


@needs_node
def test_再_open_後も採番が続く(tmp_path):
    r = run(
        tmp_path,
        [
            start(),
            tool({"op": "add", "title": "a"}),
            shutdown(),
            start(sid="z"),
            tool({"op": "add", "title": "b"}),
        ],
    )
    assert "追加 n3" in text(r["results"][-1])


@needs_node
def test_note_と_cancel_が通る(tmp_path):
    r = run(
        tmp_path,
        [
            start(),
            tool({"op": "add", "title": "a"}),
            tool({"op": "note", "id": "n2", "text": "メモ"}),
            tool({"op": "cancel", "id": "n2", "reason": "不要"}),
        ],
    )
    assert "注釈を追記" in text(r["results"][2])
    assert "取消 n2" in text(r["results"][3])


@needs_node
def test_plan_は提案だけで承認しない(tmp_path):
    r = run(
        tmp_path,
        [
            start(),
            tool(
                {
                    "op": "plan",
                    "goal": "目標",
                    "tasks": [{"title": "t1"}, {"title": "t2", "deps": [0]}],
                }
            ),
        ],
    )
    t = text(r["results"][-1])
    assert "計画を提案" in t and "利用者だけ" in t


@needs_node
def test_返り値は_content_と_details(tmp_path):
    r = run(tmp_path, [start(), tool({"op": "add", "title": "a"})])
    res = r["results"][-1]
    assert res["content"][0]["type"] == "text"
    assert res["details"]["op"] == "add" and res["details"]["id"] == "n2"


@needs_node
def test_list_は何も追記しない(tmp_path):
    r = run(
        tmp_path,
        [start(), tool({"op": "add", "title": "a"}), tool({"op": "list"}), tool({"op": "list"})],
    )
    tools = [j for j in r["journal"] if j["type"] == "tool.call"]
    assert [t["data"]["op"] for t in tools] == ["add", "list", "list"]


# ── 失敗・拒否 ──


@needs_node
def test_存在しない_id_の_set_は拒否され状態は変わらない(tmp_path):
    r = run(
        tmp_path,
        [
            start(),
            tool({"op": "add", "title": "a"}),
            tool({"op": "set", "id": "n9", "status": "done"}),
            tool({"op": "list"}),
        ],
    )
    assert text(r["results"][2]).startswith("拒否")
    assert "n2" in text(r["results"][3])


@needs_node
def test_取消の二重実行は拒否され状態は変わらない(tmp_path):
    r = run(
        tmp_path,
        [
            start(),
            tool({"op": "add", "title": "a"}),
            tool({"op": "cancel", "id": "n2", "reason": "x"}),
            tool({"op": "list"}),
            tool({"op": "cancel", "id": "n2", "reason": "y"}),
            tool({"op": "list"}),
        ],
    )
    assert text(r["results"][4]).startswith("拒否")
    assert text(r["results"][3]) == text(r["results"][5])


@needs_node
@pytest.mark.parametrize(
    "args",
    [
        {"op": "spawn", "title": "x"},
        {"op": "approve", "id": "g1"},
        {"op": "resume", "id": "g1"},
        {"op": "budget", "id": "g1", "usd": 5},
        {"op": "add"},
        {"op": "add", "title": "x", "extra": 1},
        {"op": "set", "id": "n1", "status": "failed"},
        {"op": "set", "id": "../x", "status": "done"},
        {"op": "note", "id": "n1"},
        {},
        "add",
        None,
    ],
)
def test_禁止の_op_や不正な引数は拒否される(tmp_path, args):
    r = run(tmp_path, [start(), tool(args), tool({"op": "list"})])
    assert text(r["results"][1]).startswith("拒否")
    assert r["results"][1]["details"].get("error")
    # 台帳は空のまま
    assert "ready 0 · running 0" in text(r["results"][2]) or "0" in text(r["results"][2])
    assert "n2" not in text(r["results"][2])


@needs_node
def test_タイトルの制御文字を含む引数も台帳に入れない(tmp_path):
    r = run(tmp_path, [start(), tool({"op": "add", "title": "a\u0000b"}), tool({"op": "list"})])
    # 拒否されるか、制御文字を除いて入る。どちらでも本文に NUL は残らない
    assert "\u0000" not in text(r["results"][1]) and "\u0000" not in text(r["results"][2])


# ── 読み取り専用 ──


@needs_node
def test_別の会話が駆動中なら書き込まず理由を返す(tmp_path):
    r = run(
        tmp_path,
        [
            start("a", sid="sa"),
            start("b", sid="sb"),
            tool({"op": "add", "title": "a の仕事"}, pi="a"),
            tool({"op": "add", "title": "b の仕事"}, pi="b"),
            tool({"op": "list"}, pi="b"),
        ],
        pis=["a", "b"],
    )
    assert "追加 n2" in text(r["results"][2])
    refused = text(r["results"][3])
    assert (
        refused.startswith("拒否") and "書けない" in refused and "状態は変わっていない" in refused
    )
    # b の読み取りでは b の追記が無い (a の書き込みは起動後なので見えない場合がある)
    assert "b の仕事" not in text(r["results"][4])


@needs_node
def test_読み取り専用でも_list_は返る(tmp_path):
    r = run(
        tmp_path,
        [
            start("a", sid="sa"),
            tool({"op": "add", "title": "既存"}, pi="a"),
            start("b", sid="sb"),
            tool({"op": "list"}, pi="b"),
        ],
        pis=["a", "b"],
    )
    assert "既存" in text(r["results"][-1])


@needs_node
def test_読み取り専用の会話は_lease_を持たず_終了で_a_の_lease_を壊さない(tmp_path):
    r = run(
        tmp_path,
        [start("a", sid="sa"), start("b", sid="sb"), shutdown("b")],
        pis=["a", "b"],
    )
    assert r["lease"] is True


@needs_node
def test_読み取り専用の_work_コマンドは注記を付ける(tmp_path):
    r = run(
        tmp_path,
        [start("a", sid="sa"), start("b", sid="sb"), {"pi": "b", "cmd": "work"}],
        pis=["a", "b"],
    )
    assert any("読み取り専用" in n["message"] for n in r["notices"] if n["pi"] == "b")


# ── 終了 ──


@needs_node
def test_session_shutdown_で_lease_が解放される(tmp_path):
    r = run(tmp_path, [start()])
    assert r["lease"] is True
    r = run(tmp_path / "x", [start(), shutdown()])
    assert r["lease"] is False


@needs_node
def test_shutdown_の後は書けない(tmp_path):
    r = run(tmp_path, [start(), shutdown(), tool({"op": "add", "title": "x"})])
    assert text(r["results"][-1]).startswith("拒否")


@needs_node
def test_shutdown_は二重に呼んでも落ちない(tmp_path):
    r = run(tmp_path, [start(), shutdown(), shutdown()])
    assert not any("threw" in x for x in r["results"])


@needs_node
def test_shutdown_でパネルを消す(tmp_path):
    r = run(tmp_path, [start(), shutdown()])
    assert r["widgets"][-1]["lines"] is None


@needs_node
def test_終了後に別の会話が駆動を引き継げる(tmp_path):
    r = run(
        tmp_path,
        [
            start("a", sid="sa"),
            tool({"op": "add", "title": "x"}, pi="a"),
            shutdown("a"),
            start("b", sid="sb"),
            tool({"op": "add", "title": "y"}, pi="b"),
        ],
        pis=["a", "b"],
    )
    assert "追加 n3" in text(r["results"][-1])


# ── パネル・通知 ──

PLAN = {"op": "plan", "goal": "目標", "tasks": [{"title": "t1"}, {"title": "t2", "deps": [0]}]}


@needs_node
def test_goal_が無い間はパネルを出さない(tmp_path):
    r = run(tmp_path, [start()])
    assert all(w["lines"] is None for w in r["widgets"])


@needs_node
def test_goal_ができたらパネルは_5_行以内(tmp_path):
    r = run(
        tmp_path, [start(), tool(PLAN), tool({"op": "set", "id": "n2", "status": "in_progress"})]
    )
    shown = [w["lines"] for w in r["widgets"] if w["lines"]]
    assert shown, r["widgets"]
    assert all(1 <= len(lines) <= 5 for lines in shown)
    assert all(w["key"] == "work" for w in r["widgets"])
    assert "🎯" in shown[-1][0]


@needs_node
def test_パネルの各行は幅に収まる(tmp_path):
    long = "長" * 120
    r = run(tmp_path, [start(), tool({"op": "plan", "goal": long, "tasks": [{"title": long}]})])
    shown = [w["lines"] for w in r["widgets"] if w["lines"]]
    assert shown
    # 全角は幅 2 で数える (LINE_WIDTH は 60)
    for lines in shown:
        for ln in lines:
            assert sum(2 if ord(c) > 0x2E7F else 1 for c in ln) <= 64


@needs_node
def test_ui_が無い_ctx_ではウィジェットも通知も出さない(tmp_path):
    r = run(tmp_path, [start(ui=False), tool(PLAN, ui=False), {"cmd": "work", "ui": False}])
    assert r["widgets"] == [] and r["notices"] == []


@needs_node
def test_通常の操作では通知を出さない(tmp_path):
    r = run(
        tmp_path,
        [
            start(),
            tool({"op": "add", "title": "x"}),
            tool({"op": "set", "id": "n2", "status": "done"}),
        ],
    )
    assert r["notices"] == []


@needs_node
def test_work_コマンドは_list_相当を表示する(tmp_path):
    r = run(tmp_path, [start(), tool({"op": "add", "title": "調べる"}), {"cmd": "work"}])
    assert len(r["notices"]) == 1
    assert "調べる" in r["notices"][0]["message"] and r["notices"][0]["level"] == "info"


@needs_node
def test_start_前の_work_コマンドは開いていないと言う(tmp_path):
    r = run(tmp_path, [{"cmd": "work"}])
    assert "開いていない" in r["notices"][0]["message"]


# ── 記録 (journal) ──


@needs_node
def test_journal_に操作の結果を_1_件ずつ記録し本文は入れない(tmp_path):
    r = run(
        tmp_path,
        [
            start(),
            tool({"op": "add", "title": "秘密の本文"}),
            tool({"op": "set", "id": "n9", "status": "done"}),
        ],
    )
    calls = [j for j in r["journal"] if j["type"] == "tool.call"]
    assert [(c["data"]["op"], c["data"]["ok"]) for c in calls] == [("add", True), ("set", False)]
    assert "秘密の本文" not in json.dumps(r["journal"], ensure_ascii=False)


@needs_node
def test_journal_の_session_start_に_mode_が入る(tmp_path):
    r = run(tmp_path, [start()])
    s = [j for j in r["journal"] if j["type"] == "session.start"]
    assert s and s[0]["data"]["mode"] == "driver"


# ── 静的な検査 ──


def test_register_ts_の通知は選別の表を通す():
    src = REGISTER.read_text(encoding="utf-8")
    assert 'select("run.warning")' in src
    assert src.index('select("run.warning")') < src.index('notify(message, "warning")')


def test_index_ts_は_1_行の呼び出しだけ足す():
    src = INDEX.read_text(encoding="utf-8")
    assert 'import { registerWork } from "./work/register.ts";' in src
    assert src.count("registerWork(") == 1
    assert "registerWork(pi, { child: CHILD });" in src


def test_register_ts_は旗の既定が無効():
    src = REGISTER.read_text(encoding="utf-8")
    assert 'env.PI_WORK_TOOL === "1"' in src and 'env.PI_WORK !== "0"' in src
