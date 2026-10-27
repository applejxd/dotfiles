// model-choice.ts の表試験 (CHG-0043)。結果を JSON で標準出力へ出す (照合は test_pi_model_choice.py)。
//
//   node test/agents/pi/model_choice_driver.mjs
//
// see docs/change/0043-model-catalog.md
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const mod = await import(pathToFileURL(join(ROOT, "home", "dot_config", "pi", "harness", "model-choice.ts")).href);
const { splitSpec, resolveChoice, modelArgument, describeChoice, catalogText, allowedList, parseEffort } = mod;

const copilot = {
	provider: "github-copilot",
	models: [
		{ id: "claude-sonnet-5.5", family: "claude-sonnet", generation: [5, 5], verified: true, cost: "normal" },
		{ id: "gpt-6.1-sol", family: "gpt-sol", generation: [6, 1], verified: true, cost: "normal" },
		{ id: "gpt-6.1-terra", family: "gpt-terra", generation: [6, 1], verified: true, cost: "normal" },
	],
};
const bedrock = {
	provider: "amazon-bedrock",
	models: [
		{ id: "us.anthropic.claude-opus-5-5", family: "claude-opus", generation: [5, 5], verified: false, cost: "high" },
		{ id: "us.openai.gpt-6.1-terra", family: "gpt-terra", generation: [6, 1], verified: false, cost: "normal" },
	],
};
const PARENT = "github-copilot/claude-sonnet-5.5";
const DEFAULTS = ["github-copilot/gpt-6.1-terra", "github-copilot/claude-sonnet-5.5:medium"];
const base = (o) => ({ parentModel: PARENT, catalog: copilot, agentDefaults: DEFAULTS, ...o });
const run = (o) => {
	try {
		const c = resolveChoice(base(o));
		return { ok: true, model: c.model, effort: c.effort ?? null, source: c.source, arg: modelArgument(c), inCatalog: c.inCatalog, unverified: c.unverified, cost: c.cost, line: describeChoice(c) };
	} catch (e) {
		return { ok: false, error: String(e.message) };
	}
};

const out = {};

out.split = {
	plain: splitSpec("gpt-6.1-sol"),
	with_provider: splitSpec("github-copilot/gpt-6.1-sol"),
	with_level: splitSpec("github-copilot/claude-sonnet-5.5:medium"),
	bedrock: splitSpec("amazon-bedrock/us.anthropic.claude-sonnet-5-5:low"),
	bedrock_version_suffix: splitSpec("amazon-bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0"),
	not_a_level: splitSpec("gpt-6.1-sol:bogus"),
	off: splitSpec("gpt-6.1-sol:off"),
};

// 既定 (省略): 役割の既定、無ければ親
out.defaults = {
	review: run({ agentDefault: "github-copilot/gpt-6.1-terra" }),
	worker_with_level: run({ agentDefault: "github-copilot/claude-sonnet-5.5:medium" }),
	explore_follows_parent: run({}),
};

// モデルの指定
out.model = {
	catalog_bare: run({ agentDefault: "github-copilot/gpt-6.1-terra", modelArg: "gpt-6.1-sol" }),
	catalog_qualified: run({ agentDefault: "github-copilot/gpt-6.1-terra", modelArg: "github-copilot/gpt-6.1-sol" }),
	parent_exact: run({ agentDefault: "github-copilot/gpt-6.1-terra", modelArg: PARENT }),
	not_in_catalog: run({ agentDefault: "github-copilot/gpt-6.1-terra", modelArg: "gpt-6-sol" }),
	old_generation: run({ modelArg: "claude-sonnet-5" }),
	haiku: run({ modelArg: "claude-haiku-5.5" }),
	other_provider_spoof: run({ modelArg: "amazon-bedrock/us.openai.gpt-6.1-terra" }),
	other_provider_same_id: run({ modelArg: "openai/gpt-6.1-sol" }),
	blank_is_unset: run({ agentDefault: "github-copilot/gpt-6.1-terra", modelArg: "  " }),
};

// effort の指定と優先順位
out.effort = {
	only_effort_on_default: run({ agentDefault: "github-copilot/gpt-6.1-terra", effortArg: "high" }),
	model_and_effort: run({ agentDefault: "github-copilot/gpt-6.1-terra", modelArg: "gpt-6.1-sol", effortArg: "max" }),
	suffix_only: run({ agentDefault: "github-copilot/gpt-6.1-terra", modelArg: "github-copilot/gpt-6.1-sol:low" }),
	effort_beats_suffix: run({ agentDefault: "github-copilot/gpt-6.1-terra", modelArg: "github-copilot/gpt-6.1-sol:low", effortArg: "xhigh" }),
	same_model_keeps_default_level: run({ agentDefault: "github-copilot/claude-sonnet-5.5:medium", modelArg: "github-copilot/claude-sonnet-5.5" }),
	other_model_drops_default_level: run({ agentDefault: "github-copilot/claude-sonnet-5.5:medium", modelArg: "gpt-6.1-sol" }),
	default_level_kept_without_args: run({ agentDefault: "github-copilot/claude-sonnet-5.5:medium" }),
	off: run({ agentDefault: "github-copilot/gpt-6.1-terra", effortArg: "off" }),
	off_suffix: run({ modelArg: "gpt-6.1-sol:off" }),
	bogus: run({ effortArg: "ultra" }),
	numeric: run({ effortArg: 3 }),
	filler_empty: run({ agentDefault: "github-copilot/gpt-6.1-terra", effortArg: "" }),
	filler_null: run({ agentDefault: "github-copilot/gpt-6.1-terra", effortArg: null }),
	every_level: Object.fromEntries(["minimal", "low", "medium", "high", "xhigh", "max"].map((l) => [l, run({ effortArg: l }).effort])),
};

// 親が別のプロバイダに切り替わったとき
{
	const o = { parentModel: "openai/gpt-6.1-sol", catalog: copilot, agentDefaults: DEFAULTS };
	const ok = (m) => {
		try {
			return resolveChoice({ ...o, modelArg: m }).model;
		} catch (e) {
			return `ERR ${e.message.split(".")[0]}`;
		}
	};
	out.other_provider_parent = { parent_exact: ok("openai/gpt-6.1-sol"), catalog: ok("gpt-6.1-sol"), spoof: ok("openai/gpt-6.1-terra") };
}

// カタログが無いプロバイダ (従来どおり: 親と役割の既定だけ)
{
	const o = { parentModel: "faux/spike", catalog: null, agentDefaults: ["faux/other"] };
	const ok = (m) => {
		try {
			return resolveChoice({ ...o, modelArg: m }).model;
		} catch (e) {
			return `ERR ${e.message.split(".")[0]}`;
		}
	};
	out.no_catalog = { parent: ok("faux/spike"), default: ok("faux/other"), other: ok("faux/third"), omitted: resolveChoice({ ...o }).model };
}

// 表示の印
out.flags = {
	bedrock_unverified: (() => {
		const c = resolveChoice({ parentModel: "amazon-bedrock/us.anthropic.claude-sonnet-5-5", catalog: bedrock, agentDefaults: [], modelArg: "us.openai.gpt-6.1-terra" });
		return { unverified: c.unverified, line: describeChoice(c) };
	})(),
	bedrock_high_cost: (() => {
		const c = resolveChoice({ parentModel: "amazon-bedrock/us.anthropic.claude-sonnet-5-5", catalog: bedrock, agentDefaults: [], modelArg: "us.anthropic.claude-opus-5-5", effortArg: "max" });
		return { cost: c.cost, line: describeChoice(c) };
	})(),
	parent_outside_catalog: run({ modelArg: PARENT }).inCatalog,
};

out.allowed = allowedList(base({}));
out.catalog_text = catalogText(copilot);
out.catalog_text_none = catalogText(null);
out.parse = { a: parseEffort("high") ?? null, b: parseEffort("") ?? null, c: parseEffort(undefined) ?? null };

process.stdout.write(JSON.stringify(out));
