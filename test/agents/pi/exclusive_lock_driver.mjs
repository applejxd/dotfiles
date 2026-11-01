// 排他ロック (exclusive-lock.ts) を、使い捨ての git リポジトリで直接動かして固定する。結果を JSON で標準出力へ出す (照合は test_pi_exclusive_lock.py)。
//
//   node test/agents/pi/exclusive_lock_driver.mjs
//
// 競合の試験のため、自分自身を子プロセスとして起動する (--child acquire <JSON>)。
// see docs/change/0055-async-approval.md
import { execFile, execFileSync } from "node:child_process";
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, symlinkSync, writeFileSync } from "node:fs";
import { relative } from "node:path";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const H = resolve(ROOT, "home", "dot_config", "pi", "harness");
const lock = await import(pathToFileURL(resolve(H, "exclusive-lock.ts")).href);
const ops = await import(pathToFileURL(resolve(H, "pending-ops.ts")).href);

const ENV = { ...process.env, GIT_AUTHOR_NAME: "t", GIT_AUTHOR_EMAIL: "t@example.test", GIT_COMMITTER_NAME: "t", GIT_COMMITTER_EMAIL: "t@example.test" };
const git = (cwd, ...args) => execFileSync("git", args, { cwd, env: ENV, encoding: "utf8" }).trim();
const gitIn = (cwd, input, ...args) => execFileSync("git", args, { cwd, env: ENV, encoding: "utf8", input }).trim();
const gitOk = (cwd, ...args) => {
	try {
		return git(cwd, ...args);
	} catch {
		return null;
	}
};

const holder = (n, attempt = `att-${n}`) => ({ runningId: `20260101000${String(n).padStart(4, "0")}`, attemptId: attempt });
const probeOf = (p) => () => p;
const ALIVE = { attempt: "reserved", owner: "alive" };
const RESERVED_GONE = { attempt: "reserved", owner: "gone" };

// ---- 子プロセス ----
// barrier: N 人が probe に入る (= 全員が同じ旧ロックを読み終えた) まで待ってから返す。probe は旧 holder (att-9) だけを回復可能とする
const sleepMs = (ms) => Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
function barrierProbe(dir, n) {
	return (h) => {
		writeFileSync(join(dir, String(process.pid)), "x");
		const until = Date.now() + 20000;
		while (readdirSync(dir).length < n && Date.now() < until) sleepMs(5);
		return h.attemptId === "att-9" ? RESERVED_GONE : ALIVE;
	};
}
if (process.argv[2] === "--child") {
	const a = JSON.parse(process.argv[4]);
	const probe = a.barrier ? barrierProbe(a.barrier.dir, a.barrier.n) : probeOf(a.probe);
	const r = lock.acquireLock(a.cwd, a.holder, { probe, env: ENV });
	console.log(JSON.stringify(r));
	process.exit(0);
}

const child = (args) =>
	new Promise((res) => {
		execFile(process.execPath, [fileURLToPath(import.meta.url), "--child", "acquire", JSON.stringify(args)], { env: ENV, encoding: "utf8" }, (err, stdout) => {
			res(err ? { crash: String(err.message).slice(0, 200) } : JSON.parse(stdout));
		});
	});

function repo() {
	const dir = mkdtempSync(join(tmpdir(), "pi-lock-"));
	git(dir, "init", "-q", "-b", "main");
	writeFileSync(join(dir, "seed.txt"), "seed\n");
	git(dir, "add", "-A");
	git(dir, "commit", "-q", "-m", "seed");
	return dir;
}
const lockRefs = (cwd) => git(cwd, "for-each-ref", "--format=%(refname)", "refs/pi/lock/").split("\n").filter(Boolean);
const keyOf = (cwd) => lock.lockKeyOf(cwd, ENV).key;
const acq = (cwd, h, probe = ALIVE) => lock.acquireLock(cwd, h, { probe: probeOf(probe), env: ENV });
const code = (r) => (r.ok ? "ok" : r.code);

const out = {};

// 1. 取得・解放・二重取得・他者のロックを解放しない
{
	const cwd = repo();
	const a = acq(cwd, holder(1));
	const b = acq(cwd, holder(2));
	const readA = lock.readLock(cwd, keyOf(cwd), ENV);
	const bogus = lock.releaseLock(cwd, { ref: a.handle.ref, oid: "e".repeat(40) }, ENV);
	const foreign = lock.releaseLock(cwd, { ref: "refs/heads/main", oid: git(cwd, "rev-parse", "main") }, ENV);
	const stillHeld = lock.readLock(cwd, keyOf(cwd), ENV).state;
	const rel = lock.releaseLock(cwd, a.handle, ENV);
	const missing = lock.readLock(cwd, keyOf(cwd), ENV).state;
	const relAgain = lock.releaseLock(cwd, a.handle, ENV);
	const c = acq(cwd, holder(3));
	out.basic = {
		a: code(a),
		refUnderLock: a.ok && a.handle.ref === `refs/pi/lock/${keyOf(cwd)}`,
		b: code(b),
		bHolder: b.ok ? null : b.holder,
		readA: readA.state === "held" ? { holder: readA.holder, hasOwner: readA.owner?.pid === process.pid || typeof readA.owner?.pid === "number" } : readA.state,
		bogusRelease: bogus.ok,
		foreignRelease: foreign.ok,
		stillHeld,
		released: rel.ok,
		missing,
		relAgain: relAgain.ok,
		reacquire: code(c),
		mainUnchanged: gitOk(cwd, "rev-parse", "main") !== null && lockRefs(cwd).length === 1,
	};
}

// 2. 同時に取る (別プロセス) → ちょうど 1 つ
{
	const rounds = [];
	for (let round = 0; round < 5; round++) {
		const cwd = repo();
		const rs = await Promise.all([1, 2, 3, 4, 5, 6].map((i) => child({ cwd, holder: holder(i), probe: ALIVE })));
		rounds.push({ oks: rs.filter((r) => r.ok).length, crashes: rs.filter((r) => r.crash).length, others: rs.filter((r) => !r.ok && !r.crash).map((r) => r.code), refs: lockRefs(cwd).length });
	}
	out.race = rounds;
}

// 3. 回復の全分岐 (probe の表)
{
	const table = {};
	for (const attempt of ["reserved", "started", "absent", "mismatch", "unreadable"]) {
		for (const owner of ["alive", "gone", "unknown"]) {
			const cwd = repo();
			const first = acq(cwd, holder(1));
			const before = lock.readLock(cwd, keyOf(cwd), ENV).oid;
			const r = acq(cwd, holder(2), { attempt, owner });
			const after = lock.readLock(cwd, keyOf(cwd), ENV);
			table[`${attempt}/${owner}`] = {
				code: code(r),
				recovered: r.ok ? (r.recovered ?? null) : null,
				kept: first.ok && (r.ok ? after.holder.attemptId === "att-2" : after.oid === before),
			};
		}
	}
	// probe が例外を投げる
	const cwd = repo();
	acq(cwd, holder(1));
	const thrown = lock.acquireLock(cwd, holder(2), { probe: () => { throw new Error("boom"); }, env: ENV });
	table.throws = { code: code(thrown), kept: lock.readLock(cwd, keyOf(cwd), ENV).holder.attemptId === "att-1" };
	// probe には、読み取った保持者が渡る
	let seen = null;
	lock.acquireLock(cwd, holder(2), { probe: (h) => ((seen = h), ALIVE), env: ENV });
	table.probeArg = seen;
	out.recovery = table;
}

// 4. 回復中の競合 (4 プロセスが、同じ旧ロックを読んだのを barrier で確かめてから回復を競う → 1 者だけ)
// probe は旧 holder (att-9) だけ回復可能と答え、新しい保持者には alive を返す。
{
	const rounds = [];
	for (let round = 0; round < 6; round++) {
		const cwd = repo();
		const old = acq(cwd, holder(9));
		const dir = mkdtempSync(join(tmpdir(), "pi-lock-bar-"));
		const rs = await Promise.all([1, 2, 3, 4].map((i) => child({ cwd, holder: holder(i), barrier: { dir, n: 4 } })));
		const w = rs.filter((r) => r.ok);
		const now = lock.readLock(cwd, keyOf(cwd), ENV);
		rounds.push({
			barrierPassed: readdirSync(dir).length === 4,
			oks: w.length,
			recovered: w.filter((r) => r.recovered === "reserved_gone").length,
			crashes: rs.filter((r) => r.crash).length,
			others: rs.filter((r) => !r.ok && !r.crash).map((r) => r.code),
			oldGone: now.state === "held" && now.oid !== old.handle.oid,
			holderIsWinner: w.length === 1 && now.state === "held" && now.oid === w[0].handle.oid,
			refs: lockRefs(cwd).length,
		});
	}
	out.recover_race = rounds;
	// 新しい保持者 (att-1) は、旧 holder 専用に回復可能と答える probe でも奪えない
	const cwd = repo();
	acq(cwd, holder(1));
	const steal = lock.acquireLock(cwd, holder(2), { probe: (h) => (h.attemptId === "att-9" ? RESERVED_GONE : ALIVE), env: ENV });
	out.new_holder_not_stolen = { code: code(steal), kept: lock.readLock(cwd, keyOf(cwd), ENV).holder?.attemptId === "att-1" };
}

// 4b. 古い handle での解放は、新しいロックを消さない (A 取得 → A 解放 → B 取得 → A の古い handle で再解放)
{
	const cwd = repo();
	const a = acq(cwd, holder(1));
	const relA = lock.releaseLock(cwd, a.handle, ENV);
	const b = acq(cwd, holder(2));
	const staleRelease = lock.releaseLock(cwd, a.handle, ENV);
	const now = lock.readLock(cwd, keyOf(cwd), ENV);
	// 回復で奪われた旧 handle も、新しいロックを消さない
	const cwd2 = repo();
	const old = acq(cwd2, holder(9));
	const rec = acq(cwd2, holder(3), RESERVED_GONE);
	const staleAfterRecovery = lock.releaseLock(cwd2, old.handle, ENV);
	const now2 = lock.readLock(cwd2, keyOf(cwd2), ENV);
	out.stale_handle = {
		relA: relA.ok,
		b: code(b),
		staleRelease: staleRelease.ok,
		bStillHeld: now.state === "held" && now.oid === b.handle.oid,
		recovered: rec.ok ? rec.recovered : code(rec),
		staleAfterRecovery: staleAfterRecovery.ok,
		recoveredStillHeld: now2.state === "held" && now2.oid === rec.handle.oid,
	};
}

// 5. 不正・symbolic・読めないロックは消さない
{
	const cases = {};
	const forge = (cwd, files) => {
		const entries = files.map(([n, t]) => `100644 blob ${gitIn(cwd, t, "hash-object", "-w", "--stdin")}\t${n}`).join("\n");
		const tree = gitIn(cwd, `${entries}\n`, "mktree");
		const oid = gitIn(cwd, "forged\n", "commit-tree", tree, "-F", "-");
		git(cwd, "update-ref", `refs/pi/lock/${keyOf(cwd)}`, oid);
		return oid;
	};
	const good = { schema: 1, runningId: "202601010000001", attemptId: "a", owner: { sessionId: "s", runtimeEpoch: "e", pid: 1, processStart: null, host: "h" }, at: new Date().toISOString() };
	const run = (name, setup) => {
		const cwd = repo();
		setup(cwd);
		const ref = `refs/pi/lock/${keyOf(cwd)}`;
		// 「消えていない」は存在ではなく、前後で raw の内容・ OID が同じかで比べる
		const snap = () => JSON.stringify({ raw: existsSync(join(cwd, ".git", ref)) ? readFileSync(join(cwd, ".git", ref), "utf8") : null, oid: gitOk(cwd, "rev-parse", "-q", "--verify", ref) });
		const before = snap();
		const read = lock.readLock(cwd, keyOf(cwd), ENV);
		// 回復できる probe (reserved × gone) を渡しても消えない
		const r = acq(cwd, holder(2), RESERVED_GONE);
		cases[name] = { state: read.state, code: code(r), kept: snap() === before && before !== JSON.stringify({ raw: null, oid: null }), mainSame: gitOk(cwd, "rev-parse", "main") !== null };
		return cwd;
	};
	cases.good_baseline = (() => {
		const cwd = repo();
		forge(cwd, [["lock.json", JSON.stringify(good)]]);
		return { state: lock.readLock(cwd, keyOf(cwd), ENV).state };
	})();
	run("not_json", (cwd) => forge(cwd, [["lock.json", "JSON ではない"]]));
	run("unknown_key", (cwd) => forge(cwd, [["lock.json", JSON.stringify({ ...good, extra: 1 })]]));
	run("bad_running_id", (cwd) => forge(cwd, [["lock.json", JSON.stringify({ ...good, runningId: "../x" })]]));
	run("bad_owner", (cwd) => forge(cwd, [["lock.json", JSON.stringify({ ...good, owner: { pid: "x" } })]]));
	run("bad_schema", (cwd) => forge(cwd, [["lock.json", JSON.stringify({ ...good, schema: 2 })]]));
	run("extra_file", (cwd) => forge(cwd, [["lock.json", JSON.stringify(good)], ["x.txt", "x"]]));
	run("wrong_name", (cwd) => forge(cwd, [["other.json", JSON.stringify(good)]]));
	const mainOf = {};
	run("symbolic", (cwd) => {
		mainOf.before = git(cwd, "rev-parse", "refs/heads/main");
		git(cwd, "symbolic-ref", `refs/pi/lock/${keyOf(cwd)}`, "refs/heads/main");
		mainOf.cwd = cwd;
	});
	cases.symbolic_main_unchanged = git(mainOf.cwd, "rev-parse", "refs/heads/main") === mainOf.before;
	run("missing_object", (cwd) => {
		// 存在しないオブジェクトを指す壊れた ref (loose ref を直接書く)
		const path = join(cwd, ".git", "refs", "pi", "lock");
		mkdirSync(path, { recursive: true });
		writeFileSync(join(path, keyOf(cwd)), `${"1".repeat(40)}\n`);
	});
	const loose = (cwd, text) => {
		const path = join(cwd, ".git", "refs", "pi", "lock");
		mkdirSync(path, { recursive: true });
		writeFileSync(join(path, keyOf(cwd)), text);
	};
	run("dangling_symbolic", (cwd) => git(cwd, "symbolic-ref", `refs/pi/lock/${keyOf(cwd)}`, "refs/heads/nonexistent"));
	run("symbolic_loop", (cwd) => loose(cwd, `ref: refs/pi/lock/${keyOf(cwd)}\n`));
	run("empty_loose", (cwd) => loose(cwd, ""));
	run("garbage_loose", (cwd) => loose(cwd, "not-an-oid\n"));
	run("bad_attempt_id", (cwd) => forge(cwd, [["lock.json", JSON.stringify({ ...good, attemptId: "a b/../c" })]]));
	run("bad_at", (cwd) => forge(cwd, [["lock.json", JSON.stringify({ ...good, at: "yesterday-ish" })]]));
	run("oversize_blob", (cwd) => forge(cwd, [["lock.json", JSON.stringify({ ...good, pad: "x".repeat(20000) })]]));
	out.invalid = cases;
}

// 6. 鍵
{
	const cwd = repo();
	const wt = join(mkdtempSync(join(tmpdir(), "pi-lock-wt-")), "wt");
	git(cwd, "worktree", "add", "-q", "-b", "feature/x", wt);
	const sub = join(cwd, "sub", "deep");
	mkdirSync(sub, { recursive: true });
	const link = join(mkdtempSync(join(tmpdir(), "pi-lock-ln-")), "link");
	symlinkSync(cwd, link);
	const other = repo();
	const k = (p, env = ENV) => lock.lockKeyOf(p, env);
	const base = k(cwd);
	out.keys = {
		shape: /^[0-9a-f]{64}$/.test(base.key),
		linked: k(wt).key === base.key,
		subdir: k(sub).key === base.key,
		symlink: k(link).key === base.key,
		gitDirEnvIgnored: k(cwd, { ...ENV, GIT_DIR: join(other, ".git") }).key === base.key,
		other: k(other).key !== base.key,
		relativeCwd: (() => {
			const rel = relative(process.cwd(), sub);
			const r = k(rel);
			return r.ok && r.key === base.key && !rel.startsWith("/");
		})(),
		bare: (() => {
			const bare = mkdtempSync(join(tmpdir(), "pi-lock-bare-"));
			git(bare, "init", "-q", "--bare");
			const a = acq(bare, holder(1));
			const b = acq(bare, holder(2));
			return { key: k(bare).ok && k(bare).key !== base.key, a: code(a), b: code(b), read: lock.readLock(bare, k(bare).key, ENV).state, rel: a.ok && lock.releaseLock(bare, a.handle, ENV).ok };
		})(),
		sha256: (() => {
			const dir = mkdtempSync(join(tmpdir(), "pi-lock-sha256-"));
			if (gitOk(dir, "init", "-q", "--object-format=sha256", "-b", "main") === null) return null;
			writeFileSync(join(dir, "s.txt"), "s\n");
			git(dir, "add", "-A");
			git(dir, "commit", "-q", "-m", "seed");
			const a = acq(dir, holder(1));
			const b = acq(dir, holder(2));
			const read = lock.readLock(dir, k(dir).key, ENV);
			const rec = acq(dir, holder(3), RESERVED_GONE);
			return { a: code(a), oidLen: a.ok ? a.handle.oid.length : 0, b: code(b), read: read.state, recovered: rec.ok ? rec.recovered : code(rec), rel: rec.ok && lock.releaseLock(dir, rec.handle, ENV).ok };
		})(),
		// 別 worktree から取ったロックは、本体から見える
		sharedLock: (() => {
			const a = acq(wt, holder(1));
			const b = acq(cwd, holder(2));
			return { a: code(a), b: code(b) };
		})(),
	};
}

// 7. hook・署名が動かない
{
	const cwd = repo();
	const hooks = join(cwd, "evil-hooks");
	mkdirSync(hooks);
	const mark = join(cwd, "HOOK-RAN");
	for (const name of ["reference-transaction", "post-commit", "pre-commit", "commit-msg", "prepare-commit-msg"]) {
		writeFileSync(join(hooks, name), `#!/bin/sh\ntouch "${mark}"\nexit 1\n`);
		chmodSync(join(hooks, name), 0o755);
	}
	git(cwd, "config", "core.hooksPath", hooks);
	git(cwd, "config", "commit.gpgsign", "true");
	git(cwd, "config", "gpg.program", "/bin/false");
	const before = { head: git(cwd, "rev-parse", "HEAD"), status: git(cwd, "status", "--porcelain"), heads: git(cwd, "for-each-ref", "refs/heads") };
	const a = acq(cwd, holder(1));
	const rel = a.ok ? lock.releaseLock(cwd, a.handle, ENV) : { ok: false };
	const after = { head: git(cwd, "rev-parse", "HEAD"), status: git(cwd, "status", "--porcelain"), heads: git(cwd, "for-each-ref", "refs/heads") };
	out.safe = { acquired: a.ok, released: rel.ok, hookRan: existsSync(mark), untouched: JSON.stringify(before) === JSON.stringify(after) };
}

// 8. 保留の一覧に混ざらない
{
	const cwd = repo();
	const a = acq(cwd, holder(1));
	const p = ops.saveOp(cwd, { action: "git_integrate", params: { source: "feature/x" }, premise: {}, reason: "timeout", request: { id: "r", sessionId: "s", cwd: "/w" }, createdAt: new Date().toISOString() });
	const list = ops.listOps(cwd);
	out.list = { acquired: a.ok, entries: list.entries.map((e) => e.id), onlyPending: list.entries.length === 1 && list.entries[0].id === p.id, count: ops.countPending(cwd), lockRefs: lockRefs(cwd).length };
	const reconciled = ops.reconcileOps(cwd, { retentionDays: 30, resultRetentionDays: 90, now: Date.now() + 400 * 86400 * 1000 });
	out.list.lockSurvivesReconcile = lockRefs(cwd).length === 1 && !reconciled.some((r) => r.includes("lock"));
}

// 9. forceRelease
{
	const cwd = repo();
	const a = acq(cwd, holder(1));
	const wrong = lock.forceRelease(cwd, "d".repeat(40), ENV);
	const stillHeld = lock.readLock(cwd, keyOf(cwd), ENV).state;
	const right = lock.forceRelease(cwd, a.handle.oid, ENV);
	const again = lock.forceRelease(cwd, a.handle.oid, ENV);
	// 不正な内容のロックも、期待 OID が合えば消せる
	const bad = gitIn(cwd, "bad\n", "commit-tree", gitIn(cwd, "", "mktree"), "-F", "-");
	git(cwd, "update-ref", `refs/pi/lock/${keyOf(cwd)}`, bad);
	const invalidRelease = lock.forceRelease(cwd, bad, ENV);
	// symbolic ref は消さない
	git(cwd, "symbolic-ref", `refs/pi/lock/${keyOf(cwd)}`, "refs/heads/main");
	const sym = lock.forceRelease(cwd, git(cwd, "rev-parse", "main"), ENV);
	out.force = { wrong: wrong.ok, stillHeld, right: right.ok, again: again.ok, invalidRelease: invalidRelease.ok, symbolic: sym.ok, mainExists: gitOk(cwd, "rev-parse", "refs/heads/main") !== null };
}

out.api = Object.keys(lock).sort();
console.log(JSON.stringify(out));
