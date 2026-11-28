const MODELS = new Set([
  "gemini-3.8-flash", "gemini-4-argon", "gemini-4-carbon", "gemini-4-hydrogen", "gemini-4-neon",
]);
const MAX_IMAGES = 10;
const MAX_BYTES = 4 * 1024 * 1024;
// テキスト・ツール定義・JSON の余地を残し、最後に実際の送信サイズを検査する。
const DEFAULT_OVERHEAD_BYTES = 512 * 1024;
const OMITTED = "[Copilot の画像上限のため過去の画像を省略。元の履歴には残っています。]";
const OMITTED_BYTES = Buffer.byteLength(OMITTED, "utf8");
const KNOWN_ROLES = new Set(["system", "developer", "assistant", "tool", "user"]);
const isTarget = (model) => model?.provider === "github-copilot" && model.api === "openai-completions" && MODELS.has(model.id);
const size = (value) => Buffer.byteLength(JSON.stringify(value), "utf8");
const mib = (bytes) => `${(bytes / (1024 * 1024)).toFixed(2)} MiB`;

function measureNonImageBytes(messages) {
  let bytes = 0;
  for (const message of messages) {
    if (!message || typeof message !== "object") {
      bytes += size(message);
      continue;
    }
    // 送信されない内部メタデータ（toolResult.details・usage など）を除き、ワイヤ相当の要素だけ測る。
    if (message.role === "system") {
      bytes += size({
        role: message.role,
        content: message.content,
        sections: message.sections,
        toolsAdded: message.toolsAdded,
      });
      continue;
    }
    if (!Array.isArray(message.content)) {
      bytes += size({ role: message.role, content: message.content, summary: message.summary, output: message.output, command: message.command });
      continue;
    }
    const content = message.content.map((part) => (part?.type === "image" ? null : part));
    bytes += size({ role: message.role, content, toolName: message.toolName, toolCallId: message.toolCallId });
  }
  return bytes;
}

function measureNonImage(messages) {
  try {
    return measureNonImageBytes(messages);
  } catch {
    return undefined;
  }
}

function planHistory(messages, overheadBytes = DEFAULT_OVERHEAD_BYTES) {
  const lastUser = messages.findLastIndex((message) => message.role === "user");
  const images = [];
  messages.forEach((message, messageIndex) => {
    if (!Array.isArray(message.content)) return;
    message.content.forEach((part, partIndex) => {
      if (part?.type === "image") {
        const url = `data:${part.mimeType};base64,${part.data}`;
        images.push({ messageIndex, partIndex, url, bytes: Buffer.byteLength(url, "utf8") });
      }
    });
  });
  const currentCount = images.filter(({ messageIndex }) => messageIndex >= lastUser).length;
  if (currentCount > MAX_IMAGES) {
    return { reason: `現在ターンだけで画像が ${currentCount} 枚あります（上限 10 枚）。分割するか、Sol の新規セッションへ切り出してください。` };
  }

  // 画像ゼロでも非画像バイト数を計っておき、送信直前でツール定義等のオーバーヘッドを正しく差分計測する。
  const nonImageBytes = measureNonImage(messages);
  if (images.length === 0) {
    return { messages: undefined, urls: [], omitted: 0, nonImageBytes };
  }

  // ネイティブの user / toolResult の区別がある段階だけで、過去の画像を減らす。
  // 画像単体ではなく、非画像コンテキストと直近のツール定義等のオーバーヘッドも含めた全体予算で判定する。
  const imageBudget = Math.max(0, MAX_BYTES - (nonImageBytes ?? 0) - overheadBytes);
  let imageBytes = images.reduce((sum, { bytes }) => sum + bytes, 0);
  const edited = new Map();
  let omitted = 0;
  for (const { messageIndex, partIndex, bytes } of images) {
    if (messageIndex >= lastUser || (images.length - omitted <= MAX_IMAGES && imageBytes <= imageBudget)) break;
    const message = messages[messageIndex];
    const copy = edited.get(messageIndex) ?? { ...message, content: [...message.content] };
    copy.content[partIndex] = { type: "text", text: OMITTED };
    edited.set(messageIndex, copy);
    imageBytes = Math.max(0, imageBytes - bytes + OMITTED_BYTES);
    omitted++;
  }
  return {
    messages: omitted ? messages.map((message, i) => edited.get(i) ?? message) : undefined,
    urls: images.slice(omitted).map(({ url }) => url),
    omitted,
    nonImageBytes: nonImageBytes === undefined ? undefined : nonImageBytes + omitted * OMITTED_BYTES,
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
  const observedOverheadByModel = new Map();
  pi.on("session_start", () => {
    pending = undefined;
    observedOverheadByModel.clear();
  });
  // 同じ要求を別の signal で再送する cache warming は、現在ターンの照合を通らない。
  pi.on("cache_warming_decision", (_event, ctx) => isTarget(ctx.model) ? { action: "stop" } : undefined);
  pi.on("context_with_system", (event, ctx) => {
    pending = undefined;
    if (!isTarget(ctx.model)) return;
    const overhead = observedOverheadByModel.get(ctx.model.id) ?? DEFAULT_OVERHEAD_BYTES;
    const { messages, ...plan } = planHistory(event.messages, overhead);
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
    const imageBytes = urls.reduce((sum, url) => sum + Buffer.byteLength(url, "utf8"), 0);
    // ツール定義や変換後の JSON 差分をモデルごとの次回見積もりへ反映する（下限は既定の余地、上限で過大評価を防ぐ）。
    if (plan.nonImageBytes !== undefined) {
      const extraBytes = bytes - imageBytes - plan.nonImageBytes;
      observedOverheadByModel.set(
        ctx.model.id,
        extraBytes > 0 ? Math.min(MAX_BYTES, Math.max(DEFAULT_OVERHEAD_BYTES, extraBytes + 64 * 1024)) : DEFAULT_OVERHEAD_BYTES,
      );
    }
    // 画像 0 枚のリクエストは画像ガードで止めない（長文テキスト会話は Pi 本体の圧縮・リトライに任せる）。
    if (urls.length > MAX_IMAGES || (urls.length > 0 && bytes > MAX_BYTES)) {
      stop(ctx, `過去の画像を除いても上限を超えます（画像 ${urls.length} 枚 / 全体 ${mib(bytes)} / 画像 ${mib(imageBytes)}、上限 10 枚・4 MiB）。画像の分割・縮小、または Sol の新規セッションを使ってください。`);
      return;
    }
    if (plan?.omitted) notify(ctx, `Copilot Gemini: 過去の画像を ${plan.omitted} 枚省略しました（履歴は保持）。`, "info");
  });
}
