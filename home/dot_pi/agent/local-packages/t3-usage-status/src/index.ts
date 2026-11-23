/**
 * t3-usage-status: pi のセッションのキャッシュヒット率 (CH%)・費用・コンテキスト使用率を T3 Code に出す。
 *
 * pi の TUI のフッターは費用・最新の CH%・コンテキスト使用率を出すが、T3 Code の中で動く pi にはフッターが無い。
 * そこでセッションのエントリから CH% と費用を、pi 自身のフッター
 * (dist/modes/interactive/components/footer.js) と同じ計算で求め、コンテキスト使用率は ctx.getContextUsage() から得て、
 * ctx.ui.setStatus で出す。T3 は「Pi · CH97.2% $24.480 ctx41.2%」という入力欄のバナーにする (web・モバイル)。
 *
 * 並び順: T3 は status を key ごとに、最初に出した順に並べる (「Pi · <text> · <text>」)。この拡張の key (usage) が
 * 先頭になるよう、コンテキスト使用率は、空のセッションでも (不明なら ctx--) 出す。sandbox・TPS/TTFT は別の拡張の key。
 *
 * 出すのは RPC モード (ctx.mode === "rpc") のときだけ。T3 は常に RPC で pi を動かす。
 * pi 自身の TUI では何も出さないので、フッターが唯一の表示のまま (二重にならない)。
 *
 * 置き場: このパッケージ (home/dot_pi/agent/local-packages/t3-usage-status)。
 * 撤去: home/.chezmoitemplates/pi-stock-packages の ./local-packages/t3-usage-status の 1 行と、このディレクトリ。
 * 仕組み・撤去の条件: docs/adr/0031-evaluate-existing-extensions-first.md の「例外として残す自作の一覧」、README.md。
 */
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

const STATUS_KEY = "usage";

interface UsageLike {
  readonly input?: number;
  readonly cacheRead?: number;
  readonly cacheWrite?: number;
  readonly cost?: { readonly total?: number };
}

interface EntryLike {
  readonly type?: string;
  readonly usage?: UsageLike;
  readonly message?: { readonly role?: string; readonly usage?: UsageLike };
}

const num = (value: number | undefined): number =>
  typeof value === "number" && Number.isFinite(value) ? value : 0;

/**
 * pi のフッターのセッション統計の写し。合計は全エントリの和 (assistant のメッセージ・usage 付きの
 * toolResult・"usage" エントリ・compaction と branch_summary)。ヒット率は最新の assistant の
 * メッセージだけから cacheRead / (input + cacheRead + cacheWrite) で求め、セッションに
 * cacheRead か cacheWrite が 1 つでもあるときだけ出す。
 * contextPercent (コンテキスト使用率) は、undefined なら出さず、null (不明。圧縮の直後など) なら ctx--、数なら ctx41.2% と、
 * CH% と費用のあとに出す。
 */
export function computeStatusText(
  entries: readonly unknown[],
  contextPercent?: number | null,
): string | undefined {
  let cost = 0;
  let cacheReadTotal = 0;
  let cacheWriteTotal = 0;
  let latestHitRate: number | undefined;

  const add = (usage: UsageLike | undefined): void => {
    if (!usage) return;
    cacheReadTotal += num(usage.cacheRead);
    cacheWriteTotal += num(usage.cacheWrite);
    cost += num(usage.cost?.total);
  };

  for (const raw of entries) {
    const entry = raw as EntryLike;
    if (entry.type === "usage") {
      add(entry.usage);
    } else if (entry.type === "message" && entry.message?.role === "assistant") {
      add(entry.message.usage);
      const usage = entry.message.usage;
      if (usage) {
        const promptTokens = num(usage.input) + num(usage.cacheRead) + num(usage.cacheWrite);
        latestHitRate = promptTokens > 0 ? (num(usage.cacheRead) / promptTokens) * 100 : undefined;
      }
    } else if (entry.type === "message" && entry.message?.role === "toolResult") {
      add(entry.message.usage);
    } else if (entry.type === "branch_summary" || entry.type === "compaction") {
      add(entry.usage);
    }
  }

  const parts: string[] = [];
  if ((cacheReadTotal > 0 || cacheWriteTotal > 0) && latestHitRate !== undefined) {
    parts.push(`CH${latestHitRate.toFixed(1)}%`);
  }
  if (cost > 0) {
    parts.push(`$${cost.toFixed(3)}`);
  }
  if (contextPercent === null) {
    parts.push("ctx--");
  } else if (typeof contextPercent === "number" && Number.isFinite(contextPercent)) {
    parts.push(`ctx${contextPercent.toFixed(1)}%`);
  }
  return parts.length > 0 ? parts.join(" ") : undefined;
}

/**
 * コンテキスト使用率。API が無い (古い pi) ときだけ undefined (出さない)。API はあるが値が取れないとき
 * (圧縮の直後・最初の応答の前の仮想モデルなど。getContextUsage が undefined を返す) は null (ctx--)。
 * 後者でも出すのは、空のセッションで usage が最初に登録され、T3 の banner の先頭になるようにするため。
 */
function contextPercentOf(ctx: ExtensionContext): number | null | undefined {
  if (typeof ctx.getContextUsage !== "function") return undefined;
  const percent = ctx.getContextUsage()?.percent;
  return typeof percent === "number" && Number.isFinite(percent) ? percent : null;
}

export default function t3UsageStatus(pi: ExtensionAPI): void {
  const update = (ctx: ExtensionContext): void => {
    if (ctx.mode !== "rpc") return;
    ctx.ui.setStatus(STATUS_KEY, computeStatusText(ctx.sessionManager.getEntries(), contextPercentOf(ctx)));
  };

  pi.on("session_start", async (_event, ctx) => {
    update(ctx);
  });
  pi.on("turn_end", async (_event, ctx) => {
    update(ctx);
  });
  // 圧縮とモデルの切り替えで、コンテキスト使用率が変わる (turn_end を待たずに更新する)
  pi.on("session_compact", async (_event, ctx) => {
    update(ctx);
  });
  pi.on("model_select", async (_event, ctx) => {
    update(ctx);
  });
  pi.on("session_shutdown", async (_event, ctx) => {
    if (ctx.mode === "rpc") {
      ctx.ui.setStatus(STATUS_KEY, undefined);
    }
  });
}
