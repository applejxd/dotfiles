# セキュリティ機能

## 概要

この文書は**何を守り、なぜその方式にしたか**を定義する。手順は書かない。

| 知りたいこと | 参照先 |
| --- | --- |
| 新しい機械での初回の導入（2 フェーズ bootstrap） | [README](../../README.md#初期化と適用2-フェーズ-bootstrap) |
| age 鍵の作成・バックアップ、プロジェクトの設定、鍵の復旧 | [秘密情報の管理セットアップ（sops + age）](sops-age.md) |
| `bw` が見つからない・復号できないとき | [トラブルシューティング](troubleshooting.md) |

## 秘密情報の管理

公開リポジトリに秘密を置かずに dotfiles を共有するため、秘密は Bitwarden と
sops (age) に置き、リポジトリにはそれを引くテンプレートと暗号文だけを置く。

### 保護対象と置き場所

| 秘密 | 置き場所 | 展開先 |
| --- | --- | --- |
| Git の `user.name` / `user.email` | Bitwarden の Login 項目 `gitconfig`（Username と、カスタムフィールド `email`） | `~/.config/git/user` |
| sops 用の age 秘密鍵 | Bitwarden の Secure Note `SOPS age identity personal`（ノートに鍵の行） | `~/.config/sops/age/keys.txt`（mode 600） |
| プロジェクトの API キー | 各プロジェクトの `.env.json`（sops で暗号化してコミット） | ファイルには出さない。mise がプロジェクト内でだけ環境変数に載せる |
| sudo パスワード | どこにも保存しない | スクリプトの `sudo -v` が実行時に尋ねる（macOS は `home/.chezmoitemplates/sudo-keepalive.sh.tmpl`。変数に持たない） |

Bitwarden 由来のファイルを展開するのは、ユーザ名が `applejxd` の機械だけ。
それ以外のユーザでは `.chezmoiignore.tmpl` が外す。

- Git の user 情報は Ubuntu / WSL / macOS / Windows native で展開する
  （`bw` は Windows では Winget で入る）
- age 秘密鍵は Ubuntu / WSL / macOS だけ。Windows native では `.config/*` の除外に
  入ったままにしている（Windows で sops を使っていないため）

Windows は `.config/*` を丸ごと除外しているので、`.chezmoiignore.tmpl` は
`!.config/git/` で**ディレクトリだけ**を戻している。`!.config/git/**` で中身まで
戻すと、「一度だけ展開する」除外が打ち消され、`apply` のたびに Bitwarden を引く
（`!` の取り消しはすべての除外より優先される）。

### 脅威と守らないもの

| 防ぐ | 防がない |
| --- | --- |
| 公開リポジトリからの個人情報・鍵の流出 | 侵害済みの PC からの読み出し（隔離する仕組みではない） |
| 平文 `.env` の誤コミットと放置 | プロジェクト内で起動した子プロセスへの API キーの継承。**Codex や Claude Code をプロジェクト内で起動すると、それらにも API キーが渡る** |
| AI エージェントによる age 鍵の読み出し（`~/.config/sops/age` と `**/keys.txt` を permission・hook・sandbox で拒否。[エージェント権限仕様](agent-permissions.md)） | エージェント以外のプロセス（利用者のシェルなど）による読み出し |

### ツールの役割

| ツール | 役割 |
| --- | --- |
| SOPS + age | API キーの暗号化 |
| mise | プロジェクト入退場時の自動ロード・アンロード |
| Bitwarden Password Manager | age 秘密鍵と Git の user 情報の保管 |
| chezmoi | 新しい環境で Bitwarden から秘密を展開する |

Bitwarden Secrets Manager の `bws` は使用しない。

## Bitwarden連携

- **`bw` は事前に入れなくてよい。** `chezmoi apply` の途中で Windows は Winget
  （`Bitwarden.CLI`）、Unix は mise（`npm:@bitwarden/cli`、個人用ユーザのみ）が入れる。
  Ubuntu の snap 版は動作しないため使わない
- **そのため新しい機械では 2 フェーズになる。** 1 回目の `apply` の時点では
  `bw` もセッションも無く、Bitwarden 由来のファイルは飛ばされる。`bw` が入った後に
  `BW_SESSION` を渡して 2 回目の `apply` をすると展開される。
  Docker 上でスタブの `bw` を使って流れを検証している
  （[bootstrap モード](testing.md#bootstrap-モード)）
- **`BW_SESSION` が無い間は展開しない。** セッションが無いと chezmoi が
  `bw unlock` を走らせ、未ログインの環境では `You are not logged in.` で
  `chezmoi apply` 全体が止まる。飛ばして次回に回すほうが安全
- **一度展開したら二度と評価しない。** 展開先が既にあれば `.chezmoiignore.tmpl`
  が外す。毎回 Bitwarden を引くと、`chezmoi diff` や日常の `apply` のたびに
  アンロックが要る。代わりに、Bitwarden 側の値を変えても自動では反映されない
- **`private_user.tmpl` は `bw` が PATH に無ければ空を描画する。** セッションだけ
  あって `bw` が無い状況でもテンプレート評価で止まらない
- **`bitwarden.unlock = "auto"`** は `bw` がある状態で `chezmoi init` したときだけ
  `chezmoi.toml` に入る。`BW_SESSION` が無いときに chezmoi が自分でアンロックし、
  終了時に再ロックする設定だが、上の除外があるため今のテンプレートでは
  セッション無しで Bitwarden を引く経路は無い
- **項目は名前で引く。** 同じ名前の項目が 2 つあるとテンプレート評価が失敗する

### age 秘密鍵の扱い

- **SOPS 用の age 秘密鍵を、同じ age 鍵で chezmoi 暗号化しない。** 復号に要る鍵が
  暗号化ファイルの中にある循環になる。そのため Bitwarden テンプレートから生成する
- **展開先は `private_` 接頭辞で置く。** chezmoi が秘密ファイルとして扱い、mode 600 になる
- **鍵そのものは画面にもログにも出さない。** 鍵の確認は公開鍵（`age1...`）を
  再計算して比べる。手順は [秘密情報の管理セットアップ（sops + age）](sops-age.md)

### 廃止した仕組み: chezmoi 本体の age 暗号化

以前は chezmoi 本体の age 暗号化（`~/.config/chezmoi/key.txt` と
`.chezmoi.toml.tmpl` の `encryption = "age"`）も設定していた。
`chezmoi add --encrypt` したファイルを復号するためのものだったが、
暗号化ファイルを一度も運用しておらず、Bitwarden テンプレート方式
（`{{ (bitwarden ...) }}` を直接書く形）と機能が重複していたため廃止した。
既存マシンに `~/.config/chezmoi/key.txt` が残っていても `chezmoi apply` は
削除しないので、不要であれば手動で削除する。

## AI エージェントの実行境界（Ubuntu / WSL）

OpenCode を OS のアクセス制御（[Fence](https://github.com/fencesandbox/fence)）で囲って起動する
（[CHG-0004](../change/closed/0004-opencode-sandbox.md)、[CHG-0009](../change/closed/0009-ocs-simplify-for-accidents.md)）。
通常起動（`opencode`）と**併用**する段階。構成・起動順序・境界の組み立て規則は
[OpenCode 隔離起動のアーキテクチャ](opencode-sandbox.md)。ここでは
**何を守り、何を守らないか**を書く。境界の目的は**エージェントのうっかり**
（外部への誤送信、ワークスペース外の破壊、秘密の誤読）の防止に絞っている
（[ADR-0012](../adr/0012-ocs-boundary-for-accidents.md)）。

```bash
ocs         # 隔離起動（境界の内側で起動する）
opencode    # 通常起動（境界なし）
```

### 何を守り、何を守らないか

**列挙型の規則では任意コード実行の権限境界を作れない**ため、保護の主役を
OS 側へ移した。ただし境界は万能ではない。

| 守る | 守らない |
| --- | --- |
| ホストの秘密情報（`~/.ssh`・資格情報）。読み取りは既定で拒否し、道具の置き場と作業用の親ディレクトリだけを開ける。**例外: モデル API の資格情報**は共有する DB にあり、内側から平文で読める（[決めた例外](opencode-sandbox.md#既知の制約)） | **ワークスペースの中**。`.env` や `.git/hooks` は shell から届く |
| Windows 側（`/mnt`）とホストの `/tmp` | 開けた作業用ディレクトリ（`~/src` など）に紛れた秘密の読み取り |
| 起動ディレクトリの外（`~/.cache`・OpenCode のデータディレクトリなどの例外を除く）への書き込み | ローカルの Git 履歴（未コミット作業は起動前に退避する） |
| 通信を許可したドメイン以外への通信 | 通信を許可したドメインへ何を送るか |
| 保護機構そのもの（`denyWrite`） | 他のプロジェクトの会話（DB を共有する） |

permission 規則のうち**ワークスペース内を対象とするものは「ツール操作上の
禁止」にすぎない**。`read` / `edit` ツールは止まるが、shell からは同じ対象へ
届く。誤操作の抑止にはなるが、**任意コードに対する保護ではない**。

### プロジェクトごとの追加の許可

起動ディレクトリ以下は無条件に許可する。それ以外を開けたいときだけ、
プロジェクトが `<起動ディレクトリ>/.opencode/sandbox.toml` に書く
（キーは `read` / `write` / `network_allow`）。

```toml
# <プロジェクト>/.opencode/sandbox.toml
read = ["/mnt/d/datasets/example"]
write = ["/mnt/d/outputs/example"]
network_allow = ["api.example.com"]
```

**承認は取らない。** 起動時に足す分を表示し、そのまま適用する。精査していない
リポジトリが自分で境界を広げることは、ADR-0012 で非目的にした。`.opencode` は
保護対象なので、境界の内側のエージェントが書き足すことはできない
（[プロジェクトごとの追加](opencode-sandbox.md#プロジェクトごとの追加)）。

### 受容しているリスク

- 未コミット・未追跡・ignored のファイルは失いうる
- ローカルの Git 履歴も失いうる（`.git` は書き込み可能領域の中）
- 信頼済みリモートへ push 済みの内容は、**ローカルの破壊だけでは**失われない
  （復旧にはリモート側の保持と可用性が要る）
- DB を共有するので、エージェントのうっかりで DB を壊すと全部の履歴と snapshot に響く
- `ocs` は境界を張る前にホストで Fence・`git`・`opencode` を動かし、Fence の PATH と
  `git` の `GIT_*` を除いて、環境変数は利用者の環境のまま渡す。
  精査していないワークスペースがそれらを騙すことは対象外
  （[ADR-0012](../adr/0012-ocs-boundary-for-accidents.md) の非目的）

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

**未審査の作業コピーを OpenCode の通常起動（`opencode`）で開かないこと。** 起動時に
プロジェクト設定を探索し、plugin・MCP・formatter・LSP が動きうる。

## セキュリティ要件

- Bitwardenマスターパスワードの安全な管理
- age鍵の適切な保管（秘密鍵は Bitwarden の Secure Note に保存）
- 定期的なパスワード・キーのローテーション
- `BW_SESSION`環境変数の取り扱いに注意（展開が済んだら `unset BW_SESSION` してよい）
- API プロバイダ側でも、プロジェクトごとに API キーと利用上限を分ける
