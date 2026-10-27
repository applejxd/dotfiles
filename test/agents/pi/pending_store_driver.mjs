// pending-store.ts の試験 (CHG-0046)。使い捨てのリポジトリで場面を動かし、結果を JSON で標準出力へ出す (照合は test_pi_pending_store.py)。
//
//   node test/agents/pi/pending_store_driver.mjs
//
// see docs/change/0046-guarded-action-timeout.md
import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const mod = await import(pathToFileURL(join(ROOT, "home", "dot_config", "pi", "harness", "pending-store.ts")).href);
const { snapshotStaged, savePendingSnapshot, listPending, showPending, dropPending } = mod;

const tmp = mkdtempSync(join(tmpdir(), "pending-store-"));
// 利用者の設定に左右されない (git の名前・メールも無い環境を再現)
const ENV = { ...process.env, HOME: tmp, GIT_CONFIG_GLOBAL: "/dev/null", GIT_CONFIG_SYSTEM: "/dev/null", GIT_CONFIG_NOSYSTEM: "1" };
for (const k of ["GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"]) delete ENV[k];

function g(cwd, ...args) {
	const r = spawnSync("git", args, { cwd, encoding: "utf8", env: ENV });
	return { ok: r.status === 0, out: String(r.stdout ?? "").replace(/\n+$/, "") };
}
function repo(name, { commit = true } = {}) {
	const dir = join(tmp, name);
	spawnSync("git", ["init", "-q", "-b", "main", dir], { env: ENV });
	if (commit) {
		writeFileSync(join(dir, "a.txt"), "a\n");
		g(dir, "add", "a.txt");
		g(dir, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "base");
	}
	return dir;
}
// 子プロセスの git が、このドライバの ENV (名前・メール無し) で動くように、モジュール側の環境を合わせる
Object.assign(process.env, ENV);

const out = {};
try {
	// 1. 待つ間に別の操作がインデックスを変えても、退避は表示した内容
	{
		const dir = repo("r1");
		writeFileSync(join(dir, "x.txt"), "shown\n");
		g(dir, "add", "x.txt");
		const head = g(dir, "rev-parse", "HEAD").out;
		const snap = snapshotStaged(dir, "feat: shown", "req1");
		// 待っている間: 別のファイルをステージし、x.txt も書き換える
		writeFileSync(join(dir, "y.txt"), "later\n");
		g(dir, "add", "y.txt");
		writeFileSync(join(dir, "x.txt"), "changed\n");
		const indexBefore = g(dir, "ls-files", "-s").out;
		const statusBefore = g(dir, "status", "--porcelain").out;
		const saved = savePendingSnapshot(dir, snap);
		const files = g(dir, "ls-tree", "-r", "--name-only", saved.ref).out.split("\n");
		out.shown = {
			snapOk: !!snap,
			savedOk: saved.ok,
			files,
			xContent: g(dir, "show", `${saved.ref}:x.txt`).out,
			parentIsBase: g(dir, "rev-parse", `${saved.ref}^`).out === head,
			headUnchanged: g(dir, "rev-parse", "HEAD").out === head,
			branchUnchanged: g(dir, "symbolic-ref", "HEAD").out === "refs/heads/main",
			indexUnchanged: g(dir, "ls-files", "-s").out === indexBefore,
			statusUnchanged: g(dir, "status", "--porcelain").out === statusBefore,
			message: g(dir, "log", "-1", "--format=%B", saved.ref).out,
		};
	}
	// 2. 独立: 2 つ目の親は表示時点の HEAD。1 つ目ではない。同じ tree・別のメッセージも保存できる
	{
		const dir = repo("r2");
		writeFileSync(join(dir, "x.txt"), "one\n");
		g(dir, "add", "x.txt");
		const head = g(dir, "rev-parse", "HEAD").out;
		const s1 = savePendingSnapshot(dir, snapshotStaged(dir, "first", "r-a"));
		const s2 = savePendingSnapshot(dir, snapshotStaged(dir, "second (same tree)", "r-b"));
		out.independent = {
			bothOk: s1.ok && s2.ok,
			distinctRefs: s1.ref !== s2.ref,
			parent2IsBase: g(dir, "rev-parse", `${s2.ref}^`).out === head,
			sameTree: g(dir, "rev-parse", `${s1.ref}^{tree}`).out === g(dir, "rev-parse", `${s2.ref}^{tree}`).out,
		};
	}
	// 3. 一覧・表示・破棄
	{
		const dir = repo("r3");
		writeFileSync(join(dir, "x.txt"), "one\n");
		g(dir, "add", "x.txt");
		const s1 = savePendingSnapshot(dir, snapshotStaged(dir, "older", "r-1"));
		const s2 = savePendingSnapshot(dir, snapshotStaged(dir, "newer", "r-2"));
		const list = listPending(dir);
		const shown = showPending(dir, s2.ref);
		const refusedForeign = dropPending(dir, "refs/heads/main");
		const dropped = dropPending(dir, s1.ref);
		out.manage = {
			order: list.map((e) => e.subject),
			branch: list[0].branch,
			shownHasFile: shown.includes("x.txt"),
			refusedForeign,
			dropped,
			remaining: listPending(dir).map((e) => e.subject),
			mainStillThere: g(dir, "rev-parse", "-q", "--verify", "refs/heads/main").ok,
		};
	}
	// 4. 空 (ステージ済みが無い) は退避しない。コミットの無いリポジトリでは親無しで保存できる
	{
		const dir = repo("r4");
		const empty = snapshotStaged(dir, "nothing", "r");
		const unborn = repo("r4u", { commit: false });
		writeFileSync(join(unborn, "n.txt"), "n\n");
		g(unborn, "add", "n.txt");
		const snap = snapshotStaged(unborn, "first commit", "r");
		const saved = savePendingSnapshot(unborn, snap);
		out.edge = {
			emptyIsNull: empty === null,
			unbornOk: saved.ok,
			unbornNoParent: g(unborn, "rev-list", "--parents", "-n1", saved.ref).out.split(" ").length === 1,
			unbornHeadMissing: !g(unborn, "rev-parse", "-q", "--verify", "HEAD").ok,
		};
	}
	// 5. 確定した tree が消えていたら、保存に失敗する (成功を返さない)
	{
		const dir = repo("r5");
		writeFileSync(join(dir, "x.txt"), "x\n");
		g(dir, "add", "x.txt");
		const snap = snapshotStaged(dir, "m", "r");
		const bad = savePendingSnapshot(dir, { ...snap, treeOid: "1".repeat(40) });
		out.missing = { ok: bad.ok, hasReason: !bad.ok && bad.reason.length > 0, refs: listPending(dir).length };
	}
} finally {
	rmSync(tmp, { recursive: true, force: true });
}
console.log(JSON.stringify(out));
