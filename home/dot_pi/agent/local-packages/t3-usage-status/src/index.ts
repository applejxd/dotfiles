/**
 * t3-usage-status: pi のセッションの費用とキャッシュヒット率 (CH%) を T3 Code に出す。
 *
 * pi の TUI のフッターは費用と最新の CH% を出すが、T3 Code の中で動く pi にはフッターが無い。
 * そこでセッションのエントリから同じ 2 つの数を、pi 自身のフッター
 * (dist/modes/interactive/components/footer.js) と同じ計算で求め、ctx.ui.setStatus で出す。
 * T3 は「Pi · CH97.2% $24.480」という入力欄のバナーにする (web・モバイル)。
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
 */
export function computeStatusText(entries: readonly unknown[]): string | undefined {
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
  return parts.length > 0 ? parts.join(" ") : undefined;
}

export default function t3UsageStatus(pi: ExtensionAPI): void {
  const update = (ctx: ExtensionContext): void => {
    if (ctx.mode !== "rpc") return;
    ctx.ui.setStatus(STATUS_KEY, computeStatusText(ctx.sessionManager.getEntries()));
  };

  pi.on("session_start", async (_event, ctx) => {
    update(ctx);
  });
  pi.on("turn_end", async (_event, ctx) => {
    update(ctx);
  });
  pi.on("session_shutdown", async (_event, ctx) => {
    if (ctx.mode === "rpc") {
      ctx.ui.setStatus(STATUS_KEY, undefined);
    }
  });
}
