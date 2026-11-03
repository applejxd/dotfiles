// 起票の依頼文（brief）の読み取り専用 CLI。結果の JSON を 1 行で標準出力へ。終了コード: 成功 0・記録なし/拒否 2・想定外 1。
// 使い方: node apps/pr-viewer/brief-cli.ts show <repo> feature/<名>
// 圧縮などで依頼文の原文を見失った pi が、読み直すための入口。書き込みはしない（git-view の読み取り用の入口だけを使う）。
import { briefView } from "./brief.ts";
import { nameProblem } from "./feature-create.ts";
import { openRepo, prKeyOf } from "./git-view.ts";
import { readBriefRecord } from "./review-api.ts";

function emit(obj: unknown, code: number): void {
	process.stdout.write(`${JSON.stringify(obj)}\n`);
	process.exitCode = code;
}

const bad = (): void => emit({ ok: false, code: "bad_input", reason: "入力が正しくありません。" }, 2);

async function main(argv: string[]): Promise<void> {
	const [cmd, repoPath, branch, ...rest] = argv;
	if (cmd !== "show" || !repoPath || repoPath.startsWith("-") || !branch || rest.length > 0) return bad();
	const m = /^feature\/(.+)$/.exec(branch);
	if (!m || nameProblem(m[1])) return bad();
	const repo = await openRepo(repoPath);
	if (!repo) return emit({ ok: false, code: "no_repo", reason: "リポジトリを開けません。" }, 2);
	const rec = await readBriefRecord(repo, prKeyOf(branch));
	if (!rec) return emit({ ok: false, code: "no_brief", reason: "この枝の依頼文の記録はありません。" }, 2);
	emit({ ok: true, branch, name: rec.brief.d.name, brief: briefView(rec.brief) }, 0);
}

await main(process.argv.slice(2)).catch(() => emit({ ok: false, code: "failed", reason: "読み取りに失敗しました。" }, 1));
