# Fence を pi のシェルの先に置く実測（WSL2）と、起動の遅さの原因

- **観測日**: 2026-11-12
- **問い**: Fence（既存の囲いの CLI）を、pi の `shellPath` の先に置くと、bash・`bg_run`・`!`・子エージェントを包めるか。1 コマンドごとの遅さは何が原因で、避けられるか。
- **結論**: 包める。GPU・秘密の非表示・`/tmp` の分離・通信の許可リスト・標準のキャッシュも、設定で通った。遅さは、WSL の `/mnt` 配下の `PATH` 要素の参照（約 0.77 秒）と、作業ディレクトリのファイル数に比例する走査が主因。ラッパーで `PATH` から `/mnt` を外すと、1 コマンド約 1.0 秒が約 0.25 秒になる（実測）。公式は「コマンドごとに包む使い方より、エージェント全体を 1 回包む使い方」を勧めており、常駐・再利用の仕組みは無い。

## 環境と方法

| 項目 | 値 |
| --- | --- |
| OS | WSL2（kernel 6.18.58.1-microsoft-standard-WSL2）、Ubuntu 24.04.5 |
| Fence | 0.1.67（Built 2026-09-01、commit 3e0eefe8）。mise で導入 |
| bubblewrap / Landlock | 0.9.0 / ABI v7 |
| pi | 1.5.0（stock） |
| 試験場 | `.tmp/handson/fence-spike/`（git 管理外）。使い捨ての git リポジトリ `ws/` と、その worktree `wt/` |
| 呼び方 | 作業ツリーの `.pi/settings.json` に `shellPath` を置き、ラッパーが呼ばれたことを、囲いの外のログで確かめた。ラッパーは `fence --settings <設定> -c "$2"` |
| 公式の調査 | 子（`researcher`）が、公式の docs・issue・PR・リリースを調べた。親が、要点（benchmarking.md の脚注、issue #233・#86、PR #238、最新リリース）を原文または API で確かめた |

## 結果: 包めるか

| 試験 | 結果 |
| --- | --- |
| pi の bash ツール | `shellPath` を通った。HOME への書き込みは拒否された |
| `bg_run`（`pi-background`） | 通った。HOME への書き込みは拒否された |
| 利用者の bash（`!` と同じ経路。RPC の `bash`） | 通った。拒否された。TUI の `!` は未確認 |
| 子エージェント（`worker`）の bash | 通った（ラッパーのログに呼び出しが残った）。子が HOME へ書く試験は、権限の層（`external_directory`）が先に拒否したので、囲いでの確認は未実施 |
| GPU | `devices: {"mode": "minimal", "allow": ["/dev/dxg"]}` で `nvidia-smi -L` が RTX 3070 を認識 |
| 秘密・履歴・Windows ドライブ | `defaultDenyRead: true` と `allowRead` で、`.bash_history`・`.zsh_history`・`.ssh`・`.config/gh`・`.npmrc`・`.aws`・`.gnupg`・`/mnt/c`・`/mnt/d`・`/mnt/e` が見えない |
| `/tmp` のソケット | tmux・X11 のソケットが見えない（`/tmp` は内側専用） |
| `/run/user`（rootless docker のソケット） | **既定では見える**。`denyRead: ["/run/user"]` で塞いだ |
| `.git/config`・`.git/hooks` | `denyWrite` で書けない。`git commit` はできる |
| 標準のキャッシュ | `allowWrite` に `~/.cache/uv` を足すと書ける。足していない `~/.cache` 直下は書けない |
| 通信 | `allowedDomains` に入れた `example.com` だけ通る（`github.com` は止まる） |
| worktree | `.` だけでは、`gitdir` が外にあり `git` が動かない。設定の生成で `gitdir`・`commondir` を足すと、`commit` もでき、共有の `hooks`・`config` は書けない |

## 結果: 1 コマンドあたりの遅さ

囲いなしは約 5 ミリ秒、`bwrap` 直接は約 8 ミリ秒。以下は `fence -c true` の 1 回あたり。

| 条件 | 1 回あたり |
| --- | --- |
| 既定（`PATH` に `/mnt` 配下が 6 要素。cwd は小さい） | 約 1.0 秒（設定を空にしても同じ） |
| `PATH` から `/mnt` 配下を外した | 約 0.25 秒 |
| cwd が、ファイル 14 万件の checkout（`.tmp` を含む main） | 約 1.9 秒（`PATH` を外すと約 1.2 秒） |
| cwd が、ファイル 1,676 件の worktree、`PATH` を外した | 約 0.25 秒 |

観察:

- `fence -d` の時刻つきログでは、約 0.8 秒が「プロキシとブリッジの起動後〜機能の検出」の間に集中する。この間、子プロセスは生まれず、`stat` 系のシステムコールが多い（`/proc` の標本）。
- 設定の有無、`HOME` の中身（空にしても同じ）、通信の設定は、基底の約 1 秒を変えない。
- cwd が大きいと、基底に加えて走査の時間が乗る。Fence には `FindDangerousFiles`・`getMandatoryDenyPaths`（`internal/sandbox/dangerous.go`）がある（バイナリの文字列で確認。走査の対象は推測）。

## 公式の情報（取得日 2026-11-12）

- **既知の問題**: [docs/benchmarking.md](https://raw.githubusercontent.com/fencesandbox/fence/main/docs/benchmarking.md)（2026-04-24 の基準値）で、`GetRuntimeDeniedExecutablePaths`（毎回呼ばれる）の `Empty` が WSL で 1,698 ms、native Linux で 1.1 ms。脚注 [¹] に「Known WSL slowdown。WSL の interop 層が `/mnt/*` をまたぐ `stat` / `EvalSymlinks` を直列化するため、と思われる（likely）」とある。「WSL では 1〜3 秒が基準」とも書く。
- **公式の推奨**: コマンドごとに `fence -c` を回すより、`fence -- <agent>` のように**エージェント全体を 1 回包む**。初期化を償却すると 1 回あたり約 6〜11 µs。docs/agents.md の対応表でも、pi は `code` テンプレートで全体を包む形。
- **常駐・再利用の仕組み・プロキシだけを省くフラグ**: 見つからなかった（探した場所: docs/configuration.md、ARCHITECTURE.md、benchmarking.md、agents.md）。`network.allowedDomains: ["*"]` はブリッジを省くが、プロキシは起動し、通信の強制が外れる。ブリッジとプロキシの初期化は、公式の計測で約 93〜101 ms。
- **cwd の走査**: [issue #233](https://github.com/fencesandbox/fence/issues/233)（2026-09-26、open）と [issue #86](https://github.com/fencesandbox/fence/issues/86)（2026-03-23、open）が、`**/` 始まりのパターンが毎回 cwd を再帰的に歩くことを報告している。[PR #238](https://github.com/fencesandbox/fence/pull/238)（全パターンを 1 回の走査にまとめる。2026-10-10 作成）は、マージされずに 2026-11-05 に close された。
- **メンテ状況**: 最新リリースは v0.1.67（2026-09-01）。以降 2.5 か月リリースがない。main の最新コミットは 2026-09-10 の dependabot。open の issue は 35 件、PR は 5 件。リポジトリは `Use-Tusk/fence` から `fencesandbox/fence` に移っている。
- **WSL2 の制約**: `networkingMode=mirrored` は seccomp の user-notification リスナーを占有するので、`runtimeExecPolicy: "argv"` が使えない（microsoft/WSL#9548）。
- **セキュリティモデル**: 敵対的なコードの封じ込めは目的外（defense-in-depth）。
- **見つからなかったもの**: pi のシェルをコマンドごとに包む事例、`denyWrite` が未存在のパスに効かない件、git worktree・`/run` の扱い（探した語: worktree、`/run`、defaultDenyRead、denyWrite、nonexistent）。

## 解釈（推測を含む）

- 基底の約 1 秒は、公式が認める WSL の遅さと整合する。公式は `/usr/bin` などの参照が遅いとするが、手元では、`PATH` の `/mnt` 配下の要素を外すだけで約 0.77 秒が消えた（`/mnt` 配下は 6 要素で、1 要素あたり約 0.13 秒）。公式の脚注の仮説（`/mnt` をまたぐ `stat` が遅い）と整合する。公式の docs には、この回避策の記述は見つからなかった。
- ラッパーが `PATH` から `/mnt` を外すのは、内側から Windows の実行ファイルを呼ばせない意味でも自然。ただし、WSL の interop（`powershell.exe` など）を内側で使えなくなる。
- 残る約 0.25 秒は、プロキシとブリッジの初期化（公式の計測と同程度）。
- cwd が大きい main の checkout（`.tmp` に 14 万ファイル）で遅い。feature の worktree（1,676 ファイル）では影響が小さい。

## 限界・未検証

- `PATH` を外す案は、Fence 0.1.67・この機械の 1 回の測定（3 回ずつ）。別の機械・別の版では未確認。
- TUI の `!`、`read`・`write`・`edit`、MCP・拡張のプロセス、実際の開発作業での使い勝手は未検証。
- 子エージェントが HOME へ書く試験は、権限の層が先に止めたため、囲いの効果は未確認。
- cwd の走査の正体（どのパターンか）は、`fence config show` やソースで確かめていない。
- 上流への報告（`PATH` の `/mnt` を外すと速くなる）は、外部への書き込みなので、していない。
