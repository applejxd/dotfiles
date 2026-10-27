// session-tmp.ts の表試験 (CHG-0042)。結果を JSON で標準出力へ出す (照合は test_pi_session_tmp.py)。
//
//   node test/agents/pi/session_tmp_driver.mjs
//
// see docs/change/0042-tmp-lifecycle.md
import { spawn, spawnSync } from "node:child_process";
import { existsSync, lstatSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, utimesSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const HARNESS = resolve(ROOT, "home", "dot_config", "pi", "harness");
const mod = await import(pathToFileURL(join(HARNESS, "session-tmp.ts")).href);
const { SessionTmp, idTail, ownerRecord, survivors, MAX_DIR_LEN } = mod;

const base = mkdtempSync(join("/tmp", "st-")); // 置き場のパス長の上限 (MAX_DIR_LEN) を超えないよう、短い場所を使う
process.on("exit", () => rmSync(base, { recursive: true, force: true }));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const ORIGINAL_TMPDIR = process.env.TMPDIR;

let n = 0;
function repo(withTmp = true) {
	const dir = join(base, `r${++n}`);
	mkdirSync(dir);
	if (withTmp) mkdirSync(join(dir, ".tmp"));
	return dir;
}
const mk = (opts = {}) => new SessionTmp({ enabled: true, harnessDir: HARNESS, ...opts });
// UUIDv7 の形 (先頭は時刻、末尾がランダム)
const sid = (tail) => `01a17a79-9100-737d-bab3-a2f2${tail.padStart(8, "0")}`.slice(0, 36);
const out = {};

// 1. 作る: 末尾 8 文字・.owner・TMPDIR・権限
{
	process.env.TMPDIR = ORIGINAL_TMPDIR ?? "";
	const r = repo();
	const t = mk();
	const dir = t.start(r, sid("deadbeef"));
	const owner = JSON.parse(readFileSync(join(dir, ".owner"), "utf-8"));
	out.create = {
		dir_rel: dir.slice(r.length),
		tmpdir_is_dir: process.env.TMPDIR === dir,
		owner_pid_is_self: owner.pid === process.pid,
		owner_keys: Object.keys(owner).sort(),
		mode_dir: (lstatSync(dir).mode & 0o777).toString(8),
		mode_owner: (lstatSync(join(dir, ".owner")).mode & 0o777).toString(8),
		id_tail: idTail("01a17a79-9100-737d-bab3-a2f20a7bf075"),
		id_tail_short: idTail("ab", 8),
	};
}

// 2. 作らない場合: .tmp が無い・リンク・無効
{
	const before = process.env.TMPDIR;
	const none = mk().start(repo(false), sid("00000001"));
	const r = repo(false);
	const real = join(base, "real-tmp");
	mkdirSync(real);
	symlinkSync(real, join(r, ".tmp"));
	const linked = mk().start(r, sid("00000002"));
	const disabled = mk({ enabled: false }).start(repo(), sid("00000003"));
	// s がリンク
	const r2 = repo();
	const elsewhere = join(base, "elsewhere");
	mkdirSync(elsewhere);
	symlinkSync(elsewhere, join(r2, ".tmp", "s"));
	const slink = mk().start(r2, sid("00000004"));
	out.skip = { no_tmp: none ?? null, tmp_symlink: linked ?? null, disabled: disabled ?? null, s_symlink: slink ?? null, tmpdir_unchanged: process.env.TMPDIR === before, elsewhere_empty: !existsSync(join(elsewhere, "00000004")) };
}

// 3. reload は同じ置き場を使い、quit 以外では消さない。quit は作った置き場をすべて消す
{
	const r = repo();
	const t = mk();
	const d1 = t.start(r, sid("aaaaaaa1"));
	const reload = t.start(r, sid("aaaaaaa1"));
	const d2 = t.start(r, sid("bbbbbbb2")); // /new の後の、新しいセッション
	const kept = {};
	for (const reason of ["reload", "new", "resume", "fork"]) {
		const res = await t.teardown(reason);
		kept[reason] = { removed: res.removed.length, d1: existsSync(d1), d2: existsSync(d2) };
	}
	const quit = await t.teardown("quit");
	out.lifecycle = { reload_same: reload === d1, distinct: d1 !== d2, kept, quit_removed: quit.removed.length, d1_after: existsSync(d1), d2_after: existsSync(d2), kept_after: quit.kept.length };
}

// 4. 衝突: 同じ末尾の別のセッションの置き場があれば、末尾を伸ばし、相手には触れない
{
	const r = repo();
	const other = join(r, ".tmp", "s", "cafef00d");
	mkdirSync(other, { recursive: true });
	writeFileSync(join(other, ".owner"), JSON.stringify({ pid: 1, start: "1", pidns: "x", host: "y" }));
	writeFileSync(join(other, "keep.txt"), "x");
	const t = mk();
	const dir = t.start(r, sid("cafef00d"));
	await t.teardown("quit");
	out.collision = { tail_len: dir.split("/").pop().length, other_intact: existsSync(join(other, "keep.txt")), own_removed: !existsSync(dir) };
}

// 5. パス長
{
	const deep = repo();
	let long = deep;
	while (long.length < MAX_DIR_LEN + 10) {
		long = join(long, "deeper-directory-name");
		mkdirSync(long, { recursive: true });
	}
	mkdirSync(join(long, ".tmp"));
	out.long_path = { dir: mk().start(long, sid("12345678")) ?? null, max: MAX_DIR_LEN };
}

// 6. 生き残り: その TMPDIR を持つプロセスがいれば消さず、いなくなれば消す
{
	const r = repo();
	const t = mk({ waitMs: 400 });
	const dir = t.start(r, sid("55555555"));
	const child = spawn("sleep", ["30"], { env: { ...process.env, TMPDIR: dir }, stdio: "ignore" });
	await sleep(200);
	const found = survivors(dir);
	const blocked = await t.teardown("quit");
	const still = existsSync(dir);
	child.kill("SIGKILL");
	await sleep(300);
	const done = await t.teardown("quit");
	out.survivors = { found: found.includes(child.pid), blocked_removed: blocked.removed.length, dir_kept_while_alive: still, removed_after_exit: done.removed.length, dir_after: existsSync(dir) };
}

// 7. 起動時の掃除: 死んだ持ち主の置き場は消え、生きているもの・確証できないものは残る。1 日 1 回の掃除の印
{
	const r = repo();
	const t = mk();
	const live = t.start(r, sid("77777777"));
	const dead = join(r, ".tmp", "s", "dead0000");
	mkdirSync(dead);
	const gone = spawn("sleep", ["30"], { stdio: "ignore" });
	writeFileSync(join(dead, ".owner"), JSON.stringify(ownerRecord(gone.pid)));
	gone.kill("SIGKILL");
	await sleep(300);
	const unknown = join(r, ".tmp", "s", "unknown0");
	mkdirSync(unknown);
	writeFileSync(join(r, ".tmp", "my-experiment"), "x"); // 未知の名前は消えない
	const started = t.sweep(r);
	for (let i = 0; i < 50 && existsSync(dead); i++) await sleep(100);
	const stamp1 = existsSync(join(r, ".tmp", ".clean-stamp"));
	out.sweep = { started, dead_removed: !existsSync(dead), live_kept: existsSync(live), unknown_kept: existsSync(unknown), unknown_name_kept: existsSync(join(r, ".tmp", "my-experiment")), stamp: stamp1 };
	// 2 回目 (印が新しい) は、s/ だけ。再生成できる名前は消さない
	const disposable = join(r, ".tmp", "tools-ext-old");
	mkdirSync(disposable);
	const old = new Date(Date.now() - 3 * 86400 * 1000);
	utimesSync(disposable, old, old);
	t.sweep(r);
	await sleep(1200);
	out.sweep.disposable_kept_on_second_run = existsSync(disposable);
	// 印が古ければ、再生成できる名前も消える
	const past = new Date(Date.now() - 2 * 86400 * 1000);
	utimesSync(join(r, ".tmp", ".clean-stamp"), past, past);
	t.sweep(r);
	for (let i = 0; i < 50 && existsSync(disposable); i++) await sleep(100);
	out.sweep.disposable_removed_when_stamp_old = !existsSync(disposable);
}

process.stdout.write(JSON.stringify(out));
