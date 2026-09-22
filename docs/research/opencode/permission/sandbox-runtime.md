# Anthropic Sandbox Runtime（`srt`）を OpenCode に使えるか

> **調査日: 2026-09-22 / 対象: `@anthropic-ai/sandbox-runtime` v0.0.76（Ubuntu on WSL2）**
>
> [CHG-0004](../../../change/0004-opencode-sandbox.md) の前提調査。
> 「個別に穴を塞ぎ続ける」方針から「OS のアクセス制御を主役にする」方針へ
> 切り替えられるかを確かめた。

## 0. 結論

| # | 問い | 結果 |
| --- | --- | --- |
| 1 | `srt` は Claude Code 専用か | **汎用**。「任意のプロセスに境界をかぶせる」と自称 |
| 2 | 導入済みか | **済み**（seccomp のため mise で入れてあった） |
| 3 | ファイルの隔離は効くか | **効く**。ただし `denyRead` に**強い癖**がある（下記 3 章） |
| 4 | ドメイン制限は効くか | **効く**（`github.com` 200 / `example.com` 遮断） |
| 5 | 認証情報を落とせるか | **落とせる**。`git push` も `gh` も認証に失敗する |
| 6 | WSL2 の socket 脱出は塞がるか | **塞がる**（`cmd.exe` の起動が拒否された） |
| 7 | `chezmoi`（snap）は動くか | **動かない**。snap の阻却事由を実地で再現 |

**採用可能。ただし `denyRead` の癖と snap の解消が前提になる。**

## 1. 起動方法（名前が衝突する）

`bin` は `srt` だが、**PATH の `srt` は Python の字幕処理ツール**だった。
mise 経由でも解決されないので、実体を直接叩く。

```sh
node ~/.local/share/mise/installs/npm-anthropic-ai-sandbox-runtime/latest\
/node_modules/@anthropic-ai/sandbox-runtime/dist/cli.js \
  -s <settings.json> -c '<command>'
```

`-d` で詳細ログが出る。**設定が無視されたときはここにしか出ない**（下記 3 章）。

## 2. Linux での実装

デバッグログで確認した。

```text
[SeccompFilter] Found apply-seccomp binary: .../vendor/seccomp/x64/apply-seccomp
[Sandbox Linux] Applying seccomp filter for Unix socket blocking
[Sandbox Linux] Wrapped command with bwrap (network, filesystem, seccomp(unix-block) restrictions)
```

bubblewrap + seccomp + **sandbox の外に置いたプロキシ**の 3 点構成。
ドメイン判定はプロキシが持つので、全サブプロセスに等しく効く。

## 3. `denyRead` は「許可領域の内側」にしか効かない

**最も重要な癖。** 許可領域の外に書いた `denyRead` は**黙って読み飛ばされる**。

```text
[Sandbox Linux] Skipping deny path not within allowed paths: …/.git/config
[Sandbox Linux] Skipping non-existent deny path not within allowed paths: …/.bashrc
```

実測は次のとおり。

| 設定 | `~/.ssh` | `~/.config/gh` | `~/.git-credentials` |
| --- | --- | --- | --- |
| `denyRead: ["~/.ssh", …]` | **読めた** | **読めた** | **読めた** |
| `denyRead: ["/home/applejxd/.ssh", …]`（絶対パス） | **読めた** | **読めた** | **読めた** |
| `denyRead: ["/home/applejxd"]` + `allowRead` で再許可 | 拒否 | 拒否 | 拒否 |

**`~` の展開の問題ではない。** 読み取りは既定で全面許可で、`denyRead` は
「広い領域を deny してから `allowRead` で戻す」形でしか機能しない。
README の Linux 向けレシピ（`denyRead: ["/home"], allowRead: ["."]`）が
唯一の正しい書き方で、**ピンポイントの deny は効かない**。

> 設定を書いても**エラーにならず黙って無視される**。これは今日踏んだ
> 「`~/` 始まりの read deny glob が一度も当たらない」件と同じ型の事故で、
> **設定した気になって開いたままになる**。導入時は必ず実地で確かめる。

### `allowWrite` との競合

`denyRead: ["/home/applejxd"]` の下で `allowWrite` に**サブディレクトリ**を
指定すると書き込みが失敗した（`Read-only file system`）。
`allowWrite` を**ワークスペースの根**にすると成功した。

| `allowWrite` | 結果 |
| --- | --- |
| `…/chezmoi/.tmp/sbx`（サブディレクトリ） | **失敗** |
| `…/chezmoi`（根） | 成功 |

### `$HOME` は差し替えられる

広い `denyRead` を掛けると、sandbox 内の `$HOME` が別の場所になる。
`$HOME` 直下への書き込みは**成功するが実ホームには現れない**。
「書けた」を境界の破れと誤読しないこと（実ホームを確認して無害と判定した）。

## 4. 効いたもの（実運用に近い設定）

`denyRead: ["/home/applejxd"]` + `allowRead` にワークスペース・mise・
`~/.cache`・`~/.local/bin` + `allowWrite` にワークスペース根・`~/.cache`・`/tmp`。

| 検査 | 結果 |
| --- | --- |
| `~/.ssh` / `~/.config/gh` / `~/.git-credentials` | **拒否** |
| ワークスペースの読み書き | 成功 |
| `git log` | 成功 |
| **`git push`** | **`fatal: could not read Username`** |
| **`gh auth status`** | **`You are not logged into any GitHub hosts`** |
| `curl https://github.com` | `200` |
| `curl https://example.com`（許可外） | **遮断**（`000`） |
| `cmd.exe /c echo`（WSL の脱出経路） | **拒否** |
| `mise --version` | 成功（ただし `mise.jdx.dev` が許可外で警告） |
| `uv --version` | 成功 |
| **`chezmoi --version`** | **snap の internal error** |

**認証情報を見せないだけで `git push` と `gh` の書き込みが止まる。**
コマンド文字列の判定は 1 つも要らない。

## 5. `chezmoi` が snap である限り成立しない

```text
2026/09/22 … cmd_run.go:18
See https://forum.snapcraft.io/t/46210 …
internal error, please report: running "…"
```

以前の調査の結論を**別ルートで再現**した。`sudo snap install chezmoi --classic`
（README のブートストラップ 1 行）を公式インストーラの静的バイナリへ
置き換えることが前提になる。

`~/.local/bin` は PATH にあり、`chezmoi upgrade` も使えるようになる
（snap 版では効かない）。

## 6. 許可リストに足りないもの

現在の `[sandbox] claude_network_allow` は Claude 向けに作られており、
`mise.jdx.dev` が入っていない（`mise-versions.jdx.dev` はある）。
OpenCode を包むなら実地で不足を洗う必要がある。

不足しても破綻はせず、接続が失敗するだけなので追記で回復できる。

## 再確認すべき情報源

- `opencode serve --service` を包んだとき、TUI との通信が通るか（**未検証**）
- `chezmoi apply` を境界の外へ出す手段（**未検証**。境界内からは実行できない）
- `srt` の版が Claude Code と結合していないか（**未確認**。勝手に上がると壊れる）
- `allowWrite` がサブディレクトリだと失敗する条件（**未特定**）

[調査記録一覧へ戻る](../../index.md)
