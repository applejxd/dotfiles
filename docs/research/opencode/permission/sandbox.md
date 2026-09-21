# OpenCode V2 に sandbox はあるか（調査と代替手段）

> **調査日: 2026-09-22**
> **対象: `opencode v2.0.10` / `bwrap 0.9.0` / Ubuntu 24.04**
>
> [CHG-0002](../../../change/0002-opencode-ask-by-default.md) の段階 2 で、
> permission 層も出力フィルタも**境界にならない**と分かったため
> （[出力フィルタと子エージェント](output-filter-and-subagents.md)）、
> OS レベルの隔離が使えるかを調べた。

## 0. 結論

**組み込みの sandbox は無い。しかし設定の `shell` を差し替えることで、
外から bubblewrap を被せられる。実測で成立した。**

| 問い | 結果 |
| --- | --- |
| V2 に sandbox 機能はあるか | **無い** |
| プラグインで代替できるか | **できない**（plugin は同一プロセス内） |
| `shell` 差し替えで隔離できるか | **できる**（実測） |
| permission 層を破った手口を止められるか | **止まる**（ファイルが存在しなくなるため） |
| 任意のタイミングで有効・無効にできるか | **できる**（プロジェクト単位・環境変数の 2 通り） |
| 敵対的なリポジトリにも効くか | **効かない**（プロジェクト設定で外せる。セクション 5） |
| より強い方式はあるか | **ある**（`opencode` のプロセスごと隔離。セクション 5） |

これは**この 3 CLI のうち OpenCode だけが欠いている層**を埋める話。
Claude Code と Copilot CLI は OS レベル sandbox を内蔵しており、
このリポジトリは既にその設定を生成している
（[sandbox 機能の包括調査](../../agents/sandbox-capabilities.md)、
[agent-permissions](../../../spec/agent-permissions.md)）。

## 1. 組み込みの sandbox は無い

4 つの情報源すべてで否定された。

| 情報源 | 結果 |
| --- | --- |
| 設定スキーマ（`opencode.ai/config.json`） | `sandbox` の語が **0 件** |
| 公式 V2 ドキュメント | 該当ページ無し。Network ページはプロキシ変数のみ |
| `experimental` / `Policy` | `Policy` の `action` は `provider.use` のみ。ファイルや shell には使えない |
| バイナリの文字列 | 後述のとおり**すべて別物** |

### バイナリの `sandbox` は別の意味

`sandbox` を含む文字列は 22 箇所あるが、正体は**プロジェクトに紐づく
追加ディレクトリ**（worktree 相当）だった。

```text
`sandboxes` text NOT NULL                                  ← project テーブルの列
[ct.canonical, ...ct.sandboxes].map((Gt)=>({directory:Gt})) ← ディレクトリの配列
```

`bwrap` の 2 件は base64 文字列の偶然の一致（`...SBwrAPv...`）。
`unshare` の 10 件はセッション共有の解除（`session.unshare`）。
**隔離機構の痕跡はひとつも無い。**

## 2. プラグインでは代替できない

plugin は OpenCode と同じプロセスで動き、`tool.execute.before` /
`permission.evaluate` / `execute.after` で**文字列を見る**だけ。
コマンドは結局ホストの権限で実行される。

実測済みの限界は次のとおり。

| 層 | すり抜ける手口 |
| --- | --- |
| 実行前のコマンド検査 | `-exe""c` / `F=path; cat $F` / 子プロセス |
| 実行後の出力検査 | `base64` / `tr` による符号化 |

どちらも[実測](output-filter-and-subagents.md)で確認した。
**プロセスの外側に境界を置かない限り塞がらない。**

## 3. `shell` を差し替えると外から被せられる

設定に `shell`（「terminal と bash tool で使う既定シェル」）がある。
ここを実行ファイルに向けると、**shell ツールの実行がそこを通る**。

### 実測: 呼ばれ方

```jsonc
{ "shell": "/abs/path/wrapper.sh" }
```

```text
argv: -c echo SHELLWRAP_OK
```

`-c <コマンド>` で渡ってくる。つまり `exec bwrap … /bin/bash "$@"` と
書けば、そのまま隔離下で実行できる。

### 実測: 隔離が効く

deny リスト型（全部 read-only で見せ、秘密だけ空で覆い、
ワークスペースとキャッシュだけ書き込み可）で測った。

```bash
bwrap --ro-bind / / --proc /proc --dev /dev --tmpfs /tmp \
      --bind "$WS" "$WS" --bind ~/.cache ~/.cache \
      --tmpfs ~/.ssh --tmpfs ~/.gnupg --tmpfs ~/.aws \
      --tmpfs ~/.config/sops --tmpfs ~/.config/opencode --tmpfs ~/.claude \
      --chdir "$WS" --die-with-parent /bin/bash "$@"
```

| 試行 | 結果 |
| --- | --- |
| `cat ws.txt`（ワークスペース） | 成功 |
| `echo ok > ws2.txt` | 成功 |
| `touch ~/ESCAPED2.txt` | **失敗**（読み込み専用ファイルシステム） |
| `cat ~/.config/opencode/opencode.json` | **失敗**（存在しない） |
| `base64 -w0 ~/.config/opencode/opencode.json` | **失敗** |
| `F=~/.config/opencode/opencode.json; cat $F` | **失敗** |
| `python3 -c "open(…).read()"` | **失敗**（`FileNotFoundError`） |

**permission 層を破った 3 つの手口が、いずれも通らない。**
文字列を検査しているのではなく、ファイルが**存在しない**ため。
これが「安全網」と「境界」の違い。

### 実測: OpenCode 経由でも成立する

ラッパーを `shell` に設定して実際にエージェントを走らせた。

```console
$ cat ws.txt
workspace file                                    ← 成功
$ cat ~/note_probe.txt
cat: /home/applejxd/note_probe.txt: そのようなファイルやディレクトリはありません
```

### 実測: 開発ツールは使える

allow リスト型（ワークスペースだけ bind）にすると `mise` / `uv` が
`~/.local/share/mise` 配下にあるため**見えなくなり、検証コマンドが
全部動かない**。deny リスト型なら動く。

```console
$ command -v mise uv python3
/home/applejxd/.local/bin/mise
/home/applejxd/.local/share/mise/installs/uv/.../uv
/home/applejxd/.local/share/mise/installs/python/latest/bin/python3
$ uv --version
uv 0.8.12
```

### オーバーヘッド

| 方式 | 5 回の合計 |
| --- | ---: |
| 素の `bash -c true` | 23 ms |
| bwrap 経由（allow リスト型） | 128 ms |
| bwrap 経由（deny リスト型） | 142 ms |

1 回あたり **+24 ms 程度**。エージェントの 1 ターンが秒単位なので無視できる。

## 4. 任意のタイミングで有効・無効にできるか

**できる。2 通りあり、性質が違う。**

| 手段 | 効く範囲 | 用途 |
| --- | --- | --- |
| プロジェクトの `.opencode/opencode.json` で `shell` を上書き | そのプロジェクトだけ、恒久的 | **この chezmoi リポジトリで無効にする** |
| ラッパーが見る環境変数 | 起動したプロセスだけ | 一時的に外す |

### プロジェクト単位の無効化（実測）

グローバルでラッパーを指定した状態で、プロジェクト側に置いた。

```jsonc
// <project>/.opencode/opencode.json
{ "$schema": "https://opencode.ai/config.json", "shell": "/bin/bash" }
```

結果、**ラッパーは 1 度も呼ばれなかった**。プロジェクト設定が
グローバルの `shell` に勝つ。

これはこのリポジトリにとって重要。`chezmoi apply` や
`~/.config` への書き込みが仕事そのものなので、**ここでは sandbox を
無効にする必要がある**。1 ファイル置くだけで済む。

### 環境変数による一時的な切り替え（実測）

ラッパーに環境変数が届く。

```console
$ OPENCODE_SANDBOX=0 opencode run …
global-wrapper called. OPENCODE_SANDBOX=0
```

ラッパー側で分岐すれば、設定を書き換えずに外せる。

```bash
[ "${OPENCODE_SANDBOX:-1}" = 0 ] && exec /bin/bash "$@"
exec bwrap … /bin/bash "$@"
```

**制約**: 環境変数は OpenCode のプロセスに渡っている必要がある。
常駐サービス（`opencode serve --service`）は長命で、起動時の環境が
固定されるため、途中で `export` しても届かない
（[試験環境の隔離方法](../test-isolation.md)）。
`--standalone` や新しいセッションでは効く。

### エージェント単位では切り替えられない

`AgentConfig` に `shell` は無い（`model` / `tools` / `permission` などのみ）。
つまり **`bypass` エージェントでも sandbox は外れない**。
permission を全 allow にしても、ファイルが存在しない状態は変わらない。

plugin の `deny` を `bypass` が貫通しなかったのと同じ構図で、
**sandbox は permission より外側の層**であることの裏付けでもある。

## 5. `shell` 差し替えの限界と、より強い方式（2026-09-22 追記）

`shell` の差し替えは**設定で入れる保護なので、設定で外せる**。

### プロジェクト設定で無効化できてしまう

グローバルでラッパーを指定していても、
`<project>/.opencode/opencode.json` に `"shell": "/bin/bash"` を書けば
ラッパーは**1 度も呼ばれない**（セクション 4 で実測）。

これは「このリポジトリで無効にする」手段として使う一方、
**外部リポジトリが同じ方法で sandbox を外せる**ことを意味する。
permission も同じく上書きできる（[permission の穴](gaps.md)）。

つまり `shell` 差し替えは、**信頼できないリポジトリに対しては効かない**。
守りたい相手が「プロンプトインジェクションで誘導されたエージェント」なら
有効だが、「敵対的なリポジトリ」なら無効。

### より強い方式: OpenCode のプロセスごと隔離する

`opencode` 自体を bwrap の中で起動すれば、設定では外せない。

```console
$ ./sb.sh -c 'opencode --version'
opencode v2.0.12                 ← 起動する
$ ./sb.sh -c 'ls ~/.ssh | wc -l'
0                                ← 秘密は見えない
```

| | `shell` 差し替え | プロセスごと隔離 |
| --- | --- | --- |
| 覆う範囲 | shell ツールのみ | **全ツール + MCP + plugin** |
| プロジェクト設定で外せるか | **外せる** | 外せない |
| 有効・無効の切り替え | 設定・環境変数 | **起動方法**（ラッパー経由か否か） |
| 実装場所 | `opencode.json` の 1 行 | 起動コマンド（mise task / alias） |

**後者のほうが素直**。permission の穴（`grep` / `glob` が `read` deny を
迂回する）も、MCP が sandbox の外という問題も、同時に解決する。

切り替えは「ラッパー経由で起動するかどうか」になるので、
プロジェクト単位ではなく**起動単位**になる。

## 6. snap で配布されたコマンドは動かない

`chezmoi` はこのマシンで snap 版（`/snap/bin/chezmoi` → `/usr/bin/snap`）。
bwrap の中では起動できない。

```console
$ ./sb.sh -c 'chezmoi status'
snap-confine is packaged without necessary permissions and cannot continue
required permitted capability cap_dac_override not found in current capabilities
```

`mise` / `python3` / `git` / `uv` は動く（実測）。

**このリポジトリで sandbox を無効にする理由は「書き込み範囲」ではなく
これ。** 秘密だけ隠して書き込みを許す形（Claude / Copilot と同じ方針）に
しても、`chezmoi` が動かないので成立しない。

## 7. 常駐サービス経由の脱出（P3-3、2026-09-22）

プロセスごと隔離しても、**localhost の常駐サービスが穴になる**。

`opencode serve --service` が動いている環境では、sandbox の内側から
到達できる。ネットワーク名前空間は分けられない（LLM API に要る）ため。

```console
$ ./sbx.sh -c 'curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:49374/'
401
```

401 が返るのは認証があるから。**その資格情報は
`~/.config/opencode/service.json` にある。**

```json
{"password": "…"}
```

内側で読めてしまうと、外側のサービスにツールを実行させられる。
**sandbox の完全な迂回**になる。

### 対処

| 対処 | 効果 |
| --- | --- |
| `--ro-bind /dev/null ~/.config/opencode/service.json` | パスワードが読めなくなる（実測） |
| `--unshare-pid` | 他プロセスが見えない（5 個まで減った） |

`/proc/<外側の pid>/environ` は**もともと読めなかった**（権限拒否）ので、
そこからの漏洩は無い。

対処後の実測。

```console
$ ./sbx2.sh -c 'wc -c < ~/.config/opencode/service.json'
/home/applejxd/.config/opencode/service.json: 許可がありません
$ ./sbx2.sh -c 'ls /proc | grep -c "^[0-9]"'
5
```

**残余リスク**: 資格情報が他の場所にも置かれていないかは未確認。
「塞いだ」と断定はできない。sandbox 内では `--standalone` で起動し、
サービスを使わせないのが素直。

### 覆う範囲は構成上そろう

プロセスごと隔離なので、`shell` / `read` / `grep` / MCP サーバ / plugin は
すべて同じ名前空間の中に入る（子プロセス、または同一プロセス）。
`shell` 差し替え案で残っていた「ツール経由は外側」という穴は無くなる。

## 8. 残る穴

`shell` の差し替えは **shell ツールにしか効かない**。

| 経路 | sandbox の内側か |
| --- | --- |
| `shell` ツール | **内側** |
| `read` / `edit` / `grep` / `glob` ツール | **外側**（OpenCode 本体が直接読む） |
| MCP サーバ | 外側（別プロセスだが sandbox 外） |
| plugin 自身 | 外側 |

つまり sandbox だけでは足りず、**permission 層と組み合わせて初めて
全経路が塞がる**。

| 経路 | 担当 |
| --- | --- |
| shell 経由 | sandbox（境界） |
| ツール経由 | permission の `read` / `edit` deny（現行 50 件 / 52 件） |

現在の構成は前者が空いていた。ここを埋めるのが sandbox の役割。

## 9. 採用する場合の検討事項

| 論点 | 内容 |
| --- | --- |
| OS 差 | 後述。**ベンダーが持っていた責任を引き取る**話で、単なる分岐ではない |
| 単一ソース | 覆うパスは `[sandbox] deny` が既にある。Claude / Copilot と同じ表から生成できる |
| Orca overlay | `shell` は `opencode.json` に書く。`OPENCODE_CONFIG` で読ませているので overlay 下でも効く |
| 書き込み範囲 | ワークスペース以外を読み取り専用にすると、`chezmoi apply` など**ホーム配下を書く作業ができなくなる**。このリポジトリの用途と衝突する |
| `git` | `~/.gitconfig` を覆うと署名やユーザ名が消える。覆う対象の精査が要る |
| 撤退 | `shell` を消すだけ。plugin と違い生成物 1 箇所 |

**最大の論点は書き込み範囲。** このリポジトリの作業自体が `~/.config` や
`~/.claude` を書き換えるため、素朴に読み取り専用にすると仕事にならない。
Claude / Copilot 側が deny リスト方式（秘密だけ塞ぎ、他は書ける）を
採っているのはこのため。同じ方針に揃えるのが自然。

### OS 差は「分岐」ではなく「責任の移動」

`[sandbox] deny` に OS 分岐は無い。パスを並べるだけで、Seatbelt を使うか
bubblewrap を使うかは **CLI が内部で決めている**。

| | Claude / Copilot | OpenCode |
| --- | --- | --- |
| sandbox の実装 | ベンダーが内蔵 | **無い** |
| このリポジトリの役割 | deny パスを宣言するだけ | **ラッパーを自作する** |
| macOS | Seatbelt をベンダーが呼ぶ | `sandbox-exec` のプロファイルを**自作** |
| Windows | Claude は非対応と決めている | 手段が無い（同じ結論を自分で出す） |

Windows で効かないのは Claude でも同じなので、新たに悪くはならない。
**差が開くのは macOS だけ。** OpenCode は 3 OS すべてに導入される構成
（`300_windows/310_packages/run_onchange_after_314_agent_cli.ps1.tmpl`）
なので、Linux だけ実装すると CLI ごとに守られ方が変わる。

`sandbox-exec` は Apple が deprecated 扱いにしており、プロファイルの
自作と維持は新たな負担になる。**macOS 実機での検証が別途要る**
（Windows 実機検証と同じ扱い。[開発ガイド](../../../spec/development.md)）。
本書の実測はすべて Linux（Ubuntu 24.04 / bwrap 0.9.0）のもの。

## 再確認すべき情報源

- <https://opencode.ai/v2/docs/plugins> / `/permissions`（sandbox の記載は無い）
- upstream が sandbox を追加する動きがあるか（**未調査**）
- `shell` の差し替えが `terminal` 機能にも及ぶか（**未検証**）
- 子エージェントと MCP サーバが `shell` 設定を継承するか（**未検証**）

[調査記録一覧へ戻る](../../index.md)
