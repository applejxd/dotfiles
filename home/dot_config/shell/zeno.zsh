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

# zeno のデフォルトキーバインドを遅延登録する。
# 現行の zeno は zeno-init を遅延実行する設計のため、シェル起動直後は
# $ZENO_LOADED が空。`--lazy` を渡すと初回キー押下時に zeno-init が発火する。
# upstream が標準 widget を増減した場合も自動で追従できる。
if (( $+functions[zeno-bind-default-keys] )); then
  zeno-bind-default-keys --lazy
fi

# 追加・上書きしたいバインドはここに書く (デフォルト bindkey の後段で適用される)
# 例:
#   bindkey '^r' zeno-smart-history-selection   # smart history widget に切替
#   bindkey -M isearch ' ' self-insert          # incremental search でスペースを通常入力に
#   export ZENO_AUTO_SNIPPET_FALLBACK=self-insert
#   export ZENO_COMPLETION_FALLBACK=expand-or-complete