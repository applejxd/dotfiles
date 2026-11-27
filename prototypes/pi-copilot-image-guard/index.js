const MODELS = new Set([
  "gemini-3.8-flash", "gemini-4-argon", "gemini-4-carbon", "gemini-4-hydrogen", "gemini-4-neon",
]);
const MAX_IMAGES = 10;
const MAX_BYTES = 4 * 1024 * 1024;
// テキスト・ツール定義・JSON の余地を残し、最後に実際の送信サイズを検査する。
const IMAGE_BUDGET = MAX_BYTES - 512 * 1024;
const OMITTED = "[Copilot の画像上限のため過去の画像を省略。元の履歴には残っています。]";
const KNOWN_ROLES = new Set(["system", "developer", "assistant", "tool", "user"]);
const isTarget = (model) => model?.provider === "github-copilot" && model.api === "openai-completions" && MODELS.has(model.id);
const size = (value) => Buffer.byteLength(JSON.stringify(value), "utf8");

function planHistory(messages) {
  const lastUser = messages.findLastIndex((message) => message.role === "user");
  const images = [];
  messages.forEach((message, messageIndex) => {
    if (!Array.isArray(message.content)) return;
    message.content.forEach((part, partIndex) => {
      if (part?.type === "image") {
        images.push({ messageIndex, partIndex, url: `data:${part.mimeType};base64,${part.data}` });
      }
    });
  });
  const currentCount = images.filter(({ messageIndex }) => messageIndex >= lastUser).length;
  if (currentCount > MAX_IMAGES) {
    return { reason: `現在ターンだけで画像が ${currentCount} 枚あります（上限 10 枚）。分割するか、Sol の新規セッションへ切り出してください。` };
  }

  // ネイティブの user / toolResult の区別がある段階だけで、過去の画像を減らす。
  let bytes = images.reduce((sum, { url }) => sum + Buffer.byteLength(url, "utf8"), 0);
  const edited = new Map();
  let omitted = 0;
  for (const { messageIndex, partIndex, url } of images) {
    if (messageIndex >= lastUser || (images.length - omitted <= MAX_IMAGES && bytes <= IMAGE_BUDGET)) break;
    const message = messages[messageIndex];
    const copy = edited.get(messageIndex) ?? { ...message, content: [...message.content] };
    copy.content[partIndex] = { type: "text", text: OMITTED };
    edited.set(messageIndex, copy);
    bytes -= Buffer.byteLength(url, "utf8");
    omitted++;
  }
  return {
    messages: omitted ? messages.map((message, i) => edited.get(i) ?? message) : undefined,
    urls: images.slice(omitted).map(({ url }) => url),
    omitted,
  };
}

function isImageDataUrl(url) {
  if (typeof url !== "string") return false;
  const comma = url.indexOf(",");
  if (comma < 0 || !/^data:image\/[a-z0-9][a-z0-9.+-]*;base64$/i.test(url.slice(0, comma))) return false;
  const data = url.slice(comma + 1);
  if (!data.length || data.length % 4) return false;
  const padding = data.endsWith("==") ? 2 : data.endsWith("=") ? 1 : 0;
  return !/[^A-Za-z0-9+/]/.test(data.slice(0, data.length - padding));
}

function outboundImages(messages) {
  const urls = [];
  for (const message of messages) {
    if (!KNOWN_ROLES.has(message?.role)) return;
    const content = message.content;
    if (typeof content === "string" || (content == null && message.role === "assistant")) continue;
    if (!Array.isArray(content)) return;
    for (const part of content) {
      if (part?.type === "text" && typeof part.text === "string") continue;
      if (message.role !== "user" || part?.type !== "image_url" || !isImageDataUrl(part.image_url?.url)) return;
      urls.push(part.image_url.url);
    }
  }
  return urls;
}

function notify(ctx, text, level) {
  if (ctx.hasUI) ctx.ui.notify(text, level);
  else console.error(text);
}

function stop(ctx, reason) {
  // Pi は provider フックの例外を捕まえるので、実際の送信を signal で中止する。
  ctx.abort();
  notify(ctx, `Copilot Gemini の画像ガード: ${reason}`, "error");
}

export default function copilotImageGuard(pi) {
  let pending;
  pi.on("context_with_system", (event, ctx) => {
    pending = undefined;
    if (!isTarget(ctx.model)) return;
    const { messages, ...plan } = planHistory(event.messages);
    pending = { id: ctx.model.id, signal: ctx.signal, ...plan };
    if (messages) return { messages };
  });
  pi.on("before_provider_request", (event, ctx) => {
    const payload = event.payload;
    // 親と別モデルの要約などには干渉しない。ここでは payload を書き換えない。
    if (!isTarget(ctx.model)) return;
    const modelId = payload?.model;
    const namedModel = typeof modelId === "string" && modelId.length > 0 && !/\s/u.test(modelId);
    if (namedModel && modelId !== ctx.model.id && !MODELS.has(modelId)) return;
    const plan = pending?.id === ctx.model.id && pending.signal === ctx.signal ? pending : undefined;
    pending = undefined;
    if (modelId !== ctx.model.id || !Array.isArray(payload.messages)) {
      stop(ctx, "想定した送信モデルまたは送信形式と一致しないため中止しました。");
      return;
    }
    if (plan?.reason) {
      stop(ctx, plan.reason);
      return;
    }
    const urls = outboundImages(payload.messages);
    if (!urls) {
      stop(ctx, "想定したメッセージ形式と一致しないため中止しました。");
      return;
    }
    const expected = plan?.urls;
    if (!expected || urls.length !== expected.length || !urls.every((url, i) => url === expected[i])) {
      stop(ctx, "送信画像を現在のコンテキストと照合できないため中止しました。新規セッションまたは Sol で試してください。");
      return;
    }
    let bytes;
    try {
      bytes = size(payload);
    } catch {
      stop(ctx, "送信サイズを確認できないため中止しました。");
      return;
    }
    if (urls.length > MAX_IMAGES || bytes > MAX_BYTES) {
      stop(ctx, "過去の画像を除いても 10 枚または 4 MiB の予算を超えます。画像の分割・縮小、または Sol の新規セッションを使ってください。");
      return;
    }
    if (plan?.omitted) notify(ctx, `Copilot Gemini: 過去の画像を ${plan.omitted} 枚省略しました（履歴は保持）。`, "info");
  });
}
