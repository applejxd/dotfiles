// bash の構文木 (同梱の mvdan-sh。vendor/mvdan-sh。mvdan/sh の GopherJS 版) の読み込みと、構文木の小さな道具。
//
// - index.js のバイト列を読んで sha256 を期待値と照合し、**照合したのと同じバイト**を評価する (読み直さない)。
//   評価は node:vm ではなく、バイト列を文字列に直して `new Function` に渡す (node・bun の両方で同じに動く。`createRequire` はパスから
//   読み直すので、検証と評価の間にファイルが差し替わる余地が残るため使わない)。
// - 失敗は例外にせず { ok: false, why } で返す (欠損・sha 不一致・評価の失敗・解析の失敗)。
//   判定に接続したときの扱い (deny) は呼び出し側が決める。この段では判定に接続しない。
// - vendor のディレクトリは引数で注入できる (試験用)。本番の既定は harness の vendor/。環境変数では切り替えない。
//
// node の型除去でそのまま動く書き方だけを使う (enum・namespace は使わない)。
// see docs/spec/guard/pi-extensions.md#確認画面の手順の一覧

import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

/** 同梱の index.js の期待値。vendor/mvdan-sh/README.md の値・試験 (test_pi_explain.py) と三者が一致すること */
export const MVDAN_SHA256 = "2b613c6ddf9ff8ba530e3d2e30a1c34a7b146abafa8408e18a9b8cdd771d0f2c";
export const MVDAN_BYTES = 1505122;

/** 構文木の 1 回分の入力 (原文のバイト列。Offset() は UTF-8 のバイト位置なので、切り出しは Buffer 経由) */
export type Src = { buf: Buffer; file: any };
export type Loaded = { ok: true; syntax: any } | { ok: false; why: string };
export type Parsed = { ok: true; src: Src } | { ok: false; why: string };
export type Diag = { ok: boolean; why: string };

const DEFAULT_DIR = fileURLToPath(new URL("../vendor/mvdan-sh", import.meta.url));
let dirOverride: string | null = null;
// 読み込みに成功した syntax (vendor のディレクトリごと)。失敗は覚えない (apply で直ったら次の呼び出しで読み直す)
const LOADED = new Map<string, any>();
// 直近に読み込めた syntax。typeOf など、syntax を引数に取らない道具が使う (同期の呼び出しだけ。並行には使わない)
let CURRENT: any = null;

/** 本番の既定の vendor ディレクトリ */
export function defaultVendorDir(): string {
	return DEFAULT_DIR;
}

/** 既定の vendor ディレクトリを差し替える (試験用。null で戻す)。環境変数の代わり */
export function setDefaultVendorDir(dir: string | null): void {
	dirOverride = dir;
}

function msg(e: unknown): string {
	return e instanceof Error ? e.message : String(e);
}

/** 構文木の道具 (syntax) を読み込む。vendorDir は vendor/mvdan-sh のディレクトリ。例外は投げない */
export function loadSyntax(vendorDir?: string): Loaded {
	const dir = vendorDir ?? dirOverride ?? DEFAULT_DIR;
	const hit = LOADED.get(dir);
	if (hit) {
		CURRENT = hit;
		return { ok: true, syntax: hit };
	}
	let bytes: Buffer;
	try {
		bytes = readFileSync(join(dir, "index.js"));
	} catch (e) {
		return { ok: false, why: `mvdan-sh が読めない: ${msg(e)}` };
	}
	const sha = createHash("sha256").update(bytes).digest("hex");
	if (sha !== MVDAN_SHA256) return { ok: false, why: `mvdan-sh の sha256 が期待値と違う (実際 ${sha})` };
	// 評価する前に、GopherJS の初期化が触る大域 (global.require・Error.stackTraceLimit) を覚えて、後で戻す
	const g: any = globalThis;
	const reqDesc = Object.getOwnPropertyDescriptor(g, "require");
	const limit = Error.stackTraceLimit;
	try {
		const mod: { exports: any } = { exports: {} };
		const noRequire = (): never => {
			throw new Error("mvdan-sh から require は使えない");
		};
		// 検証した bytes をそのまま文字列にして評価する (ファイルを読み直さない)
		const run = new Function("module", "exports", "require", new TextDecoder("utf-8").decode(bytes));
		run(mod, mod.exports, noRequire);
		const s = mod.exports?.syntax;
		if (!s || typeof s.NewParser !== "function") return { ok: false, why: "mvdan-sh の評価結果に syntax.NewParser が無い" };
		LOADED.set(dir, s);
		CURRENT = s;
		return { ok: true, syntax: s };
	} catch (e) {
		return { ok: false, why: `mvdan-sh の評価に失敗: ${msg(e)}` };
	} finally {
		if (reqDesc) Object.defineProperty(g, "require", reqDesc);
		else delete g.require;
		Error.stackTraceLimit = limit;
	}
}

/** bash として解析する。vendor が読めない・構文エラー・例外は { ok: false, why } */
export function parseSource(text: string, vendorDir?: string): Parsed {
	const l = loadSyntax(vendorDir);
	if (!l.ok) return l;
	try {
		const S = l.syntax;
		const parser = S.NewParser(S.Variant(S.LangBash));
		return { ok: true, src: { buf: Buffer.from(text, "utf8"), file: parser.Parse(text, "") } };
	} catch (e) {
		return { ok: false, why: `解析に失敗: ${msg(e)}` };
	}
}

/** 直近に読み込めた syntax (無ければ例外。parseSource が成功した後の道具から使う) */
export function currentSyntax(): any {
	if (CURRENT === null) throw new Error("mvdan-sh が読み込まれていない");
	return CURRENT;
}

// ─── 構文木の小さな道具 ─────────────────────────────────────────

export const arr = (x: any): any[] => {
	if (!x) return [];
	if (Array.isArray(x)) return x;
	if (typeof x.$length === "number") return Array.from({ length: x.$length }, (_, i) => x.$array[x.$offset + i]);
	return [];
};
export const typeOf = (n: any): string => (n ? String(currentSyntax().NodeType(n)) : "");
export const pos = (n: any): number => Number(n.Pos().Offset());
export const end = (n: any): number => Number(n.End().Offset());
export const cut = (src: Src, a: number, b: number): string => src.buf.subarray(a, Math.max(a, b)).toString("utf8");

// ─── 自己診断 ───────────────────────────────────────────────────

function callsOf(S: any, file: any): any[] {
	const out: any[] = [];
	S.Walk(file, (n: any) => {
		if (n && String(S.NodeType(n)) === "CallExpr") out.push(n);
		return true;
	});
	return out;
}

/**
 * 既知の 3 コマンドを解析して、文の数・語の位置 (UTF-8 のバイト位置)・切り出しを確かめる。
 * 読み込めない・形が違うときは { ok: false, why }。例外は投げない
 */
export function selfDiagnose(vendorDir?: string): Diag {
	try {
		const l = loadSyntax(vendorDir);
		if (!l.ok) return { ok: false, why: l.why };
		const S = l.syntax;
		// 1) 単純なコマンド: 文 1・語 4・語の始まりが 0 / 4 / 9 / 16
		let p = parseSource("git push origin main", vendorDir);
		if (!p.ok) return { ok: false, why: `自己診断 1: ${p.why}` };
		let stmts = arr(p.src.file.Stmts);
		let calls = callsOf(S, p.src.file);
		if (stmts.length !== 1 || calls.length !== 1) return { ok: false, why: "自己診断 1: 文・コマンドの数が期待と違う" };
		const w1 = arr(calls[0].Args).map((w: any) => pos(w));
		if (w1.join(",") !== "0,4,9,16") return { ok: false, why: `自己診断 1: 語の位置が期待と違う (${w1.join(",")})` };
		// 2) && とパイプ: 文 1 (BinaryCmd)・コマンド 3
		p = parseSource("cd /x && git log | head -3", vendorDir);
		if (!p.ok) return { ok: false, why: `自己診断 2: ${p.why}` };
		stmts = arr(p.src.file.Stmts);
		calls = callsOf(S, p.src.file);
		if (stmts.length !== 1 || typeOf(stmts[0].Cmd) !== "BinaryCmd" || calls.length !== 3) {
			return { ok: false, why: "自己診断 2: && とパイプの構造が期待と違う" };
		}
		// 3) 日本語: "確認" は 5 バイト目から 8 バイト (引用符込み)。位置が文字数でなくバイトであること
		p = parseSource('echo "確認"', vendorDir);
		if (!p.ok) return { ok: false, why: `自己診断 3: ${p.why}` };
		calls = callsOf(S, p.src.file);
		const words = calls.length === 1 ? arr(calls[0].Args) : [];
		if (words.length !== 2) return { ok: false, why: "自己診断 3: 語の数が期待と違う" };
		const a = pos(words[1]);
		const b = end(words[1]);
		if (a !== 5 || b !== 13 || cut(p.src, a, b) !== '"確認"') {
			return { ok: false, why: `自己診断 3: UTF-8 のバイト位置が期待と違う (${a}-${b})` };
		}
		return { ok: true, why: "既知の 3 コマンドの構造と位置が期待どおり" };
	} catch (e) {
		return { ok: false, why: `自己診断で例外: ${msg(e)}` };
	}
}
