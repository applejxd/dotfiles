#!/usr/local/bin/fish

# fish install
grep -q /usr/local/bin/fish /etc/shells
if [ $status -ne 0 ]
    sudo sh -c "echo '/usr/local/bin/fish\n' >> /etc/shells"
end

# install fisher
curl https://git.io/fisher --create-dirs -sLo ~/.config/fish/functions/fisher.fish

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
