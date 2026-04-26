# if defined load the configuration file from there
export ZENO_HOME=~/.config/zeno

# if disable deno cache command when plugin loaded
# export ZENO_DISABLE_EXECUTE_CACHE_COMMAND=1

# if enable fzf-tmux
# export ZENO_ENABLE_FZF_TMUX=1

# if setting fzf-tmux options
# export ZENO_FZF_TMUX_OPTIONS="-p"

# by default a unix domain socket is used
# if disable it
# export ZENO_DISABLE_SOCK=1

# disable builtin completion
export ZENO_DISABLE_BUILTIN_COMPLETION=1

# default (keep this to avoid compatibility issues)
# export ZENO_GIT_CAT="cat"
if command -v bat >/dev/null 2>&1; then
  # git file preview with color
  export ZENO_GIT_CAT="bat --color=always"
else
  export ZENO_GIT_CAT="cat"
fi

# default (keep this to avoid compatibility issues)
# export ZENO_GIT_TREE="tree"
if command -v eza >/dev/null 2>&1; then
  # git folder preview with color
  export ZENO_GIT_TREE="eza --tree"
else
  export ZENO_GIT_TREE="tree"
fi

# zeno のキーバインドを lazy 登録する。
# zinit 側で zeno-bootstrap.zsh だけを source している前提。
# `--lazy` を渡すと zeno-register-lazy-widgets により初回キー押下時に
# zeno 本体 (zeno-init) が読み込まれ、ロード時間を短縮できる。
if (( $+functions[zeno-bind-default-keys] )); then
  zeno-bind-default-keys --lazy
fi

# プロンプト準備や補完候補生成を裏で先行ロードしておくと初回操作が滑らか。
# zsh-defer が無い場合は何もしない (eager に呼ぶとロードコストが発生するため)。
if (( $+functions[zsh-defer] )) && (( $+functions[zeno-preload] )); then
  zsh-defer zeno-preload
fi

# 追加・上書きしたいバインドはここに書く (デフォルト bindkey の後段で適用される)
# 例:
#   bindkey '^r' zeno-smart-history-selection   # smart history widget に切替
#   bindkey -M isearch ' ' self-insert          # incremental search でスペースを通常入力に
#   export ZENO_AUTO_SNIPPET_FALLBACK=self-insert
#   export ZENO_COMPLETION_FALLBACK=expand-or-complete
