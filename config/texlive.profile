# TeX Live フルインストールプロファイル
# see https://chatgpt.com/share/67e15e0c-9b40-8008-b3b5-d6d2f8dee813

selected_scheme scheme-full  # フルインストール

TEXDIR $HOME/texlive/main     # TeX Live のインストール先
TEXMFLOCAL $HOME/texlive/texmf-local
TEXMFSYSVAR $HOME/texlive/main/texmf-var
TEXMFSYSCONFIG $HOME/texlive/main/texmf-config
TEXMFHOME $HOME/texmf

# インストールするバイナリのディレクトリ
TEXBIN $HOME/texlive/main/bin/x86_64-linux

# インストール後のシンボリックリンクは作成しない
instopt_create_links 0

# MAN / INFO のシステム登録を行わない（ローカルインストール向け）
post_code 0

# ダウンロード元リポジトリ
repository http://mirror.ctan.org/systems/texlive/tlnet

# 言語サポート（日本語関連を含むすべての言語をインストール）
selected_language en

# フルインストールのため、ドキュメント・ソースファイルも含める
tlpdbopt_install_docfiles 1
tlpdbopt_install_srcfiles 1

# 既存ファイルがあっても強制的に上書き
instopt_adjustpath 1
instopt_overwrite_existing 1
