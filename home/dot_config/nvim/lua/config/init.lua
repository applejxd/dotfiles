-- neovim 専用の追加設定エントリポイント
-- ~/.vimrc を source した後に init.vim から呼ばれる
-- lazy.nvim をブートストラップし、lua/plugins/*.lua をロードする

-- 1. lazy.nvim 自体がインストールされていなければ自動 clone 
local lazypath = vim.fn.stdpath("data") .. "/lazy/lazy.nvim"
if not (vim.uv or vim.loop).fs_stat(lazypath) then
  local out = vim.fn.system({
    "git",
    "clone",
    "--filter=blob:none",
    "--branch=stable",
    "https://github.com/folke/lazy.nvim.git",
    lazypath,
  })
  if vim.v.shell_error ~= 0 then
    vim.api.nvim_echo({
      { "Failed to clone lazy.nvim:\n", "ErrorMsg" },
      { out, "WarningMsg" },
      { "\nPress any key to continue (without plugins)", "" },
    }, true, {})
    vim.fn.getchar()
    return
  end
end
vim.opt.rtp:prepend(lazypath)

-- 2. lua/plugins/ 配下を再帰インポート
require("lazy").setup({
  spec = {
    { import = "plugins" },
  },
  -- ~/.vimrc 側で colorscheme は設定済みなので install フェーズで上書きしない
  install = { colorscheme = { "iceberg", "habamax" } },
  change_detection = { notify = false },
})
