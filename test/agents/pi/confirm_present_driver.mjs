// 確認の提示 (confirm-present.ts の presentConfirm) を、偽の ui で直接動かして固定する。結果を JSON で標準出力へ出す (照合は test_pi_confirm_present.py)。
//
//   node test/agents/pi/confirm_present_driver.mjs
//
// see docs/change/closed/0055-async-approval.md
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const { presentConfirm, VIEW_FULL, BACKSTOP_MS } = await import(pathToFileURL(resolve(ROOT, "home", "dot_config", "pi", "harness", "confirm-present.ts")).href);

const OPTIONS = ["承認して実行", VIEW_FULL, "拒否"];

/** select を、返す値の列で動かす偽の ui。値が関数なら呼ぶ (中断を待つ・例外を投げる用) */
function fakeUi(script, extra = {}) {
	const calls = { select: [], editor: [], custom: 0 };
	let i = 0;
	return {
		calls,
		ui: {
			select: async (title, options, opts) => {
				calls.select.push({ title, options, opts: { hasSignal: !!opts?.signal, timeout: opts?.timeout, aborted: opts?.signal?.aborted === true } });
				const step = script[Math.min(i++, script.length - 1)];
				return typeof step === "function" ? step(opts) : step;
			},
			editor: async (title, text) => {
				calls.editor.push({ title, text });
			},
			...extra,
		},
	};
}

const waitForAbort = (opts) =>
	new Promise((res) => {
		if (opts.signal.aborted) res(undefined);
		else opts.signal.addEventListener("abort", () => res(undefined), { once: true });
	});
const out = {};

// 1. 選ばれた値をそのまま返す。期限の保険 (BACKSTOP_MS) を足した timeout を select に渡す
{
	const { ui, calls } = fakeUi(["承認して実行"]);
	out.chosen = { result: await presentConfirm(ui, { title: "T", options: OPTIONS, timeoutMs: 1000 }), select: calls.select };
}

// 2. 期限なし (承認の時点の確認): timeout を渡さず、タイマーも無い
{
	const { ui, calls } = fakeUi(["拒否"]);
	out.no_timeout = { result: await presentConfirm(ui, { title: "T", options: OPTIONS }), select: calls.select };
}

// 3. 自前のタイマーが発火したら timedOut。select は中断される
{
	const { ui } = fakeUi([waitForAbort]);
	out.timeout = await presentConfirm(ui, { title: "T", options: OPTIONS, timeoutMs: 30 });
}

// 4. 呼び出し元の中断は、時間切れとは区別する
{
	const ac = new AbortController();
	const { ui } = fakeUi([waitForAbort]);
	setTimeout(() => ac.abort(), 20);
	out.caller_abort = await presentConfirm(ui, { title: "T", options: OPTIONS, timeoutMs: 5000, signal: ac.signal });
}
{
	const ac = new AbortController();
	ac.abort();
	const { ui, calls } = fakeUi([waitForAbort]);
	out.already_aborted = { result: await presentConfirm(ui, { title: "T", options: OPTIONS, timeoutMs: 5000, signal: ac.signal }), select: calls.select };
}

// 5. select が投げたら error (選択は無し)
{
	const { ui } = fakeUi([() => { throw new Error("ui の失敗"); }]);
	out.select_throws = await presentConfirm(ui, { title: "T", options: OPTIONS, timeoutMs: 1000 });
}

// 6. 「全文を見る」: ビューア (ui.custom) を開いて、閉じたら選び直す。text は押されたときに作る
{
	let made = 0;
	const { ui, calls } = fakeUi([VIEW_FULL, "承認して実行"], { custom: async () => { calls.custom++; } });
	const result = await presentConfirm(ui, { title: "T", options: OPTIONS, timeoutMs: 1000, viewFull: { title: "全文", text: () => { made++; return "本文"; } } });
	out.view_full = { result, selects: calls.select.length, custom: calls.custom, editor: calls.editor.length, made };
}
{
	const { ui, calls } = fakeUi(["承認して実行"], { custom: async () => { calls.custom++; } });
	let made = 0;
	const result = await presentConfirm(ui, { title: "T", options: OPTIONS, viewFull: { title: "全文", text: () => { made++; return "本文"; } } });
	out.view_full_not_pressed = { result, made, custom: calls.custom };
}

// 7. ui.custom が無い (RPC など) ときは editor で開く
{
	const { ui, calls } = fakeUi([VIEW_FULL, "拒否"]);
	const result = await presentConfirm(ui, { title: "T", options: OPTIONS, viewFull: { title: "全文", text: () => "本文" } });
	out.view_full_editor = { result, editor: calls.editor };
}

// 8. ビューアが投げても、確認に戻る
{
	const { ui, calls } = fakeUi([VIEW_FULL, "承認して実行"], { custom: async () => { throw new Error("描画の失敗"); } });
	out.viewer_throws = { result: await presentConfirm(ui, { title: "T", options: OPTIONS, viewFull: { title: "全文", text: () => "本文" } }), selects: calls.select.length };
}

// 9. 「全文を見る」のあとの select が投げても、無限に回らず error で返る (選択は残さない)
{
	const { ui, calls } = fakeUi([VIEW_FULL, () => { throw new Error("2 回目の失敗"); }], { custom: async () => {} });
	out.second_select_throws = { result: await presentConfirm(ui, { title: "T", options: OPTIONS, viewFull: { title: "全文", text: () => "本文" } }), selects: calls.select.length };
}

// 10. viewFull を渡していないのに「全文を見る」が選ばれたら、そのまま返す (呼び出し側が選択肢に出さない責任を持つ)
{
	const { ui, calls } = fakeUi([VIEW_FULL]);
	out.view_full_without_content = { result: await presentConfirm(ui, { title: "T", options: OPTIONS }), selects: calls.select.length };
}

out.backstop_ms = BACKSTOP_MS;
console.log(JSON.stringify(out));
