// 子エージェントのモデルと effort (推論の強さ) の選択 (CHG-0043)。判定は純粋な関数で、pi には依存しない。
//
// - 選べるモデル = カタログ (設定のプロバイダのもの) ∪ 親の完全な provider/id ∪ 役割の既定のモデル
// - effort は別の引数 (minimal / low / medium / high / xhigh / max)。`off` は選ばせない
//   (Claude Sonnet 5.5 は `:off` で HTTP 400 になる。2026-10-27 実測)。モデルが対応しない段は pi が丸める
// - 優先順位: 明示の effort > 明示の model の接尾辞 (`id:level`) >（モデルを上書きしないときの）役割の既定の effort > pi の既定
// - 結果には、使ったモデルと effort・既定か指定か・未確認・高コストの印を必ず出す (表示は安全境界ではない。U1 は利用者が受容)
//
// node の型除去でそのまま動く書き方だけを使う (コンストラクタの引数プロパティ・enum は使わない)。
// see docs/change/0043-model-catalog.md

export const EFFORTS = ["minimal", "low", "medium", "high", "xhigh", "max"] as const;
export type Effort = (typeof EFFORTS)[number];
const LEVELS = new Set<string>(["off", ...EFFORTS]);

export interface CatalogEntry {
	id: string;
	family: string;
	generation: number[];
	verified: boolean;
	cost: string;
	note?: string;
}
export interface Catalog {
	provider: string;
	reviewed_on?: string;
	enforce_verified?: boolean;
	models: CatalogEntry[];
}

export interface Spec {
	provider?: string;
	id: string;
	level?: string;
}

/** `[provider/]id[:level]` を分ける。level は pi の thinking の段のときだけ (Bedrock の `...-v2:0` は id のまま) */
export function splitSpec(spec: string): Spec {
	let rest = spec.trim();
	let level: string | undefined;
	const colon = rest.lastIndexOf(":");
	if (colon > 0 && LEVELS.has(rest.slice(colon + 1))) {
		level = rest.slice(colon + 1);
		rest = rest.slice(0, colon);
	}
	const slash = rest.indexOf("/");
	if (slash > 0) return { provider: rest.slice(0, slash), id: rest.slice(slash + 1), ...(level ? { level } : {}) };
	return { id: rest, ...(level ? { level } : {}) };
}

export interface Choice {
	/** 完全修飾 (`provider/id`)。`--model` へは、effort があれば `:effort` を付けて渡す */
	model: string;
	effort?: Effort;
	source: "default" | "specified";
	/** 役割の既定 (比べるため。既定が無ければ親のモデル) */
	defaultModel: string;
	inCatalog: boolean;
	unverified: boolean;
	cost: string;
}

export interface ChoiceInput {
	/** 親が今使っているモデル (`provider/id`) */
	parentModel: string;
	catalog: Catalog | null | undefined;
	/** 役割の既定 (`provider/id[:level]`)。無ければ親に追従 */
	agentDefault?: string | null;
	/** 宣言済みの全役割の既定 (許可の集合に入る) */
	agentDefaults: string[];
	modelArg?: string;
	effortArg?: string;
}

const full = (s: Spec, fallbackProvider: string): string => `${s.provider ?? fallbackProvider}/${s.id}`;

export function parseEffort(value: unknown): Effort | undefined {
	if (value === undefined || value === null || value === "" || value === false || value === 0) return undefined; // 埋め草
	if (typeof value !== "string" || !(EFFORTS as readonly string[]).includes(value)) {
		throw new Error(`effort must be one of: ${EFFORTS.join(", ")} (got ${JSON.stringify(value)}; "off" is not allowed)`);
	}
	return value as Effort;
}

/** 許可の集合を、人に見せる一覧にする */
export function allowedList(input: ChoiceInput): string[] {
	const parent = splitSpec(input.parentModel);
	const provider = input.catalog?.provider ?? parent.provider ?? "";
	const out: string[] = [];
	const add = (s: string) => {
		if (!out.includes(s)) out.push(s);
	};
	for (const m of input.catalog?.models ?? []) add(`${provider}/${m.id}`);
	add(input.parentModel);
	for (const d of input.agentDefaults) {
		const s = splitSpec(d);
		add(full(s, provider));
	}
	return out;
}

export function resolveChoice(input: ChoiceInput): Choice {
	const parent = splitSpec(input.parentModel);
	if (!parent.provider) throw new Error(`parent model has no provider: ${input.parentModel}`);
	const parentFull = full(parent, parent.provider);
	const configured = input.catalog?.provider ?? parent.provider;
	const def = input.agentDefault ? splitSpec(input.agentDefault) : { provider: parent.provider, id: parent.id };
	const defFull = full(def, configured);
	const effortArg = parseEffort(input.effortArg);

	const entryOf = (provider: string, id: string): CatalogEntry | undefined =>
		provider === configured ? input.catalog?.models.find((m) => m.id === id) : undefined;
	const describe = (modelFull: string) => {
		const s = splitSpec(modelFull);
		const e = s.provider ? entryOf(s.provider, s.id) : undefined;
		return { inCatalog: e !== undefined, unverified: e !== undefined && !e.verified, cost: e?.cost ?? "normal" };
	};

	const modelArg = typeof input.modelArg === "string" && input.modelArg.trim() !== "" ? input.modelArg.trim() : undefined;
	if (!modelArg) {
		return {
			model: defFull,
			...(effortArg ? { effort: effortArg } : def.level && def.level !== "off" ? { effort: def.level as Effort } : {}),
			source: effortArg ? "specified" : "default",
			defaultModel: defFull,
			...describe(defFull),
		};
	}

	const spec = splitSpec(modelArg);
	if (spec.level === "off") throw new Error(`effort "off" is not allowed (model: ${modelArg})`);
	const wanted = full(spec, configured);
	const allowed = allowedList(input);
	const allowedFull = new Set(allowed);
	// 設定と違うプロバイダは、親の完全な provider/id と役割の既定に一致するときだけ許可される (allowedList に入っている)
	if (!allowedFull.has(wanted)) {
		throw new Error(`model not allowed: ${modelArg}. Allowed: ${allowed.join(", ")}`);
	}
	// 明示の effort > 明示の model の接尾辞 >（同じモデルなら）役割の既定の effort > pi の既定
	let effort: Effort | undefined = effortArg;
	if (!effort && spec.level) effort = spec.level as Effort;
	if (!effort && wanted === defFull && def.level && def.level !== "off") effort = def.level as Effort;
	return {
		model: wanted,
		...(effort ? { effort } : {}),
		source: "specified",
		defaultModel: defFull,
		...describe(wanted),
	};
}

/** pi の `--model` に渡す文字列 */
export function modelArgument(choice: Choice): string {
	return choice.effort ? `${choice.model}:${choice.effort}` : choice.model;
}

/** 結果に必ず出す 1 行 */
export function describeChoice(choice: Choice): string {
	const parts = [`model: ${choice.model}`, `effort: ${choice.effort ?? "(pi default)"}`];
	parts.push(choice.source === "specified" ? `specified by the caller (role default: ${choice.defaultModel})` : "role default");
	if (!choice.inCatalog) parts.push("outside the catalog (parent or role default)");
	if (choice.unverified) parts.push("UNVERIFIED (tool calling not confirmed)");
	if (choice.cost === "high") parts.push("HIGH COST");
	return parts.join(", ");
}

/** `guarded_task` の説明に出す、カタログの一覧 */
export function catalogText(catalog: Catalog | null | undefined): string {
	if (!catalog || catalog.models.length === 0) return "";
	const rows = catalog.models.map((m) => {
		const flags = [`${m.family} ${m.generation.join(".")}`, m.verified ? "verified" : "UNVERIFIED", m.cost === "high" ? "HIGH COST" : ""]
			.filter(Boolean)
			.join(", ");
		return `  - ${catalog.provider}/${m.id} (${flags})`;
	});
	return (
		"Models you may set with `model` (only when the user asks for one; otherwise omit it and the role default is used):\n" +
		`${rows.join("\n")}\n` +
		`\`effort\` (only when the user asks): ${EFFORTS.join(" | ")}. A level the model does not support is clamped by pi. Never use "off".`
	);
}

// 子の 1 往復の上限 (ミリ秒)。役割の timeout_minutes (省略・不正は 15 分)。試験は環境変数で全部を上書きする。
// 「まとめに入れ」の steer は、この上限の 0.8 倍で送られる (children.ts)
export const DEFAULT_ROUND_MINUTES = 15;
export const roundTimeoutMs = (agents: Record<string, any>, agentName: string): number =>
	Number(process.env.PI_HARNESS_TEST_ROUND_MS) || (Number(agents[agentName]?.timeout_minutes) || DEFAULT_ROUND_MINUTES) * 60 * 1000;
