# syntax=docker/dockerfile:1
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Tokyo \
    LANG=ja_JP.UTF-8 \
    LC_ALL=ja_JP.UTF-8

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      ca-certificates curl git sudo fish zsh locales tzdata bash && \
    sed -i 's/# ja_JP.UTF-8/ja_JP.UTF-8/' /etc/locale.gen && \
    sed -i 's/# en_US.UTF-8/en_US.UTF-8/' /etc/locale.gen && \
    locale-gen && \
    rm -rf /var/lib/apt/lists/*

# chezmoi の個別インストール
RUN curl -fsLS get.chezmoi.io | sh

ARG USER_NAME=tester
ARG USER_UID=1001
ARG USER_GID=1001
RUN if ! getent group ${USER_GID} >/dev/null; then \
        groupadd -g ${USER_GID} ${USER_NAME}; \
    else \
        groupadd ${USER_NAME}; \
    fi && \
    if ! getent passwd ${USER_UID} >/dev/null; then \
        useradd -m -u ${USER_UID} -g ${USER_NAME} -s /bin/bash ${USER_NAME}; \
    else \
        useradd -m -g ${USER_NAME} -s /bin/bash ${USER_NAME}; \
    fi && \
    echo "${USER_NAME} ALL=(ALL) NOPASSWD:ALL" >/etc/sudoers.d/90-${USER_NAME} && \
    chmod 0440 /etc/sudoers.d/90-${USER_NAME}

# 実行スクリプトをコピーして実行権限付与
COPY run_chezmoi.sh /usr/local/bin/run_chezmoi
RUN chmod +x /usr/local/bin/run_chezmoi

USER ${USER_NAME}
WORKDIR /home/${USER_NAME}

# 既定はツールのバージョン表示のみ（composeでcommandを上書き）
CMD bash -lc 'echo "chezmoi: $(chezmoi --version)"; echo "git: $(git --version)"; echo "shell: $SHELL"; sleep infinity'