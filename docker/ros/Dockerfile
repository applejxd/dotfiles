FROM tiryoh/ros-desktop-vnc:noetic

#---------#
# cleanup #
#---------#

RUN apt-get clean && \ 
  rm -rf /var/lib/apt/lists/*

RUN mkdir /workspace
WORKDIR /workspace

#------#
# User #
#------#

# ARG USERNAME=user
# ARG GROUPNAME=user
# ARG UID=1000
# ARG GID=1000

# RUN if ! grep -q $GID /etc/group; then groupadd -g $GID $GROUPNAME; fi
# RUN if ! grep -q $UID /etc/group; then useradd -m -s /bin/zsh -u $UID -g $GID $USERNAME; fi
# RUN groupadd -g $GID $GROUPNAME
# RUN useradd -m -s /bin/bash -u $UID -g $GID $USERNAME
# USER $USERNAME