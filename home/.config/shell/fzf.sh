###########
# options #
###########

# 探索コマンド
# cf. https://qiita.com/kamykn/items/aa9920f07487559c0c7e
export FZF_DEFAULT_COMMAND='rg --files --hidden --follow --glob "!.git/*"'
# デフォルト設定. 下に表示, 境界線表示, 高さ指定.
export FZF_DEFAULT_OPTS='--layout=reverse --border --height 60%'
# オプション設定. bat でプレビュー, 色付き, ファイル名付き, グリッドあり
export FZF_CTRL_T_OPTS='--preview "bat  --color=always --style=header,grid --line-range :100 {}"'

# オプション設定. tree でプレビュー, 色付き, 日本語対応
# 最後のオプション cf. http://bit.ly/35TBnvE
export FZF_ALT_C_OPTS='--preview "tree -C -N {} | head -200" --select-1 --exit-0'

###########
# git-fzf #
###########

# fbr - checkout git branch
# cf. http://bit.ly/34zmzkt
function fbr() {
    local branches branch
    branches=$(git branch -vv) &&
    branch=$(echo "$branches" | fzf +m) &&
    git checkout $(echo "$branch" | awk '{print $1}' | sed "s/.* //")
}

# fbrm - checkout git branch (including remote branches)
# cf. http://bit.ly/34zmzkt
function fbrm() {
    local branches branch
    branches=$(git branch --all | grep -v HEAD) &&
    branch=$(echo "$branches" | fzf-tmux -d $(( 2 + $(wc -l <<< "$branches") )) +m) &&
    git checkout $(echo "$branch" | sed "s/.* //" | sed "s#remotes/[^/]*/##")
}

# fshow - git commit browser
# cf. http://bit.ly/34zmzkt
function fshow() {
    git log --graph --color=always \
        --format="%C(auto)%h%d %s %C(black)%C(bold)%cr" "$@" |
        fzf --ansi --no-sort --reverse --tiebreak=index --bind=ctrl-s:toggle-sort \
            --bind "ctrl-m:execute:
                (grep -o '[a-f0-9]\{7\}' | head -1 |
                xargs -I % sh -c 'git show --color=always % | less -R') << 'FZF-EOF'
                {}
                FZF-EOF"
}

# worktree移動
# cf. http://bit.ly/34zmzkt
function cdworktree() {
    # カレントディレクトリがGitリポジトリ上かどうか
    git rev-parse &>/dev/null
    if [ $? -ne 0 ]; then
        echo fatal: Not a git repository.
        return
    fi

    local selectedWorkTreeDir=`git worktree list | fzf | awk '{print $1}'`

    if [ "$selectedWorkTreeDir" = "" ]; then
        # Ctrl-C.
        return
    fi

    cd ${selectedWorkTreeDir}
}

# interactive 'diff' and 'add'
# cf. http://bit.ly/34GCFZK
fadd() {
    local out q n addfiles
    while out=$(
            git status --short |
                awk '{if (substr($0,2,1) !~ / /) print $2}' |
                fzf-tmux --multi --exit-0 --expect=ctrl-d); do
        q=$(head -1 <<< "$out")
        n=$[$(wc -l <<< "$out") - 1]
        addfiles=(`echo $(tail "-$n" <<< "$out")`)
        [[ -z "$addfiles" ]] && continue
        if [ "$q" = ctrl-d ]; then
            git diff --color=always $addfiles | less -R
        else
            git add $addfiles
        fi
    done
}

##############
# docker-fzf #
##############

# Select a docker container to start and attach to
function da() {
  local cid
  cid=$(docker ps -a | sed 1d | fzf -1 -q "$1" | awk '{print $1}')

  [ -n "$cid" ] && docker start "$cid" && docker attach "$cid"
}

# Select a running docker container to stop
function ds() {
  local cid
  cid=$(docker ps | sed 1d | fzf -q "$1" | awk '{print $1}')

  [ -n "$cid" ] && docker stop "$cid"
}

# Select a docker container to remove
function drm() {
  local cid
  cid=$(docker ps -a | sed 1d | fzf -q "$1" | awk '{print $1}')

  [ -n "$cid" ] && docker rm "$cid"
}

