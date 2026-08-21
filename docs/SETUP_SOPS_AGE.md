# bw + SOPS + mise：プロジェクト Secret 管理ガイド

## 目的

API キーを平文の `.env` に置かず、暗号化したまま Git 管理する。
プロジェクトへ移動すると mise が自動的に復号・ロードし、
普段は通常どおりコマンドを実行できる構成にする。

## 役割分担

| ツール | 役割 |
| --- | --- |
| SOPS + age | API キーの暗号化 |
| mise | プロジェクト入退場時の自動ロード・アンロード |
| Bitwarden Password Manager | age 秘密鍵の保管 |
| chezmoi | 新しい環境で age 秘密鍵を Bitwarden から復元 |

Bitwarden Secrets Manager の `bws` は使用しない。

## このリポジトリでの配置

| 項目 | 値 |
| --- | --- |
| Bitwarden の項目名 | `SOPS age identity personal`（Secure Note） |
| chezmoi のソース | `home/dot_config/sops/age/private_keys.txt.tmpl` |
| 展開先 | `~/.config/sops/age/keys.txt`（`private_` 属性により mode 600） |
| mise の鍵パス設定 | `home/dot_config/mise/config.toml.tmpl` の `sops.age_key_file` |
| Bitwarden 自動アンロック | `home/.chezmoi.toml.tmpl` の `bitwarden.unlock = "auto"` |

`.chezmoiroot=home` 構成のため、リポジトリ上のパスは `home/` 配下になる。

## 設計判断（なぜこの配置なのか）

- **SOPS 用 age 秘密鍵そのものを、同じ age 鍵で chezmoi 暗号化してはいけない。**
  復号に必要な鍵が暗号化ファイル内にある循環状態になる。
  そのため chezmoi の Bitwarden テンプレートから生成する
- **鍵は `private_` 接頭辞で配置する。** chezmoi が秘密ファイルとして扱い、
  パーミッションが 600 になる
- **`.chezmoiignore` で「一度だけ展開」にする。** 毎回 Bitwarden を引くと
  `chezmoi diff` がマスターパスワードを要求して日常操作が止まる
- **Bitwarden Item 名が一意でない場合は Item UUID を指定する。**
  名前解決に失敗するとテンプレート評価が落ちる
- **`bitwarden.unlock = "auto"` を使う。** `BW_SESSION` が無いときだけ
  chezmoi が `bw unlock` を実行し、処理終了時に Vault を再ロックする
- **エージェントからの読み出しは hook で拒否する。** `~/.config/sops/age/**` と
  `keys.txt` をガード対象にしている（[agents-permissions.md](agents-permissions.md)）

## 1. 前提ツール

次のコマンドを利用可能にする。

```bash
bw --version
age --version
sops --version
mise --version
```

zsh で mise を有効化していない場合は `~/.zshrc` に次を追加する。

```bash
eval "$(mise activate zsh)"
```

## 2. age 秘密鍵を作成する（初回のみ）

```bash
mkdir -p ~/.config/sops/age
age-keygen -o ~/.config/sops/age/keys.txt
chmod 600 ~/.config/sops/age/keys.txt
```

表示された `age1...` 形式の公開鍵を控える。

mise へ秘密鍵の場所を設定する。

```bash
mise settings set sops.age_key_file ~/.config/sops/age/keys.txt
```

> このリポジトリでは `home/dot_config/mise/config.toml.tmpl` に
> 設定済みなので、`chezmoi apply` していれば実行不要。

## 3. 秘密鍵を Bitwarden へバックアップする（初回のみ）

通常の Bitwarden Password Manager で Secure Note を作成する。

- 名前: `SOPS age identity personal`
- ノート: `AGE-SECRET-KEY-1...` で始まる秘密鍵の行

秘密鍵は `~/.config/sops/age/keys.txt` からコピーする。

CLI からバックアップを検証する場合は、保存した秘密鍵から公開鍵を再計算する。

```bash
BW_SESSION="$(bw unlock --raw)" \
  bw get notes "SOPS age identity personal" | age-keygen -y -
```

出力された `age1...` が手順 2 で控えた公開鍵と一致すればよい。

### chezmoi の復元テンプレート

`home/dot_config/sops/age/private_keys.txt.tmpl` の内容は次の 1 行。

```text
{{ (bitwarden "item" "SOPS age identity personal").notes }}
```

## 4. 各プロジェクトを設定する

プロジェクト直下に次の 3 ファイルを置く。

```text
project/
├── mise.toml
├── .sops.yaml
└── .env.json
```

### mise.toml

```toml
[env]
_.file = { path = ".env.json", redact = true }
```

### .sops.yaml

`age1...` を手順 2 で控えた公開鍵へ置き換える。

```yaml
creation_rules:
  - path_regex: ^\.env\.json$
    age: age1xxxxxxxxxxxxxxxx
```

### .env.json

次のコマンドで作成・編集する。

```bash
sops .env.json
```

エディタ内では通常の JSON として入力する。

```json
{
  "OPENAI_API_KEY": "sk-xxxxxxxx",
  "ANTHROPIC_API_KEY": "sk-ant-xxxxxxxx"
}
```

保存後、値は SOPS によって暗号化される。

## 5. mise 設定を信頼する（プロジェクト初回のみ）

```bash
mise trust
mise env --redacted
```

Secret 値が `[redacted]` と表示されれば設定完了。

## 6. Git へコミットする

```bash
git add mise.toml .sops.yaml .env.json
git commit -m "Add encrypted project secrets"
```

`.env.json` は暗号化済みなのでコミットする。平文ファイルは `.gitignore` へ追加する。

```text
.env
*.decrypted.env
```

`~/.config/sops/age/keys.txt` はコミットしない。

## 7. 日常操作

プロジェクトへ移動すると mise が Secret を自動ロードする。

```bash
cd project
python app.py
pytest
terraform plan
```

特別な実行ラッパーは不要。プロジェクト外へ移動すると mise が環境変数を外す。

Secret の追加・更新は次のコマンドで行う。

```bash
sops .env.json
```

## 8. 新しい PC・WSL 環境で復旧する

chezmoi がテンプレートを評価する前に `bw` をインストールしておく。
このリポジトリでは mise が `npm:@bitwarden/cli` を入れるため、
[README](../README.md) の 2 フェーズ bootstrap に従う。

```bash
bw login
chezmoi init --apply git@github.com:applejxd/dotfiles.git
```

chezmoi が Bitwarden のアンロックを要求し、`~/.config/sops/age/keys.txt` を生成する。

mise 側の鍵パス設定が dotfiles に含まれていない場合だけ次を実行する。

```bash
mise settings set sops.age_key_file ~/.config/sops/age/keys.txt
```

各プロジェクトでは初回のみ `mise trust` を実行する。

## トラブルシューティング

### 鍵が見つからない

```bash
# Bitwarden の項目を確認
bw list items --search "SOPS age"
```

テンプレートの展開を確認する場合、出力に秘密が含まれるので画面に注意する。

```bash
chezmoi execute-template '{{ (bitwarden "item" "SOPS age identity personal").notes }}'
```

### `chezmoi diff` がマスターパスワードを要求する

鍵がまだ展開されていない状態。`chezmoi apply` を一度実行すると、
以降は `.chezmoiignore` によりテンプレート評価がスキップされる。

### 権限エラー

`private_` 接頭辞により 600 で作成されるが、手動で直す場合は次のとおり。

```bash
chmod 600 ~/.config/sops/age/keys.txt
```

## 注意点

- プロジェクト内で起動した子プロセスは、ロードされた API キーを継承する。
  **Codex や Claude Code をプロジェクト内で起動すると、それらにも API キーが渡る**
- この構成は Git への誤コミットや平文 `.env` の放置を防ぐが、
  侵害済み PC を隔離する仕組みではない
- API プロバイダ側でも、プロジェクトごとに API キーと利用上限を分ける
- mise の SOPS 連携は現時点で experimental 扱いで、対応形式は JSON・YAML・TOML

## 補足: 廃止した仕組み

以前は chezmoi 本体の age 暗号化（`~/.config/chezmoi/key.txt` と
`.chezmoi.toml.tmpl` の `encryption = "age"`）も設定していた。
`chezmoi add --encrypt` したファイルを復号するためのものだったが、
暗号化ファイルを一度も運用しておらず、Bitwarden テンプレート方式
（`{{ (bitwarden ...) }}` を直接書く形）と機能が重複していたため廃止した。

既存マシンに `~/.config/chezmoi/key.txt` が残っている場合、
`chezmoi apply` では削除されないので、不要であれば手動で削除する。

## 公式資料

- [mise: SOPS 連携](https://mise.jdx.dev/environments/secrets.html)
- [SOPS 公式ドキュメント](https://github.com/getsops/sops)
- [age 公式](https://github.com/FiloSottile/age)
- [Bitwarden Password Manager CLI](https://bitwarden.com/help/cli/)
- [chezmoi: Bitwarden 連携](https://www.chezmoi.io/reference/templates/bitwarden-functions/)
