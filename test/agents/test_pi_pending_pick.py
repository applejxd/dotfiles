"""``/pending`` の ID 省略 (TUI で選ぶ)・Tab 補完・resolve の対話 (``home/dot_config/pi/harness/pending-pick.ts``)。

``test/agents/pi/pending_pick_driver.mjs`` が、偽の pi・偽の ctx・使い捨ての git リポジトリで ``/pending`` を動かして JSON で出す
(node の型除去を使うので、22.18 未満の node では飛ばす)。
選択は ID を決めるだけで、承認・破棄・決着の確認は既存の経路 (``approvePending`` / ``resolvePending``) がそのまま行う。
"""

from __future__ import annotations

import json
import re
import subprocess

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

RUNNER = ROOT / "test" / "agents" / "pi" / "pending_pick_driver.mjs"

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")


@pytest.fixture(scope="module")
def table():
    proc = subprocess.run(
        [_node(), str(RUNNER)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=300,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-1000:]
    return json.loads(proc.stdout)


def test_candidates_are_filtered_per_kind_approve_oldest_first_others_newest_first(table):
    c = table["cands"]
    i = c["ids"]
    # approve: アダプタのある pending だけ (アダプタの無い操作・running・done は出ない)。待ち行列なので古い順
    assert c["approve"] == [i["p1"], i["p3"], i["p4"], i["p5"]]
    assert c["show"] == [i["d2"], i["d1"], i["r1"], i["p5"], i["p4"], i["p3"], i["p2"], i["p1"]]
    assert c["sortedNewestFirst"] is True
    # drop: pending の action だけ (アダプタの有無は問わない)
    assert c["drop"] == [i["p5"], i["p4"], i["p3"], i["p2"], i["p1"]]
    # resolve: running と、実行器が記録した unknown だけ (成功した done は出ない)
    assert c["resolve"] == [i["d1"], i["r1"]]


def test_labels_fit_in_44_cells_and_keep_action_and_age_but_not_the_id(table):
    c = table["cands"]
    assert c["maxWidth"] <= 44
    assert c["anyControl"] is False and c["anyNewline"] is False
    assert re.match(rf"^{re.escape('long_action_name_abcdef')} たった今", c["longLabel"])
    assert c["briefLabel"].startswith("briefed_op たった今 <<ABC>>")
    # brief が無いときは、記録の最初の引数の 1 行目
    assert c["firstArgLabel"].startswith("fake_op たった今 最初の引数の一行目")
    assert "二行目" not in c["firstArgLabel"]
    assert c["ctrlLabel"].startswith("fake_op たった今 ")


def test_identical_labels_get_the_id_tail_4_digits_and_only_those(table):
    d = table["dup"]
    assert d["maxWidth"] <= 44 and d["d1"] != d["d2"]
    assert d["d1"].endswith(f" …{d['tails'][0]}") and d["d2"].endswith(f" …{d['tails'][1]}")
    assert "…" not in d["u"]


def test_an_empty_adapter_table_still_asks_whether_the_exclusive_attempt_stopped(table):
    e = table["empty_table_resolve"]
    assert len(e["selects"]) == 2 and "確かめ" in e["selects"][1]
    assert "決着させていない" in e["text"] or "--confirm-stopped" in e["text"]
    assert e["state"]["running"] is True and e["locks"] == 1


def test_the_chosen_row_is_processed_even_when_all_visible_parts_of_labels_are_equal(table):
    s = table["same_label"]
    assert len(set(s["tails"])) == 1  # 末尾 4 桁も同じ
    assert s["unique"] is True and s["maxWidth"] <= 44
    assert s["text"].startswith("破棄した:") and s["target"] in s["text"]
    # 選んだ (2 行目の) ID だけが消える
    assert sum(s["gone"]) == 1
    assert [i for i, g in zip(s["created"], s["gone"], strict=True) if g] == [s["target"]]


def test_tail_match_resolves_a_unique_id_and_keeps_full_ids_unchanged(table):
    t = table["tail"]
    assert t["uniqueSame"] is True
    assert (
        t["full"] == "見つからない (/pending list で ref を確かめる)"
    )  # 15 桁は従来の経路 (探索しない)
    assert "短すぎる" in t["short2"] and "短すぎる" in t["short1"] and t["still"] is True
    assert t["zero"] == "見つからない (/pending list で確認する)"
    # kind ごとの候補の集合で探す: approve では running は当たらない。show では当たる
    assert (
        t["approveRunning"] == "見つからない (/pending list で確認する)"
        and t["showRunning"] is True
    )
    assert t["approveTail"]["state"]["pending"] is False  # 末尾で選んだ保留が承認されて実行された


def test_tail_match_with_several_hits_asks_among_only_those(table):
    t = table["tail"]
    assert t["found"] is True
    m = t["many"]
    assert m["matches"] >= 2 and m["optionsAreMatches"] is True
    assert "一意でない" in m["rpc"] and m["rpcSelects"] == 0
    assert "選ばなかった" in m["cancel"] and m["firstStillThere"] is True
    assert (
        m["chosenText"].startswith("破棄した:")
        and m["firstGone"] is True
        and m["secondStillThere"] is True
    )


def test_no_candidates_says_so_and_does_nothing(table):
    z = table["zero"]
    for sub in ("approve", "show", "drop"):
        assert "対象が無い" in z[sub]["text"] and z[sub]["selects"] == 0
    assert z["marks"] == 0


def test_approve_with_one_candidate_skips_the_picker_and_matches_the_id_route(table):
    a = table["approve_one"]
    assert a["pick"] == a["id"]
    assert a["pick"]["state"]["pending"] is False  # 実行されて pending を外れた
    assert len(a["pick"]["selects"]) == 1  # 承認の画面だけ (選択は出ない)
    assert a["pick"]["selects"][0]["options"][0] == "承認して実行"


def test_show_with_one_candidate_skips_the_picker(table):
    s = table["show_one"]
    assert s["same"] is True and s["selects"] == 0 and s["hasId"] is True


def test_drop_always_asks_even_for_one_candidate(table):
    d = table["drop_one"]
    assert d["options"] == 2 and d["firstHasTail"] is True
    assert "選ばなかった" in d["cancelText"] or "やめ" in d["cancelText"]
    assert "選ばなかった" in d["escText"]
    assert d["stillThere"] is True  # やめる・Esc では消えない
    assert d["doneText"].startswith("破棄した:") and d["after"] is False


def test_several_candidates_show_a_picker_with_the_labels_and_cancel_does_nothing(table):
    m = table["many"]
    assert m["selectCount"] == 1 and m["optionsAreLabels"] is True and m["title"]
    assert (
        "選ばなかった" in m["noneText"] and m["noneMarks"] == 0 and m["noneStates"] == [True, True]
    )
    # 2 番目 (新しい方。approve は古い順) を選ぶと、その ID で承認の画面へ進み、承認で実行される
    assert m["secondSelects"] == 2 and m["secondOptions"][0] == "承認して実行"
    assert m["secondStates"] == [True, False]


def test_non_tui_refuses_approve_and_never_shows_a_picker(table):
    n = table["non_tui"]
    assert "対話 (TUI)" in n["approve"] and "対話 (TUI)" in n["noUi"]
    assert n["selects"] == 0 and n["still"] is True
    assert n["showText"] == "/pending " and n["dropText"] == "/pending "  # 従来の USAGE


def test_completion_lists_subcommands_and_ids_oldest_first_for_approve_with_labels(table):
    c = table["completion"]
    assert c["isFunction"] is True and c["subShape"] is True
    assert c["sub"] == ["list", "show", "approve", "resolve", "drop", "unlock", "log"]
    assert c["ap"] == ["approve"]
    # pi は、コマンド名の後ろの全体 (空白を含む) を渡し、返した value で全体を置き換える
    assert c["approveValues"] == c["approveIds"]
    assert c["approveLabels"] == c["expectedLabels"]
    assert c["prefixed"] == c["prefixedExpect"] and c["none"] is None
    assert len(c["show"]) == 3
    assert c["list"] is None and c["unknown"] is None
    assert c["thrown"] is None  # 例外は握りつぶして null


def test_resolve_offers_only_the_valid_results_for_each_stage(table):
    def kinds(options):
        return [o.split(" ")[0].rstrip(":—") for o in options]

    assert kinds(table["reserved"]["selects"][1]) == ["pending", "abandon"]
    assert (
        "決着させた" in table["reserved"]["text"] and table["reserved"]["state"]["pending"] is True
    )
    sp = table["started_plain"]
    assert kinds(sp["selects"][1]) == ["success", "failed", "retry"] and len(sp["selects"]) == 2
    assert sp["state"]["running"] is False
    assert kinds(table["unknown"]["selects"][1]) == ["success", "failed"]
    assert table["unknown"]["resolved"] == "human"
    assert all(" — " in o or ":" in o for o in sp["selects"][1])  # 説明が付く


def test_resolve_of_a_started_exclusive_attempt_asks_whether_it_stopped(table):
    e = table["exclusive"]
    assert len(e["noSelects"]) == 3 and "確かめ" in e["noSelects"][2]["title"]
    assert any("確かめた" in o for o in e["noSelects"][2]["options"])
    assert "git・hook" in e["noText"]
    assert e["afterNo"]["state"]["running"] is True and e["afterNo"]["locks"] == 1  # 何も決着しない
    assert "決着させた" in e["yesText"] and "統合ロックを外した" in e["yesText"]
    assert e["afterYes"]["state"]["running"] is False and e["afterYes"]["locks"] == 0


def test_resolve_with_only_an_id_skips_the_id_picker_and_the_classic_form_is_unchanged(table):
    assert table["id_only"]["selects"] == 1 and "決着させた" in table["id_only"]["text"]
    k = table["classic"]
    assert "対話 (TUI)" in k["rpc"] and k["rpcSelects"] == 0
    assert "選ばなかった" in k["esc"]
    assert "決着させた" in k["old"] and k["oldSelects"] == 0 and k["state"]["running"] is False


def test_legacy_retreats_are_shown_but_never_offered_for_drop_or_approve_and_a_middle_digit_run_is_not_a_tail(
    table,
):
    t = table["legacy_and_middle"]
    # 旧形式の退避は、表示の候補にだけ出る (破棄・承認の候補には、新形式の保留だけ)
    assert t["legacyId"] in t["show"] and t["a"] in t["show"]
    assert t["drop"] == [t["a"]] and t["approve"] == [t["a"]]
    # 末尾でない位置の桁は、一致にしない (部分一致で拾わない)
    assert t["mid"] and t["a"].endswith(t["mid"]) is False
    assert "見つからない" in t["middleText"] and t["middleSelects"] == 0


def test_hub_one_approvable_goes_straight_to_the_approval_screen(table):
    a = table["hub"]["approveOne"]
    assert a["selects"] == 1 and a["first"] == "承認して実行"  # 選択は出ず、承認の画面だけ
    assert a["pending"] is False and a["marks"] == ["execute:fake_op"]


def test_hub_marks_approvals_and_processes_the_chosen_second_row(table):
    t = table["hub"]["approveTwo"]
    assert len(t["options"]) == 2 and all(o.startswith("承認 ") for o in t["options"])
    assert t["maxWidth"] <= 44
    assert t["states"] == [True, False]  # 2 番目 (新しい方。hub は古い順) だけが処理された
    assert t["marks"] == ["execute:long_action_name_abcdef"]  # 2 件目 (新しい方) の操作


def test_approve_and_hub_are_oldest_first_but_show_and_drop_stay_newest_first(table):
    o = table["order"]
    old, mid, new = o["oldest"], o["mid"], o["newest"]
    # 保存の順 (mid → oldest → newest) ではなく、時刻の順で並ぶ
    assert o["approve"] == [old, mid, new] and o["hub"] == [old, mid, new]
    assert o["show"] == [new, mid, old] and o["drop"] == [new, mid, old]
    # 先頭 (既定のカーソル位置) は一番古い保留。先頭を選ぶと、それが承認される
    assert o["firstIsLabel"] is True
    assert o["processed"] == [True, False, False]


def test_hub_escape_does_nothing(table):
    e = table["hub"]["esc"]
    assert "選ばなかった" in e["text"] and e["selects"] == 1
    assert e["marks"] == [] and e["states"] == [True, True]


def test_hub_running_and_unknown_go_to_the_resolve_dialog(table):
    h = table["hub"]
    r = h["runningOne"]
    assert len(r["selects"]) == 1 and r["selects"][0][0].startswith(
        "pending"
    )  # 選ばず、種類の選択へ
    assert "決着させた" in r["text"] and r["state"]["running"] is False
    t = h["resolveTwo"]
    assert len(t["options"]) == 2 and all(o.startswith("決着 ") for o in t["options"])
    assert t["kinds"] == ["success", "failed"] and t["resolvedBy"] == "human"


def test_hub_legacy_and_adapterless_pending_show_details(table):
    h = table["hub"]
    assert h["legacyOne"] == {"selects": 0, "same": True, "notList": True}
    s = h["showTwo"]
    assert len(s["options"]) == 2 and all(o.startswith("詳細 ") for o in s["options"])
    assert s["selectsAfter"] == 1 and s["marks"] == []


def test_hub_without_candidates_returns_the_plain_list(table):
    h = table["hub"]
    assert h["zero"] == {"text": "退避したコミットは無い", "selects": 0}
    # 成功した結果 (done) は候補に入らない (/pending log で見る)
    assert h["doneOnly"]["cands"] == 0 and h["doneOnly"]["selects"] == 0


def test_hub_leaves_list_and_non_tui_unchanged(table):
    u = table["hub"]["unchanged"]
    assert u["listSelects"] == 0 and u["listHasId"] is True
    assert u["rpcSelects"] == 0 and u["rpcSame"] is True
    assert u["noUiSelects"] == 0 and u["noUiSame"] is True and u["pending"] is True
