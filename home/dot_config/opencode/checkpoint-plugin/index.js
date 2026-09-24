import { execFile } from "node:child_process"
import { readFileSync } from "node:fs"
import { homedir } from "node:os"
import { join } from "node:path"

// checkpoint スキルの CLI。機械節の生成と保存先の解決はここが単一ソースで、
// この plugin には書かない (Python 側と二重に持つと必ずずれる)。
// ★スキルは OpenCode 専用。~/.claude/skills ではなくここにある。
//   see docs/change/closed/0001-compaction-context-handover.md 「方針転換」
const SKILL = join(homedir(), ".config/opencode/skills/checkpoint")
const CLI = join(SKILL, "scripts/checkpoint.py")
const TEMPLATE = join(SKILL, "references/checkpoint-template.md")

// 圧縮を跨いだことを示す印。ctx.storage はセッションではなく plugin に
// 紐づくので、キーにセッション ID を含める。
export const key = (sessionID) => `pending:${sessionID}`

// 圧縮が**成功した**ことを知らせるイベント。
// ★上流 (v2.0.14 packages/core/src/session/compaction.ts) では
//   "Nothing to compact yet" の門番が prepare より前にあり、そこでは Failed を
//   publish して返る。Ended は成功経路でしか publish されない。
const ENDED = "session.compaction.ended"

// lint --structure が検査する 6 節。生成物がこれを満たさなければ採用しない。
const SECTIONS = ["Goal", "Constraints", "State", "Evidence", "Next", "Refs"]

// ★再入防止。generate も模型呼び出しなので、文脈が溢れたままだと圧縮を
//   誘発しうる。同じセッションで二重に走らせない。
const BUSY = new Set()

const run = (args, cwd, input) =>
  new Promise((resolve) => {
    const child = execFile(
      "python3",
      [CLI, ...args],
      { cwd, timeout: 20_000 },
      (err, stdout) => resolve(err ? null : stdout),
    )
    if (input !== undefined) {
      child.stdin.end(input)
    }
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

const prompt = () =>
  "いまから会話が圧縮されます。後任が作業を再開できる引き継ぎを書いてください。\n\n"
  + "出力の決まり:\n"
  + "- 下の雛形の 6 つの見出しを、この順序で、markdown でそのまま出す\n"
  + "- ヘッダのコメント (<!-- checkpoint: -->) と機械節は**書かない**\n"
  + "- 全体で 2000 文字以内。前置きや説明を添えない\n"
  + "- 推測を書かない。`## Evidence` は実行したコマンドと結果だけ\n"
  + "- `## Next` は次の 1 手を、手順と合格条件まで書く\n\n"
  + `${readFileSync(TEMPLATE, "utf8")}`

const header = (sessionID) =>
  `<!-- checkpoint: v1\n     session: ${sessionID}\n     cli: opencode\n`
  + `     updated_at: ${new Date().toISOString()}\n`
  + "     covered_through: 圧縮の直前 (plugin が自動生成)\n-->\n"

// 圧縮の要求を組み立てるとき。
// ★ここで印を置かないこと。このフックは「圧縮を試みる側」に付いていて、
//   この後 "Nothing to compact yet" で失敗することがある (実測)。
// ★絶対に投げない。ここで失敗しても圧縮そのものを壊してはいけない。
export async function onCompaction(ctx, e, cwd) {
  if (!e?.sessionID) return

  // 機械的な事実は無条件に残す。生成が失敗しても最低限これは残る。
  await run(
    ["snapshot", "--session", e.sessionID, "--cwd", cwd, "--trigger", "compaction"],
    cwd,
  ).catch(() => null)

  if (BUSY.has(e.sessionID)) return
  BUSY.add(e.sessionID)
  try {
    // ★generate は会話履歴が見えている (実測)。材料を詰め直す必要は無い。
    // ★空文字が返ることがある (実測)。1 度だけ引き直す。
    let body = ""
    for (let attempt = 0; attempt < 2 && !body; attempt++) {
      const out = await ctx.session.generate({
        sessionID: e.sessionID,
        prompt: prompt(),
        options: { temperature: 0 },
      })
      const text = out?.text?.trim() ?? ""
      if (text && SECTIONS.every((s) => text.includes(`## ${s}`))) body = text
    }
    if (!body) return

    const resolved = await paths(e.sessionID, cwd)
    if (!resolved?.checkpoint) return

    await run(
      ["write", resolved.checkpoint, "--keep-prev", resolved.prev],
      cwd,
      `${header(e.sessionID)}${body}\n`,
    )
    await run(
      ["snapshot", "--session", e.sessionID, "--cwd", cwd, "--trigger", "compaction"],
      cwd,
    )

    // 圧縮の要約そのものを引き継ぎにする。別々に持つと必ず片方が古くなる。
    // ★result を設定すると OpenCode は自前の要約生成を飛ばす (実測)。
    e.result = { summary: readFileSync(resolved.checkpoint, "utf8") }
  } catch {
    // 握りつぶす。result を設定しなければ OpenCode の要約に戻るだけ。
  } finally {
    BUSY.delete(e.sessionID)
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
//   1 手番のうち**ステップごとに**走る (実測で 5 回)。
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
