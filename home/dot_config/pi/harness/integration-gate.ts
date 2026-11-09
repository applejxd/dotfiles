// 保護ブランチへの統合の確認 (`[pi.confirm] integration`)。判定器の結果を、必要なら必須確認 (bypass でも省略不可) に引き上げる。
//
// 緩める方向の処理は無い: deny はそのまま、すでに必須確認のものもそのまま、それ以外を引き上げるだけ。
// bash の統合コマンドは、judge/gitintegration.ts が静的に分類する。
//   always / unknown  常に必須確認 (保護 ref を直接変える・対象が静的に決まらない)
//   head              現在のブランチを動かす (merge・cherry-pick・pull・am・reset など)。cwd が自由区 (feature の linked worktree)
//                     なら日常の操作なので判定器の結果のまま。自由区でない・判定できないときは必須確認 (deny にしない)
//                     先頭が `cd <絶対パス> && git ...` (区切りは && だけ。残りは直接の git 1 コマンド) で残りが head のときだけ、
//                     実体のパスの cd 先で自由区かを見る (文法と理由は docs/spec/guard/pi-decide.md)
//                     (feature の worktree への develop の取り込みを、確認なしで通す。develop を直接変えるものは cd が付いても必須確認)
// git を起動するのは head のときだけ (毎回の edit / write や通常の bash では起動しない)。
// 保証の範囲は「ガードが識別する直接経路」(alias・外部スクリプト・別のプロセスの中の ref の書き込みは見ない)。
// see docs/change/closed/0053-worktree-integration-gate.md
import { realpathSync, statSync } from "node:fs";
import { MUST_CONFIRM_INTEGRATION_PREFIX } from "./confirm-view.ts";
import { classifyFreeZone, DEFAULT_PROTECTED, type FreeZone } from "./freezone.ts";
import { classifyIntegration } from "./judge/gitintegration.ts";
import { REPO_SELECTING_VARS } from "./pending-store.ts";
import { clip200 } from "./judge/shared.ts";

type Decision = { decision: "allow" | "ask" | "deny"; reason: string; source: string; mustConfirm?: boolean };

export type IntegrationConfig = { enabled: boolean; protectedRefs: readonly string[] };

const SHELL_TOOLS = new Set(["bash", "bg_run"]);

/** rules.json の judge.common から設定を読む。`[pi.confirm] integration` が真のときだけ有効。保護 ref は `[pi.integrate] protected_refs` */
export function integrationConfig(common: any): IntegrationConfig {
	const pi = common?.pi ?? {};
	const refs = pi.integrate?.protected_refs;
	const list = Array.isArray(refs) && refs.every((r: unknown) => typeof r === "string") && refs.length > 0 ? (refs as string[]) : DEFAULT_PROTECTED;
	return { enabled: pi.confirm?.integration === true, protectedRefs: list };
}

// cd の行き先に使えるリテラル。絶対パスだけ (相対は CDPATH で別の場所になりうる)。引用なし・'…'・"…" のいずれか
const CD_LEADING = /^[ \t]*cd[ \t]+(?:"([^"]+)"|'([^']+)'|([^\s"']+))[ \t]*&&[ \t]*(git[ \t][^\n]*)$/;
const CD_PATH_OK = /^\/[A-Za-z0-9_./@+:,=%-]*$/;
// 残りに 1 文字でもあれば対象外 (別の宛先・非同期・サブシェル・展開・リダイレクトを作れる)
const REST_FORBIDDEN = /[;&|\n\r`$()<>{}]/;

/** 先頭の `cd <絶対パス> && git ...` だけを分ける。許可の文法は小さく厳密 (docs/spec/guard/pi-decide.md)。それ以外は null */
export function splitLeadingCd(command: string): { dir: string; rest: string } | null {
	const m = CD_LEADING.exec(command);
	if (!m) return null;
	const dir = m[1] ?? m[2] ?? m[3];
	const rest = m[4].replace(/[ \t]+$/, "");
	if (!dir || !CD_PATH_OK.test(dir) || dir.split("/").includes("..")) return null;
	if (REST_FORBIDDEN.test(rest)) return null;
	return { dir, rest };
}

function realDirectory(path: string): string | null {
	try {
		const real = realpathSync(path);
		return statSync(real).isDirectory() ? real : null;
	} catch {
		return null;
	}
}

export function tightenIntegration(
	d: Decision,
	tool: string,
	input: unknown,
	cwd: string,
	cfg: IntegrationConfig,
	deps: { classify?: (cwd: string, refs: readonly string[]) => FreeZone; env?: NodeJS.ProcessEnv } = {},
): Decision {
	if (!cfg.enabled || !SHELL_TOOLS.has(tool)) return d;
	if (d.decision === "deny" || (d.decision === "ask" && d.mustConfirm === true)) return d;
	const command = String((input as any)?.command ?? "");
	const r = classifyIntegration(command, cfg.protectedRefs);
	if (r.kind === "none") return d;
	let why = r.reason;
	const classify = deps.classify ?? ((c, refs) => classifyFreeZone(c, refs));
	if (r.kind === "head") {
		const fz = classify(cwd, cfg.protectedRefs);
		if (fz.free) return d;
		why = `${r.reason}。feature の linked worktree の中ではない (${fz.reason})`;
	} else if (r.kind === "unknown") {
		// 先頭が `cd <絶対パス> && git ...` だけで残りが head なら、cd 先が自由区かを見る。それ以外は従来どおり必須確認
		const lead = splitLeadingCd(command);
		const inner = lead ? classifyIntegration(lead.rest, cfg.protectedRefs) : null;
		if (lead && inner?.kind === "head") {
			const selecting = REPO_SELECTING_VARS.filter((k) => (deps.env ?? process.env)[k] !== undefined);
			const target = selecting.length ? null : realDirectory(lead.dir);
			if (selecting.length) {
				why = `${inner.reason}。リポジトリを選ぶ環境変数 (${selecting.join(",")}) があるので cd 先を信じない`;
			} else if (target) {
				const fz = classify(target, cfg.protectedRefs);
				if (fz.free) return d;
				why = `${inner.reason}。cd 先 (${clip200(lead.dir)}) が feature の linked worktree の中ではない (${fz.reason})`;
			} else {
				why = `${inner.reason}。cd 先 (${clip200(lead.dir)}) が存在しない`;
			}
		}
	}
	return {
		decision: "ask",
		mustConfirm: true,
		source: "rule",
		reason: `${MUST_CONFIRM_INTEGRATION_PREFIX}${why}\n実行しようとしているコマンド: ${clip200(command)}`,
	};
}
