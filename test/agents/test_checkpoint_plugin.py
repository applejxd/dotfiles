"""checkpoint-plugin の振る舞いを node で実際に動かして確かめる。

静的な文字列一致ではなく、偽の ``ctx`` を渡して関数を呼ぶ。ここで固定して
いるのは、実測で見つけた次の欠陥の再発防止である。

- 欠陥 A: 圧縮の**要求を組み立てた**だけで印を置くと、その後 "Nothing to
  compact yet" で失敗したときに、起きていない圧縮の引き継ぎを後続の要求へ
  流し込む (実測でモデルが読んでしまった)
- 欠陥 B: 圧縮の直後に走るのは内部の継続要求のことがある。そこで印を消すと
  **次にユーザが話しかけたときには残っていない**
- 書き込みに失敗しても、残っていた古い記録を要約に採用しない
- 近い時刻に作られた別セッションの記録を注入しない

see docs/change/closed/0001-compaction-context-handover.md
see docs/spec/checkpoint.md
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "home/dot_config/opencode/checkpoint-plugin/index.js"
SKILL = ROOT / "home/dot_config/opencode/skills/checkpoint"
CLI = SKILL / "scripts/executable_checkpoint.py"
TEMPLATE = SKILL / "references/checkpoint-template.md"

# 近い時刻に作られた 2 つのセッション。英数字化した先頭 8 文字が同じになる。
SESSION = "ses_f1d80f67affeAbCdEfGhIjKlMn"
NEIGHBOR = "ses_f1d80c05cffeOpQrStUvWxYz01"

GENERATED = "KUJIRA42"

RUNNER = r"""
import * as plugin from "./mod.mjs"

const [kase, cwd, session] = JSON.parse(process.argv[2])

const BODY = ["Goal", "Constraints", "State", "Evidence", "Next", "Refs"]
  .map((s) => `## ${s}\n\nKUJIRA42\n`)
  .join("\n")

// lint が重複として落とす生成。文字列を含むかどうかだけでは見分けられない。
const DUPLICATED = `${BODY}\n## Refs\n\nKUJIRA42\n`

// 「## Evidence」が文中にしか無い生成。
const INLINE = BODY.replace("## Evidence\n\nKUJIRA42\n", "本文中に ## Evidence と書いただけ\n")

// 予算 (2000 文字) を超えるが見出しは正しい生成。
const LONG = BODY.replace("## State\n\nKUJIRA42\n", `## State\n\nKUJIRA42 ${"x".repeat(3000)}\n`)

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
  system: (event?.system ?? []).map((s) => String(s.text)),
  summary: event?.result?.summary ?? null,
  generateCalls: ctx._calls.length,
})

const ended = { type: "session.compaction.ended", data: { sessionID: session } }
const failed = { type: "session.compaction.failed", data: { sessionID: session } }

const cases = {
  // 成功した圧縮で、その回に記録を保存できていれば印を置く。
  "watch-ended": async () => {
    const ctx = makeCtx([ended])
    await ctx.storage.set(plugin.savedKey(session), { at: "x" })
    await plugin.watchCompaction(ctx)
    return dump(ctx)
  },
  // 記録を保存できなかった圧縮では、成功しても印を置かない。
  "watch-ended-without-record": async () => {
    const ctx = makeCtx([ended])
    await plugin.watchCompaction(ctx)
    return dump(ctx)
  },
  // 生成に失敗した圧縮の後は、以前の記録を注入しない (通しの流れ)。
  "failed-generation-then-ended": async () => {
    const ctx = makeCtx([ended], [])
    await ctx.storage.set(plugin.savedKey(session), { at: "前回の圧縮" })
    await plugin.onCompaction(ctx, { sessionID: session }, cwd)
    await plugin.watchCompaction(ctx)
    const event = { sessionID: session, system: [], messages: [{ role: "user" }] }
    await plugin.onContext(ctx, event, cwd)
    return dump(ctx, event)
  },
  // 生成に成功した圧縮の後は注入する (通しの流れ)。
  "generated-then-ended": async () => {
    const ctx = makeCtx([ended], [BODY])
    await plugin.onCompaction(ctx, { sessionID: session }, cwd)
    await plugin.watchCompaction(ctx)
    const event = { sessionID: session, system: [], messages: [{ role: "user" }] }
    await plugin.onContext(ctx, event, cwd)
    return dump(ctx, event)
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
  // 見出しが重複した生成物は、引き直しても採用しない。
  "compaction-rejects-duplicated-headings": async () => {
    const ctx = makeCtx([], [DUPLICATED, DUPLICATED])
    const event = { sessionID: session }
    await plugin.onCompaction(ctx, event, cwd)
    return dump(ctx, event)
  },
  // 見出しの文字列が文中にあるだけの生成物は採用しない。
  "compaction-rejects-inline-headings": async () => {
    const ctx = makeCtx([], [INLINE, INLINE])
    const event = { sessionID: session }
    await plugin.onCompaction(ctx, event, cwd)
    return dump(ctx, event)
  },
  // lint に通らない生成は、空と同じく 1 度だけ引き直す。
  "compaction-retries-after-a-rejected-body": async () => {
    const ctx = makeCtx([], [DUPLICATED, BODY])
    const event = { sessionID: session }
    await plugin.onCompaction(ctx, event, cwd)
    return dump(ctx, event)
  },
  // 予算超過は受け入れを妨げない。
  "compaction-accepts-an-over-budget-body": async () => {
    const ctx = makeCtx([], [LONG])
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


def record(session: str, word: str) -> str:
    """ヘッダ付きの正常な記録。word は記録にしか無い合言葉。"""
    sections = "\n".join(
        f"## {s}\n\n{word}\n"
        for s in ("Goal", "Constraints", "State", "Evidence", "Next", "Refs")
    )
    return (
        f"<!-- checkpoint: v1\n     session: {session}\n     cli: opencode\n"
        f"     updated_at: 2026-01-01T00:00:00Z\n     covered_through: msg-1\n-->\n"
        f"# Checkpoint — test\n\n{sections}"
    )


def resolve(repo: Path, session: str) -> dict:
    done = subprocess.run(
        [sys.executable, str(CLI), "paths", "--session", session, "--cwd", str(repo)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(done.stdout)


def seed(repo: Path, session: str, text: str) -> Path:
    """session の保存先へ text を置く。"""
    target = Path(resolve(repo, session)["checkpoint"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """テストごとに独立した使い捨てのリポジトリ。記録は置かない。"""
    root = tmp_path / "repo"
    root.mkdir()
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
    return root


@pytest.fixture(scope="module")
def runner(tmp_path_factory) -> tuple[str, Path]:
    """plugin を読み込む node 側の置き場。状態を持たないので共有してよい。"""
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
    return node, work


@pytest.fixture
def call(runner, repo):
    node, work = runner

    def run(kase: str, session: str = SESSION) -> dict:
        done = subprocess.run(
            [node, str(work / "run.mjs"), json.dumps([kase, str(repo), session])],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        return json.loads(done.stdout)

    return run


def test_only_a_completed_compaction_sets_the_marker(call):
    assert call("watch-ended")["keys"] == [f"pending:{SESSION}"]


def test_a_compaction_without_a_saved_record_sets_no_marker(call):
    """記録を保存できなかった回は、圧縮が成功しても注入の印を置かない。"""
    assert call("watch-ended-without-record")["keys"] == []


def test_a_failed_generation_does_not_inject_an_older_record(call, repo):
    """★生成に失敗して標準の要約に戻った回に、以前の記録を渡さない。

    以前は保存先に残る古い記録を「圧縮前に保存した引き継ぎ」として注入していた。
    """
    seed(repo, SESSION, record(SESSION, "OLDRECORD"))

    result = call("failed-generation-then-ended")

    assert result["summary"] is None
    assert result["system"] == []
    assert result["keys"] == []


def test_a_generated_record_is_injected_after_the_compaction(call):
    result = call("generated-then-ended")
    assert len(result["system"]) == 1
    assert GENERATED in result["system"][0]
    assert result["keys"] == []


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


def test_the_record_is_generated_and_becomes_the_summary(call, repo):
    """★圧縮の要約と引き継ぎを一本化する。

    別々に持つと必ず片方が古くなる（実際に意味内容だけ 1 日古いまま残った）。
    ``e.result`` を設定すると OpenCode は自前の要約生成を飛ばす（実測）。
    """
    result = call("compaction-generates-the-record")
    assert result["generateCalls"] == 1
    summary = result["summary"]
    assert summary is not None
    for heading in ("Goal", "Constraints", "State", "Evidence", "Next", "Refs"):
        assert f"## {heading}\n\n{GENERATED}" in summary
    assert f"session: {SESSION}" in summary
    # 機械節も同じ成果物に入る
    assert "## Snapshot" in summary
    # 要約と保存した記録は同じもの
    saved = Path(resolve(repo, SESSION)["checkpoint"]).read_text(encoding="utf-8")
    assert summary == saved
    # 注入の印は圧縮の成功イベントで置く。ここでは「保存できた」印だけ
    assert result["keys"] == [f"saved:{SESSION}"]


def test_an_empty_generation_is_retried_once(call):
    """★空が返ることがある（実測: 同じプロンプトで通ったり空だったり）。"""
    result = call("compaction-retries-once")
    assert result["generateCalls"] == 2
    assert result["summary"] is not None
    assert GENERATED in result["summary"]


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


@pytest.mark.parametrize(
    "case",
    ["compaction-rejects-duplicated-headings", "compaction-rejects-inline-headings"],
)
def test_a_body_that_fails_lint_is_not_adopted(call, repo, case):
    """★受け入れ判定を CLI の lint に揃える。

    旧実装は「`## Goal` などの文字列を含むか」だけを見ていて、見出しが重複した
    生成や、文中に見出しの文字列があるだけの生成を要約に採用していた。
    採用しない生成は保存もしない。
    """
    result = call(case)

    assert result["generateCalls"] == 2
    assert result["summary"] is None
    saved = Path(resolve(repo, SESSION)["checkpoint"]).read_text(encoding="utf-8")
    assert GENERATED not in saved


def test_a_body_that_fails_lint_is_retried_once(call):
    result = call("compaction-retries-after-a-rejected-body")
    assert result["generateCalls"] == 2
    assert result["summary"] is not None
    assert result["summary"].count("## Refs") == 1


def test_an_over_budget_body_is_still_adopted(call):
    """★予算超過では捨てない。捨てると新しい引き継ぎより古い記録が残る。"""
    result = call("compaction-accepts-an-over-budget-body")
    assert result["generateCalls"] == 1
    assert result["summary"] is not None
    assert GENERATED in result["summary"]


def test_a_failed_write_does_not_adopt_the_old_record(call, repo):
    """★書き込みに失敗したら、残っていた古い記録を要約にしない。

    古い正常な記録を置いたうえで、``--keep-prev`` の先をディレクトリにして
    write を失敗させる。成否を見ずに読み直すと古い記録が要約に化ける。
    """
    old = record(SESSION, "OLDREC77")
    target = seed(repo, SESSION, old)
    Path(resolve(repo, SESSION)["prev"]).mkdir()

    result = call("compaction-generates-the-record")

    assert result["generateCalls"] == 1
    assert result["summary"] is None
    # 古い記録の意味内容は残っている（機械節だけは生成前に更新される）
    kept = target.read_text(encoding="utf-8").partition("<!-- machine:")[0]
    assert kept.strip() == old.strip()
    assert GENERATED not in kept


def test_the_record_reaches_a_user_turn_and_is_then_consumed(call, repo):
    text = record(SESSION, "UMIHEBI3")
    seed(repo, SESSION, text)

    result = call("context-user-turn")

    assert len(result["system"]) == 1
    injected = result["system"][0]
    assert "圧縮" in injected
    assert text.strip() in injected
    assert result["keys"] == []


def test_mid_turn_requests_get_the_record_but_keep_the_marker(call, repo):
    """★欠陥 B の再発防止。

    圧縮の直後に走るのは内部の継続要求のことがある。そこで消すと、次に
    ユーザが話しかけたときには残っていない (実測)。入れるが消さない。
    """
    text = record(SESSION, "UMIHEBI3")
    seed(repo, SESSION, text)

    result = call("context-mid-turn")

    assert len(result["system"]) == 1
    assert text.strip() in result["system"][0]
    assert result["keys"] == [f"pending:{SESSION}"]


def test_without_a_marker_nothing_is_injected(call, repo):
    seed(repo, SESSION, record(SESSION, "UMIHEBI3"))
    result = call("context-no-marker")
    assert result["system"] == []
    assert result["keys"] == []


def test_a_neighboring_session_does_not_get_this_record(call, repo):
    """★近い時刻に作られた別セッションへ、この記録を注入しない。

    旧実装は英数字の先頭 8 文字を保存名にしていて、2 つが同じファイルを読んだ。
    """
    seed(repo, SESSION, record(SESSION, "UMIHEBI3"))

    result = call("context-user-turn", session=NEIGHBOR)

    assert result["system"] == []


def test_a_record_owned_by_another_session_is_not_injected(call, repo):
    """★保存先に別セッションの記録があっても読まない（ヘッダで照合する）。"""
    seed(repo, NEIGHBOR, record(SESSION, "UMIHEBI3"))

    result = call("context-user-turn", session=NEIGHBOR)

    assert result["system"] == []
