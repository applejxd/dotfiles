" unable BG color for transparet BG
" autocmd ColorScheme * highlight Normal ctermbg=None
" autocmd ColorScheme * highlight LineNr ctermbg=None
" autocmd ColorScheme * highlight EndOfBuffer ctermbg=None

" use jj as ESC key without console output
inoremap <silent> jj <ESC>

" for dark iceberg theme
set background=dark
" iceberg theme
colorscheme iceberg

" syntax highlight
syntax on 
" for Dockerfile extension
autocmd BufNewFile,BufRead *.dockerfile set filetype=dockerfile

" line number
set number
" auto-indent
set autoindent

" matching ()
set showmatch
" matching focus time
set matchtime=1

" indent: 4 spaces -> 2 spaces
set tabstop=2
set shiftwidth=2
