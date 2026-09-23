# セキュリティ機能

## 概要

個人情報と機密設定を安全に管理するため、Bitwarden と sops (age) を使用します。
この文書は役割分担とセキュリティ要件を定義し、詳細な導入・復旧手順は
[Secret管理セットアップ](sops-age.md) に集約します。

## Bitwarden連携

個人情報をBitwardenで安全に管理し、dotfilesを公開リポジトリで共有可能にします。

### 設定方法

#### 1. Bitwarden CLIのインストール

通常は `chezmoi apply` 中に Windows では Winget (`Bitwarden.CLI`)、Unix では
mise (`npm:@bitwarden/cli`) で自動投入されるため **明示インストール不要**。
クリーン環境では「2 フェーズ bootstrap」（[README](../../README.md) 参照）で:

1. `chezmoi init applejxd && chezmoi apply` → OS ごとのパッケージ管理で bw を導入
2. `bw login` と `BW_SESSION` の設定 → `chezmoi init applejxd && chezmoi apply` で
   Bitwarden 連携を有効化（Windows は gitconfig、Unix は加えて sops age 鍵）

手動で先に入れたい場合は:

```bash
# Windows
winget install --id Bitwarden.CLI --exact

# Unix: mise 経由
mise use -g npm:@bitwarden/cli

# macOS (brew でも可。ただし mise 版と PATH 競合に注意)
brew install bitwarden-cli
```

> Ubuntu の `sudo snap install bw --classic` は動作不良のため非推奨。

#### 2. Bitwardenアイテムの作成

```bash
bw login

# 最新データを同期
bw sync

# Login itemを作成（名前: gitconfig）
# Username: [GitHubユーザー名]
# Custom Fields:
#   - email: [GitHubメールアドレス]
```

#### 3. chezmoiでの使用

```bash
# Bitwardenにログイン
bw login

# データを同期（重要！）
bw sync

# セッション開始
export BW_SESSION="$(bw unlock --raw)"

# 設定ファイル適用
chezmoi apply
```

#### 日常的な使用パターン

```bash
# 一括実行
bw sync && export BW_SESSION="$(bw unlock --raw)" && chezmoi apply
```

## sops による API キー管理

API キーは平文の `.env` に置かず、sops (age) で暗号化したまま Git 管理し、
mise がプロジェクト入退場時に自動でロード・アンロードします。

### 役割分担

| ツール | 役割 |
| --- | --- |
| SOPS + age | API キーの暗号化 |
| mise | プロジェクト入退場時の自動ロード・アンロード |
| Bitwarden Password Manager | age 秘密鍵の保管 |
| chezmoi | 新しい環境で age 秘密鍵を Bitwarden から復元 |

Bitwarden Secrets Manager の `bws` は使用しません。

### 鍵の配置

age の秘密鍵は Bitwarden から自動で展開されます。

| 項目 | 値 |
| --- | --- |
| Bitwarden の項目名 | `SOPS age identity personal` |
| chezmoi のソース | `home/dot_config/sops/age/private_keys.txt.tmpl` |
| 展開先 | `~/.config/sops/age/keys.txt`（`private_` 接頭辞により mode 600） |
| mise の設定 | `sops.age_key_file = "~/.config/sops/age/keys.txt"` |

一度展開された後は `.chezmoiignore` により再展開されません。
毎回 Bitwarden を引くと `chezmoi diff` がマスターパスワードを要求するためです。

**SOPS 用の age 秘密鍵を、同じ age 鍵で chezmoi 暗号化してはいけません。**
復号に必要な鍵が暗号化ファイル内にある循環状態になります。

### 鍵が無い場合

`mise install` の直後に案内が出ます。次を実行してください。

```bash
bw login
export BW_SESSION="$(bw unlock --raw)"
chezmoi apply
```

### 詳細な手順

セットアップ、プロジェクトごとの設定、日常操作、新環境での復旧は
[Secret管理セットアップ](sops-age.md) にまとめています。

> **補足**: 以前は chezmoi 本体の age 暗号化（`~/.config/chezmoi/key.txt` と
> `encryption = "age"`）も設定していましたが、暗号化ファイルを一度も
> 運用しておらず、Bitwarden テンプレート方式と機能が重複していたため廃止しました。
> 既存マシンに `~/.config/chezmoi/key.txt` が残っている場合は手動で削除できます
> （`chezmoi apply` では削除されません）。

## AI エージェントの実行境界（Ubuntu / WSL）

OpenCode を OS のアクセス制御で囲って起動する
（[CHG-0004](../change/0004-opencode-sandbox.md)）。通常版と**併用**する段階。

```bash
ocs
```

### 何を守り、何を守らないか

**列挙型の規則では任意コード実行の権限境界を作れない**ため、保護の主役を
OS 側へ移した。ただし境界は万能ではない。

| 守る | 守らない |
| --- | --- |
| ホストの秘密（`~/.ssh`・認証情報） | **ワークスペースの中**。`.env` や `.git/hooks` は shell から届く |
| Windows 側（`/mnt`）とホストの `/tmp` | 未コミット作業とローカルの Git 履歴 |
| 許可ドメイン以外への通信 | 許可ドメインへ何を送るか |
| 保護機構そのもの（`denyWrite`） | 許可した範囲内での事故 |

permission 規則のうち**ワークスペース内を対象とするものは「ツール操作上の
禁止」にすぎない**。`read` / `edit` ツールは止まるが、shell からは同じ対象へ
届く。誤操作の抑止にはなるが、**任意コードに対する保護ではない**。

### 追加の許可は「要求」と「承認」に分ける

起動ディレクトリ以下は無条件に許可する。それ以外を開けたいときだけ、
プロジェクトが `<起動ディレクトリ>/.opencode/sandbox.toml` で**要求**する。

```text
<プロジェクト>/.opencode/sandbox.toml         ← 要求（リポジトリと一緒に移動）
~/.local/state/opencode-sandbox/trusted.json  ← 承認（マシンごと・境界の外）
```

| 場面 | 動き |
| --- | --- |
| 初回 | 要求内容を表示し、**承認するまで起動しない** |
| 承認後 | 記録に残り、次回から黙って通る |
| 要求が変わった | ハッシュが変わるので**再承認** |
| 対話できない | **起動しない**（`--trust` のときだけ通す） |

> **リポジトリは「要求」できるが「付与」はできない。** 要求だけで通すと、
> 敵対的なリポジトリが `~/.ssh` を自分で開けられる。これは仮定ではなく、
> OpenCode 自身の permission が実在する穴として持っている
> （[permission の穴 §5](../research/opencode/permission/gaps.md#5-プロジェクト設定がグローバルの-deny-を上書きする2026-09-23-再確認)）。
>
> 承認の記録は**境界の外**に置く。内側から書けるならエージェントが
> 自分で自分を承認できる。

承認画面には `~` や相対パスを**展開した後の形**を出す。承認の対象は
「何が開くか」であって、書かれた文字列ではない。

### 受容しているリスク

- 未コミット・未追跡・ignored のファイルは失いうる
- ローカルの Git 履歴も失いうる（`.git` は書き込み可能領域の中）
- 信頼済みリモートへ push 済みの内容は、**ローカルの破壊だけでは**失われない
  （復旧にはリモート側の保持と可用性が要る）

snapshot（`/undo`）は**日常の取り消し機能**であって保全ではない。復旧データ
自身が同じ shell から消せるうえ、捕捉は best effort。

### `chezmoi apply` は人間が行う

**単なるファイル複製ではない。** 変更されたコードをホスト権限へ移す操作なので、
`.chezmoiscripts/`・mise タスク・シェル起動設定・Git hooks・ランチャーが
審査対象に入る。

> **`chezmoi diff` を最初の審査に使わないこと。** テンプレートを評価するため
> `output` 関数が外部コマンドを実行する。`git diff` も外部 diff・textconv・
> pager の設定次第で外部プログラムを起動し、その設定は作業コピー側から
> 変更できる。
>
> 1. まずテンプレートを評価せず、データとして読む
> 2. テンプレートと参照先の審査が済んでから `chezmoi diff` を使う

**未審査の作業コピーを通常版の OpenCode で開かないこと。** 起動時に
プロジェクト設定を探索し、plugin・MCP・formatter・LSP が動きうる。

## セキュリティ要件

- Bitwardenマスターパスワードの安全な管理
- age鍵の適切な保管（秘密鍵は Bitwarden の Secure Note に保存）
- 定期的なパスワード・キーのローテーション
- `BW_SESSION`環境変数の取り扱いに注意
