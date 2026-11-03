"""pr-inbox.ts (PR レビューの受信箱 S2: 通知 + take + off) の試験。

時計・タイマー・UI は偽物を注入して決定的に回す (実時間に頼らない)。リポジトリは架空の名前の実際の git の ref。
アプリ側の書き込みは、共有ライブラリ (review-git.ts) で直接イベントを追記して真似る。

see docs/change/0061-pr-inbox.md
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "home" / "dot_config" / "pi" / "harness"

PRELUDE = f"""
import * as I from {json.dumps((HARNESS / "pr-inbox.ts").as_uri())};
import * as P from {json.dumps((HARNESS / "pr-review.ts").as_uri())};
import * as L from {json.dumps((HARNESS / "review-log.ts").as_uri())};
import * as G from {json.dumps((HARNESS / "review-git.ts").as_uri())};
import {{ randomUUID }} from "node:crypto";

const cwd = process.argv[2];
const arg = JSON.parse(process.argv[3] || "null");
const out = (x) => process.stdout.write(JSON.stringify(x));
const git = P.gitIn(cwd);
const now = () => "2026-01-01T00:00:00Z";
const tick = () => new Promise((r) => setImmediate(r));

// 偽のタイマー (手で回す)。fire は生きているものだけ、fireAll は閉じたものも呼ぶ (世代の確認用)
const ivs = [];
const timers = {{
	setInterval: (fn, ms) => {{ const t = {{ fn, ms, cleared: false, unref() {{ this.unrefed = true; }} }}; ivs.push(t); return t; }},
	clearInterval: (t) => {{ t.cleared = true; }},
}};
const active = () => ivs.filter((t) => !t.cleared);
const fire = async () => {{ for (const t of active()) await t.fn(); }};
const fireAll = async () => {{ for (const t of ivs) await t.fn(); }};

// 偽の ctx・pi。呼ばれた副作用を記録する
const mkEnv = (over = {{}}) => {{
	const calls = {{ status: [], notify: [], sent: [], bell: 0 }};
	const ctx = {{
		cwd, hasUI: true, mode: "tui", isIdle: () => true,
		ui: {{ setStatus: (k, v) => calls.status.push([k, v]), notify: (m, l) => calls.notify.push([m, l]) }},
		...over,
	}};
	const commands = {{}};
	const handlers = {{}};
	const pi = {{
		sendMessage: (m, o) => calls.sent.push([m, o]),
		registerCommand: (n, c) => (commands[n] = c),
		on: (ev, fn) => (handlers[ev] = fn),
	}};
	return {{ calls, ctx, pi, commands, handlers }};
}};

// git の呼び出しを数える (wrap で差し込める)
const mkGit = (wrap) => {{
	const log = [];
	const g2 = async (argv, opts) => {{
		log.push(argv);
		return wrap ? wrap(argv, opts) : git(argv, opts);
	}};
	return {{ log, g2 }};
}};
const isRead = (a) => a[0] === "rev-parse" && a.includes("--verify") && String(a.at(-1)).startsWith("refs/pi/review/");
const reads = (log) => log.filter(isRead).length;
const lists = (log) => log.filter((a) => a[0] === "for-each-ref").length;

const mkInbox = (g2, over = {{}}) => {{
	const env = over.env ?? mkEnv();
	const inbox = I.createInbox({{
		gitFor: () => g2, now, sessionId: () => "sess-1", defer: (f) => f(), pollMs: 5000, timers,
		bell: () => env.calls.bell++, ...over.deps,
	}});
	return {{ inbox, env }};
}};

const O = (c) => c.repeat(40);
const KEY = L.prKeyOf("feature/x");
const KEY2 = L.prKeyOf("feature/y");
const VS = async () => {{
	const rp = async (r) => (await git(["rev-parse", r])).stdout.trim();
	const source = await rp("refs/heads/feature/x");
	const target = await rp("refs/heads/develop");
	const base = (await git(["merge-base", target, source])).stdout.trim();
	return {{ source, target, base }};
}};
const metaOf = (key, branch) => ({{ schema: 1, pr: key, branch, target: "develop", createdAt: "2026-01-01T00:00:00Z" }});
const ev = (t, d, vs, o = {{}}) => ({{ v: 1, id: o.id ?? randomUUID(), t, by: o.by ?? "app", at: "2026-01-01T00:00:00Z", vs, d }});
const appSend = async (bodies, key = KEY, branch = "feature/x") => {{
	const vs = await VS();
	const comments = bodies.map((b) => ev("comment", {{ thread: "", anchor: null, body: b }}, vs));
	for (const c of comments) c.d.thread = c.id;
	const submit = ev("submit", {{
		batchId: randomUUID(), kind: "changes", items: comments.map((c) => c.id),
		dest: {{ worktreeId: P.worktreeIdOf(cwd) }},
	}}, vs);
	const res = await G.appendEvents(git, key, metaOf(key, branch), () => [...comments, submit]);
	if (!("commit" in res)) throw new Error("appSend failed: " + JSON.stringify(res));
	return {{ comments, submit }};
}};
const state = async (key = KEY) => {{
	const r = await G.readPr(git, key);
	return r.kind === "ok" ? L.foldState(r.meta, r.events, r.events.at(-1)?.vs ?? await VS()) : r;
}};
const refList = async () => (await git(["for-each-ref", "--format=%(objectname) %(refname)", "refs/pi/review/"])).stdout;
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

GENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Test User",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test User",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
}


def g(repo, *args, input=None):
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        input=input,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=GENV,
        check=False,
    )
    assert proc.returncode == 0, (args, proc.stderr)
    return proc.stdout.strip()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "example-app"
    r.mkdir()
    g(r, "init", "-q", "-b", "develop")
    (r / "a.txt").write_text("1\n", encoding="utf-8")
    g(r, "add", ".")
    g(r, "commit", "-q", "-m", "init")
    g(r, "switch", "-q", "-c", "feature/x")
    (r / "a.txt").write_text("1\n2\n", encoding="utf-8")
    g(r, "commit", "-q", "-am", "feat: x")
    g(r, "switch", "-q", "develop")
    return r


@pytest.fixture
def js(tmp_path):
    n = [0]

    def _js(repo, body, arg=None):
        n[0] += 1
        script = tmp_path / f"t{n[0]}.mjs"
        script.write_text(
            PRELUDE
            + "\n(async () => {\n"
            + body
            + "\n})().catch((e) => { console.error(e); process.exit(1); });\n",
            encoding="utf-8",
        )
        proc = subprocess.run(
            [_node(), str(script), str(repo), json.dumps(arg)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr[-3000:]
        return json.loads(proc.stdout)

    return _js


# ─── 1. oid キャッシュ ──────────────────────────────────────────────


def test_unchanged_oid_is_not_reread_and_first_tick_reads_all(repo, js):
    r = js(
        repo,
        """
        await appSend(["a"]);
        await appSend(["b"], KEY2, "feature/y");
        const { log, g2 } = mkGit();
        const { inbox, env } = mkInbox(g2);
        await inbox.start(env);
        const first = reads(log);
        await fire(); await fire();
        const afterIdle = reads(log);
        await appSend(["c"]);
        await fire();
        out({ first, afterIdle, afterChange: reads(log), lists: lists(log) });
        """,
    )
    assert r["first"] == 2  # 初回は全 PR を読む
    assert r["afterIdle"] == 2  # oid が同じなら読み直さない
    assert r["afterChange"] == 3  # 変わったキーだけ読む
    assert r["lists"] == 4  # tick ごとに for-each-ref は 1 回


# ─── 2. 通知は件数が増えたときだけ ──────────────────────────────────


def test_notifies_only_when_the_count_increases_and_clears_at_zero(repo, js):
    r = js(
        repo,
        """
        await appSend(["a"]);
        const { g2 } = mkGit();
        const { inbox, env } = mkInbox(g2);
        await inbox.start(env);
        const c1 = { notify: env.calls.notify.length, bell: env.calls.bell, status: env.calls.status.slice() };
        await fire(); await fire();
        const same = { notify: env.calls.notify.length, bell: env.calls.bell, status: env.calls.status.length };
        await appSend(["b"]);
        await fire();
        const up = { notify: env.calls.notify.length, bell: env.calls.bell, last: env.calls.status.at(-1) };
        await inbox.take(env);
        const afterTake = env.calls.status.at(-1);
        await fire();
        const zero = { last: env.calls.status.at(-1), notify: env.calls.notify.length, bell: env.calls.bell };
        out({ c1, same, up, afterTake, zero, texts: env.calls.notify.map((n) => n[0]) });
        """,
    )
    assert r["c1"]["notify"] == 1 and r["c1"]["bell"] == 1
    assert r["c1"]["status"] == [["pr-inbox", "📨 レビュー 1 件"]]
    assert r["same"] == {"notify": 1, "bell": 1, "status": 1}  # 同じ件数では何も出ない
    assert r["up"]["notify"] == 2 and r["up"]["bell"] == 2
    assert r["up"]["last"] == ["pr-inbox", "📨 レビュー 2 件"]
    assert r["afterTake"] == [
        "pr-inbox",
        None,
    ]  # take の直後にバッジを更新する (次の tick を待たない)
    assert r["zero"]["last"] == ["pr-inbox", None]  # 0 でバッジが消える
    assert r["zero"]["notify"] == 2 and r["zero"]["bell"] == 2  # 減ったときは通知しない
    assert "/pr inbox take" in r["texts"][0]


def test_no_bell_outside_the_tui(repo, js):
    r = js(
        repo,
        """
        await appSend(["a"]);
        const { g2 } = mkGit();
        const env = mkEnv({ mode: "print" });
        const { inbox } = mkInbox(g2, { env });
        await inbox.start(env);
        out({ bell: env.calls.bell, notify: env.calls.notify.length });
        """,
    )
    assert r == {"bell": 0, "notify": 1}


# ─── 3. ポーリングは ref を書かない ────────────────────────────────


def test_polling_never_writes_a_ref(repo, js):
    r = js(
        repo,
        """
        await appSend(["a"]);
        await appSend(["b"], KEY2, "feature/y");
        const before = await refList();
        const { g2 } = mkGit();
        const { inbox, env } = mkInbox(g2);
        await inbox.start(env);
        await fire(); await fire(); await fire();
        out({ same: before === (await refList()), unreceived: (await state()).batches.every((b) => !b.received) });
        """,
    )
    assert r == {"same": True, "unreceived": True}


# ─── 4. 読み取りの失敗は再試行 ─────────────────────────────────────


def test_a_failed_read_is_not_remembered_and_is_retried(repo, js):
    r = js(
        repo,
        """
        await appSend(["a"]);
        let fail = true;
        const { log, g2 } = mkGit(async (argv, opts) => {
          if (fail && isRead(argv)) return { code: 128, stdout: "", stderr: "boom" };
          return git(argv, opts);
        });
        const { inbox, env } = mkInbox(g2);
        await inbox.start(env);
        const afterFail = { reads: reads(log), notify: env.calls.notify.length };
        fail = false;
        await fire();
        const afterRetry = { reads: reads(log), notify: env.calls.notify.length };
        await fire();
        out({ afterFail, afterRetry, final: reads(log) });
        """,
    )
    assert r["afterFail"] == {"reads": 1, "notify": 0}
    assert r["afterRetry"] == {"reads": 2, "notify": 1}
    assert r["final"] == 2  # 成功したら覚える


def test_a_removed_key_leaves_the_candidates(repo, js):
    r = js(
        repo,
        """
        await appSend(["a"]);
        const { g2 } = mkGit();
        const { inbox, env } = mkInbox(g2);
        await inbox.start(env);
        const before = inbox.status().unread;
        await git(["update-ref", "-d", "refs/pi/review/" + KEY]);
        await fire();
        out({ before, after: inbox.status().unread, last: env.calls.status.at(-1) });
        """,
    )
    assert r == {"before": 1, "after": 0, "last": ["pr-inbox", None]}


# ─── 5. take ────────────────────────────────────────────────────────


def test_take_claims_and_sends_once_idle_then_follow_up(repo, js):
    r = js(
        repo,
        """
        await appSend(["本文-A"]);
        const { g2 } = mkGit();
        const { inbox, env } = mkInbox(g2);
        await inbox.take(env);
        const first = env.calls.sent.slice();
        await inbox.take(env);
        const second = { sent: env.calls.sent.length, notify: env.calls.notify.at(-1) };
        await appSend(["本文-B"]);
        env.ctx.isIdle = () => false;
        await inbox.take(env);
        out({ first, second, running: env.calls.sent.at(-1), received: (await state()).batches.map((b) => !!b.received) });
        """,
    )
    assert len(r["first"]) == 1
    msg, opts = r["first"][0]
    assert (
        msg["customType"] == "pr-review" and msg["display"] is True and "本文-A" in msg["content"]
    )
    assert opts == {"triggerTurn": True}
    assert r["second"]["sent"] == 1 and "取り込める新着はありません" in r["second"]["notify"][0]
    assert r["running"][1] == {"deliverAs": "followUp"} and "本文-B" in r["running"][0]["content"]
    assert r["received"] == [True, True]


def test_take_and_the_existing_injection_never_consume_twice(repo, js):
    r = js(
        repo,
        """
        await appSend(["only-once"]);
        const { g2 } = mkGit();
        const { inbox, env } = mkInbox(g2);
        const [, injected] = await Promise.all([inbox.take(env), P.collectInjection(git, "other", now)]);
        const texts = [...env.calls.sent.map((s) => s[0].content), injected].filter((t) => t && t.includes("only-once"));
        const s = await state();
        out({ texts: texts.length, receipts: s.batches.filter((b) => b.received).length });
        """,
    )
    assert r == {"texts": 1, "receipts": 1}


def test_take_tells_the_user_when_sending_fails_after_the_receipt(repo, js):
    r = js(
        repo,
        """
        await appSend(["a"]);
        const { g2 } = mkGit();
        const env = mkEnv();
        env.pi.sendMessage = () => { throw new Error("send failed"); };
        const { inbox } = mkInbox(g2, { env });
        await inbox.take(env);
        out({ notify: env.calls.notify, received: (await state()).batches[0].received != null });
        """,
    )
    assert r["received"] is True
    assert any("失敗" in n[0] and n[1] == "error" for n in r["notify"])


# ─── 6. 開始は冪等 ──────────────────────────────────────────────────


def test_start_is_idempotent_and_stop_ends_ticks(repo, js):
    r = js(
        repo,
        """
        await appSend(["a"]);
        const { log, g2 } = mkGit();
        const { inbox, env } = mkInbox(g2);
        await inbox.start(env);
        await inbox.start(env);
        const activeAfterTwo = active().length;
        const unrefed = active().every((t) => t.unrefed === true) && active()[0].ms === 5000;
        const base = lists(log);
        await fire();
        const perFire = lists(log) - base;
        inbox.stop();
        const afterStop = { active: active().length };
        const b2 = lists(log);
        await fireAll();
        out({ activeAfterTwo, unrefed, perFire, afterStop, ticksAfterStop: lists(log) - b2 });
        """,
    )
    assert r["activeAfterTwo"] == 1 and r["unrefed"] is True
    assert r["perFire"] == 1
    assert r["afterStop"] == {"active": 0} and r["ticksAfterStop"] == 0


def test_a_tick_that_is_still_running_is_not_started_twice(repo, js):
    r = js(
        repo,
        """
        await appSend(["a"]);
        let release; const gate = new Promise((r) => (release = r));
        let reached; const hit = new Promise((r) => (reached = r));
        const { log, g2 } = mkGit(async (argv, opts) => {
          if (argv[0] === "for-each-ref") { reached(); await gate; }
          return git(argv, opts);
        });
        const { inbox, env } = mkInbox(g2);
        const p1 = inbox.start(env);
        await hit;
        const p2 = fire();
        const p3 = fire();
        await tick();
        const during = lists(log);
        release();
        await p1; await p2; await p3;
        out({ during, total: lists(log) });
        """,
    )
    assert r == {
        "during": 1,
        "total": 1,
    }  # 実行中の tick がある間、タイマーが鳴っても重ねて始めない


# ─── 7. 世代 ────────────────────────────────────────────────────────


def test_an_old_tick_does_not_notify_after_stop_and_restart(repo, js):
    r = js(
        repo,
        """
        await appSend(["a"]);
        let release; const gate = new Promise((r) => (release = r));
        let reached; const hit = new Promise((r) => (reached = r));
        let slow = true;
        const { g2 } = mkGit(async (argv, opts) => {
          if (slow && argv[0] === "for-each-ref") { slow = false; reached(); await gate; }
          return git(argv, opts);
        });
        const env1 = mkEnv();
        let bells = 0;
        const { inbox } = mkInbox(g2, { env: env1, deps: { bell: () => bells++ } });
        const p1 = inbox.start(env1);
        await hit;
        inbox.stop();
        const env2 = mkEnv();
        await inbox.start(env2);
        release();
        await p1;
        await tick();
        out({ old: env1.calls, fresh: { notify: env2.calls.notify.length, bell: bells } });
        """,
    )
    assert r["old"]["notify"] == [] and r["old"]["bell"] == 0
    assert [s for s in r["old"]["status"] if s[1] is not None] == []
    assert r["fresh"] == {"notify": 1, "bell": 1}  # 通知は新しい世代の 1 回だけ


def test_an_old_tick_does_not_overwrite_the_state_of_the_new_generation(repo, js):
    r = js(
        repo,
        """
        await appSend(["a"]);
        let release; const gate = new Promise((r) => (release = r));
        let reached; const hit = new Promise((r) => (reached = r));
        let slow = true;
        const { g2 } = mkGit(async (argv, opts) => {
          if (slow && isRead(argv)) { slow = false; reached(); await gate; }
          return git(argv, opts);
        });
        const env1 = mkEnv();
        const { inbox } = mkInbox(g2, { env: env1 });
        const p1 = inbox.start(env1);
        await hit;
        inbox.stop();
        const env2 = mkEnv();
        await inbox.start(env2);
        await appSend(["b"]);
        release();
        await p1; await tick();
        const before = env2.calls.notify.length;
        await fire();
        out({ before, after: env2.calls.notify.length, last: env2.calls.status.at(-1), unread: inbox.status().unread });
        """,
    )
    # 旧世代の tick が、新世代の「前回の件数」やキャッシュを書き換えると、新世代が 2 件目を見逃す
    assert r["before"] == 1 and r["after"] == 2, r
    assert r["last"] == ["pr-inbox", "📨 レビュー 2 件"] and r["unread"] == 2


# ─── 8. 古い ctx ────────────────────────────────────────────────────


def test_a_stale_ctx_stops_the_timer_quietly(repo, js):
    r = js(
        repo,
        """
        await appSend(["a"]);
        const { g2 } = mkGit();
        const env = mkEnv();
        env.ctx.ui.setStatus = () => { throw new Error("This extension ctx is stale after session replacement or reload"); };
        const { inbox } = mkInbox(g2, { env });
        await inbox.start(env);
        out({ active: active().length, all: ivs.length });
        """,
    )
    assert r == {"active": 0, "all": 1}


# ─── 9. 登録 (off が既定・非 TUI・子) ──────────────────────────────


def test_child_registers_nothing_and_off_is_the_default(repo, js):
    r = js(
        repo,
        """
        const child = mkEnv();
        I.registerPrInbox(child.pi, { child: true, defer: (f) => f(), timers });
        const e = mkEnv();
        I.registerPrInbox(e.pi, { child: false, defer: (f) => f(), timers, now, sessionId: () => "s" });
        const registered = { commands: Object.keys(e.commands), handlers: Object.keys(e.handlers).sort() };
        await e.handlers.session_start({ reason: "startup" }, e.ctx);
        const afterStart = active().length;
        // 非 TUI では on にしてもポーリングを始めない
        const nui = mkEnv({ hasUI: false });
        await e.commands.pr.handler("inbox on", nui.ctx);
        const nonTui = active().length;
        await e.commands.pr.handler("inbox on", e.ctx);
        const on = active().length;
        await e.handlers.session_start({ reason: "new" }, e.ctx);
        const afterSecondStart = active().length;
        await e.commands.pr.handler("inbox off", e.ctx);
        const off = { active: active().length, last: e.calls.status.at(-1) };
        await e.commands.pr.handler("inbox on", e.ctx);
        await e.handlers.session_shutdown({}, e.ctx);
        out({ child: { commands: Object.keys(child.commands), handlers: Object.keys(child.handlers) },
              registered, afterStart, nonTui, on, afterSecondStart, off, afterShutdown: active().length });
        """,
    )
    assert r["child"] == {"commands": [], "handlers": []}
    assert r["registered"] == {
        "commands": ["pr"],
        "handlers": ["session_shutdown", "session_start"],
    }
    assert (r["afterStart"], r["nonTui"], r["on"], r["afterSecondStart"]) == (0, 0, 1, 1)
    assert r["off"] == {"active": 0, "last": ["pr-inbox", None]}
    assert r["afterShutdown"] == 0


# ─── review 指摘: 世代・再開始・take の無効化 ────────────────────────────


def test_an_old_tick_failing_to_find_the_worktree_does_not_blind_the_new_generation(repo, js):
    r = js(
        repo,
        """
        await appSend(["a"]);
        let release1; const gate1 = new Promise((r) => (release1 = r));
        let reached1; const hit1 = new Promise((r) => (reached1 = r));
        let release2; const gate2 = new Promise((r) => (release2 = r));
        let reached2; const hit2 = new Promise((r) => (reached2 = r));
        let tops = 0; let lists = 0;
        const { g2 } = mkGit(async (argv, opts) => {
          if (argv[0] === "rev-parse" && argv.includes("--show-toplevel") && ++tops === 1) {
            reached1(); await gate1; return { code: 1, stdout: "", stderr: "" };
          }
          if (argv[0] === "for-each-ref" && ++lists === 1) { reached2(); await gate2; }
          return git(argv, opts);
        });
        const env1 = mkEnv();
        const { inbox } = mkInbox(g2, { env: env1 });
        const p1 = inbox.start(env1);
        await hit1;
        inbox.stop();
        const env2 = mkEnv();
        const p2 = inbox.start(env2);
        await hit2;
        release1(); await p1; await tick();
        release2(); await p2; await tick();
        out({ notify: env2.calls.notify.length, last: env2.calls.status.at(-1) });
        """,
    )
    # 旧世代の「作業ツリーを見つけられない」結果が、新世代の宛先を消すと、新着を見失う
    assert r == {"notify": 1, "last": ["pr-inbox", "📨 レビュー 1 件"]}


def test_an_old_tick_with_a_stale_listing_does_not_wipe_the_new_generation(repo, js):
    r = js(
        repo,
        """
        let release; const gate = new Promise((r) => (release = r));
        let reached; const hit = new Promise((r) => (reached = r));
        let slow = true;
        const { g2 } = mkGit(async (argv, opts) => {
          if (slow && argv[0] === "for-each-ref") {
            slow = false;
            const res = await git(argv, opts); // 空の一覧を受け取ってから止まる
            reached(); await gate; return res;
          }
          return git(argv, opts);
        });
        const env1 = mkEnv();
        const { inbox } = mkInbox(g2, { env: env1 });
        const p1 = inbox.start(env1);
        await hit;
        inbox.stop();
        await appSend(["a"]);
        const env2 = mkEnv();
        await inbox.start(env2);
        release(); await p1; await tick();
        await fire();
        out({ notify: env2.calls.notify.length, last: env2.calls.status.at(-1), unread: inbox.status().unread });
        """,
    )
    # 古い一覧 (空) が新世代のキャッシュや件数を消していると、次の tick で同じレビューをもう一度通知する
    assert r == {"notify": 1, "last": ["pr-inbox", "📨 レビュー 1 件"], "unread": 1}


def test_restarting_keeps_the_notified_count_but_off_then_on_notifies_again(repo, js):
    r = js(
        repo,
        """
        await appSend(["a"]);
        const { g2 } = mkGit();
        const { inbox, env } = mkInbox(g2);
        await inbox.start(env);
        await inbox.start(env); // new_session で session_start が 2 回来る
        const twice = { notify: env.calls.notify.length, bell: env.calls.bell, last: env.calls.status.at(-1) };
        inbox.stop(); // /pr inbox off
        await inbox.start(env);
        out({ twice, afterOff: { notify: env.calls.notify.length, bell: env.calls.bell } });
        """,
    )
    # 再開始で同じ件数を再通知しない (バッジは出し直す)。off → on は新たに知らせる
    assert r["twice"] == {"notify": 1, "bell": 1, "last": ["pr-inbox", "📨 レビュー 1 件"]}
    assert r["afterOff"] == {"notify": 2, "bell": 2}


def test_take_across_a_shutdown_neither_claims_nor_notifies_nor_sends(repo, js):
    r = js(
        repo,
        """
        await appSend(["a"]);
        let release; const gate = new Promise((r) => (release = r));
        let reached; const hit = new Promise((r) => (reached = r));
        let slow = false;
        const { g2 } = mkGit(async (argv, opts) => {
          if (slow && argv[0] === "rev-parse" && argv.includes("--show-toplevel")) { slow = false; reached(); await gate; }
          return git(argv, opts);
        });
        const { inbox, env } = mkInbox(g2);
        await inbox.start(env);
        const before = env.calls.notify.length;
        slow = true;
        const p = inbox.take(env);
        await hit;
        inbox.shutdown();
        release();
        await p;
        const st = await state();
        out({ sent: env.calls.sent.length, notify: env.calls.notify.length - before,
              unreceived: st.batches.filter((b) => !b.received).length });
        """,
    )
    # shutdown をまたいだ take は、受領を始めず、通知も送信もしない (受領の記録も残らない)
    assert r == {"sent": 0, "notify": 0, "unreceived": 1}


def test_a_deferred_send_is_dropped_after_a_shutdown_but_kept_after_off(repo, js):
    r = js(
        repo,
        """
        const run = async (how) => {
          await appSend([how]);
          let held = null;
          const { g2 } = mkGit();
          const { inbox, env } = mkInbox(g2, { deps: { defer: (f) => (held = f) } });
          await inbox.start(env);
          await inbox.take(env); // 受領し、送信は保留 (圧縮中)
          if (how === "shutdown") inbox.shutdown(); else inbox.stop();
          held();
          return env.calls.sent.length;
        };
        out({ shutdown: await run("shutdown"), off: await run("off") });
        """,
    )
    # shutdown では古い pi に送らない。利用者が打った take は、その後の off では取り消さない
    assert r == {"shutdown": 0, "off": 1}


def test_take_with_nothing_new_survives_a_stale_ctx(repo, js):
    r = js(
        repo,
        """
        const { g2 } = mkGit();
        const env = mkEnv();
        env.ctx.ui.notify = () => { throw new Error("This extension ctx is stale after session replacement or reload"); };
        const { inbox } = mkInbox(g2, { env });
        let err = null;
        try { await inbox.take(env); } catch (e) { err = String(e); }
        out({ err });
        """,
    )
    assert r == {"err": None}  # 「新着はありません」の通知が古い ctx で失敗しても、例外を投げない


def test_the_shutdown_handler_invalidates_a_running_take(repo, js):
    r = js(
        repo,
        """
        await appSend(["a"]);
        let release; const gate = new Promise((r) => (release = r));
        let reached; const hit = new Promise((r) => (reached = r));
        let slow = false;
        const g2 = async (argv, opts) => {
          if (slow && argv[0] === "rev-parse" && argv.includes("--show-toplevel")) { slow = false; reached(); await gate; }
          return git(argv, opts);
        };
        const e = mkEnv();
        I.registerPrInbox(e.pi, { child: false, defer: (f) => f(), timers, now, sessionId: () => "s", gitFor: () => g2 });
        slow = true;
        const p = e.commands.pr.handler("inbox take", e.ctx);
        await hit;
        await e.handlers.session_shutdown({}, e.ctx);
        release();
        await p;
        out({ sent: e.calls.sent.length, notify: e.calls.notify.length });
        """,
    )
    assert r == {"sent": 0, "notify": 0}


# ─── 10. 圧縮中の保留 ──────────────────────────────────────────────


def test_take_during_compaction_is_sent_after_it(repo, js):
    r = js(
        repo,
        """
        await appSend(["a"]);
        const queue = [];
        const { g2 } = mkGit();
        const { inbox, env } = mkInbox(g2, { deps: { defer: (f) => queue.push(f) } });
        await inbox.take(env);
        const during = env.calls.sent.length;
        for (const f of queue) f();
        out({ during, after: env.calls.sent.length });
        """,
    )
    assert r == {"during": 0, "after": 1}


# ─── 11. 静的 ───────────────────────────────────────────────────────


def test_pr_inbox_has_only_allowed_imports_and_no_network():
    text = (HARNESS / "pr-inbox.ts").read_text(encoding="utf-8")
    imports = re.findall(r"""^\s*import\b[^;]*?from\s+["']([^"']+)["']""", text, re.M)
    assert imports, "import 文が読めていない"
    assert all(
        i.startswith("node:") or i in ("./pr-review.ts", "./review-git.ts", "./review-log.ts")
        for i in imports
    ), imports
    assert not re.search(
        r"node:(http|https|net|http2|dgram)|\bfetch\(|createServer|\.listen\(", text
    )
