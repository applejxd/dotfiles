# Raspberry Pi 4 がメモリ切れで SSH ごと固まった件

- **観測日**: 2026-09-26（[CHG-0008](../../change/closed/0008-raspi-branching.md) の実機適用を進めていた日）
- **対象**: Raspberry Pi 4（RAM 3.7GB、SD カード）、Ubuntu 22.04 for Raspberry Pi（aarch64）、
  swap 0
- **一次情報**: コミット `5a84096`（zram / earlyoom の導入）と `edf21b4`
  （gitleaks フックの置き換え）の本文。**固まっている間のログは取れていない**

いまの対策（zram と earlyoom の設定値）は
[プロジェクト構造](../../spec/structure.md#メモリが尽きても-ssh-できるようにする)、
gitleaks をプレビルドで動かす理由は
[開発ガイド](../../spec/development.md#gitleaks-はプレビルドを使う) が正本。

## 経過

1. Pi の上で pre-commit を走らせた。公式の gitleaks フックは `language: golang` で、
   初回にフック環境を作るとき Go で gitleaks をソースビルドする
2. ビルドの最中に、ログが 12 分以上途絶えた
3. SSH に応答しなくなり、電源の抜き差しで復旧した

## 原因（推定）

swap 0 の状態でメモリが尽き、OOM キラーがなかなか動かなかったと見ている。その間
カーネルはプログラムのコードを追い出しては SD から読み直すので、sshd も応答
できなくなる。固まっている間の状態は観測できていないので、**これは推定**。

## その後の確認

- Pi でだけ zram-tools と earlyoom を入れた（`5a84096`）。実機で `zram0` 1.9G の
  swap と、earlyoom の除外設定（sshd / systemd / tailscaled）を確認した
- gitleaks フックを `mise exec -- gitleaks` のローカルフックへ置き換えた
  （`edf21b4`）。`pre-commit run --all-files` が Go のビルド無しで通った
- 同じ負荷をかけて固まらないことは、まだ試していない
