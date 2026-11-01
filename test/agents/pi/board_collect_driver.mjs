// 盤面の収集部品 (board-collect.ts) を、実際の一時リポジトリに対して動かす。照合は test_pi_board_collect.py。
//
//   node test/agents/pi/board_collect_driver.mjs '<JSON>'
//   {"op":"save","cwd":...,"input":{...}}  保留を 1 件保存して結果を出す
//   {"op":"collect","cwd":...,"now":...,"target":"develop"}  collectBoardInput と、buildBoard → renderBoard (幅 44) を出す
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const H = resolve(ROOT, "home", "dot_config", "pi", "harness");
const imp = (f) => import(pathToFileURL(resolve(H, f)).href);

const a = JSON.parse(process.argv[2]);
let out;
if (a.op === "save") {
	const ops = await imp("pending-ops.ts");
	out = ops.saveOp(a.cwd, a.input);
} else {
	const c = await imp("board-collect.ts");
	const b = await imp("board.ts");
	try {
		const input = c.collectBoardInput(a.cwd, {
			now: a.now,
			children: [],
			modes: { bypass: false },
			...(a.target ? { target: a.target } : {}),
			...(a.maxFeatures !== undefined ? { maxFeatures: a.maxFeatures } : {}),
		});
		out = { threw: false, input, lines: b.renderBoard(b.buildBoard(input), { width: 44, now: a.now }) };
	} catch (e) {
		out = { threw: true, error: String(e) };
	}
}
process.stdout.write(JSON.stringify(out));
