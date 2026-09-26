# syntax=docker/dockerfile:1
#
# chezmoi の cold start 検証用イメージ。
# ベースは compose の build.args で差し替える (test/compose.yaml を参照)。
#
# ★ここで入れるのは「素の機械に最初からあるもの」だけにする。
#   zsh / fish などを先に入れると、それを導入するはずの
#   .chezmoiscripts が no-op になり、依存漏れを隠してしまう。
#   (zsh は 100_linux/130_shell が、その他は各スクリプトが入れる)
ARG BASE_IMAGE=ubuntu:24.04
FROM ${BASE_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Tokyo \
    LANG=ja_JP.UTF-8 \
    LC_ALL=ja_JP.UTF-8

# ca-certificates / curl / git: chezmoi 自身の導入と clone に要る
# sudo: .chezmoiscripts が apt を叩く
# locales / tzdata: ja_JP.UTF-8 を使う設定があるため (未生成だと警告が出る)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      ca-certificates curl git sudo locales tzdata && \
    sed -i 's/# ja_JP.UTF-8/ja_JP.UTF-8/' /etc/locale.gen && \
    sed -i 's/# en_US.UTF-8/en_US.UTF-8/' /etc/locale.gen && \
    locale-gen && \
    rm -rf /var/lib/apt/lists/*

# chezmoi の bootstrap (README の「クイックスタート」と同じ公式インストーラ)
RUN curl -fsLS get.chezmoi.io | sh -s -- -b /usr/local/bin

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

COPY run_chezmoi.sh /usr/local/bin/run_chezmoi
RUN chmod +x /usr/local/bin/run_chezmoi

USER ${USER_NAME}
WORKDIR /home/${USER_NAME}

CMD bash -lc 'echo "chezmoi: $(chezmoi --version)"; echo "os: $(. /etc/os-release && echo "$PRETTY_NAME")"; echo "arch: $(uname -m)"; sleep infinity'
