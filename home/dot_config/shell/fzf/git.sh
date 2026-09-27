#!/bin/bash

#-----#
# git #
#-----#

if command -v "git" >/dev/null 2>&1; then
    # fbr - checkout git branch
    # see http://bit.ly/34zmzkt
    function fbr() {
        local branches branch
        branches=$(git branch -vv) &&
            branch=$(echo "$branches" | fzf +m) &&
            git checkout "$(echo "$branch" | awk '{print $1}' | sed "s/.* //")"
    }

    # fbrm - checkout git branch (including remote branches)
    # see http://bit.ly/34zmzkt
    function fbrm() {
        local branches branch
        branches=$(git branch --all | grep -v HEAD) &&
            branch=$(echo "$branches" |
                fzf-tmux -d $((2 + $(wc -l <<<"$branches"))) +m) &&
            git checkout "$(echo "$branch" | sed "s/.* //" | sed "s#remotes/[^/]*/##")"
    }

    # fshow - git commit browser
    # see http://bit.ly/34zmzkt
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
    # see http://bit.ly/34zmzkt
    function cdworktree() {
        # カレントディレクトリがGitリポジトリ上かどうか
        if ! (git rev-parse &>/dev/null); then
            echo fatal: Not a git repository.
            return
        fi

        local selectedWorkTreeDir
        selectedWorkTreeDir=$(git worktree list | fzf | awk '{print $1}')

        if [[ "$selectedWorkTreeDir" = "" ]]; then
            # Ctrl-C.
            return
        fi

        cd "$selectedWorkTreeDir" || exit
    }

    # interactive 'diff' and 'add'
    # see https://qiita.com/reviry/items/e798da034955c2af84c5
    function fadd() {
        local out input_key select_num selected_files
        # "out" is true except when cancel fzf selection
        # --exit-0: Exit if lenght of the list is 0
        while out=$(git status --short | awk '{if (substr($0,2,1) !~ / /) print $2}' | fzf --exit-0 --expect=ctrl-d); do
            # Use "fzf --expect=KEY" function (see https://www.mankier.com/1/fzf#Options-Scripting)
            input_key=$(echo "$out" | head -1)
            # Arithmetric Expansion
            select_num=$(($(echo "$out" | wc -l) - 1))
            selected_files=$(echo "$out" | tail "-$select_num")
            [[ -z "$selected_files" ]] && continue

            if [ "$input_key" == ctrl-d ]; then
                # Show diff
                git diff --color=always "$selected_files" | less -R
            else
                # When input ENTER
                git add "$selected_files"
            fi
        done
    }
fi
