// 盤面の収集部品 (board-collect.ts) を、実際の一時リポジトリに対して動かす。照合は test_pi_board_collect.py。
//
//   node test/agents/pi/board_collect_driver.mjs '<JSON>'
//   {"op":"legacy","cwd":...}  旧形式の退避を 1 件保存して結果を出す
//   {"op":"collect","cwd":...,"now":...,"target":"develop"}  collectBoardInput と、buildBoard → renderBoard (幅 44) を出す
import { execFileSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const H = resolve(ROOT, "home", "dot_config", "pi", "harness");
const imp = (f) => import(pathToFileURL(resolve(H, f)).href);

const a = JSON.parse(process.argv[2]);
let out;
if (a.op === "legacy") {
	const store = await imp("pending-store.ts");
	const env = { ...process.env, GIT_AUTHOR_NAME: "t", GIT_AUTHOR_EMAIL: "t@example.test", GIT_COMMITTER_NAME: "t", GIT_COMMITTER_EMAIL: "t@example.test" };
	const git = (...args) => execFileSync("git", args, { cwd: a.cwd, env, encoding: "utf8" }).trim();
	writeFileSync(join(a.cwd, "legacy.txt"), "legacy\n");
	git("add", "legacy.txt");
	out = store.savePendingSnapshot(a.cwd, store.snapshotStaged(a.cwd, "feat: legacy", "req-legacy"));
	git("reset", "-q");
} else {
	const c = await imp("board-collect.ts");
	const b = await imp("board.ts");
	try {
		const input = c.collectBoardInput(a.cwd, {
			now: a.now,
			children: [],
			modes: { bypass: false },
			...(a.target ? { target: a.target } : {}),
			...(a.profileDefaults ? { profileDefaults: a.profileDefaults } : {}),
			...(a.maxFeatures !== undefined ? { maxFeatures: a.maxFeatures } : {}),
		});
		out = { threw: false, input, lines: b.renderBoard(b.buildBoard(input), { width: 44, now: a.now }) };
	} catch (e) {
		out = { threw: true, error: String(e) };
	}
}
process.stdout.write(JSON.stringify(out));
