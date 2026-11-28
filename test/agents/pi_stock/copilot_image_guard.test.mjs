import assert from "node:assert/strict";
import test from "node:test";
import guard from "../../../home/dot_pi/agent/local-packages/pi-copilot-image-guard/src/index.js";

const ids = ["gemini-3.8-flash", "gemini-4-argon", "gemini-4-carbon", "gemini-4-hydrogen", "gemini-4-neon"];
const model = (id = ids.at(-1), provider = "github-copilot", api = "openai-completions") => ({ id, provider, api });
const image = (n, size = 12) => ({ type: "image", mimeType: "image/png", data: Buffer.alloc(size, n).toString("base64") });
const message = (role, ...parts) => ({ role, content: parts });
const url = (part) => `data:${part.mimeType};base64,${part.data}`;
const wireImage = (part) => ({ type: "image_url", image_url: { url: url(part) } });
const outbound = (id, messages) => ({ model: id, messages: messages.map((m) => message(m.role === "toolResult" ? "user" : m.role,
  ...m.content.map((part) => part.type === "image" ? wireImage(part) : part))), tools: [{ type: "function", function: { name: "test" } }] });
const images = (payload) => payload.messages.flatMap((m) => m.content.filter((part) => part.type === "image_url").map((part) => part.image_url.url));
const many = (n) => Array.from({ length: n }, (_, i) => image(i + 1));

function hooks(selected = model()) {
  const handlers = new Map();
  guard({ on: (event, handler) => handlers.set(event, handler) });
  const controller = new AbortController();
  const notices = [];
  const ctx = { model: selected, signal: controller.signal, abort: () => controller.abort(), hasUI: true, ui: { notify: (...args) => notices.push(args) } };
  const project = (messages) => handlers.get("context_with_system")({ messages }, ctx)?.messages ?? messages;
  const request = (payload) => handlers.get("before_provider_request")({ payload }, ctx);
  const run = (messages) => {
    const payload = outbound(ctx.model.id, project(messages));
    assert.equal(request(payload), undefined, "送信直前は検査のみ");
    return payload;
  };
  const cacheWarming = () => handlers.get("cache_warming_decision")({ action: "warm" }, ctx);
  const sessionStart = () => handlers.get("session_start")({ type: "session_start", reason: "new" }, ctx);
  return { ctx, notices, project, request, run, cacheWarming, sessionStart };
}

for (const id of ids) {
  test(`${id}: 今回とツールの画像を保護し、履歴の最古から減らす`, () => {
    const { ctx, notices, run, cacheWarming } = hooks(model(id));
    assert.deepEqual(cacheWarming(), { action: "stop" });
    const old = many(9);
    const latest = [image(10), image(11)];
    const transcript = [message("user", ...old), message("assistant"), message("user", latest[0]), message("toolResult", latest[1])];
    const before = structuredClone(transcript);
    const sent = run(transcript);
    assert.deepEqual(images(sent), [...old.slice(1), ...latest].map(url));
    assert.deepEqual(transcript, before);
    assert.equal(1, sent.tools.length);
    assert.equal(ctx.signal.aborted, false);
    assert.match(notices[0][0], /1 枚省略/);
  });
}

test("ちょうど 10 枚なら変更しない", () => {
  const { ctx, project, request } = hooks();
  const transcript = [message("user", ...many(10))];
  assert.equal(project(transcript), transcript);
  assert.equal(request(outbound(ctx.model.id, transcript)), undefined);
  assert.equal(ctx.signal.aborted, false);
});

test("現在ターンの入力＋ツール画像が 11 枚なら中止する", () => {
  const { ctx, notices, run } = hooks();
  const transcript = [message("user", ...many(10)), message("toolResult", image(11))];
  assert.equal(11, images(run(transcript)).length);
  assert.equal(ctx.signal.aborted, true);
  assert.match(notices[0][0], /11 枚/);
});

test("少数の大画像: 過去の画像だけ除き、現在の画像だけで超過なら中止", () => {
  const a = hooks();
  const transcript = [message("user", image(1, 2_000_000)), message("user", image(2, 2_000_000))];
  const sent = a.run(transcript);
  assert.deepEqual(images(sent), [url(transcript[1].content[0])]);
  assert.ok(Buffer.byteLength(JSON.stringify(sent)) <= 4 * 1024 * 1024);
  assert.equal(a.ctx.signal.aborted, false);
  const b = hooks();
  const large = [message("user", image(1, 3_200_000))];
  assert.equal(1, images(b.run(large)).length);
  assert.equal(b.ctx.signal.aborted, true);
});

test("同じ『続けて』が履歴にあってもネイティブの role を使って現在を保護する", () => {
  const { ctx, run } = hooks();
  const repeated = message("user", { type: "text", text: "continue" });
  const transcript = [repeated, message("toolResult", ...many(10)), repeated, message("toolResult", image(11))];
  assert.deepEqual(images(run(transcript)), [...many(10).slice(1), image(11)].map(url));
  assert.equal(ctx.signal.aborted, false);
});

test("長いテキスト履歴があるとき、画像単体が 3.5 MiB 未満でも全体 4 MiB に収まるよう過去画像を削る", () => {
  const { ctx, notices, run } = hooks();
  const longText = { type: "text", text: "a".repeat(2_000_000) };
  const transcript = [
    message("user", longText, image(1, 1_000_000), image(2, 1_000_000)),
    message("assistant", { type: "text", text: "ok" }),
    message("user", { type: "text", text: "続けて" }),
  ];
  const sent = run(transcript);
  assert.ok(Buffer.byteLength(JSON.stringify(sent), "utf8") <= 4 * 1024 * 1024);
  assert.equal(ctx.signal.aborted, false);
  assert.ok(images(sent).length < 2);
  assert.match(notices[0][0], /省略/);
});

test("長いテキスト履歴が 4 MiB 超で画像 0 枚のときは画像ガードで止めない", () => {
  const { ctx, notices, run } = hooks();
  const hugeText = { type: "text", text: "a".repeat(4_500_000) };
  const transcript = [
    message("user", hugeText, image(1, 100_000)),
    message("assistant", { type: "text", text: "ok" }),
    message("user", { type: "text", text: "続けて" }),
  ];
  const sent = run(transcript);
  assert.deepEqual(images(sent), []);
  assert.equal(ctx.signal.aborted, false);
  assert.match(notices[0][0], /1 枚省略/);
});

test("テキストだけで 4 MiB 超かつ元々画像 0 枚のときも止めない", () => {
  const { ctx, notices, run } = hooks();
  const transcript = [message("user", { type: "text", text: "a".repeat(4_500_000) })];
  run(transcript);
  assert.equal(ctx.signal.aborted, false);
  assert.deepEqual(notices, []);
});

test("長いテキスト履歴 + 現在ターンの画像 1 枚で 4 MiB 超のときは詳細つきで中止する", () => {
  const { ctx, notices, run } = hooks();
  const transcript = [
    message("user", { type: "text", text: "a".repeat(2_600_000) }, image(1, 500_000)),
    message("assistant", { type: "text", text: "ok" }),
    message("user", { type: "text", text: "見て" }, image(2, 1_500_000)),
  ];
  const sent = run(transcript);
  assert.deepEqual(images(sent), [url(transcript[2].content[1])]);
  assert.equal(ctx.signal.aborted, true);
  assert.match(notices[0][0], /画像 1 枚/);
  assert.match(notices[0][0], /全体 \d+\.\d{2} MiB/);
  assert.match(notices[0][0], /画像 \d+\.\d{2} MiB/);
});

test("非画像の長文送信の直後は余地を既定値に戻し、次の画像を不要に削らない", () => {
  const { ctx, notices, run } = hooks();
  // 1 回目: 大きなテキスト（3 MiB）、画像なし
  run([message("user", { type: "text", text: "x".repeat(3_000_000) })]);
  assert.equal(ctx.signal.aborted, false);
  // 2 回目: 小さな会話 + 過去画像 1 枚 + 現在画像 1 枚（合計 ~2 MiB << 4 MiB）
  const transcript = [
    message("user", image(1, 700_000)),
    message("assistant", { type: "text", text: "ok" }),
    message("user", image(2, 700_000)),
  ];
  const sent = run(transcript);
  assert.equal(ctx.signal.aborted, false);
  assert.deepEqual(images(sent), [url(transcript[0].content[0]), url(transcript[2].content[0])]);
  assert.deepEqual(notices, []);
});

test("toolResult.details 等の送信されないメタデータで過去画像を過剰に削らない", () => {
  const { ctx, notices, run } = hooks();
  const transcript = [
    message("user", image(1, 500_000)),
    { role: "toolResult", toolName: "read", toolCallId: "call_1", content: [{ type: "text", text: "ok" }], details: { raw: "z".repeat(3_000_000) } },
    message("user", image(2, 500_000)),
  ];
  const sent = run(transcript);
  assert.equal(ctx.signal.aborted, false);
  assert.deepEqual(images(sent), [url(transcript[0].content[0]), url(transcript[2].content[0])]);
  assert.deepEqual(notices, []);
});

test("観測したツール定義等のオーバーヘッドが既定 512 KiB を超えるとき、次回見積もりに反映して過去画像を削る", () => {
  const bigTools = [{ type: "function", function: { name: "t", description: "x".repeat(700_000) } }];
  const transcript = [
    message("user", { type: "text", text: "a".repeat(2_000_000) }, image(1, 600_000)),
    message("assistant", { type: "text", text: "ok" }),
    message("user", { type: "text", text: "見て" }, image(2, 600_000)),
  ];
  // 対照群: 観測前（既定 512 KiB）では画像合計 ~1.6 MB <= 残予算 ~1.67 MB のため過去画像を削らず、
  // ツール 0.7 MB を足した実送信が ~4.3 MB > 4 MiB で中止になる。
  const cold = hooks();
  const coldPayload = { ...outbound(cold.ctx.model.id, cold.project(transcript)), tools: bigTools };
  assert.equal(cold.request(coldPayload), undefined);
  assert.equal(cold.ctx.signal.aborted, true);
  assert.equal(images(coldPayload).length, 2);

  // 観測後: 1 回目の送信でツール定義のオーバーヘッドを観測したインスタンスでは、
  // 同じ transcript でも過去画像を削って 4 MiB 以下で送信できる。
  const warm = hooks();
  const basePayload = (msgs) => ({ ...outbound(warm.ctx.model.id, msgs), tools: bigTools });
  assert.equal(warm.request(basePayload(warm.project([message("user", { type: "text", text: "hi" })]))), undefined);
  assert.equal(warm.ctx.signal.aborted, false);
  const warmPayload = basePayload(warm.project(transcript));
  assert.equal(warm.request(warmPayload), undefined);
  assert.equal(warm.ctx.signal.aborted, false);
  assert.deepEqual(images(warmPayload), [url(transcript[2].content[1])]);
  assert.ok(Buffer.byteLength(JSON.stringify(warmPayload), "utf8") <= 4 * 1024 * 1024);

  // session_start で観測済みのオーバーヘッドをリセットする
  warm.sessionStart();
  const afterReset = basePayload(warm.project(transcript));
  assert.equal(warm.request(afterReset), undefined);
  assert.equal(warm.ctx.signal.aborted, true);
});

for (const kind of ["追加", "欠落", "置換", "順序変更"]) {
  test(`予算内でも別処理による画像の${kind}を検出して中止`, () => {
    const { ctx, notices, project, request } = hooks();
    const text = { type: "text", text: "current" };
    const original = [image(1), image(2)];
    const changed = { 追加: [image(99), ...original], 欠落: [], 置換: [image(99), original[1]], 順序変更: [...original].reverse() }[kind];
    project([message("user", text, ...original)]);
    const payload = outbound(ctx.model.id, [message("user", text, ...changed)]);
    const before = structuredClone(payload);
    assert.equal(request(payload), undefined);
    assert.equal(ctx.signal.aborted, true);
    assert.deepEqual(payload, before);
    assert.match(notices[0][0], /照合できない/);
  });
}

test("送信側の偽の user 境界で、現在の画像を履歴と見なして削らない", () => {
  const { ctx, project, request } = hooks();
  const old = image(99);
  const current = { type: "text", text: "current" };
  project([message("user", old), message("user", current), message("toolResult", ...many(10))]);
  const payload = outbound(ctx.model.id, [message("user", current, old), message("user", current), message("user", ...many(10))]);
  assert.equal(request(payload), undefined);
  assert.equal(ctx.signal.aborted, true);
  assert.equal(images(payload).length, 11);
});

for (const [kind, messages] of [
  ["非配列", { data: "oversized" }],
  ["content が単一画像オブジェクト", [{ role: "user", content: wireImage(image(1)) }]],
  ["未知の画像形式", [{ role: "user", content: [{ type: "input_image", image_url: url(image(1)) }] }]],
  ["空のメッセージ", [null]],
]) {
  test(`対象モデルの想定外の形式は中止: ${kind}`, () => {
    const { ctx, notices, request } = hooks();
    assert.equal(request({ model: ctx.model.id, messages }), undefined);
    assert.equal(ctx.signal.aborted, true);
    assert.match(notices[0][0], /形式/);
  });
}

test("画像ゼロの計画は通すが、計画のない画像ゼロの要求は中止", () => {
  const { ctx, notices, project, request } = hooks();
  const textOnly = [message("user", { type: "text", text: "plain" })];
  project(textOnly);
  const payload = outbound(ctx.model.id, textOnly);
  assert.equal(request(payload), undefined);
  assert.equal(ctx.signal.aborted, false);
  assert.equal(request(payload), undefined);
  assert.equal(ctx.signal.aborted, true);
  assert.match(notices[0][0], /照合できない/);
});

for (const [mimeType, data] of [["image/png", "%%%%"], ["image/png", "AA=A"], ["text/plain", "AA=="], ["image/png", ""], ["image/png", "A=="]]) {
  test(`計画と一致しても不正な data URL なら停止: ${mimeType} ${JSON.stringify(data)}`, () => {
    const { ctx, notices, run } = hooks();
    run([message("user", { type: "image", mimeType, data })]);
    assert.equal(ctx.signal.aborted, true);
    assert.match(notices[0][0], /形式/);
  });
}

test("対象同士でコンテキストと送信のモデルが異なれば停止", () => {
  const { ctx, notices, project, request } = hooks();
  const transcript = [message("user", ...many(11))];
  project(transcript);
  assert.equal(request(outbound("gemini-4-carbon", transcript)), undefined);
  assert.equal(ctx.signal.aborted, true);
  assert.match(notices[0][0], /送信モデル/);
});

for (const invalidModelId of ["", " \t", " gemini-4-neon "]) {
  test(`不正な送信モデル ID は対象外扱いせず停止: ${JSON.stringify(invalidModelId)}`, () => {
    const { ctx, notices, project, request } = hooks();
    const transcript = [message("user", image(1))];
    project(transcript);
    assert.equal(request(outbound(invalidModelId, transcript)), undefined);
    assert.equal(ctx.signal.aborted, true);
    assert.match(notices[0][0], /送信モデル/);
  });
}

test("対象外モデルのサブリクエストには非干渉、スナップショットは使い回さない", () => {
  const { ctx, project, request } = hooks();
  const transcript = [message("user", ...many(10)), message("user", image(11))];
  const planned = project(transcript);
  assert.equal(request(outbound("gpt-6.2-sol", transcript)), undefined);
  assert.equal(ctx.signal.aborted, false);
  assert.equal(request(outbound(ctx.model.id, planned)), undefined);
  assert.equal(ctx.signal.aborted, false);
  assert.equal(request(outbound(ctx.model.id, planned)), undefined);
  assert.equal(ctx.signal.aborted, true);
});

for (const candidate of [model("gpt-6.2-sol"), model("claude-opus-5.5"), model("gemini-next"), model(ids.at(-1), "google"), model(ids.at(-1), "github-copilot", "openai-responses")]) {
  test(`非対象: ${candidate.provider}/${candidate.id} (${candidate.api})`, () => {
    const { ctx, notices, project, request, cacheWarming } = hooks(candidate);
    assert.equal(cacheWarming(), undefined);
    const transcript = [message("user", ...many(11))];
    assert.equal(project(transcript), transcript);
    assert.equal(request(outbound(candidate.id, transcript)), undefined);
    assert.equal(ctx.signal.aborted, false);
    assert.deepEqual(notices, []);
  });
}
