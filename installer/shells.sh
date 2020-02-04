#!/bin/sh
# install shells from Homebrew

# bash install
grep -q /usr/local/bin/bash /etc/shells
if [ $? -ne 0 ]; then
    sudo sh -c "echo '/usr/local/bin/bash\n' >> /etc/shells"
fi

# zsh install
grep -q /usr/local/bin/zsh /etc/shells
if [ $? -ne 0 ]; then
    sudo sh -c "echo '/usr/local/bin/zsh\n' >> /etc/shells"
    # change the default shell
    chsh -s /usr/local/bin/zsh
fi

# fish install
grep -q /usr/local/bin/fish /etc/shells
if [ $? -ne 0 ]; then
    sudo sh -c "echo '/usr/local/bin/fish\n' >> /etc/shells"
fi