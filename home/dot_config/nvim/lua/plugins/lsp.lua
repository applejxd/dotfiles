-- LSP: mason + nvim-lspconfig (新 API: vim.lsp.config / vim.lsp.enable)
-- nvim 0.11+ では require('lspconfig').server.setup() は deprecated
-- nvim-lspconfig は各サーバの cmd / filetypes / root を提供する lsp/*.lua を持っており
-- vim.lsp.config() がそれを自動マージする

return {
  {
    "williamboman/mason.nvim",
    cmd = "Mason",
    build = ":MasonUpdate",
    opts = {
      ui = { border = "rounded" },
    },
  },

  {
    "williamboman/mason-lspconfig.nvim",
    dependencies = { "williamboman/mason.nvim" },
    opts = {
      ensure_installed = {
        "lua_ls",
        "bashls",
        "pyright",
        "jsonls",
        "yamlls",
        "marksman",
      },
      -- 明示的に vim.lsp.enable() を nvim-lspconfig 側で呼ぶため自動 enable は無効化。
      -- ここで自動 enable すると capabilities 設定前にサーバが起動して
      -- blink.cmp の補完が LSP から流れてこなくなる
      automatic_enable = false,
    },
  },

  {
    "neovim/nvim-lspconfig",
    event = { "BufReadPre", "BufNewFile" },
    dependencies = {
      "williamboman/mason-lspconfig.nvim",
      "saghen/blink.cmp",
    },
    config = function()
      -- (a) blink.cmp の capabilities を取得  
      local capabilities = require("blink.cmp").get_lsp_capabilities()

      -- (b) 全サーバ共通: 補完 capabilities を blink.cmp に揃える
      vim.lsp.config("*", {
        capabilities = capabilities,
      })

      -- (c) サーバ別の上書き設定
      vim.lsp.config("lua_ls", {
        settings = {
          Lua = {
            runtime = { version = "LuaJIT" },
            diagnostics = { globals = { "vim" } },
            workspace = {
              library = vim.api.nvim_get_runtime_file("", true),
              checkThirdParty = false,
            },
            telemetry = { enable = false },
          },
        },
      })

      -- (d) 設定がそろったところでサーバを有効化（順序が重要）
      vim.lsp.enable({
        "lua_ls",
        "bashls",
        "pyright",
        "jsonls",
        "yamlls",
        "marksman",
      })

      -- LSP がバッファに attach されたタイミングでキーマップを設定
      vim.api.nvim_create_autocmd("LspAttach", {
        callback = function(ev)
          local map = function(mode, lhs, rhs, desc)
            vim.keymap.set(mode, lhs, rhs, { buffer = ev.buf, desc = desc })
          end
          map("n", "gd", vim.lsp.buf.definition, "LSP: definition")
          map("n", "gD", vim.lsp.buf.declaration, "LSP: declaration")
          map("n", "gi", vim.lsp.buf.implementation, "LSP: implementation")
          map("n", "gr", vim.lsp.buf.references, "LSP: references")
          map("n", "K", vim.lsp.buf.hover, "LSP: hover")
          map("n", "<C-k>", vim.lsp.buf.signature_help, "LSP: signature")
          map("n", "<Leader>rn", vim.lsp.buf.rename, "LSP: rename")
          map("n", "<Leader>ca", vim.lsp.buf.code_action, "LSP: code action")
          map("n", "[d", function()
            vim.diagnostic.jump({ count = -1, float = true })
          end, "Diag: prev")
          map("n", "]d", function()
            vim.diagnostic.jump({ count = 1, float = true })
          end, "Diag: next")
          map("n", "<Leader>e", vim.diagnostic.open_float, "Diag: float")
          map("n", "<Leader>F", function()
            vim.lsp.buf.format({ async = true })
          end, "LSP: format")
        end,
      })

      -- 診断表示の整形
      vim.diagnostic.config({
        virtual_text = { prefix = "●" },
        severity_sort = true,
        float = { border = "rounded", source = "if_many" },
      })
    end,
  },
}
