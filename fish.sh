#!/bin/sh

# The Friendly Interactive SHell (fish)
if !(type "fish" > /dev/null 2>&1); then
    # Install fish
    brew install fish
    sudo sh -c "echo '/usr/local/bin/fish\n' >> /etc/shells"
    # Install fisher
    rm ~/.config/fish/functions/fisher.fish
    curl -Lo ~/.config/fish/functions/fisher.fish --create-dirs git.io/fisher
    # chsh -s /usr/local/bin/fish
fi

# fzf : fuzzy finder
fisher add jethrokuan/fzf
# The command z
fisher add jethrokuan/z
# The command bd (to parent directories)
fisher add 0rax/fish-bd
# ghq
fisher add decors/fish-ghq
# The Powerline of fish, bobthefish
fisher add oh-my-fish/theme-bobthefish
