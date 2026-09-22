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

### `allowWrite` が効く条件（規則を確定させた）

`denyRead` を広く掛けた下での `allowWrite` の挙動を、6 通りの組み合わせで
総当たりした。**「内側で書けるか」と「外に実体が残るか」を別々に測ること**が
要点で、これを分けないと結論を誤る。

| allowRead | allowWrite | 内側 | 実体 |
| --- | --- | --- | --- |
| WS | WS | OK | **残る** |
| WS | SUB | NG | 消える |
| WS, SUB | SUB | NG | 消える |
| WS | SUB, WS | OK | **残る** |
| (なし) | WS | OK | **残る** |
| SUB | SUB | OK | **root は消える** |

- **R1**: `allowWrite` のパスの**祖先**を `allowRead` に載せると、その
  `allowWrite` は無効化される（内側で `EROFS`）。読み取り専用の bind が
  入れ子の書き込み許可を覆うため。**完全一致なら問題ない**
- **R2**: `allowRead` にも `allowWrite` にも載っていない領域への書き込みは
  **成功したように見えて消える**。最も危険
- **R3**: `allowRead` に載っていれば、少なくとも `EROFS` で**気づける**

**実務上の指針**: 書きたい領域は**根ごと** `allowWrite` に載せ、その祖先を
`allowRead` に載せない。触りうる領域は必ずどちらかに載せる。

> 過去に 2 回踏んだ `EROFS` はすべて R1 が原因だった。
> **R2 は黙ってデータを失う**ので、設定を書いたら必ず実体を確認する。

### `denyWrite` は `allowWrite` の内側で効く

ディレクトリ単位で機能し、`allowWrite` より優先される。実測では保護対象
4 箇所すべてで新規ファイル作成が拒否され、**実体は 0 件**だった。

検証は**上書きではなく新規ファイル作成**で行うこと。効かなかった場合に
ソースを壊さないため。

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

## 7. サービスごと包む案は**成立しない**（P0-1）

OpenCode のサービスは **TCP `127.0.0.1` で待ち受け**、TUI がそこへ接続する。

```text
LISTEN 127.0.0.1:49374  users:(("opencode",pid=…))
```

Linux の `srt` は**ネットワーク名前空間を丸ごと除去する**（README）。
通信は unix socket 経由のプロキシだけになるため、内側で待ち受けても
外からは届かない。実測した。

| 位置 | 結果 |
| --- | --- |
| 内側で `bind 127.0.0.1:45671` | **成功** |
| 外側から接続 | **`TimeoutError`** |

`enableWeakerNetworkIsolation` は **macOS 専用**（trustd 向け）で、この件には
効かない。**サービスを包むと TUI が接続できなくなる。**

## 8. 実行ごとに包む案は成立する

plugin が `tool.execute.before` で **`e.input.command` を差し替えられる**。
計装で確認した。

```json
{"phase":"before","original":"echo REWRITE_ME","mutated":"echo REWRITTEN_BY_PLUGIN"}
{"phase":"after","output":"REWRITTEN_BY_PLUGIN\nCommand exited with code 0."}
```

モデルが受け取ったのは差し替え後の出力だった。よって
**shell の実行だけを `srt` で包む**構成が採れる。

### 引き換えに失うもの

**`read` / `edit` / `grep` / `glob` は境界の外に残る。** これらは shell を
経由しないため、包む対象にならない。permission の deny と既存の結果フィルタを
**捨てられない**。

### 故障時の振る舞い

plugin が死ぬと、包む処理と `allow` への引き上げが**同時に**死ぬ。
結果は「包まれないが確認は出る」= 現在の状態に縮退する。危険側へは倒れない。

## 9. プロジェクト単位の許可リストは効く

秘密を拒否したまま、chezmoi 管理下の非機密パスだけを開けられる。

| パス | 設定 | 結果 |
| --- | --- | --- |
| `~/.ssh` | 未許可 | **拒否** |
| `~/.config/gh` | 未許可 | **拒否** |
| `~/.config/opencode` | 未許可 | **拒否** |
| `~/.config/shell` | `allowRead` | **読める** |
| `~/.config/mise` | `allowRead` | **読める** |
| `~/.config` 自体の一覧 | — | 読める（子は個別に判定） |
| `. ~/.config/shell/shellenv.sh` | — | **読み込み成功** |

パス単位で粒度が出る。**ただし許可リストをプロジェクト側に置いてはいけない。**
敵対的なリポジトリが `~/.ssh` を自分で許可できてしまい、
[プロジェクト設定がグローバルに勝つ問題](gaps.md)と同じ穴になる。
`common.toml` にプロジェクトパスをキーとして持たせる。

## 10. 版は Claude Code と共有している（P0-3）

```toml
# home/dot_config/mise/config.toml.tmpl
"npm:@anthropic-ai/sandbox-runtime" = "latest"
```

`latest` の浮動指定で、Claude の `sandbox.seccomp.applyPath` も同じ `latest` を
指している。**片方の都合で上げると両方の挙動が変わる。** OpenCode でも使うなら
版を固定するか、壊れたときに両方を見る前提にする。

## 11. 固定費は 1 回あたり約 650 ms

CLI 経由で包むと、`echo` 1 回でも待たされる。

| 実行 | 所要 |
| --- | --- |
| 素の `echo` | **7 ms** |
| `srt` 包みの `echo` | **657 ms** |

CLI は毎回 node の起動とプロキシの初期化を行うため。**実行ごとに包む構成では
この固定費が全 shell 呼び出しに乗る。**

**回避策**: plugin は node（サービス）の中で動くので、CLI ではなく
**ライブラリ API** を使う。`SandboxManager.initialize()` を plugin のロード時に
1 回だけ呼び、コマンドごとには `wrapWithSandbox()`（文字列を返すだけ）を呼ぶ。
プロキシの起動を償却できる。**未計測**なので、実装時に測り直す。

参考として、確認を 1 回出すと人間の応答待ちで秒単位かかる。約 94% の
呼び出しが無確認になるなら、数百 ms の固定費は割に合う可能性が高い。

## 12. `--stdio` は行き止まり（P0-1 の再確認）

`opencode serve` に `--stdio` があるので、TCP を避けられれば
「サービスごと包む」案が復活する可能性を追った。**復活しない。**

TUI 側の接続手段は `--server <URL>`（HTTP）だけで、stdio で繋ぐ口が無い。
`--stdio` は別用途（ACP / MCP）のもの。

## 13. 組み込みツールは `execute.before` で止められる

反転案（shell で代替できるツールを禁止して境界の内側へ寄せる）の要。
`execute.before` で例外を投げると**ツールが失敗し、メッセージがモデルへ届く**。

```text
✗ Grep "Dotfiles" failed
Error: grep ツールは使えません。shell の `grep -rn` を使ってください。
```

モデルは理由をそのまま報告し、指示どおり代替手段を試さなかった。
誘導の `deny` と同じ挙動で、**向きだけが逆**になる。

| | いまの誘導 | 反転後 |
| --- | --- | --- |
| 目的 | permission の `deny` が効く経路へ寄せる | **OS の境界の内側へ寄せる** |
| 例 | `cat` → `read` ツール | `grep` ツール → shell の `grep -rn` |

## 14. 保護機構そのものが書き換えられる

`edit` の permission を実際に当てて確かめた。**全て書ける。**

```text
★書ける  home/dot_config/agents/common.toml.tmpl
★書ける  home/dot_config/opencode/guide-plugin/index.js
★書ける  scripts/agents/generate.py
★書ける  home/dot_config/mise/config.toml.tmpl
```

`chezmoi apply` を 1 回承認させれば保護が消える。**境界の内側で完結する経路**で、
外部レビュー（Astra）の指摘どおりだった。

`srt` の `denyWrite` は `allowWrite` より優先されるので、ワークスペース内でも
これらだけ書き込み禁止にできる。

## 15. ライブラリ API で固定費は 44 ms まで落ちる

CLI 経由の 657 ms は node の起動とプロキシ初期化を毎回やり直すため。
`SandboxManager.initialize()` を 1 回だけ呼び、コマンドごとには
`wrapWithSandbox()` を使うと解消する。

| 実行 | 素 | 包んだ | 上乗せ |
| --- | --- | --- | --- |
| `echo x` | 3 ms | 47 ms | **44 ms** |
| `grep -rn permission docs/` | 19 ms | 59 ms | **40 ms** |

`initialize()` は **426 ms**。plugin のロード時に 1 回だけ払う。

**plugin はサービス（node）の中で動くので、この構成が取れる。** CLI を
呼び出す実装にしてはいけない。

> **この 44 ms は楽観的だった。** あらかじめ包んだ文字列を実行するだけの
> 計測で、呼び出しごとに `wrapWithSandbox()` を通す実装では **91 ms**
> （試作で実測）。許容値には収まるが、**実装時の見積もりは 90 ms 前後**を
> 使うこと。

## 16. 移行後の自動化率（実履歴 1,128 呼び出し）

止まる要因を「承認待ち」と「失敗」に分けて数えた。**無人で進めたい場合、
失敗のほうが厄介**（止まったうえに理由が分かりにくい）。

| 区分 | 件数 | 割合 |
| --- | --- | --- |
| 自動で進む | 1,033 | **91.6%** |
| 承認で止まる | 15 | 1.3% |
| 失敗で止まる | 80 | **7.1%** |

加えて `grep` / `glob` ツール 36 件が shell へ移るので自動側に入る。

### 承認で残るもの

| 件数 | 内容 |
| --- | --- |
| 13 | `chezmoi apply` / `re-add` |
| 2 | `git push` |

### 失敗で止まるもの（対処可能）

| 件数 | 内容 | 対処 |
| --- | --- | --- |
| 50 | `opencode.ai` が許可外 | ドメイン許可リストへ追加 |
| 25 | `gh` / `git fetch` に認証情報が要る | 読み取り専用 PAT を境界内へ |
| 5 | `claude.ai` / `example.com` | 同上 |

対処後の見込みは **自動 98.7% / 承認 1.3% / 失敗ほぼ 0%**。

> **「自動」は「境界内で成功する」前提。** ワークスペース・`/tmp`・`~/.cache`
> 以外へ書くコマンドは失敗する。過去のリダイレクト先を見た限りほぼ無いが
> ゼロではない。実運用で洗い出す。

## 再確認すべき情報源

| # | 減らしたい不確実性 | 方法 |
| --- | --- | --- |
| （決着済み） | P0-1 / P0-2 / P0-3 と許可リストの粒度 | 上記 7〜10 章 |
| 残り | `srt` の起動遅延が実用に耐えるか（**未計測**） | 包んだコマンドと素のコマンドで所要時間を比べる |
| 残り | `allowWrite` がサブディレクトリだと失敗する条件（**未特定**） | — |
| 残り | 許可漏れドメインの洗い出し（`mise.jdx.dev` が不足） | 検証コマンドを境界内で一巡させる |

[調査記録一覧へ戻る](../../index.md)
