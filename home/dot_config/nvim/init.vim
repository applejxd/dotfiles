set runtimepath^=~/.vim runtimepath+=~/.vim/after
let &packpath = &runtimepath
source ~/.vimrc

" --- neovim 専用 (lazy.nvim + LSP + blink.cmp) ---
if has('nvim')
  lua require('config')
endif
