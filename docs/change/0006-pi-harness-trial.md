# CHG-0006: Pi / oh-my-pi を利便性の軸で試す

- **状態**: In progress
- **更新日**: 2026-09-24
- **基準**: 未導入の状態から開始。既存は Claude Code / Copilot CLI / OpenCode V2

## 目的と非目的

**目的**: Pi (earendil-works/pi) と oh-my-pi (can1357/oh-my-pi、`omp`) を
**利便性の軸で**評価し、第一サポートを変えていける状態を作る。

**非目的**:

- **これらを OS 境界（`ocs`）へ入れること。** 下記「軸について」を参照
- `common.toml` の permission 生成系へ組み込むこと
- 4 OS すべてへの展開。まず Ubuntu / WSL で 1 つ通す

**発端**: 「今後いろいろなハーネスを試す予定。どれを第一サポートにするかは
検討段階で変えていく。動機は効率ではなく興味」という要望。

## 軸について（この案件の前提）

**Pi は設計思想として安全性より利便性を取っている。** 公式リポジトリに
permission 機構を持たないと明記があり、権限制御は拡張か外部の OS sandbox へ
委ねる設計になっている。

> Pi does not include a built-in permission system for restricting filesystem,
> process, network, or credential access.

したがって **[CHG-0004](closed/0004-opencode-sandbox.md) と同じ安全性第一の物差しで
評価しない。** 同じ物差しを当てると、これらの harness の長所（最小構成・
拡張性・IDE 統合）が全部「欠点」として出力されるため、判断材料にならない。

**代わりに、払っている代償を正確に言語化したうえで利便性を取る。**
代償は下記「払う代償」に列挙する。「危険だからやめる」ではなく
「これが起きうると知ったうえで使う」という形にする。

## 現在地

### 調べて分かったこと

| 項目 | Pi | oh-my-pi (`omp`) |
| --- | --- | --- |
| 位置づけ | 最小・ハッカブルな核 | Pi のフォーク。IDE 統合が売り |
| 導入 | `npm i -g --ignore-scripts` / 公式スクリプト | `curl -fsSL https://omp.sh/install \| sh` / bun / brew / **mise** / nix |
| 設定 | `~/.pi/agent/settings.json` | **`~/.omp/agent/config.yml`**、MCP は `~/.omp/agent/mcp.json` |
| skills | Agent Skills 仕様に準拠 | 同左 |
| 固有機能 | 拡張（TypeScript、ホットリロード）、4 モード（interactive / print-JSON / RPC / SDK） | LSP 統合、DAP（実デバッガ駆動）、subagents、plan mode、hashline edits、time-traveling rules |

### 最も重要な発見: `omp` は `~/.claude` を探索ルートに含むが、skills は opt-in

`omp` の設定探索ルートは次の固定順（公式ドキュメント
`docs/config-usage.md` の記述）。

```text
config roots:      .omp  →  .claude  →  .codex  →  .gemini
user-level bases:  ~/.omp/agent,  ~/.claude,  ~/.codex,  ~/.gemini
project-level:     <cwd>/.omp,    <cwd>/.claude,  ...
```

**ただし「探索ルートに含む」ことと「`~/.claude/skills` を読む」ことは別。**
実機で確認した既定値:

```text
skills.enableClaudeUser    = false   ← 既定で無効
skills.enableClaudeProject = true
skills.enableAgentsUser    = true
skills.enablePiUser        = true
```

| 置き場 | 件数 | 既定で見えるか |
| --- | ---: | --- |
| `~/.claude/skills`（このリポジトリの自作） | 16 | **見えない** |
| `~/.agents/skills`（Orca 由来） | 4 | 見える |

**素のままでは自作 skills が 1 つも使えない。** フラグ
（`enableClaudeUser`）ではなく `skills.customDirectories` にパスで明示する
方式を採った。フラグは `~/.claude` 配下の何が有効になるか読めないが、
パス指定なら「どこから来た skill か」が設定を見るだけで分かる。

### 2 つ目の門: `enabledProviders` が他ツールのユーザ領域を丸ごと閉じている

`skills.enableClaudeUser` は**門の 1 枚目でしかなかった**。公式ドキュメント
`docs/settings.md` に、より上流の門がある。

> `enabledProviders` opts foreign user-level configuration sources into
> discovery. Its default is empty, so user roots from Cursor, Codex, Claude,
> Claude marketplace plugins, Gemini, OpenCode, Windsurf, and GitHub **do not
> load until their provider id is listed**. Project roots remain enabled.

つまり既定では、`~/.claude` 配下のユーザ領域は**何一つ読まれない**。
skills だけの話ではなかった。閉じていたのは次の全部。

| 資産 | 実体 | 既定 |
| --- | --- | --- |
| **MCP サーバ定義** | `~/.claude.json` の `mcpServers`（`deepwiki`） | **読まれない** |
| スラッシュコマンド | `~/.claude/commands/*.md`（4 件） | 読まれない |
| ユーザ文脈ファイル | `~/.claude/CLAUDE.md` | 読まれない |
| LSP 設定 | `~/.claude/lsp.*` | 読まれない |
| skills | `~/.claude/skills`（16 件） | 読まれない |

**段 1.5 で skills が通ったのは、`customDirectories` がプロバイダ機構を
迂回して直接ディレクトリを走査するため。** 門を開けたのではなく、
横を通していた。だから MCP には効かなかった。

`enabledProviders: [claude]` を入れると 1 枚目の門が開く。`*` / `all` では
なく `claude` だけにしたのは、codex / gemini / opencode / cursor / windsurf /
github / claude-plugins まで同時に開くと「どの定義が採用されたか見えにくい」
という既知の懸念（下記「未解決点」）をそのまま悪化させるため。

> **`~/.claude/hooks/` は開いても実行されない**（確認済み）。omp が拾う hook は
> `hooks/pre/` `hooks/post/` 配下の `.ts` / `.js` ファクトリだけで、このリポジトリが
> 置いているのは `~/.claude/hooks/*.py` と `*.sh`。`pre/` / `post/` も無い。
> `settings.json` の `hooks` 節（Claude Code 形式）も omp は読まない。
> **Claude 用に生成した hook が omp で暴発する経路は無い。**

### 訂正した思い込み

| 当初 | 実際 |
| --- | --- |
| 設定は `~/.omp/config.yml` | `~/.omp/agent/config.yml` |
| skills の再利用には設定が要る | **設定が要る（当初の想定が正しかった）。** 一度「標準で読む」と誤認したが、実機で `enableClaudeUser = false` を確認して撤回 |
| 「設定形式が違うから単一ソースに入れない」 | **形式変換は生成器の得意分野**。本質は「同じ意味の設定項目が無い」こと |

3 つ目が重要。理由を取り違えると次の判断を誤る。JSON / YAML の差は障害では
ない。permission という**概念自体が無い**ことが障害。

2 つ目は自分の誤りを記録として残す。`config-usage.md` の config roots に
`.claude` があるのを見て「skills も読む」と早合点した。**探索ルートに含むことと、
その配下の資産を読むことは別**だった。外部レビュー（Astra）は
「他ツールのユーザー領域の読み込みは opt-in」と正しく指摘しており、
実機の既定値がそれを裏付けた。

### まだ分からないこと

- 16 個の skills が**実際に完走するか**。Agent Skills 仕様が揃えているのは
  主に発見と記述の形式で、サブエージェント API・ツール名・Orca 依存・シェル
  環境への依存は残る。`review-loop` や `arxiv-paper-ja` は委譲手順まで動くか
  見る必要がある
- MCP の接続定義を共有できても、OAuth のログイン状態まで共有できるとは限らない
- `omp` の subagent が使う隔離バックエンドの実体（README は
  "optionally workspace-isolated" と書いており、常に git worktree とは限らない）

## 推奨設定（`omp config list` の全項目を見た結果）

`omp config list` は 9 節・約 400 項目ある。**ほとんどは既定のままでよい。**
既定が明らかに惜しいもの、既存資産と繋がるものだけを挙げる。

### 採用（実装済み）

| 設定 | 既定 → 採用値 | なぜその値か |
| --- | --- | --- |
| `enabledProviders` | `[]` → `["claude"]` | 既定では `~/.claude.json` の MCP も `~/.claude/commands` も**読まれない**。`*` にせず `claude` だけにして、採用元を 1 つに絞る |
| `commands.enableClaudeUser` | `false` → `true` | `~/.claude/commands/*.md`（`ask` / `commit` / `criticalthink` / `onboarding`）をそのまま `/ask` 等として使える。新規に書くものが無い |
| `bashInterceptor.enabled` | `false` → `true` | 下記 |
| `skills.customDirectories` | `[]` → `~/.claude/skills` | 段 1.5 で実施済み |

### `bashInterceptor` を入れた理由と、正確な挙動

`bash` を `read` / `grep` / `glob` / `edit` / `write` / `hub` へ振り替える。
**内蔵の既定パターンが、このリポジトリが `common.toml` に書いている誘導規則と
ほぼ同じ内容**（`cat`/`head`/`tail` → `read`、`grep`/`rg` → `grep`、
`find`/`fd` → `glob`、`sed -i` → `edit`、`echo >` → `write`）。
**パターンを 1 行も書かずに他の CLI と挙動が揃う**ので採った。

> **呼称の食い違いを実測した。** 公式ドキュメントは "redirects Bash commands
> to dedicated tools **rather than defining whether a command may execute**"
> と書くが、`omp config list` の説明文は "**Block** shell commands that have
> dedicated tools" になっている。実際にはその bash 呼び出し自体は通らず、
> モデルへ「こちらのツールを使え」と返る。**止まるのは事実**。
> ただし止める対象は道具の選び方であって到達範囲ではない（同じことは
> `eval` 経由でも素通りする）。**境界ではない**ので、この案件の軸と矛盾しない。

### 見送り（根拠つき）

| 設定 | 見送る理由 |
| --- | --- |
| `task.isolation.enabled` / `worktree.*` | subagent の隔離バックエンドの実体が未確認（下記「まだ分からないこと」）。段 2 の前に作り込まない |
| `memory.backend` / `autolearn.enabled` | 外部サービスや追加モデルが要る。素の使い勝手を測る前に入れると、何が効いたか分からなくなる |
| `find.enabled` | `auto` のままで足りる。`on` は `judge` ロールが TypeSafe の native モデルに解決できるときだけ働き、`TYPESAFE_API_KEY` が要る |
| `github.enabled` | 内蔵 GitHub ツール。`github-issue` skill と繋がる見込みはあるが、**認証経路が未確認**（`gh` の資格情報を使うのか独自なのか読めなかった） |
| `enabledProviders` に `*` | 7 ソースを同時に開くと、採用された定義の出所が追えない |

### 好みで決まるもの（実装しない。使ってみて決める）

ここは「正解がある」類ではないので値を置かない。段 2 を回してから選ぶ。

| 設定 | 既定 | 振れ幅 |
| --- | --- | --- |
| `autoResume` | `false` | `true` にすると同じディレクトリの直近セッションを自動で継ぐ。`omp -c` を毎回打つか、勝手に繋がるのを嫌うかの好み |
| `compaction.idleEnabled` | `false` | `true` は待ち時間中に圧縮を済ませる。ターン中に止まらなくなる代わり、裏でトークンを使う |
| `readLineNumbers` | `false` | `edit.mode = hashline` が既に行番号付きで読ませるので、重ねる意味があるかは好み |
| `includeWorkspaceTree` | `false` | 起動時にツリーを入れる。当たりは早くなるが文脈を食う |
| `tui.vimMode` / `tui.mouse` | `false` | 操作の好み |
| `error.notify` | `off` | `on` で失敗時に通知。WSL で通知が届くかは**未確認** |

### 採らなかった実装方式: `PI_CONFIG_FILES` オーバーレイ

「chezmoi 管理の YAML を 1 枚置いて `PI_CONFIG_FILES` で読ませる」方式も
検討した。書き込み競合が原理的に起きない（オーバーレイは読み取り専用）点は
魅力だが、2 つの理由で採らなかった。

- **優先順位が `/settings` より上。** `defaults <- global <- project <-
  PI_CONFIG_FILES <- --config <- runtime` なので、オーバーレイに書いた鍵は
  UI から変更できなくなる（変更は global に書かれ、負ける）
- **ファイルが無いと起動が落ちる。** オーバーレイは strict で、欠損・不正
  YAML・非マッピングが全てハードエラー。chezmoi 適用前の環境で `omp` が
  起動しなくなる

## Pi を入れるならこの設定（未導入。調査のみ）

実装はしない（段 4 の材料）。公式ドキュメント
`packages/coding-agent/docs/` を読んで分かったこと。

### Pi は MCP を持たない

**`packages/coding-agent/docs/` の 39 ファイル全てに `MCP` の記述が 1 件も無い。**
`settings.md` にも MCP の項目が無い。拡張（TypeScript）で自作する余地は
あるが、**`common.toml` の `[[mcp]]` を Pi へ配る先が存在しない。**

これは omp との実質的な差になる。omp 側は `enabledProviders: [claude]` の
1 行で既存の MCP 定義が繋がるのに対し、Pi は同じことに拡張の実装が要る。

> 後述のとおり**この判定は静的な読みのみ**で、実機では確認していない。

### 設定の置き場と、既定で惜しいところ

設定は `~/.pi/agent/settings.json`（`PI_CODING_AGENT_DIR` で移動可能）。
omp の `~/.omp/agent/config.yml` とは**別物なので共有させない**
（既存の「未解決点」のとおり）。

| 設定 | 既定 | 入れるなら | 理由 |
| --- | --- | --- | --- |
| `defaultTools` | `["read","bash","edit","write"]` | `+ grep` `find` `ls` | **これが一番惜しい。** `grep` / `find` / `ls` は実装されているのに既定で無効で、素のままだと検索を全部 `bash` でやることになる |
| `skills` | `[]` | `["~/.claude/skills"]` | Pi が素で見るのは `~/.pi/agent/skills` と `~/.agents/skills` だけ。自作 16 個は `~/.claude/skills` にあるので明示が要る（omp の `customDirectories` と同じ話） |
| `defaultThinkingLevel` | `"medium"` | `"high"` | omp の既定は `high`。比較の条件を揃えるため |
| `defaultProjectTrust` | `"ask"` | 変えない | 段 4 では毎回聞かせて、どこを信頼したか見えるようにする |

`skills` は**再帰的に**走査される（omp の `customDirectories` は非再帰）。
同じパスを渡しても拾う範囲が違いうるので、段 4 で件数を突き合わせる。

### 比較を成立させるための注意

- `enableInstallTelemetry` の既定が `true`。匿名の導入・更新レポートを送る。
  止めるかは好み
- Pi の skills は `name` とディレクトリ名の不一致を**警告しない**。このリポジトリの
  約束（`SKILL.md` の `name` はディレクトリ名と一致）は Pi では検出されないので、
  Pi で通っても他で通るとは限らない

## 評価基準

**必須**（これが通らなければ試用の意味がない）:

- 普段の作業が 1 周完走する: 認証 → skills 発見 → MCP 呼び出し →
  編集 → テスト → セッション再開
- 既存の Claude Code / OpenCode の設定を**壊さない**

**望ましい**:

- 16 個の skills のうち、常用するものが動く
- 乗り換えの持ち物が「git の変更・課題・Markdown の checkpoint」で足りる
  （セッション DB や独自 memory の互換性を前提にしない）

**採用しない基準**:

- 「OS 境界に入るかどうか」は評価しない（目的外）

## 払う代償

代償の本質は **「意図と実行の間にあった確認機会が減り、誤りに気づいた時点で
既に副作用が発生している」**こと。

| 具体的に起きうること | 運用での緩和（設定ではなく習慣で効くもの） |
| --- | --- |
| パスの取り違えで別プロジェクトやホームの設定を編集する | 対象リポジトリ直下から起動する。初回比較は専用 checkout を使う |
| 未コミット作業を上書きし、元が分からなくなる | 開始前に区切ってローカルコミット。未追跡の重要ファイルも保全する |
| `gh` / クラウド CLI / MCP から公開・削除・外部更新が走る | 開発用アカウントを既定にし、本番資格情報は必要なときだけ用意する |
| 読んだ秘密がモデル送信・会話ログ・公開コミットへ入る | 秘密は source state の外で管理。push 前の差分確認と secret scan |
| subagent が費用・CPU・ディスクを増やし、ポートや DB で衝突する | 最初は小さな並列から。課金上限・作業別ポート・テスト DB |

**git と作業ディレクトリの選択は、混同を減らして復旧しやすくする手段**であって、
アクセスを止めるものではない。git は外部 API の更新や送信済みの情報を戻せない。

## 実施計画

| 段 | 内容 | 状態 |
| --- | --- | --- |
| 1 | `omp` を導入する（既存の AI CLI 導入スクリプトへ合流） | **完了**（2026-09-24。`v18.2.11`） |
| 1.5 | 自作 skills を `omp` から見えるようにする | **完了**（2026-09-24） |
| 1.6 | 既存の MCP / コマンドを `omp` へ繋ぐ（`enabledProviders`） | **完了**（2026-09-24。実機での疎通は段 2） |
| 2 | 普段の作業を 1 周通す（認証・skills・MCP・編集・再開） | 未着手 |
| 3 | 常用 skills が動くか確認し、動かないものを記録 | 未着手 |
| 4 | Pi を比較用に追加し、同じ開始コミット・同じ課題で比べる | 未着手 |
| 5 | 第一サポートを決める（または「決めない」と決める） | 未着手 |

**段 2 より先に設定を作り込まない。** ただし skills が 1 つも見えないのは
観測以前なので、段 1.5 だけは先に入れた。

## 候補比較

| 候補 | 支持する根拠 | 不利な点・反証 | 未検証点 | 扱い | 次の確認 |
| --- | --- | --- | --- | --- | --- |
| `omp` から入る | LSP / DAP / subagent / MCP が揃い、最初の成果まで近い。`~/.claude` を読む | フォークなので上流追随が不明 | skills が完走するか | **採用**（先行） | 段 2 |
| Pi から入る | 小さい核から自分の操作体系を作れる | 既存 3 ハーネス相当の利便性を再構築すると、試用が開発プロジェクトになる | — | 検証中（比較用） | 段 4 |
| 両方を同時に整備 | — | **インストールは軽いが、両方の独自拡張を育てるのは重い** | — | 見送り | — |
| 共通ランチャー / セッション変換器を作る | — | 初期段階で作るのは早すぎる | — | 見送り | — |

## 仕様への変更案

| 変更対象 | 変更前 → 変更後 | 理由・証拠 | 適用結果 |
| --- | --- | --- | --- |
| `agent-cli-install.sh.tmpl` | （なし）→ `omp` を追加 | 既存 3 CLI と同じ流儀に合流させる | **完了** |
| `[web] allow_domains` | → `pi.dev` / `omp.sh` を追加 | ドキュメント参照用 | **完了** |
| `400_unix/420_omp_skills` | （なし）→ `skills.customDirectories` へ `~/.claude/skills` を追記 | 既定 `enableClaudeUser = false` で自作 skills が 1 つも見えない | **完了** |
| `400_unix/430_omp_claude_assets` | （なし）→ `enabledProviders` へ `claude` を追記 | 既定 `[]` で `~/.claude.json` の MCP もコマンドも読まれない | **完了** |
| 同上 | （なし）→ `commands.enableClaudeUser` を `true` に種まき | 既存の Claude コマンド 4 件をそのまま使う | **完了** |
| 同上 | （なし）→ `bashInterceptor.enabled` を `true` に種まき | 内蔵の既定パターンが `common.toml` の誘導規則とほぼ同じ。**パターンを書かずに**他 CLI と挙動が揃う | **完了** |
| `common.toml` へ omp 固有設定を足す | **足さない** | 「共通プロファイルを増やさず個別設定に書く」方針。omp の設定は `~/.omp/agent/config.yml` が正本 | **対象外** |
| `common.toml` の permission 生成 | 変更しない | **permission という概念が無い**ので翻訳先が無い | **対象外** |
| `~/.omp/agent/config.yml` の chezmoi 管理 | 丸ごとは管理しない | 認証・セッション・自動生成 memory を含む。**必要な 1 項目だけ** CLI 経由で追記する | **完了**（方式を確定） |

### `~/.omp/agent/config.yml` を `modify_` にしなかった理由

`omp` 自身がこのファイルを書き換える。`modify_` でファイルを所有すると、
UI や `omp config set` で変えた分と綱引きになる。

代わりに `run_onchange_after_` から **`omp` の writer を呼ぶ**方式にした
（`~/.claude.json` を CLI 経由で触る `410_claude_mcp` と同じ考え方）。
追記のみで、既にあるものは触らない。

> **実装で踏んだ癖**: `omp config get --json` は配列ではなく
> `{"key":…, "value":[…]}` を返す。配列として読むと必ず解析に失敗し、
> 毎回「未登録」と判定して冪等性が壊れる（実際に一度踏んだ）。

### 真偽値を「一度だけ置く」ことにした理由

配列（`customDirectories` / `enabledProviders`）は**追記で冪等にできる**。
既にあれば足さない、が素直に書ける。

真偽値はそうはいかない。`omp config get` が返すのは**実効値**なので、
「まだ設定していない」と「既定値と同じ値を意図して明示した」が区別できない。
毎回入れ直す実装にすると、UI や `omp config set` で意図して戻した設定を
次の `chezmoi apply` が黙って覆す。

そこで `~/.omp/agent/.chezmoi-seeded` に**置いた鍵の名前を控え、2 回目以降は
触らない**。初期値だけこちらが用意し、以後はユーザのものにする。

`run_once_` を使わなかったのは、**omp 未導入の回を取りこぼすため**。
`run_once_` はスクリプト内容ごとに 1 回しか走らないので、その 1 回で
`omp` が無いと二度と種まきされない。`run_onchange_` + 控えなら、omp があった
回にだけ控えるので導入が後になっても拾える。

## 重要な更新

- **2026-09-24**: 起票。**安全性の軸で評価しない**ことを前提として明記した
- **2026-09-24**: `omp` が `~/.claude` を config root として読むと知り、
  「skills は設定不要」と判断した。**これは誤りで同日中に撤回**（下記）
- **2026-09-24**: 実機で `skills.enableClaudeUser = false`（既定）を確認。
  探索ルートに `.claude` が含まれることと、`~/.claude/skills` を読むことは
  別だった。**素のままでは自作 skills が 1 つも見えない**。
  `skills.customDirectories` へパスで明示する方式で対処した
- **2026-09-24**: `[CHG-0005](0005-agents-config-naming.md)` の A2（固有設定の
  native 分離）は、この案件の結論が出るまで**優先度を下げる**。
  第一サポートが変わるなら、整理の対象も変わるため
- **2026-09-24**: `omp config list` の全項目（9 節・約 400 件）を見た。
  **`skills.enableClaudeUser` は門の 1 枚目でしかなかった。** より上流に
  `enabledProviders` があり、既定 `[]` で `~/.claude` のユーザ領域が
  **丸ごと**閉じている。段 1.5 で skills が通ったのは
  `customDirectories` がプロバイダ機構を迂回していたためで、**MCP には
  効いていなかった**。`enabledProviders: [claude]` で 1 枚目を開けた
- **2026-09-24**: Pi の公式ドキュメント 39 ファイルに **MCP の記述が 1 件も無い**
  ことを確認。`common.toml` の `[[mcp]]` を Pi へ配る先は現時点で存在しない
  （静的な読みのみ。実機未確認）

## 未解決点

- **`enabledProviders: [claude]` の効果を実機で確認できていない。**
  `omp` が未認証（`No models available`）で、`/mcp list` はモデル呼び出しを
  伴うため到達しなかった。**段 2 の最初に `/mcp list` で `deepwiki` が
  出ることを確認する。** 出なければこの設定は無効
- `enabledProviders` を開くと omp が `~/.claude/settings.json` を**設定源**と
  しても読むかは**未確認**。公式ドキュメントは「他ツールが寄与するのは
  project レベルの設定」と読めるので user レベルの同ファイルは対象外の
  はずだが、裏は取れていない。読まれた場合 `permissions` / `hooks` /
  `sandbox` といった omp のスキーマに無い鍵をどう扱うかも不明
- `~/.claude/CLAUDE.md` がユーザ文脈として載るようになったはず。
  omp の文脈は `~/.omp/agent/AGENTS.md` が最優先で**ユーザ文脈は 1 つしか
  生き残らない**ため、どちらが採用されたか段 2 で確認する
- `omp` は設定ファイルを**自身も書き換える**（設定移行、MCP 設定の書き込み）。
  UI で変えたら chezmoi へ戻す運用を徹底しないと、次の `apply` で消える
- 便利な自動発見の代償として、**どの定義が採用されたかが見えにくい**。
  skills・MCP・規約それぞれに探索順位と重複処理がある。初回に確認しておく
- `PI_CONFIG_DIR` で基底を差し替えられるが、Pi と `omp` で**同じディレクトリを
  共有させない**こと。状態形式の互換性は保証されていない

## 終了結果

<!-- Done にするとき記入 -->
