// 盤面 (board.ts) の純関数を、固定の入力で動かして結果を JSON で標準出力へ出す。照合は test_pi_board.py。
//
//   node test/agents/pi/board_driver.mjs
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const b = await import(pathToFileURL(resolve(ROOT, "home", "dot_config", "pi", "harness", "board.ts")).href);

const base = () => ({
	now: 1_000_000,
	children: [],
	isolation: [],
	worktrees: [],
	pending: { ops: [], legacyCount: 0, broken: 0 },
	modes: {},
	bgJobs: { running: 0, finished: 0 },
});
const iso = (jobId) => ({
	version: 1,
	jobId,
	repo: "/r",
	worktree: `/tmp/pi-agent-${jobId}`,
	startCommit: "a",
	snapshotCommit: "b",
	createdAt: "2026-01-01T00:00:00Z",
	state: "running",
});
const widths = (lines) => lines.map((l) => [...l].reduce((n, ch) => n + (/[\u1100-\u115f\u2e80-\ua4cf\uac00-\ud7a3\uff00-\uff60\uffe0-\uffe6]/.test(ch) ? 2 : 1), 0));
const render = (input, width) => b.renderBoard(b.buildBoard(input), { width, now: input.now });

const out = {};

out.empty = { lines: render(base(), 46), snap: b.buildBoard(base()) };

const full = base();
full.children = [
	{ id: "c1", agent: "worker", state: "running", ageMs: 192_000, roundMs: 5000, calls: 3, tokens: 1200, cost: 0.05, lastTool: "bash" },
	{ id: "c2", agent: "review", state: "idle", ageMs: 60_000 },
];
full.isolation = [iso("j1")];
full.worktrees = b.parseWorktreePorcelain(
	"worktree /repo\nHEAD aaa\nbranch refs/heads/develop\n\nworktree /repo/.tmp/worktrees/board-model\nHEAD bbb\nbranch refs/heads/feature/board-model\n\nworktree /tmp/pi-agent-j1\nHEAD ccc\ndetached\n",
);
full.pending = { ops: [{ id: "0123456789abcdef", state: "pending", action: "git_push", ageMs: 90_000 }], legacyCount: 2, broken: 0 };
full.modes = { bypass: false, orchestrate: true, sandbox: "fence" };
full.bgJobs = { running: 1, finished: 4 };
out.full = render(full, 80);

const wide = structuredClone(full);
wide.children = [{ id: "子エージェント全角", agent: "ワーカー", state: "running", ageMs: 1000, lastTool: "全角のツール名が長い長い長い長い長い長い" }];
wide.worktrees = b.parseWorktreePorcelain("worktree /repo\nbranch refs/heads/main\n\nworktree /r/全角の長いディレクトリ名前前前前前前前前\nbranch refs/heads/feature/全角の機能名\n");
out.wide = {};
for (const w of [46, 80]) {
	const lines = render(wide, w);
	out.wide[w] = { lines, widths: widths(lines) };
}

const hostile = base();
hostile.children = [{ id: "c\x1b[31m1", agent: "w\x1b]0;x\x07", state: "idle", ageMs: 1, lastTool: "\x1b]0;x\x07evil\x1b[2J" }];
hostile.worktrees = b.parseWorktreePorcelain("worktree /r\nbranch refs/heads/main\n\nworktree /r/a\x1b[1mb\nbranch refs/heads/feature/x\x07y\n");
out.hostile = render(hostile, 80);

const many = base();
many.children = Array.from({ length: 20 }, (_, i) => ({ id: `c${i}`, agent: "worker", state: "idle", ageMs: i }));
out.many = { snap: b.buildBoard(many), lines: render(many, 80) };

const broken = base();
broken.isolation = [iso("ok1"), { broken: true, file: "bad.json" }];
out.broken = { snap: b.buildBoard(broken), lines: render(broken, 80) };

out.porcelain = b.parseWorktreePorcelain(
	[
		"worktree /repo",
		"HEAD 111",
		"branch refs/heads/main",
		"",
		"worktree /repo/.tmp/worktrees/x",
		"HEAD 222",
		"branch refs/heads/feature/foo-bar",
		"",
		"worktree /tmp/pi-agent-abc",
		"HEAD 333",
		"detached",
		"locked in use",
		"",
		"worktree /bare.git",
		"bare",
		"",
		"worktree /gone",
		"HEAD 444",
		"branch refs/heads/old",
		"prunable gitdir file points to non-existent location",
		"garbage line",
		"",
	].join("\n"),
);
out.porcelainJunk = b.parseWorktreePorcelain("zzz\nHEAD x\n\n\nworktree\n");

const own = base();
own.pending = {
	ops: ["alive", "gone", "unknown", undefined].map((s, i) => ({ id: `id${i}`.padEnd(10, "0"), state: "running", action: "op", ageMs: 5000, ...(s ? { owner: { state: s } } : {}) })),
	legacyCount: 0,
	broken: 0,
};
out.owners = render(own, 80);

const all = [...out.empty.lines, ...out.full, ...out.hostile, ...out.many.lines, ...out.broken.lines, ...out.owners, ...out.wide[46].lines, ...out.wide[80].lines];
out.all = all;
out.roundtrip = JSON.stringify(b.buildBoard(full)) === JSON.stringify(JSON.parse(JSON.stringify(b.buildBoard(full))));
out.v = b.buildBoard(full).v;

process.stdout.write(JSON.stringify(out));
