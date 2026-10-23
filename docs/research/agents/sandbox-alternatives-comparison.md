# 自作サンドボックスの代替候補の比較（WSL2・pi・資格情報・ホストの道具・子の隔離）

<!-- 現在の総合判断は docs/change/ の候補比較表が正本（CHG-0033）。
     ここは「いつ何を観測したか」を積む場所 -->

## 記録 C1 — 2026-10-24

- **対象**: Docker Sandboxes（`sbx`）、nono、Anthropic の sandbox-runtime（`srt`）、Claude Code のネイティブのサンドボックス、Fence（現行の下地）、OpenShell（[O1・O2](openshell-comparison.md)）
- **環境**: WSL2（Ubuntu、カーネル 6.18、Landlock ABI 7）。基準コミット `d3a2da5`
- **方法の限界**: どれも**動かしていない**。保存した原文（公式の docs・README、個人の導入記事、比較記事）を `explore` の子に分担して読ませ、親が代表的な行を原文で確かめた（確かめた行は「確認済み」と書く）。子の抜き書きのうち親が確かめていない行は「子の抜き書き」と書く

### 問い

現行の自作サンドボックス（[`ocs` と `pis`、判定器、子の worktree 隔離](../../change/0033-sandbox-build-value-assessment.md)）が必要とする条件のうち、この環境（WSL2 のホストで、dotfiles を管理し、`pi` を使い、ホストの道具 `mise`・`uv` をそのまま使う）で、既製品が最初から満たすものと満たさないものは何か。

### 事前の予想

OpenShell と Docker Sandboxes は、コンテナまたは VM を前提とするため、ホストの道具をそのまま使えず、この環境には合わない。nono は OS の隔離型で、現行の Fence に近く、資格情報の代理を足せる。

### 結果

#### 軸ごとの原文（取得日 2026-10-24）

| 軸 | Docker Sandboxes | nono | srt / Claude Code ネイティブ | Fence（現行の下地） |
| --- | --- | --- | --- | --- |
| WSL2・Windows | Windows 11 と macOS（arm64）が対応。Windows ネイティブで動き、WSL2 の Linux ディストロは要らない。HypervisorPlatform が要る。WSL2 の中で動かす記述は**原文に無い**（確認済み: `andrewlock-docker-sandbox-microvm.md:77`、子の抜き書き: `…:79`、`docker-sandboxes-product.md:290`） | macOS・Linux・Windows（WSL2）。WSL2 では Landlock の V1〜V3 でファイル制御は完全。**資格情報の代理（`--credential`）は既定で拒否**（`insecure_proxy` を明示した場合のみ）。ポートごとのネットワーク制御は不可（確認済み: `nono-docs-wsl2.md:71`。子の抜き書き: `:61`、`:69`、`:166`、`:178`） | Claude Code ネイティブは macOS・Linux・WSL2 で動き、ネイティブ Windows ではサンドボックスなし（子の抜き書き: `claude-code-sandboxing-docs.md:137`）。srt は Windows のネイティブが alpha（`rywalker-anthropic-sandbox-runtime.md:34`） | macOS と Linux。Windows は WSL 経由のみ（子の抜き書き: `rywalker-fence.md:36`）。現行の環境で WSL2 の実測あり（`docs/research/opencode/permission/fence.md`） |
| 対応する CLI と pi | Claude Code・Codex・Cursor・Devin・Copilot CLI・OpenCode など。**pi は原文に無い**（`Shell` のサンドボックスは目次にある）。確認済み: pi の語は 3 ファイルに出ない | Claude Code・Codex・Copilot・OpenCode・Goose・OpenClaw・Hermes・**Pi**、自作も可（確認済み: `nono-github-readme.md:282`）。Pi は「pack が提供する、審査済みの能力で動く」（子の抜き書き: `:350`） | Claude Code ネイティブは Claude 専用。srt は他のコマンドを包める（子の抜き書き: `rywalker-anthropic-sandbox-runtime.md:46`）。pi 向けは、HN の報告として拡張経由の利用がある（同 `:146`） | Claude Code・Codex・Amp・Gemini CLI・Copilot・OpenCode・Factory など。pi は列挙に無いが、「コマンドの接頭辞」として任意の CLI を包める（子の抜き書き: `fence-github-readme.md:214`、`rywalker-fence.md:106`） |
| 資格情報 | ネットワーク境界で注入し、**サンドボックスの内側からは見えない**（確認済み: `docker-sandboxes-product.md:295`） | プロキシで注入（phantom token）。ただし WSL2 では既定で使えない（上の行）。`--env-credential` は子に見える（子の抜き書き: `rywalker-nono.md:141`） | srt は `network.tlsTerminate`（実験）でマスクと置換。Claude Code は「資格情報の拒否一覧は組み込みで無い」（子の抜き書き: `rywalker-anthropic-sandbox-runtime.md:122`、`claude-code-sandboxing-docs.md:575`） | 原文に記述なし（この環境の実装では資格情報は境界の内側に置く例外。[CHG-0033](../../change/0033-sandbox-build-value-assessment.md)の「現在地」） |
| ホストの道具 | イメージから作る。`mise`・`uv` をそのまま使えるかは**原文に記述なし**。エージェントごとの専用イメージ（子の抜き書き: `andrewlock-…:150`）。Kits で道具を足せる（`docker-sandboxes-product.md` の記述） | OS の隔離（コマンドの接頭辞）。ホストの道具をそのまま使える前提（子の抜き書き。原文の明示は未確認） | OS の隔離型。Claude Code は `excludedCommands` で隔離の外で動かせる。`watchman` は非互換（子の抜き書き: `claude-code-sandboxing-docs.md:446`、`:1064`） | コマンドの接頭辞で、任意の CLI に統合作業なしで差し込める（子の抜き書き: `rywalker-fence.md:106`） |
| 子・並列の隔離 | `branch` モードで、サンドボックスが `.sbx/` に git worktree を作る。自分で作った worktree の中で動かすと**コミットできない**（子の抜き書き: `andrewlock-…:188`、`:260`）。サンドボックスごとに Docker Engine を持つ | 原文に記述なし | Claude Code の子エージェントは親と同じプロセス・同じ設定（子の抜き書き: `claude-code-sandboxing-docs.md:1315`）。worktree のとき共有の `.git` に書ける（同 `:692`） | 原文に記述なし。入れ子の bubblewrap は動かない（子の抜き書き: `rywalker-fence.md:142`）。現行の実装は Landlock で包む（[CHG-0029](../../change/0029-worktree-isolation.md)） |
| GPU | 設定に「GPU のパススルー」の語はある。条件・OS は原文に記述なし | 原文に記述なし | 原文に記述なし | 現行の実測: `devices.allow` で通る（`CHG-0029`） |
| 成熟度・不具合 | 「Docker sandboxes are experimental」（確認済み: `andrewlock-…:67`）。著者は、性能の低下が「deal breaker」、コミット署名が未解決と述べる（子の抜き書き: `:303`〜`:309`） | 新しい（v0.26.0 で WSL2 に対応。`nono.sh` の記事）。WSL2 の init が seccomp の通知リスナーを占有し、2 つ目で EBUSY（子の抜き書き: `nono-docs-wsl2.md:154`、microsoft/WSL#9548、2023-01 から未解決） | srt は「Beta Research Preview」。Linux の `denyRead` は glob 先頭の形などで**効かない**ことがある（子の抜き書き: `claude-code-sandbox-runtime-github.md:752`、`:788`） | pre-1.0（v0.1.x）、「強い隔離境界を意図しない」、リソース制限なし（子の抜き書き: `rywalker-fence.md:120`、`:124`、`:128`） |

#### 追加の事実

- **コマンド単位の判定層**: 比較記事は、Fence のコマンド拒否を「実行ファイルのパスに基づく。`git push` のような複数語の意図は、同等の子プロセスの動作を防ぐ一般的な保証ではない」と述べる（子の抜き書き: `rywalker-local-agent-sandboxes.md:132`）。今回読んだ範囲で、`pi` 向けに**コマンドの内容を解析して拒否する層**を提供する既製品の記述は、見つからなかった（探していない範囲がある。「未確認」）
- **資格情報の代理の先行例**: Docker Sandboxes・OpenShell・nono・（実験）srt に、設計上の記述がある。いずれも「環境変数で渡した値は子から見える」「許可された API の誤用は防げない」という限界を持つ（Blaxel の記事は、ベンダーの記事として別に保存。親は未読）
- **OpenShell の WSL2・コンテナの前提、CVE**: [O1・O2](openshell-comparison.md)

### 考察

言える:

- 事前の予想のうち、OpenShell と Docker Sandboxes が「ホストの道具をそのまま使えない」点は、**原文で確かめきれていない**（どちらも「原文に記述なし」）。イメージから作る、という記述から、そうなる可能性が高いが、これは推測
- 予想と違った点: nono は **pi を名指しで対応**している。一方、WSL2 では、**資格情報の代理が既定で使えない**（seccomp の通知リスナーが WSL2 の init に占有されるため）。つまり nono は、この環境では、ファイル制御（Landlock）は使えるが、資格情報の代理は使えない
- Docker Sandboxes は、Windows ネイティブで動き、資格情報の注入とブランチごとの worktree を持つが、**この環境（WSL2 の中）で動かす記述が無く**、pi も対応一覧に無い

言えない: どの候補も、この環境で実際に動くかは、実測していない。現行より安全か、乗り換えて得か、は、この記録では決められない（案件 CHG-0033 の段 P4・P5）。

### 次の問い

- nono を、この環境の WSL2 で、ファイル制御だけ小さく試す（`pi` を包めるか、現行の境界との差）
- 「コマンド内容の解析層」を持つ既製品が本当に無いか、広く探す（現行の判定器の限界価値の評価に必要）
- Docker Sandboxes の WSL2 の中での動作（Linux 版の `sbx` が WSL2 で動くか。製品ページに Linux 向けのインストールの記述がある）

### 参照

- <https://docs.docker.com/ai/sandboxes/>、<https://www.docker.com/products/docker-sandboxes/>、<https://andrewlock.net/running-ai-agents-safely-in-a-microvm-using-docker-sandbox/>（個人の導入記事）
- <https://nono.sh/docs/cli/internals/wsl2>、<https://github.com/always-further/nono>
- <https://code.claude.com/docs/en/sandboxing>、sandbox-runtime の README、<https://rywalker.com/research/local-agent-sandboxes>（比較記事）
- <https://gist.github.com/wincent/2752d8d97727577050c043e4ff9e386e>（一覧の gist。`wincent-coding-agent-sandboxes-gist.md`。分類のみで、評価の記述は読んでいない）

> 原文の抜き書き（行番号）は、親が確かめたものと、子（`explore`）が抜き出したものを区別して書いた。子の抜き書きの行番号は、一部が近似である。
