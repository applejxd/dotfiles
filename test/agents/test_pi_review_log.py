"""review-log.ts (PR レビュー状態のイベントログの純粋関数) の試験。

node の型除去で `.ts` を直接読む。入力は Python 側で組み、薄い node の実行器に JSON で渡す。
"""

import json
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LOG_TS = ROOT / "home" / "dot_config" / "pi" / "harness" / "review-log.ts"

RUNNER = f"""
import * as L from {json.dumps(LOG_TS.as_uri())};
let raw = "";
for await (const c of process.stdin) raw += c;
const {{ fn, calls }} = JSON.parse(raw);
process.stdout.write(JSON.stringify(calls.map((a) => L[fn](...a))));
"""


def _node() -> str | None:
    node = shutil.which("node")
    if not node:
        return None
    out = subprocess.run(
        [node, "--version"], capture_output=True, text=True, encoding="utf-8", check=False
    ).stdout
    match = re.match(r"v(\d+)\.(\d+)", out.strip())
    if not match:
        return None
    return node if (int(match.group(1)), int(match.group(2))) >= (22, 18) else None


pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")


@pytest.fixture(scope="module")
def runner(tmp_path_factory):
    path = tmp_path_factory.mktemp("review-log") / "run.mjs"
    path.write_text(RUNNER, encoding="utf-8")
    return path


@pytest.fixture
def call(runner):
    def _call(fn, *calls):
        proc = subprocess.run(
            [_node(), str(runner)],
            input=json.dumps({"fn": fn, "calls": [list(c) for c in calls]}),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr[-2000:]
        return json.loads(proc.stdout)

    return _call


# ─── イベントの組み立て ──────────────────────────────────────────────

SRC, TGT, BASE = "a" * 40, "b" * 40, "c" * 40
VS = {"source": SRC, "target": TGT, "base": BASE}
META = {
    "schema": 1,
    "pr": "pxxxxxxxxxxxxxxxx",
    "branch": "feature/x",
    "target": "develop",
    "createdAt": "2026-01-01T00:00:00Z",
}


def _id() -> str:
    return str(uuid.uuid4())


def ev(t, d, **kw):
    return {
        "v": 1,
        "id": kw.get("id", _id()),
        "t": t,
        "by": kw.get("by", "pi"),
        "at": kw.get("at", "2026-01-01T00:00:00Z"),
        "vs": kw.get("vs", VS),
        "d": d,
    }


def comment(body="x", thread=None, anchor=None, **kw):
    i = kw.pop("id", _id())
    return ev("comment", {"thread": thread or i, "anchor": anchor, "body": body}, id=i, **kw)


def submit(items, kind="comment", dest="w1", batch=None, **kw):
    return ev(
        "submit",
        {"batchId": batch or _id(), "kind": kind, "items": items, "dest": {"worktreeId": dest}},
        **kw,
    )


def receipt(batch, **kw):
    return ev("receipt", {"batchId": batch, "sessionId": "s1"}, **kw)


def request(rid=None, **kw):
    d = {
        "requestId": rid or _id(),
        "sourceRef": "refs/heads/feature/x",
        "sourceOid": SRC,
        "targetRef": "refs/heads/develop",
        "targetOid": TGT,
        "baseOid": BASE,
        "message": "m",
        "cleanup": "branch_and_worktree",
    }
    return ev("merge_request", d, **kw)


def started(rid, **kw):
    return ev("merge_started", {"requestId": rid, "pendingId": "p1"}, **kw)


def result(rid, outcome="success", **kw):
    return ev("merge_result", {"requestId": rid, "outcome": outcome}, **kw)


def jsonl(events):
    return "".join(json.dumps(e, separators=(",", ":")) + "\n" for e in events)


def parse(call, text):
    return call("parseEvents", [text])[0]


def fold(call, events, current=VS):
    return call("foldState", [META, events, current])[0]


# ─── prKeyOf ────────────────────────────────────────────────────────


def test_pr_key_fixed_vectors(call):
    # API 契約と同じ値 (sha256("v1\0refs/heads/<branch>") の先頭 16 桁) を固定する
    got = call("prKeyOf", ["feature/x"], ["develop"], [""])
    assert got == ["pdd2499ad86614332", "p75ebc837a5045992", "p977398d56d1a9dcb"]


# ─── parseEvents ────────────────────────────────────────────────────


def test_parse_accepts_valid_log_and_empty(call):
    s = submit([], batch=_id())
    events = [comment(), s, receipt(s["d"]["batchId"])]
    r = parse(call, jsonl(events))
    assert r["ok"] is True and [e["id"] for e in r["events"]] == [e["id"] for e in events]
    assert parse(call, "") == {"ok": True, "events": []}


def _bad(call, text, expect):
    r = parse(call, text)
    assert r["ok"] is False and expect in r["reason"], r


def test_parse_rejects_invalid_json_and_body_not_leaked(call):
    marker = "BODY-MARKER-123"
    r = parse(call, '{"v":1, "body": "' + marker + '"\n')
    assert r["ok"] is False and "invalid_json" in r["reason"] and marker not in r["reason"]
    _bad(call, jsonl([comment()]).rstrip("\n"), "no_trailing_newline")
    _bad(call, jsonl([comment()]) + "\n", "invalid_json")  # 空行
    _bad(call, "[1]\n", "not_object")


def test_parse_rejects_unknown_type_and_missing_fields(call):
    e = comment()
    _bad(call, jsonl([{**e, "t": "nope"}]), "unknown_type")
    for key in ["id", "by", "at", "vs", "d", "v", "t"]:
        e2 = {k: v for k, v in e.items() if k != key}
        r = parse(call, jsonl([e2]))
        assert r["ok"] is False, key
    _bad(call, jsonl([{**e, "by": "root"}]), "bad_by")
    _bad(call, jsonl([{**e, "d": {"thread": e["id"], "anchor": None}}]), "bad_comment")  # body 欠け
    _bad(call, jsonl([{**e, "d": {"thread": e["id"], "anchor": None, "body": 5}}]), "bad_comment")
    bad_anchor = {"path": "a", "side": "middle", "blob": SRC, "line": 1, "lineEnd": 1}
    _bad(call, jsonl([comment(anchor=bad_anchor)]), "bad_comment")
    good_anchor = {"path": "a", "side": "new", "blob": SRC, "line": 1, "lineEnd": 2}
    assert parse(call, jsonl([comment(anchor=good_anchor)]))["ok"] is True
    _bad(call, jsonl([submit([], kind="bogus")]), "bad_submit")
    _bad(call, jsonl([ev("summary", {"done": "d", "files": "x", "findings": []})]), "bad_summary")
    _bad(
        call,
        jsonl([ev("merge_result", {"requestId": _id(), "outcome": "maybe"})]),
        "bad_merge_result",
    )


def test_parse_rejects_bad_id_duplicates_time_and_oid(call):
    e = comment()
    _bad(call, jsonl([{**e, "id": "not-a-uuid"}]), "bad_id")
    _bad(call, jsonl([e, {**comment(), "id": e["id"]}]), "duplicate_id")
    _bad(call, jsonl([{**e, "at": "yesterday"}]), "bad_at")
    _bad(call, jsonl([{**e, "at": "2026-13-45T00:00:00Z"}]), "bad_at")
    # Date.parse が受け付けても、ISO 8601 の形でなければ断る
    _bad(call, jsonl([{**e, "at": "2026/01/01 00:00:00"}]), "bad_at")
    for field in ("source", "target", "base"):
        _bad(call, jsonl([{**e, "vs": {**VS, field: "zz"}}]), "bad_vs")
    for bad_oid in ["g" * 40, "a" * 39, "A" * 40, "a" * 41]:
        _bad(call, jsonl([{**e, "vs": {**VS, "source": bad_oid}}]), "bad_vs")
    _bad(
        call,
        jsonl([request(rid=_id()) | {"d": {**request()["d"], "sourceOid": "zz"}}]),
        "bad_merge_request",
    )


def test_parse_rejects_oversized_body_and_log(call):
    big = comment(body="x" * 16384)  # JSON のラッパーで 16384 B を超える
    _bad(call, jsonl([big]), "body_too_large")
    ok = comment(body="x" * 16000)
    assert parse(call, jsonl([ok]))["ok"] is True
    # 多バイト文字はバイトで数える (文字数なら 6000 文字で収まってしまう)
    _bad(call, jsonl([comment(body="あ" * 6000)]), "body_too_large")
    _bad(call, "x" * 524289, "events_too_large")
    _bad(call, jsonl([comment() for _ in range(2001)]), "too_many_events")


def test_parse_receipt_and_merge_references(call):
    _bad(call, jsonl([receipt(_id())]), "receipt_without_submit")
    s = submit([])
    _bad(
        call, jsonl([receipt(s["d"]["batchId"]), s]), "receipt_without_submit"
    )  # 順序: submit が先
    _bad(call, jsonl([s, s | {"id": _id()}]), "duplicate_batch")
    _bad(call, jsonl([started(_id())]), "merge_without_request")
    _bad(call, jsonl([result(_id())]), "merge_without_request")
    rq = request()
    rid = rq["d"]["requestId"]
    assert parse(call, jsonl([rq, started(rid), result(rid)]))["ok"] is True
    _bad(call, jsonl([rq, rq | {"id": _id()}]), "duplicate_request")


# ─── checkAppend ────────────────────────────────────────────────────


def test_check_append_limits_and_reserve(call):
    c, rc, ms = comment(), receipt(_id()), result(_id())
    ck = lambda b, n, e: call("checkAppend", [b, n, e])[0]  # noqa: E731
    assert ck(0, 0, c) == {"ok": True}
    assert ck(0, 0, comment(body="x" * 16384)) == {"ok": False, "reason": "body_too_large"}
    assert ck(524288 - 10, 5, c) == {
        "ok": False,
        "reason": "reserved",
    }  # 通常のイベントは、終端用のバイト枠を使わせない
    assert ck(524288 - 10, 5, rc) == {
        "ok": False,
        "reason": "events_too_large",
    }  # 終端でも全体の上限は越えられない
    # バイトの余裕 (32 KB): 上限の近くまで通常のイベントで埋めても、receipt は書ける
    assert ck(524288 - 32768 - 1000, 5, c) == {"ok": True}
    assert ck(524288 - 1000, 5, c) == {"ok": False, "reason": "reserved"}
    assert ck(524288 - 1000, 5, rc) == {"ok": True}
    assert ck(524288 - 1000, 5, ms) == {"ok": True}
    assert ck(0, 2000, rc) == {"ok": False, "reason": "too_many_events"}
    assert ck(0, 1999, rc) == {"ok": True}
    # 予約: 1900 件以上は終端の種別以外を断る
    assert ck(0, 1899, c) == {"ok": True}
    assert ck(0, 1900, c) == {"ok": False, "reason": "reserved"}
    assert ck(0, 1900, submit([])) == {"ok": False, "reason": "reserved"}
    assert ck(0, 1900, request()) == {"ok": False, "reason": "reserved"}
    assert ck(0, 1900, rc) == {"ok": True}
    assert ck(0, 1950, ms) == {"ok": True}
    assert ck(0, 1950, started(_id())) == {"ok": True}


def test_serialize_roundtrip_and_new_id(call):
    events = [comment(), comment()]
    text = call("serializeEvents", [events])[0]
    assert text == jsonl(events)
    assert text.endswith("\n") and text.count("\n") == 2
    assert parse(call, text)["ok"] is True
    a, b = call("newId", [], [])
    assert a != b and re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", a
    )


# ─── foldState ──────────────────────────────────────────────────────


def test_thread_status_transitions(call):
    c = comment()
    assert fold(call, [c])["threads"][0]["status"] == "unsent"
    s = submit([c["id"]])
    st = fold(call, [c, s])
    assert st["threads"][0]["status"] == "sent"
    r = receipt(s["d"]["batchId"])
    assert fold(call, [c, s, r])["threads"][0]["status"] == "read"
    reply = comment(thread=c["id"], by="pi")
    st = fold(call, [c, s, r, reply])
    assert st["threads"][0]["status"] == "replied"
    assert [x["id"] for x in st["threads"][0]["comments"]] == [c["id"], reply["id"]]
    # 受領の前の返信 (submit に含まれない) は「返信済み」にしない
    early = comment(thread=c["id"])
    assert fold(call, [c, early, s, r])["threads"][0]["status"] == "read"
    assert fold(call, [c, s, early])["threads"][0]["status"] == "sent"
    # 利用者 (by = app) が受領後に足したコメントでは「返信済み」にならない (表示用の状態は pi のコメントだけを数える)
    mine = comment(thread=c["id"], by="app")
    assert fold(call, [c, s, r, mine])["threads"][0]["status"] == "read"
    # 別のスレッドは影響されない
    other = comment()
    st = fold(call, [c, other, s, r])
    assert {t["id"]: t["status"] for t in st["threads"]} == {c["id"]: "read", other["id"]: "unsent"}


def test_batches_and_unread(call):
    c1, c2 = comment(), comment()
    s1 = submit([c1["id"]], dest="w1")
    s2 = submit([c2["id"]], dest="w2")
    st = fold(call, [c1, c2, s1, s2])
    assert [b["received"] for b in st["batches"]] == [False, False]
    assert [b["batchId"] for b in call("unreadBatches", [st, "w1"])[0]] == [s1["d"]["batchId"]]
    assert call("unreadBatches", [st, "w3"])[0] == []
    st = fold(call, [c1, c2, s1, s2, receipt(s1["d"]["batchId"])])
    assert call("unreadBatches", [st, "w1"])[0] == []
    assert [b["batchId"] for b in call("unreadBatches", [st, "w2"])[0]] == [s2["d"]["batchId"]]
    assert st["batches"][0]["received"] is True and st["batches"][0]["sessionId"] == "s1"


def test_review_state_follows_latest_submit_kind(call):
    assert fold(call, [])["review"] == "none"
    assert fold(call, [submit([], kind="changes")])["review"] == "changes"
    assert (
        fold(call, [submit([], kind="changes"), submit([], kind="approve")])["review"] == "approve"
    )
    assert (
        fold(call, [submit([], kind="approve"), submit([], kind="changes")])["review"] == "changes"
    )
    # comment の送信ではレビュー状態を変えない (GitHub と同じ)。approve の後に comment を送っても approve のまま
    assert (
        fold(call, [submit([], kind="approve"), submit([], kind="comment")])["review"] == "approve"
    )
    assert fold(call, [submit([], kind="comment")])["review"] == "none"


def test_review_goes_stale_when_the_source_moves_but_not_when_only_a_comment_is_sent(call):
    moved = {**VS, "source": "9" * 40}
    approved = submit([], kind="approve")
    st = fold(call, [approved], current=moved)
    assert st["review"] == "approve" and st["reviewStale"] is True and st["reviewVs"] == VS
    assert fold(call, [approved])["reviewStale"] is False
    # この後に comment を送っても (vs が現在のものでも)、レビューの古さは変わらない
    later = submit([], kind="comment", vs=moved)
    assert fold(call, [approved, later], current=moved)["reviewStale"] is True
    assert fold(call, [])["reviewVs"] is None and fold(call, [])["reviewStale"] is False


@pytest.mark.parametrize("field", ["source", "target", "base"])
def test_stale_by_each_of_source_target_base(call, field):
    e = comment()
    assert fold(call, [e], VS)["stale"] is False
    cur = {**VS, field: "d" * 40}
    st = fold(call, [e], cur)
    assert st["stale"] is True and st["staleParts"][field] is True
    assert [k for k, v in st["staleParts"].items() if v] == [field]
    assert st["threads"][0]["stale"] is True


def test_stale_uses_latest_record(call):
    old = comment(vs={**VS, "source": "e" * 40})
    new = comment()
    assert fold(call, [old, new], VS)["stale"] is False
    assert fold(call, [new, old], VS)["stale"] is True


def test_summary_is_latest(call):
    s1 = ev("summary", {"done": "one", "files": [], "findings": []})
    s2 = ev("summary", {"done": "two", "files": ["a"], "findings": []})
    assert fold(call, [])["summary"] is None
    assert fold(call, [s1, s2])["summary"]["d"]["done"] == "two"


def test_merge_status_and_merged_ok(call):
    assert fold(call, [])["merge"]["status"] == "none"
    rq = request()
    rid = rq["d"]["requestId"]
    assert fold(call, [rq])["merge"]["status"] == "requested"
    st = fold(call, [rq, started(rid)])
    assert st["merge"]["status"] == "started" and st["merge"]["pendingId"] == "p1"
    st = fold(call, [rq, started(rid), result(rid, "failed")])
    assert st["merge"]["status"] == "done" and call("mergedOk", [st])[0] is False
    st = fold(call, [rq, started(rid), result(rid, "success")])
    assert st["merge"]["status"] == "done" and call("mergedOk", [st])[0] is True
    assert call("mergedOk", [fold(call, [rq, started(rid), result(rid, "refused")])])[0] is False
    # 別の要求の結果は、現在の要求の状態を進めない
    rq2 = request()
    st = fold(call, [rq, rq2, result(rid, "success")])
    assert st["merge"]["status"] == "requested" and st["merge"]["succeeded"] is True


def test_by_does_not_change_state(call):
    def build(by):
        c = comment(by=by, id="00000000-0000-4000-8000-000000000001")
        s = submit([c["id"]], by=by, batch="00000000-0000-4000-8000-000000000002", kind="changes")
        r = receipt(s["d"]["batchId"], by=by)
        rep = comment(thread=c["id"], by=by, id="00000000-0000-4000-8000-000000000003")
        rq = request(rid="00000000-0000-4000-8000-000000000004", by=by)
        return [
            c,
            s,
            r,
            rep,
            rq,
            started(rq["d"]["requestId"], by=by),
            result(rq["d"]["requestId"], by=by),
        ]

    def strip(x):
        # 表示用の by だけを取り除いて比べる
        if isinstance(x, dict):
            return {k: strip(v) for k, v in x.items() if k not in ("by", "id", "requestId")}
        if isinstance(x, list):
            return [strip(v) for v in x]
        return x

    a = fold(call, build("app"))
    b = fold(call, build("pi"))

    def authority(x):
        # 権限・統合・配送に関わる状態。by で変わってはならない
        s = strip(x)
        return {
            k: s[k]
            for k in ("review", "reviewStale", "batches", "merge", "stale", "staleParts", "count")
        }

    assert authority(a) == authority(b)
    # 表示用の「返信済み」だけは、by = pi のコメントで決まる
    assert a["threads"][0]["status"] == "read" and b["threads"][0]["status"] == "replied"
    assert b["review"] == "changes" and b["merge"]["succeeded"] is True
