# bw + SOPS + mise：プロジェクト Secret 管理ガイド

## 目的

API キーを平文の `.env` に置かず、暗号化したまま Git 管理する。
プロジェクトへ移動すると mise が自動的に復号・ロードし、
普段は通常どおりコマンドを実行できる構成にする。

この文書は手順だけを書く。何を守るか・なぜこの方式か・各ツールの役割は
[セキュリティ](security.md#秘密情報の管理) が正本。

## このリポジトリでの配置

| 項目 | 場所 |
| --- | --- |
| 鍵を展開するテンプレート | `home/dot_config/sops/age/private_keys.txt.tmpl` |
| 展開の条件（個人用ユーザ・`BW_SESSION`・一度だけ） | `home/.chezmoiignore.tmpl` |
| mise の鍵パス設定 | `home/dot_config/mise/config.toml.tmpl` の `sops.age_key_file` |
| Bitwarden 自動アンロック | `home/.chezmoi.toml.tmpl` の `bitwarden.unlock = "auto"` |

`.chezmoiroot=home` 構成のため、リポジトリ上のパスは `home/` 配下になる。
テンプレートは Bitwarden の Secure Note `SOPS age identity personal` のノートを
そのまま `~/.config/sops/age/keys.txt` へ書き出す。項目名を変えるときは
テンプレートと `test/bw-stub.sh` も合わせて変える。

## 1. 前提ツール

Ubuntu / WSL / macOS では `mise`・`sops`・`bw` が `chezmoi apply` で入る（`bw` は個人用ユーザのみ）。
**`age`（`age-keygen`）は dotfiles では入れない。** 鍵を作る・確かめるマシンでだけ
別途入れる（`sudo apt install age`、`brew install age` など）。

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

## 2. age 秘密鍵を作成する（最初の 1 台だけ）

Bitwarden に鍵が既にあるなら作らない。[8. 新しい PC・WSL 環境で復旧する](#8-新しい-pcwsl-環境で復旧する) へ進む。

```bash
mkdir -p ~/.config/sops/age
age-keygen -o ~/.config/sops/age/keys.txt
chmod 600 ~/.config/sops/age/keys.txt
```

表示された `age1...` 形式の公開鍵を控える。後から出すときは
`age-keygen -y ~/.config/sops/age/keys.txt`（公開鍵だけを出力する）。

mise の鍵パスは `home/dot_config/mise/config.toml.tmpl` で設定済み。dotfiles を
使わない環境だけ `mise settings set sops.age_key_file ~/.config/sops/age/keys.txt` を実行する。

## 3. 秘密鍵を Bitwarden へバックアップする（最初の 1 台だけ）

通常の Bitwarden Password Manager で Secure Note を作成する。

- 名前: `SOPS age identity personal`（同じ名前の項目を他に作らない）
- ノート: `AGE-SECRET-KEY-1...` で始まる秘密鍵の行

秘密鍵は `~/.config/sops/age/keys.txt` からコピーする。

保存した鍵が正しいかは、公開鍵を再計算して比べる。秘密鍵は画面に出さない。

```bash
BW_SESSION="$(bw unlock --raw)" \
  bw get notes "SOPS age identity personal" | age-keygen -y -
```

出力された `age1...` が手順 2 で控えた公開鍵と一致すればよい。

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
mise の SOPS 連携は現時点で experimental 扱いで、対応形式は JSON・YAML・TOML。

## 5. mise 設定を信頼する（プロジェクト初回のみ）

```bash
mise trust
mise env --redacted
```

秘密情報の値が `[redacted]` と表示されれば設定完了。

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

プロジェクトへ移動すると mise が秘密情報を自動ロードする。

```bash
cd project
python app.py
pytest
terraform plan
```

特別な実行ラッパーは不要。プロジェクト外へ移動すると mise が環境変数を外す。
プロジェクト内で起動した AI CLI にも API キーが渡る点に注意する
（[脅威と守らないもの](security.md#脅威と守らないもの)）。

秘密情報の追加・更新は次のコマンドで行う。

```bash
sops .env.json
```

## 8. 新しい PC・WSL 環境で復旧する

PC 全体の導入は [README の 2 フェーズ bootstrap](../../README.md#初期化と適用2-フェーズ-bootstrap)
に従う。フェーズ 2 の `chezmoi apply` で鍵も展開される。鍵に固有の条件は次のとおり。

- ユーザ名が `applejxd` の Ubuntu / WSL / macOS でだけ展開する。
  Windows native では展開しない
- `BW_SESSION` が無い `apply` では展開しない
- `~/.config/sops/age/keys.txt` が既にあると、Bitwarden の値で上書きしない。
  入れ替えるときはファイルを消してから、`BW_SESSION` を設定して `chezmoi apply` する
- Bitwarden の項目を別の端末で作った・直した直後は、先に `bw sync` する

展開できたかは公開鍵で確かめる。

```bash
ls -l ~/.config/sops/age/keys.txt              # 存在し、-rw------- であること
age-keygen -y ~/.config/sops/age/keys.txt      # .sops.yaml の age1... と一致すること
```

各プロジェクトでは初回のみ `mise trust` を実行する。

## トラブルシューティング

### 鍵が展開されない

上から順に確かめる。どれも秘密鍵そのものは表示しない。

```bash
ls -l ~/.config/sops/age/keys.txt   # 既にあれば apply は触らない（上書きしない）
echo "${BW_SESSION:+set}"           # set と出なければセッションが無い
bw status                           # "status":"unlocked" であること
```

`chezmoi apply` の途中で `bw` が入った場合は案内が出る
（Linux の `run_onchange_after_125_mise.sh.tmpl`）。そのとおり
`bw login` → `export BW_SESSION="$(bw unlock --raw)"` → `chezmoi apply` を行う。

項目名で引けないときは、同名の項目が複数あるか、項目が無い。ID と名前だけを出して確かめる
（`bw list items` や `bw get item` をそのまま実行すると、ノートの秘密鍵まで表示される）。

```bash
bw list items --search "SOPS age identity personal" \
  | python3 -c 'import json, sys; [print(i["id"], i["name"]) for i in json.load(sys.stdin)]'
```

1 行だけ出れば正しい。

### 鍵はあるが復号できない

鍵ファイルの公開鍵と、暗号化に使った公開鍵を比べる。

```bash
age-keygen -y ~/.config/sops/age/keys.txt
grep 'age:' .sops.yaml
```

一致しない場合は別の鍵で暗号化されている。Bitwarden 側の鍵とも比べるときは
[手順 3](#3-秘密鍵を-bitwarden-へバックアップする最初の-1-台だけ) の検証コマンドを使う。
chezmoi の Bitwarden 関数を通した値まで確かめたいときも、公開鍵に変換してから出す。

```bash
chezmoi execute-template '{{ (bitwarden "item" "SOPS age identity personal").notes }}' \
  | age-keygen -y -
```

> パイプを外すと**秘密鍵がそのまま端末に出る。** 画面共有・録画・AI エージェントの
> セッション中には外さない。

### 権限エラー

`private_` 接頭辞により 600 で作成されるが、手動で作った場合などは次で直す。

```bash
chmod 600 ~/.config/sops/age/keys.txt
```

## 公式資料

- [mise: SOPS 連携](https://mise.jdx.dev/environments/secrets.html)
- [SOPS 公式ドキュメント](https://github.com/getsops/sops)
- [age 公式](https://github.com/FiloSottile/age)
- [Bitwarden Password Manager CLI](https://bitwarden.com/help/cli/)
- [chezmoi: Bitwarden 連携](https://www.chezmoi.io/reference/templates/bitwarden-functions/)
