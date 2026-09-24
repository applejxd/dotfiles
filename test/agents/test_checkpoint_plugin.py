"""checkpoint-plugin の振る舞いを node で実際に動かして確かめる。

静的な文字列一致ではなく、偽の ``ctx`` を渡して関数を呼ぶ。ここで固定して
いるのは、実測で見つけた次の 2 つの欠陥の再発防止である。

- 欠陥 A: 圧縮の**要求を組み立てた**だけで印を置くと、その後 "Nothing to
  compact yet" で失敗したときに、起きていない圧縮の引き継ぎを後続の要求へ
  流し込む (実測でモデルが読んでしまった)
- 欠陥 B: 圧縮の直後に走るのは内部の継続要求のことがある。そこで印を消すと
  **次にユーザが話しかけたときには残っていない**

see docs/change/0001-compaction-context-handover.md
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "home/dot_config/opencode/checkpoint-plugin/index.js"
SKILL = ROOT / "home/dot_config/opencode/skills/checkpoint"
CLI = SKILL / "scripts/executable_checkpoint.py"
TEMPLATE = SKILL / "references/checkpoint-template.md"

SESSION = "ses_testABC12345"
# checkpoint.py の _short_sid と同じ規則 (英数字だけを残して先頭 8 文字)。
SHORT = "sestestA"

RUNNER = r"""
import * as plugin from "./mod.mjs"

const [kase, cwd, session] = JSON.parse(process.argv[2])

const BODY = ["Goal", "Constraints", "State", "Evidence", "Next", "Refs"]
  .map((s) => `## ${s}\n\nKUJIRA42\n`)
  .join("\n")

const makeCtx = (events = [], replies = []) => {
  const store = new Map()
  const calls = []
  return {
    _store: store,
    _calls: calls,
    storage: {
      get: async (k) => store.get(k),
      set: async (k, v) => void store.set(k, v),
      remove: async (k) => void store.delete(k),
    },
    event: {
      subscribe: () =>
        (async function* () {
          for (const e of events) yield e
        })(),
    },
    session: {
      generate: async (arg) => {
        calls.push(arg)
        return { text: replies.shift() ?? "" }
      },
    },
  }
}

const dump = (ctx, event) => ({
  keys: [...ctx._store.keys()],
  system: (event?.system ?? []).map((s) => String(s.text).slice(0, 60)),
  summary: event?.result?.summary ?? null,
  generateCalls: ctx._calls.length,
})

const ended = { type: "session.compaction.ended", data: { sessionID: session } }
const failed = { type: "session.compaction.failed", data: { sessionID: session } }

const cases = {
  // 成功した圧縮だけが印を置く。
  "watch-ended": async () => {
    const ctx = makeCtx([ended])
    await plugin.watchCompaction(ctx)
    return dump(ctx)
  },
  // 失敗や無関係なイベントでは置かない。
  "watch-others": async () => {
    const ctx = makeCtx([failed, { type: "session.usage.updated", data: { sessionID: session } }])
    await plugin.watchCompaction(ctx)
    return dump(ctx)
  },
  // sessionID が無いイベントでは置かない。
  "watch-no-session": async () => {
    const ctx = makeCtx([{ type: "session.compaction.ended", data: {} }])
    await plugin.watchCompaction(ctx)
    return dump(ctx)
  },
  // 欠陥 A: 圧縮フックは印を置かない。
  "compaction-sets-no-marker": async () => {
    const ctx = makeCtx()
    await plugin.onCompaction(ctx, { sessionID: session }, cwd)
    return dump(ctx)
  },
  // 圧縮の直前に引き継ぎを生成し、要約そのものに使う。
  "compaction-generates-the-record": async () => {
    const ctx = makeCtx([], [BODY])
    const event = { sessionID: session }
    await plugin.onCompaction(ctx, event, cwd)
    return dump(ctx, event)
  },
  // 空が返ることがある (実測)。1 度だけ引き直す。
  "compaction-retries-once": async () => {
    const ctx = makeCtx([], ["", BODY])
    const event = { sessionID: session }
    await plugin.onCompaction(ctx, event, cwd)
    return dump(ctx, event)
  },
  // 生成できなければ要約を乗っ取らない (OpenCode 標準の要約に戻る)。
  "compaction-falls-back-when-empty": async () => {
    const ctx = makeCtx([], [])
    const event = { sessionID: session }
    await plugin.onCompaction(ctx, event, cwd)
    return dump(ctx, event)
  },
  // 6 節が揃わない生成物は採用しない。
  "compaction-rejects-a-malformed-body": async () => {
    const ctx = makeCtx([], ["## Goal\n\nこれだけ"])
    const event = { sessionID: session }
    await plugin.onCompaction(ctx, event, cwd)
    return dump(ctx, event)
  },
  // ユーザの手番へ届いたら消す。
  "context-user-turn": async () => {
    const ctx = makeCtx()
    await ctx.storage.set(plugin.key(session), { at: "x" })
    const event = { sessionID: session, system: [], messages: [{ role: "user" }] }
    await plugin.onContext(ctx, event, cwd)
    return dump(ctx, event)
  },
  // 欠陥 B: 手番の途中では入れるが消さない。
  "context-mid-turn": async () => {
    const ctx = makeCtx()
    await ctx.storage.set(plugin.key(session), { at: "x" })
    const event = { sessionID: session, system: [], messages: [{ role: "assistant" }] }
    await plugin.onContext(ctx, event, cwd)
    return dump(ctx, event)
  },
  // 印が無ければ何も入れない。
  "context-no-marker": async () => {
    const ctx = makeCtx()
    const event = { sessionID: session, system: [], messages: [{ role: "user" }] }
    await plugin.onContext(ctx, event, cwd)
    return dump(ctx, event)
  },
}

console.log(JSON.stringify(await cases[kase]()))
"""


@pytest.fixture(scope="module")
def repo(tmp_path_factory) -> Path:
    """checkpoint を 1 つ置いた使い捨てのリポジトリ。"""
    root = tmp_path_factory.mktemp("cp-repo")
    for args in (
        ["init", "-q"],
        ["config", "user.email", "t@example.com"],
        ["config", "user.name", "t"],
    ):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    (root / "a.txt").write_text("hi\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-qm", "init"], cwd=root, check=True, capture_output=True
    )
    tmp = root / ".tmp"
    tmp.mkdir()
    (tmp / f"checkpoint-{SHORT}.md").write_text(
        "# Checkpoint\n\n## Goal\n\n合言葉は KUJIRA42 である。\n", encoding="utf-8"
    )
    return root


@pytest.fixture(scope="module")
def call(tmp_path_factory, repo):
    node = shutil.which("node")
    if not node:
        pytest.skip("node が無い (mise.toml の [tools] に宣言してある)")

    work = tmp_path_factory.mktemp("cp-js")
    # CLI と雛形は配備先を指す。試験では**リポジトリ内の実体**へ向け直す。
    src = PLUGIN.read_text("utf-8")
    src = src.replace(
        'const CLI = join(SKILL, "scripts/checkpoint.py")',
        f"const CLI = {json.dumps(str(CLI))}",
    )
    src = src.replace(
        'const TEMPLATE = join(SKILL, "references/checkpoint-template.md")',
        f"const TEMPLATE = {json.dumps(str(TEMPLATE))}",
    )
    assert "join(SKILL" not in src, "配備先の差し替えに失敗した"
    (work / "mod.mjs").write_text(src, "utf-8")
    (work / "run.mjs").write_text(RUNNER, "utf-8")

    def run(kase: str) -> dict:
        done = subprocess.run(
            [node, str(work / "run.mjs"), json.dumps([kase, str(repo), SESSION])],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(done.stdout)

    return run


def test_only_a_completed_compaction_sets_the_marker(call):
    assert call("watch-ended")["keys"] == [f"pending:{SESSION}"]


def test_failed_or_unrelated_events_set_nothing(call):
    """★失敗した圧縮で印を置かないこと。

    上流の ``execute`` は "Nothing to compact yet" の門番を prepare より前に
    置いていて、そこでは ``Failed`` を publish して返る。``Ended`` は成功経路
    でしか出ない。ここを取り違えると欠陥 A が戻る。
    """
    assert call("watch-others")["keys"] == []


def test_events_without_a_session_are_ignored(call):
    assert call("watch-no-session")["keys"] == []


def test_the_compaction_hook_never_sets_the_marker(call):
    """★欠陥 A の再発防止。圧縮フックは機械節を書くだけ。"""
    assert call("compaction-sets-no-marker")["keys"] == []


def test_the_record_is_generated_and_becomes_the_summary(call):
    """★圧縮の要約と引き継ぎを一本化する。

    別々に持つと必ず片方が古くなる（実際に意味内容だけ 1 日古いまま残った）。
    ``e.result`` を設定すると OpenCode は自前の要約生成を飛ばす（実測）。
    """
    result = call("compaction-generates-the-record")
    assert result["generateCalls"] == 1
    summary = result["summary"]
    assert summary is not None
    for heading in ("Goal", "Constraints", "State", "Evidence", "Next", "Refs"):
        assert f"## {heading}" in summary
    # 機械節も同じ成果物に入る
    assert "## Snapshot" in summary
    assert result["keys"] == []


def test_an_empty_generation_is_retried_once(call):
    """★空が返ることがある（実測: 同じプロンプトで通ったり空だったり）。"""
    result = call("compaction-retries-once")
    assert result["generateCalls"] == 2
    assert result["summary"] is not None


@pytest.mark.parametrize(
    "case", ["compaction-falls-back-when-empty", "compaction-rejects-a-malformed-body"]
)
def test_a_bad_generation_leaves_the_summary_alone(call, case):
    """★生成に失敗したら要約を乗っ取らない。

    ``result`` を設定しなければ OpenCode が自前で要約する。壊れた引き継ぎを
    要約として残すより、標準の要約に戻る方がよい。
    """
    result = call(case)
    assert result["summary"] is None


def test_the_record_reaches_a_user_turn_and_is_then_consumed(call):
    result = call("context-user-turn")
    assert len(result["system"]) == 1
    assert "圧縮" in result["system"][0]
    assert result["keys"] == []


def test_mid_turn_requests_get_the_record_but_keep_the_marker(call):
    """★欠陥 B の再発防止。

    圧縮の直後に走るのは内部の継続要求のことがある。そこで消すと、次に
    ユーザが話しかけたときには残っていない (実測)。入れるが消さない。
    """
    result = call("context-mid-turn")
    assert len(result["system"]) == 1
    assert result["keys"] == [f"pending:{SESSION}"]


def test_without_a_marker_nothing_is_injected(call):
    result = call("context-no-marker")
    assert result["system"] == []
    assert result["keys"] == []
