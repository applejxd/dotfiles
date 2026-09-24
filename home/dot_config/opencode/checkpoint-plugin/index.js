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

// 圧縮の直前。機械的な事実だけを残し、復帰用の印を置く。
// ★フックは「圧縮を起動する側」ではなく「圧縮の LLM 要求を組み立てる側」に
//   付いている。自動圧縮と /compact で経路が分かれない。
// ★絶対に投げない。ここで失敗しても圧縮そのものを壊してはいけない。
export async function onCompaction(ctx, e, cwd) {
  if (!e?.sessionID) return
  try {
    await run(
      ["snapshot", "--session", e.sessionID, "--cwd", cwd, "--trigger", "compaction"],
      cwd,
    )
    await ctx.storage.set(key(e.sessionID), { at: new Date().toISOString() })
  } catch {
    // 握りつぶす。圧縮を止めないことが最優先。
  }
}

// 圧縮の直後。印があれば checkpoint をシステム側へ戻して印を消す。
// ★context フックは毎要求で走る。印が無いときは storage を 1 回読むだけで
//   抜けること。ここに重い処理を置くと全要求が遅くなる。
export async function onContext(ctx, e, cwd) {
  if (!e?.sessionID || !Array.isArray(e.system)) return
  try {
    const pending = await ctx.storage.get(key(e.sessionID))
    if (!pending) return

    // ★先に消す。読み込みに失敗しても印を残すと、毎要求で再試行して
    //   そのたびに python を起動することになる。
    await ctx.storage.remove(key(e.sessionID))

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
  },
}
