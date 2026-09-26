#!/bin/bash
# raspi 判定が効く前の chezmoi が入れた GUI 一式と xrdp を取り除く
# 対象と残すもの: docs/spec/structure.md#入ってしまった-gui-一式を消す
#
# usage: scripts/raspi/uninstall_gui.sh [-n|--dry-run]

set -euo pipefail

# apt の出力を解析するため
export LC_ALL=C

DRY_RUN=0
case "${1:-}" in
    "") ;;
    -n | --dry-run) DRY_RUN=1 ;;
    *)
        echo "usage: $0 [-n|--dry-run]" >&2
        exit 2
        ;;
esac

run() {
    echo "+ $*"
    if [[ $DRY_RUN -eq 0 ]]; then
        "$@"
    fi
}

# 左にあって右に無い行 (どちらも sort 済み)
minus() {
    comm -23 <(printf '%s\n' "$1" | sed '/^$/d') <(printf '%s\n' "$2" | sed '/^$/d')
}

indent() {
    sed 's/^/  /'
}

# apt-get -s で削除されるパッケージ名
simulated_removals() {
    apt-get -s "$@" | awk '$1 == "Purg" || $1 == "Remv" { print $2 }' | sort -u
}

# home/.chezmoitemplates/is-raspi と同じ手がかり。デスクトップ機で走らせると i3 環境ごと消える
osrelease="$(uname -r | tr '[:upper:]' '[:lower:]')"
if [[ ! -e /proc/device-tree/model && "$osrelease" != *raspi* && "$osrelease" != *-rpi-* && ! -e /etc/rpi-issue ]]; then
    echo "Raspberry Pi ではないので中止します" >&2
    exit 1
fi

PACKAGES=(
    i3 rofi polybar lxappearance xsel
    code
    clamav clamav-daemon
    xrdp xorgxrdp
)

APT_SOURCES=(
    /etc/apt/sources.list.d/vscode.list
    /etc/apt/sources.list.d/vscode.sources
    /etc/apt/sources.list.d/microsoft-edge.list
)
MS_KEYRING=/usr/share/keyrings/microsoft.gpg

SYSTEM_PATHS=(
    /var/lib/clamav
    /var/log/clamav
    /var/log/xrdp.log
    /var/log/xrdp-sesman.log
)

# ~/.vscode-server は Remote-SSH が使うので含めない
USER_PATHS=(
    "$HOME/.vscode"
    "$HOME/.config/Code"
    "$HOME/.config/i3"
    "$HOME/.config/polybar"
    "$HOME/.cache/rofi3.druncache"
    "$HOME/.local/share/fonts/Cica"
    "$HOME/.Xmodmap"
    "$HOME/.xsession"
    "$HOME/.xsessionrc"
    "$HOME/.xsession-errors"
    "$HOME/.xsession-errors.old"
)
shopt -s nullglob
USER_PATHS+=("$HOME"/.xorgxrdp.*.log)
shopt -u nullglob

PORTAL_MASK="$HOME/.config/systemd/user/xdg-desktop-portal-gnome.service"
THINCLIENT="$HOME/thinclient_drives"

if [[ $DRY_RUN -eq 1 ]]; then
    echo "[dry-run] 実行するコマンドを表示するだけで、何も変更しません"
else
    sudo -v
fi
avail_before="$(df --output=avail -BM / | tail -1 | tr -dc '0-9')"

#------------#
# パッケージ #
#------------#

installed=()
for pkg in "${PACKAGES[@]}"; do
    status="$(dpkg-query -W -f='${db:Status-Abbrev}' "$pkg" 2>/dev/null || true)"
    if [[ -n "$status" && "$status" != un* ]]; then
        installed+=("$pkg")
    fi
done

if [[ ${#installed[@]} -eq 0 ]]; then
    echo "✅ 対象のパッケージは入っていません"
else
    targets="$(printf '%s\n' "${installed[@]}" | sort -u)"

    # 対象に依存する別のパッケージまで巻き込むなら止める
    dragged="$(minus "$(simulated_removals purge "${installed[@]}")" "$targets")"
    if [[ -n "$dragged" ]]; then
        echo "対象外のパッケージまで削除されるので中止します:" >&2
        indent <<<"$dragged" >&2
        exit 1
    fi

    # 今回の削除で孤立する依存 (i3-wm など) だけを足し、以前からの孤立は触らない
    orphans_before="$(simulated_removals autoremove)"
    removal="$(minus "$(simulated_removals --autoremove purge "${installed[@]}")" "$orphans_before")"
    if [[ -n "$orphans_before" ]]; then
        echo "以前から autoremove の対象だったものは残します: $(echo "$orphans_before" | tr '\n' ' ')"
    fi

    echo "パッケージを削除します:"
    indent <<<"$removal"
    mapfile -t removal_list <<<"$removal"
    run sudo apt-get purge -y "${removal_list[@]}"
fi

#------------#
# APT ソース #
#------------#

sources_changed=0
for src in "${APT_SOURCES[@]}"; do
    if [[ -e "$src" ]]; then
        run sudo rm -f "$src"
        sources_changed=1
    fi
done

if [[ -e "$MS_KEYRING" ]]; then
    still_used="$(grep -rlsF "$MS_KEYRING" /etc/apt/sources.list /etc/apt/sources.list.d/ || true)"
    for src in "${APT_SOURCES[@]}"; do
        still_used="$(printf '%s\n' "$still_used" | grep -vxF "$src" || true)"
    done
    if [[ -z "$still_used" ]]; then
        run sudo rm -f "$MS_KEYRING"
    else
        echo "$MS_KEYRING は他のソースが使っているので残します:"
        indent <<<"$still_used"
    fi
fi

if [[ $sources_changed -eq 1 ]]; then
    run sudo apt-get update
fi

#----------------------#
# 残ったファイルの掃除 #
#----------------------#

for path in "${SYSTEM_PATHS[@]}"; do
    if [[ -e "$path" ]]; then
        run sudo rm -rf -- "$path"
    fi
done

cica_removed=0
for path in "${USER_PATHS[@]}"; do
    if [[ -e "$path" || -L "$path" ]]; then
        run rm -rf -- "$path"
        if [[ "$path" == */fonts/Cica ]]; then
            cica_removed=1
        fi
    fi
done

if [[ $cica_removed -eq 1 ]] && command -v fc-cache >/dev/null 2>&1; then
    run fc-cache -f
fi

if [[ -L "$PORTAL_MASK" && "$(readlink "$PORTAL_MASK")" == /dev/null ]]; then
    run rm -f "$PORTAL_MASK"
    run systemctl --user daemon-reload || true
fi

# リモートのドライブが見えている可能性があるので rm -rf しない
if [[ -d "$THINCLIENT" ]]; then
    if mountpoint -q "$THINCLIENT"; then
        run fusermount -u "$THINCLIENT"
    fi
    run rmdir "$THINCLIENT" || echo "$THINCLIENT が空でないので残します"
fi

if [[ $DRY_RUN -eq 0 ]]; then
    avail_after="$(df --output=avail -BM / | tail -1 | tr -dc '0-9')"
    echo "✅ 完了：GUI 一式を削除しました (空き容量 +$((avail_after - avail_before)) MB)"
fi
