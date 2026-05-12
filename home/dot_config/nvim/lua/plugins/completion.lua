-- 補完 UI: blink.cmp (Rust 製ハイブリッド・依存少・高速)
-- LSP capabilities は lsp.lua 側で blink.cmp から取得して各 server に渡している

return {
  {
    "saghen/blink.cmp",
    version = "*", -- 公開された prebuilt fuzzy バイナリを使う
    dependencies = {
      "rafamadriz/friendly-snippets",
    },
    opts = {
      keymap = {
        -- Enter で確定、Tab/S-Tab で候補移動（active snippet 中は snippet jump）
        -- 参考: https://cmp.saghen.dev/configuration/keymap.html
        preset = "enter",
        ["<Tab>"] = { "select_next", "snippet_forward", "fallback" },
        ["<S-Tab>"] = { "select_prev", "snippet_backward", "fallback" },
      },
      appearance = {
        -- Nerd Font が無い環境でも崩れにくい mono 表記
        nerd_font_variant = "mono",
      },
      sources = {
        default = { "lsp", "path", "snippets", "buffer" }, --- 優先順
      },
      completion = {
        documentation = { auto_show = true, auto_show_delay_ms = 200 },
        menu = { border = "rounded" },
      },
      signature = { enabled = true },
    },
    opts_extend = { "sources.default" },
  },
}
