import { execFile } from "node:child_process"
import { readFileSync } from "node:fs"
import { homedir } from "node:os"
import { join } from "node:path"

// checkpoint スキルの CLI。機械節の生成と保存先の解決はここが単一ソースで、
// この plugin には書かない (Python 側と二重に持つと必ずずれる)。
// ★スキルは OpenCode 専用。~/.claude/skills ではなくここにある。
//   see docs/change/0001-compaction-context-handover.md 「方針転換」
const CLI = join(
  homedir(),
  ".config/opencode/skills/checkpoint/scripts/checkpoint.py",
)

// 圧縮を跨いだことを示す印。ctx.storage はセッションではなく plugin に
// 紐づくので、キーにセッション ID を含める。
export const key = (sessionID) => `pending:${sessionID}`

// 圧縮が**成功した**ことを知らせるイベント。
// ★上流 (v2.0.14 packages/core/src/session/compaction.ts) では
//   "Nothing to compact yet" の門番が prepare より前にあり、そこでは Failed を
//   publish して返る。Ended は成功経路でしか publish されない。
const ENDED = "session.compaction.ended"

const run = (args, cwd) =>
  new Promise((resolve) => {
    execFile(
      "python3",
      [CLI, ...args],
      { cwd, timeout: 20_000 },
      (err, stdout) => resolve(err ? null : stdout),
    )
  })

const paths = async (sessionID, cwd) => {
  const out = await run(["paths", "--session", sessionID], cwd)
  if (!out) return null
  try {
    return JSON.parse(out)
  } catch {
    return null
  }
}

// 圧縮の要求を組み立てるとき。機械的な事実だけを残す。
// ★ここで印を置かないこと。このフックは「圧縮を試みる側」に付いていて、
//   この後 "Nothing to compact yet" で**失敗することがある** (実測)。
//   置くと、起きていない圧縮の引き継ぎを後続の要求へ流し込む。
// ★絶対に投げない。ここで失敗しても圧縮そのものを壊してはいけない。
export async function onCompaction(ctx, e, cwd) {
  if (!e?.sessionID) return
  try {
    await run(
      ["snapshot", "--session", e.sessionID, "--cwd", cwd, "--trigger", "compaction"],
      cwd,
    )
  } catch {
    // 握りつぶす。圧縮を止めないことが最優先。
  }
}

// 圧縮が成功したときだけ印を置く。
// ★subscribe の引数は**イベント名ではない**。上流 v2.0.14 の
//   packages/client/src/shared-events.ts では
//   `subscribe(options?: SubscribeOptions): AsyncIterable<A>` で、
//   SubscribeOptions は `{ signal?, onActivity? }` だけ。名前を渡しても
//   絞り込まれない (実測でも全イベントが流れた)。type は自分で見ること。
// ★購読の容量は 4096 件。消費が遅れると購読ごと落ちる。だから一致しない
//   イベントでは何もせずに次へ行く。
export async function watchCompaction(ctx) {
  try {
    for await (const event of ctx.event.subscribe()) {
      if (event?.type !== ENDED) continue
      const sessionID = event.data?.sessionID
      if (!sessionID) continue
      await ctx.storage.set(key(sessionID), { at: new Date().toISOString() })
    }
  } catch {
    // 握りつぶす。購読が切れても会話は続ける。
  }
}

// 毎要求。印があれば checkpoint をシステム側へ入れる。
// ★印が無いときは ctx.storage を 1 回読むだけで抜けること。このフックは
//   1 手番のうち**ステップごとに**走る (実測で 5 回)。重い処理を置くと全体が遅くなる。
// ★消すのはユーザの手番に届けてから。圧縮の直後に走るのは内部の継続要求の
//   ことがあり、そこで消すと**次にユーザが話しかけたときには残っていない**。
export async function onContext(ctx, e, cwd) {
  if (!e?.sessionID || !Array.isArray(e.system)) return
  try {
    const pending = await ctx.storage.get(key(e.sessionID))
    if (!pending) return

    const resolved = await paths(e.sessionID, cwd)
    if (!resolved?.checkpoint) return

    const text = readFileSync(resolved.checkpoint, "utf8").trim()
    if (!text) return

    e.system.push({
      type: "text",
      text:
        "直前にコンテキスト圧縮が起きました。圧縮前に保存した引き継ぎ記録を"
        + "そのまま渡します。作業を再開する前にこれを読み、`## Next` から続けて"
        + `ください。\n\n${text}`,
    })

    // ユーザの手番へ届いたら役目は終わり。それ以外では残す。
    if (e.messages?.at(-1)?.role === "user") {
      await ctx.storage.remove(key(e.sessionID))
    }
  } catch {
    // 握りつぶす。注入できなくても会話は続ける。
  }
}

export default {
  id: "checkpoint",
  async setup(ctx) {
    const cwd = ctx.location?.project?.directory ?? ctx.location?.directory
    await ctx.session.hook("compaction", (e) => onCompaction(ctx, e, cwd))
    await ctx.session.hook("context", (e) => onContext(ctx, e, cwd))
    // ★await しない。購読は終わらないので、待つと setup が返らない。
    watchCompaction(ctx)
  },
}
