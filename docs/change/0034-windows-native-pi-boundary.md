# CHG-0034: Windows ネイティブ（PowerShell）で pi を、OS の境界つきで動かす

- **状態**: Exploring
- **更新日**: 2026-10-31
- **基準**: 現行の方針は [ADR-0017](../adr/0017-pi-only-and-ts-judge.md) 決定 5（Windows ネイティブの `pi` はガードなし。守りが要る作業は WSL の `pis`）。コミット `35fbda3`。Windows 実機は未検証

## 目的と非目的

**目的**: リポジトリが Windows 側にあり、**Windows でしか起動できないサーバやアプリも開発する**ので、エージェント（`pi`）を **Windows ネイティブ（PowerShell）のまま**、OS の境界つきで動かしたい（利用者の回答、2026-10-24。[記録 I3](../research/agents/pi-isolation-options.md)）。WSL の `pis`（Linux の中で守る形）では、Windows のプロセスを起動して確かめられないため、足りない。

**非目的**:

- 悪意あるコードに対する VM 級の隔離（現行 `pis` と同じく、エージェントのうっかりを止める水準。[ADR-0012](../adr/0012-ocs-boundary-for-accidents.md)）
- WSL の `pis`（現行）の変更
- OpenShell や Docker Sandboxes の導入（[記録 I2](../research/agents/pi-isolation-options.md) で、この動機には合わないと判断）

## 受入条件（実装前の期待動作）

次を満たす手段を探す。判定は Windows 実機で行う（WSL では検証できない。[AGENTS.md](../../AGENTS.md) の「Windows 実機での検証」）。

1. PowerShell から、`pi` を境界の中で起動できる（`pis` のように 1 コマンド）
2. 作業フォルダ（`C:\…` のリポジトリ）を読み書きできる
3. 作業フォルダの外、特に利用者のホームの秘密（`.ssh`・クラウドの認証ファイルなど）を、読めない・書けない
4. 境界の中の子プロセスに、制限が伝わる（`pi` が起動する `git`・`node`・ビルドのツール）
5. Windows ネイティブのビルドと、サーバ・アプリの起動（ローカルのポートの待ち受けを含む）を、許可した範囲でできる
6. 管理者権限が要る操作は、初回の導入の 1 回までにとどめる

## 実施計画

| 段 | 解決したいこと | 内容 | 状態 |
| --- | --- | --- | --- |
| 段 W0 | 候補が出そろっていない | 候補の事実を集める（[記録 I2・I3・I4](../research/agents/pi-isolation-options.md)） | 完了（Web 検索と原文の抜き書き。動かしていない） |
| 段 W1 | `srt` の Windows alpha が `pi` を包めるか分からない | Windows 実機で `srt` を入れ、`pi` を包んで、受入条件 1〜5 を確かめる。既知の制限（Schannel のクライアント、ユーザーごとのツール、DNS）の影響を測る | 未着手（Windows 実機が要る） |
| 段 W2 | `srt` が合わないとき、代替が分からない | 専用ユーザー方式（`fmuecke/agent-win-sandbox`）を、受入条件で比較する | 未着手 |
| 段 W3 | ガード（判定器・ハーネス）の Windows での動作が分からない | `pi` のハーネスの拡張を Windows ネイティブで動かす場合の、子の起動・停止（`spawn("pi")` が `pi.cmd` 経由、負の PID への `kill`）と判定の待ち時間を、実機で測る。境界が決まった後でよい | 未着手 |
| 段 W4 | 方針（ADR-0017 決定 5）と食い違う | 結果を踏まえて、ADR-0017 を部分改定する案を作り、`review` に見せる | 未着手 |

状態: 未着手 / 進行中 / 完了 / 保留 / 見送り / 消滅

## 現在地

- **動機は確認済み**: リポジトリが Windows 側で、Windows 起動前提のアプリも開発する。ADR-0017 の見直し条件「Windows でガード付きで使う需要が増える」に当たる可能性が高い（需要の大きさは、この 1 件の回答だけで、他の PC・利用の状況は未確認）
- **OpenShell は合わない**: Windows の経路は WSL2 + Docker Desktop の Linux コンテナ（Windows 専用のアプリは中で動かせない）。ネイティブは `mxc` が「Coming soon」で、提案の issue は 2026-10-13 に stale の自動処理で閉じた（[記録 I2](../research/agents/pi-isolation-options.md)）
- **Docker Sandboxes も合わない可能性が高い**: Windows ネイティブで動くが、`sbx run shell` は「Bash のログインシェル」の中に入る（確認済み: `docker-sbx-shell-agent.md:1882`）。Windows のアプリを動かせないとみられる（推測。ゲストが Linux かは原文で確かめていない）。pi の名指しもない
- **候補になるのは、Windows ネイティブの OS の境界**: `srt` の Windows alpha（専用ローカルユーザー `srt-sandbox`、ファイルの ACL、Windows Filtering Platform。**任意のコマンドを包める**）、Codex 型（restricted token ＋ 専用ユーザー。Codex 専用で、他の CLI に使う公式手順は見つからなかった）、専用の標準ユーザー方式。`srt` の既知の制限は [記録 I4](../research/agents/pi-isolation-options.md)
- `pi` を Windows ネイティブで包んだ報告は、**見つからなかった**（Docker Desktop のコンテナで `pi` を動かす個人のリポジトリはある。ネイティブではない）
- **2026-10-31 の議論（[CHG-0054](0054-containment-and-async-approval.md)、[ADR-0022](../adr/0022-containment-first-minimal-approvals.md) 案）**: 安全を「封じ込め（できることの制限）」を主にする方針では、**Windows ネイティブに境界が無いことが、確認を減らす・モードを廃止する障害**になる。PowerShell が必須のプロジェクトは多いので、境界なしの運用をどこまで許すかを決める必要がある
- **同じ課題を抱える他社の現状**（[記録 I5](../research/agents/pi-isolation-options.md#記録-i5--2026-10-31peer-の-windows-対応の現状とwsl-interop-の観測)）: Claude Code は、サンドボックスが macOS・Linux・WSL2 だけで、**ネイティブ Windows はサンドボックス無し**。Codex は、Windows ネイティブのサンドボックスを持ち、専用ユーザー方式（elevated）と、現在のユーザーから派生させた制限トークン方式（unelevated）の 2 種類を選べる
- **WSL の `pis` から `powershell.exe` を呼ぶ形（候補 H）**: 呼べることは確かめた（このセッションは Fence の外で、`powershell.exe` が `C:\Users` を一覧できた）。**Fence の中から呼べるか、呼べたとき Windows 側のプロセスが Fence の制限を受けるかは未確認**（推測: Windows のプロセスは Linux の Landlock の外で動くので、境界を突き抜ける。検証手順は「次の調査・実験」の 4）

## 未解決点

1. **`srt` の Windows alpha で `pi` が動くか**。特に、ユーザーごとのツール（`nvm`・`fnm`・`winget`・Scoop）が使えない、Schannel のクライアントが動かない、古い Node の `fetch` が直接接続を試みて拒否される、の影響。**再開条件**: Windows 実機を使える日（段 W1）
2. サーバ・アプリの起動（受入条件 5）が、`srt` の通信の制御（外向きの接続を専用アカウントごと遮断し、ループバックのプロキシのポートだけ例外）と両立するか。ローカルのポートの待ち受けと、ブラウザ・他プロセスからの接続
3. `srt` を 1 回インストールするときの UAC の確認とプロファイルの読み取りの許可（`--skip-profile-grant` で省ける）が、利用者の環境（個人機か制約のある環境の機か）で許されるか
4. 専用ユーザー方式（`agent-win-sandbox`）の、ライセンス・最終更新・保守の状態が未取得
5. ガードの Windows 移植（段 W3）の費用。ADR-0017 は「子の起動・停止、パス、`pis` の PowerShell 版」が大きいとしていた
6. **境界なしの運用をどこまで許すか**（[CHG-0054](0054-containment-and-async-approval.md) の段 7）。PowerShell が必須のプロジェクトで、境界を作るまでの間、候補 I（能力を絞る）でつなぐか。再開条件: 段 W1 の結果、または候補 H の検証結果

## 次の調査・実験

1. （段 W1）Windows 実機で、`srt` を入れて `pi` を包む手順書を作り、利用者に実行してもらう（`scripts/agents/` の手順書と、結果を貼る形。CHG-0029 の S5 と同じ型）
2. `agent-win-sandbox` の README とライセンスを `fetch` で確かめる（`explore` の子に任せる）
3. 段 W1 の結果で、段 W2・W3 の要否を決める
4. **候補 H の検証**（WSL でできる。Windows 実機は不要）: `pis` の内側で、読むだけの `powershell.exe -NoProfile -Command "Test-Path C:\Users\<名前>\.ssh"` を実行し、Fence が隠す場所に Windows 側から届くか（内容は読まない）、`powershell.exe` 自体が Fence の中で起動できるかを確かめる。届くなら、候補 H は境界を突き抜ける経路なので、`powershell.exe`・`cmd.exe` の起動を必須確認にするなどの対策が要る

## 評価基準

**必須**: 受入条件 1〜5。**望ましい**: 受入条件 6、ネットワークの制御、WSL の `pis` と同じ設定の単一ソース（`common.toml`）で管理できること。**判断の原則**: サンクコストを使わない（[AGENTS](../../AGENTS.md) の設計の姿勢）。結果を見て基準を変えたら、「重要な更新」に残す。

## 候補比較

| 候補 | 支持する根拠 | 不利な点・反証 | 未検証点 | 扱い | 次の確認 |
| --- | --- | --- | --- | --- | --- |
| A: `srt` の Windows alpha で `pi` を包む | 任意のコマンドを包める。Windows ネイティブ。専用アカウント・ACL・WFP の OS の境界。Apache-2.0、公式の README | alpha（「Beta Research Preview」）。Schannel が動かない。ユーザーごとのツールに届かない場合がある。DNS が囲われない。システムサービス経由の通信は遮断されない | `pi` を包めるか、受入条件 5 | **検証中（最有力。実機で試す価値）** | 段 W1 |
| B: 専用の標準ユーザー + OS の制限（`agent-win-sandbox` など） | 「Docker・WSL なしで、ネイティブのビルドツールを使う」と README が述べる。Codex が似た方式 | ライセンス・保守の状態が未取得。VM 級の隔離ではない。導入と削除に管理者権限が要る（[I1](../research/agents/pi-isolation-options.md)） | README の中身、`pi` との相性 | 保留（A が合わないとき） | 段 W2 |
| C: Codex 型（restricted token ＋ 専用ユーザー ＋ ファイアウォール）を自作 | OpenAI が方式を公開 | Codex 専用で、他の CLI に使う公式手順が見つからない。自作は保守が重い | — | 見送り（再開条件: A・B が不可で、方式を再利用できる公開の実装が見つかったとき） | — |
| D: Docker Sandboxes | Windows ネイティブで動く。資格情報の注入 | Bash の中に入る（Windows のアプリを動かせないとみられる）。experimental。pi の記述なし | ゲストの OS | 見送り（再開条件: Windows のゲストを選べると確かめたとき） | — |
| E: OpenShell | — | WSL2 + Docker Desktop の Linux コンテナ。ネイティブは `mxc` が「Coming soon」 | — | 見送り（再開条件: `mxc` の公開） | — |
| F: WSL の `pis` を `wsl` 経由で呼ぶ薄いラッパー | 現行の境界を使える | Windows のプロセスを起動できないので、この動機には足りない | — | 見送り（この動機では）。「操作を統一したいだけ」の動機なら別の案件 | — |
| G: 現状維持（素の `pi`、信頼できる環境でだけ） | 追加の保守が無い | 動機（Windows 側のリポジトリ）に対して守りが無い | — | 保留（A の結果が出るまで） | — |
| H: WSL の `pis` から `powershell.exe` を呼ぶ（interop） | WSL の境界と設定の単一ソースを使える。起動できることは確認済み（記録 I5） | Windows のプロセスが Linux の Fence の外で動くなら、境界を突き抜ける（推測）。F（wsl 経由のラッパー）と違い、Windows のプロセスを起動できるが、それを制限できない | Fence の中から起動できるか、Windows 側のファイルに届くか | 検証中（未検証） | 「次の調査・実験」の 4 |
| I: 能力を絞る（つなぎ）: PowerShell を使う作業は、役割を限定し、PowerShell の実行を必須確認にし、作業ツリーをタスクの契約で限る | 境界が無い間も、「確認は、人が情報を足せる操作に絞る」原則（ADR-0022 案）で説明できる。追加の基盤が無い | 境界ではないので、静的な判定器の穴（PowerShell の内部）を塗れない。確認が多くなる | PowerShell をどの粒度で止めるか。Codex の PowerShell AST を使った安全判定のような、静的検査が参考になるか（第三者の記事のみで、未確認） | 未評価 | 候補 A、B の結果と、候補 H の検証を見て決める |
| J: 使い捨ての Windows の VM（Windows Sandbox など）で全体を動かす | VM は強い境界（Anthropic も、サンドボックス・VM を挙げる） | 成果物の受け渡し、起動の重さ、サーバ・アプリのポート、永続の設定。Docker Sandboxes（D）と同じ課題 | — | 保留（再開条件: A、B が使えないと分かったとき） | — |

扱い: 未評価 / 検証中 / 有望 / 採用 / 保留 / 見送り

## 仕様への変更案

| 変更対象 | 変更前 → 変更後 | 理由・証拠 | 適用結果 |
| --- | --- | --- | --- |
| [ADR-0017](../adr/0017-pi-only-and-ts-judge.md) 決定 5 | Windows ネイティブはガードなし → 段 W1 の結果により、部分改定 | 見直し条件に当たる（動機の確認） | 未適用 |

## 実装・検証

未着手。段 W1 は Windows 実機が要るので、WSL の中からは検証できない。実機で回せない場合は、**Windows 側は未検証**と明記する。

## 重要な更新

- **2026-10-24**: 起票。「PowerShell で `pis` が使えない問題を OpenShell で解決できるか」の調査（[CHG-0033](0033-sandbox-build-value-assessment.md)、[記録 I2・I3・I4](../research/agents/pi-isolation-options.md)）で、OpenShell は合わないと分かった。動機が「Windows 起動前提のアプリの開発」と確認できたため、Windows ネイティブの境界を探す案件として起こした。

- **2026-10-31**: 安全を「封じ込め」を主にする方針（[ADR-0022](../adr/0022-containment-first-minimal-approvals.md) 案、[CHG-0054](0054-containment-and-async-approval.md)）の議論で、Windows ネイティブに境界が無いことが、確認を減らす・モードを廃止する障害になると整理した。候補 H（WSL の interop）、I（能力を絞る）、J（使い捨ての VM）を足し、他社の現状を [記録 I5](../research/agents/pi-isolation-options.md) に記録した。Windows 実機の段 W1 は未着手のまま
