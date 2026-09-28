# 用語集

spec・索引・README で使う用語をそろえる。1 つのものを 1 つの名前で呼ぶ。

`research/`・`change/closed/`・`adr/` の本文は書いた当時の言い方のまま残している。
そこで旧称に出会ったら、各項目の「旧称」で読み替える。

## 境界と起動の形

- **境界**（OS が強制するアクセス境界）: bwrap・seccomp・proxy などで OS が強制する
  読み書きと通信の制限。permission・hook・plugin による規則の照合は「安全網」と呼び、
  境界とは呼ばない。旧称: OS 境界、権限境界
- **機構の境界**: 「どの機構（sandbox / permission / hook）に書くか」の線引き。
  上の境界とは別の意味（[ADR-0007](../adr/0007-filesystem-guard-boundary.md)）
- **sandbox**: Claude Code / Copilot CLI に組み込みの sandbox 機能。`common.toml` の
  `[sandbox]` が設定する（[sandbox (Claude Code / Copilot CLI)](agent-sandbox.md)）
- **sandbox runtime（`srt`）**: `@anthropic-ai/sandbox-runtime`。Claude Code は同じ
  パッケージの seccomp フィルタだけを使う。以前は隔離起動も境界を張るのに使っていた
- **Fence**: bubblewrap・Landlock・seccomp とドメイン単位のプロキシで境界を張る道具
  （[fencesandbox/fence](https://github.com/fencesandbox/fence)）。隔離起動が使う
- **隔離起動（`ocs`）**: OpenCode のプロセス全体を Fence の境界の内側で起動すること。
  Ubuntu / WSL のみ（[OpenCode 隔離起動のアーキテクチャ](opencode-sandbox.md)）。
  旧称: 隔離版 OpenCode、境界版
- **通常起動（`opencode`）**: 境界なしで OpenCode を起動すること。
  旧称: 素の OpenCode、通常版
- **通常版の設定 / 隔離版の設定**: 通常起動が読む `~/.config/opencode/` と、隔離起動の
  たびに `ocs` が書き出す `~/.config/opencode-sandbox/`。「版」は設定を指すときだけ使う
- **隔離用 DB**: 以前の隔離起動がセッションを持っていた
  `<起動ディレクトリ>/.opencode-sandbox/opencode.db`。今は DB を通常起動と共有する
  （[セッションの引き継ぎ](opencode-sandbox.md#セッションの引き継ぎ)）。旧称: 隔離 DB

## 生成と配置

- **source state**: `home/` 配下。chezmoi が配置先のファイルを作る元
- **出力内容**（生成物）: `generate.py` や modify\_ スクリプトが書き出す中身
- **配置先**（生成先・配備先）: 出力内容を書くパス（`~/.claude/settings.json` など）。
  `chezmoi apply` のたびに作り直すので直接編集しない
- **実体**: symlink・shim・ローダーの先にあり、実際に実行・参照されるファイル

## 対象の CLI

- **CLI 名を先に書く。** 「両 CLI」「両方」は、直前に CLI 名を挙げた文や表の中でだけ使う。
  節をそれで書き始めない
- **無印キー**: `[sandbox]` で接頭辞の無いキー。**新しく足すキー**は、Claude Code と
  Copilot CLI の両方に効くときだけ無印にし、片方にしか効かないなら `claude_` / `copilot_`
  を付ける。既存の `seccomp_apply_path`（Claude のみ）と `shell_network_allow`
  （Claude と隔離起動）は既存の例外で、無印でも Copilot には効かない
  （[キー名の規則](agent-sandbox.md#キー名の規則)）

## 許可の種類

「許可」だけで書かず、どの許可かを明記する。

- **読み取りの許可**: sandbox や境界の内側からパスを読めるようにすること
  （`claude_read_allow`・`copilot_read_allow`・`[opencode.sandbox] read`）
- **書き込みの許可**: 同じく書けるようにすること（`*_write_allow`・`allowWrite`）
- **自動承認**: 確認画面を出さずに実行させること（permission の `allow`）。Copilot CLI が
  hook の `ask` を自動承認するのは不具合として扱う
- **通信の許可**: 接続してよいドメイン（`[web] allow_domains`・`shell_network_allow`・
  `network_allow`）
- **開発ツール自動許可**: Copilot の `allowDevToolAccess` の呼び名。自動承認ではなく、
  開発ツールの置き場へ読み書きの許可を自動で足す機能（[ADR-0008](../adr/0008-explicit-dev-tool-grants.md)）

## 秘密情報

- **秘密情報**: 漏れると困る値の総称（鍵・トークン・パスワード・個人情報）。文中の
  「秘密」は同じ意味の略。「Secret」「機密」は使わない
  （[sops-age.md](sops-age.md) の題名だけは見出しなので残している）
- **資格情報**: 秘密情報のうち認証に使う値（API キー、トークン、`service.json` の
  パスワード、隔離用 DB の `credential` 行）。旧称: 認証情報

## 適用と検証の段階

状態を書くときは、次のどこまで済んだかを分けて書く。

- **source state を更新した**: `home/` を変えた。どの機械にもまだ効いていない
- **対象の機械へ適用した**: `chezmoi apply`（`chezmoi update`）でその機械の配置先へ
  反映した。「配備」「適用済み」はこれを指す
- **実機で確かめた**: 適用した機械で動きを観測した。OS と機械を添える。
  テストや Docker だけで見たものは「テストで確かめた」と書く

## 文書化の分担（`checkpoint` と `sdd-docs`）

- **復帰記録（A1）**: 圧縮を跨ぐためのセッション別の記録。`checkpoint` スキルと
  plugin が `.tmp/` へ書く（[文脈の引き継ぎ](checkpoint.md)）
- **案件の更新（A2）**: `docs/change/` の案件を更新する。`sdd-docs` スキルが持つ
- **恒久的な文書化（B）**: `docs/research/`・`docs/adr/`・`docs/spec/` と索引へ書く。
  `sdd-docs` スキルが持つ
- CHG-0005 の A1〜A4 はその案件の段階番号で、上の A1 / A2 とは関係が無い

[仕様一覧へ戻る](index.md)
