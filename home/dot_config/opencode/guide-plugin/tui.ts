// 確認画面へコマンドの説明を出す (CLI 側)。表示はここでしかできない。
//
// ★2.0.12 は setup、dev は tui で呼ばれる。両方に反応させる。
// ★setup は複数回呼ばれ、モジュール状態も共有されないので globalThis で冪等にする。
// see docs/research/opencode/plugin/ask-description.md
const ATTACHED = Symbol.for("opencode.guide-plugin.tui.attached")

function attach(api) {
  if (globalThis[ATTACHED]) return
  globalThis[ATTACHED] = true

  api.data.on("permission.asked", (event) => {
    const message = event?.data?.message
    if (!message) return
    api.ui.toast.show({
      title: "コマンドの説明",
      message,
      variant: "warning",
      duration: 20000,
    })
  })
}

export default {
  id: "guide-tui",
  setup: (api) => attach(api),
  tui: async (api) => attach(api),
}
