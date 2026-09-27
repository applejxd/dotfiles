import { readFileSync } from "node:fs"

// 確認画面へコマンドの説明を出す (CLI 側)。表示はここでしかできない。
//
// ★2.0.12 は setup、dev は tui で呼ばれる。両方に反応させる。
// ★setup は複数回呼ばれ、モジュール状態も共有されないので globalThis で冪等にする。
// see docs/research/opencode/plugin/ask-description.md
const ATTACHED = Symbol.for("opencode.guide-plugin.tui.attached")

// 表示時間は index.js と同じ rules.json (common.toml の [opencode.ask_description]) から読む。
// 読めなくても toast は出したいので、generate.py の既定値へ倒す。
const DEFAULT_DURATION_MS = 20000

function durationMs() {
  try {
    const rules = JSON.parse(
      readFileSync(new URL("./rules.json", import.meta.url), "utf8"),
    )
    const ms = rules.ask_description?.duration_ms
    return Number.isFinite(ms) && ms > 0 ? ms : DEFAULT_DURATION_MS
  } catch {
    return DEFAULT_DURATION_MS
  }
}

function attach(api) {
  if (globalThis[ATTACHED]) return
  globalThis[ATTACHED] = true

  const duration = durationMs()
  api.data.on("permission.asked", (event) => {
    const message = event?.data?.message
    if (!message) return
    api.ui.toast.show({
      title: "コマンドの説明",
      message,
      variant: "warning",
      duration,
    })
  })
}

export default {
  id: "guide-tui",
  setup: (api) => attach(api),
  tui: async (api) => attach(api),
}
