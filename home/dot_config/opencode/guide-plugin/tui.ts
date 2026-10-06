import { readFileSync } from "node:fs"
// 本体が解決する。★静的 import に限る (動的 import は解決されない)。
import { createElement, insert, setProp } from "@opentui/solid"
import { commitPreview } from "./commit-message.js"

// 確認画面へコマンドの説明を出す (CLI 側)。表示はここでしかできない。
//
// ★2.0.12 は setup、dev は tui で呼ばれる。両方に反応させる。
// ★setup は複数回呼ばれ、モジュール状態も共有されないので globalThis で冪等にする。
// see docs/research/opencode/plugin/ask-description.md
const ATTACHED = Symbol.for("opencode.guide-plugin.tui.attached")

// 表示時間は index.js と同じ rules.json (common.toml の [opencode.ask_description]) から読む。
// 読めなくても toast は出したいので、generate.py の既定値へ倒す。
const DEFAULT_DURATION_MS = 20000

function loadAsk() {
  try {
    const rules = JSON.parse(
      readFileSync(new URL("./rules.json", import.meta.url), "utf8"),
    )
    return rules.ask_description ?? null
  } catch {
    return null
  }
}

function durationMs(ask) {
  const ms = ask?.duration_ms
  return Number.isFinite(ms) && ms > 0 ? ms : DEFAULT_DURATION_MS
}

// 本体の確認画面と同じ選び方 (子のセッションでは出さず、自分と子の保留の先頭)。
// see docs/research/opencode/plugin/ask-description.md
function pendingCommit(session, sessionID, opts) {
  if (session.get(sessionID)?.parentID) return null
  const ids = [sessionID, ...(session.family(sessionID) ?? []).filter((id) => id !== sessionID)]
  const first = ids.flatMap((id) => session.permission.list(id) ?? [])[0]
  if (first?.action !== "shell" || !first.resources?.length) return null
  return commitPreview(first.resources, opts)
}

function text(content, fg, attributes) {
  const node = createElement("text")
  if (fg) setProp(node, "fg", fg)
  if (attributes) setProp(node, "attributes", attributes)
  insert(node, content)
  return node
}

const BOLD = 1
// 端末の幅からセッション画面の左右の余白を引いた分。
const MARGIN = 6

// 確認画面のすぐ上 (session.composer.top) に出す。保留が消えれば自動で消える。
// 本文の各行は端末の幅にも収める (折り返すと狭い画面で行数が倍になる)。
function renderCommit(api, opts, input) {
  const box = createElement("box")
  setProp(box, "flexDirection", "column")
  insert(box, () => {
    const cols = Number(api.renderer?.width)
    const width = Number.isFinite(cols) ? Math.min(opts.line_width, cols - MARGIN) : opts.line_width
    const preview = pendingCommit(api.data.session, input?.sessionID, { ...opts, line_width: width })
    if (!preview) return null
    const muted = api.theme?.text?.muted
    return [
      text(preview.subject || "(件名なし)", api.theme?.text?.base, BOLD),
      ...preview.body.map((line) => text(line, muted)),
      ...(preview.extra ? [text(preview.extra, muted)] : []),
      ...(preview.added ? [text(preview.added, muted)] : []),
    ]
  })
  return box
}

function commitToast(preview) {
  return [
    preview.subject,
    ...preview.body,
    ...(preview.extra ? [preview.extra] : []),
    ...(preview.added ? [preview.added] : []),
  ].join("\n")
}

function attach(api) {
  if (globalThis[ATTACHED]) return
  globalThis[ATTACHED] = true

  const ask = loadAsk()
  const duration = durationMs(ask)
  const commit = ask?.commit ?? null
  const slotted = Boolean(commit && typeof api.ui.slot === "function")
  const stops = []
  if (slotted) {
    stops.push(
      api.ui.slot({
        append: "session.composer.top",
        render: (input) => renderCommit(api, commit, input),
      }),
    )
  }
  stops.push(
    api.data.on("permission.asked", (event) => {
      const data = event?.data
      // スロットの無い版では、抜き出した件名と本文を toast で出す。
      const preview =
        commit && !slotted && data?.resources?.length
          ? commitPreview(data.resources, commit)
          : null
      if (preview) {
        api.ui.toast.show({
          title: "コミットメッセージ",
          message: commitToast(preview),
          variant: "info",
          duration,
        })
        return
      }
      const message = data?.message
      if (!message) return
      api.ui.toast.show({
        title: "コマンドの説明",
        message,
        variant: "warning",
        duration,
      })
    }),
  )
  // 読み直されたときに登録を残さない。
  return () => {
    for (const stop of stops) if (typeof stop === "function") stop()
    globalThis[ATTACHED] = false
  }
}

export default {
  id: "guide-tui",
  setup: (api) => attach(api),
  tui: async (api) => attach(api),
}
