# CHG-0002: OpenCode の permission を既定 ask にし、自動化率を機構で回復する

- **状態**: In progress
- **更新日**: 2026-09-22
- **基準**: OpenCode V2

## 目的と非目的

**目的**: AI CLI の permission 設計から「LLM classifier への委譲」を廃止し、
OpenCode の既定を `ask` にする。そのうえで**秘密へのアクセス経路を塞ぎ**、
確認回数を機構（hook / 構造化ツール）で抑えて実用的な自動化率を保つ。

**非目的**: Claude Code / Copilot CLI の設計変更。今回は OpenCode V2 のみを
対象にする。

## 運用モード（sandbox の有無）

OpenCode には sandbox が内蔵されていないが、**`opencode` のプロセスごと
bubblewrap で隔離すれば外から被せられる**
（[sandbox の調査](../research/opencode-sandbox.md)）。

したがって**2 つのモードを前提に設計する**。

| | A: sandbox 有効 | B: sandbox 無効 |
| --- | --- | --- |
| shell 経由の読み書き | **境界あり**（ファイルが存在しない） | 境界なし |
| `read` / `grep` ツール経由 | 境界あり | permission の deny |
| 想定 | `chezmoi` を使わないプロジェクト | **このリポジトリ** |

**このリポジトリは B で運用する。** `chezmoi` が snap 版で bwrap 内から
起動できないため（実測）。書き込み範囲の問題ではないので、
秘密だけ隠す形にしても解決しない。

### 設計上の帰結

**弱いほう（B）を基準に設計し、sandbox は上に重ねる層として扱う。**
エージェントがこのリポジトリで最も危険な操作（permission 設定自体の
書き換え）を行う以上、B で成立しない設計は採らない。

この前提から、段階 2 の内容が変わる。B では `cat` / `grep` が
`read` deny を迂回できてしまうので、**構造化ツールへの誘導が
「確認回数の削減」ではなく「保護される層へ寄せる」手段になる**
（[permission の穴](../research/opencode-permission-gaps.md)）。

### 設定で入れる保護は設定で外せる

`<project>/.opencode/opencode.json` の permission は**グローバルの deny に
勝つ**（実測）。同じことが `shell` にも起きる。

| 影響 | 内容 |
| --- | --- |
| 外部リポジトリ | `.opencode/opencode.json` を含むリポジトリを開くだけで保護が外れる |
| 自分のリポジトリ | そのファイルへの write deny が無いと、エージェントが自分で権限を広げられる |

後者は `**/.opencode/opencode.json` を write deny に足して塞ぐ（未対応）。
前者は塞げない。**敵対的なリポジトリを想定するなら、設定ではなく
起動方法（プロセスごとの隔離）に頼るしかない。**

## 現在地

### 発端

このリポジトリは `home/dot_config/agents/common.toml.tmpl` を単一ソースとして、
Claude Code / Copilot CLI / Codex CLI / Gemini CLI の permission・hook・
sandbox・MCP を生成している。判定ロジックは Python
（`home/dot_claude/hooks/lib/bashrules/` で約 4,913 行、pytest 1,782 件）。

直前の作業で 4 つ目の生成先として OpenCode V2（`~/.config/opencode/opencode.json`）
を追加した。その過程で以下が判明した。

1. 従来の設計には allow / ask / deny の 3 リストに加えて「未掲載」という
   4 つ目の選択肢があり、未掲載のコマンドは Claude の `auto` モード /
   Copilot の `assisted` モードの LLM classifier に委ねる意図的な設計だった
2. **OpenCode に classifier は無い**。`allow` は「プロンプトなしで継続」の
   意味でしかない。つまり「未掲載」戦略が OpenCode では「無条件許可」へ
   静かに退化していた
3. 実測では `curl` / `wget` / `docker run` / `gh api` / `python3` /
   `chmod` / `dd` / `base64` / `git add` / `echo` / `history` などが
   全て未掲載＝無条件実行だった

ユーザはこれを受けて「LLM 判定は不安定でトークンも嵩む」として classifier
前提を捨てる決定をした。

### 決定済みの方針

1. permission の既定を `ask` にする
2. 確認回数の回復は指示（AGENTS.md）ではなく機構（hook）で行う。これは
   このリポジトリの ADR-0006「エージェントへの指示を減らし、強制は機構へ
   寄せる」の適用である
3. ハーネスごとに設定を作り込む方向へ移行する。OpenCode を tier 1 とし、
   `common.toml` の `[bash]` は Claude / Copilot 用として当面そのまま残す

### 段階の優先順位を決めた実測

実セッションのシェル呼び出しを `&&` `;` パイプで分割し、OpenCode の
照合規則で再生した。**測定時点は 2026-09-21、1,005 セグメント。既定 ask で
の確認総数は 959 件**（現行 allow 14 件を適用）。

数字は 2 種類あり**一致しない**。「セグメント数」は断片の数、
「確認減少数」は移行して実際に消える確認の数で、一部が既に静的 allow で
無確認に通っているためずれる。

| 移行対象 | セグメント数 | 確認減少数 | 備考 |
| --- | ---: | ---: | --- |
| `cd X && ...` → `workdir` | 163 | 163 | 一致 |
| 区切り用途の `echo` | 105 | 105 | 一致 |
| `cat`/`sed -n`/`head`/`tail`/`ls` → `read` | 213 | 205 | `wc` が allow にある分ずれる |
| `grep`/`rg`/`find` → `grep`/`glob` | 70 | 39 | `grep -n` と `find` が allow にあるため |
| `uv run` などの検証系 → `verify` | 57 | 57 | 一致 |
| 上記以外 | 397 | 390 | その場限りのコマンド |

5 つの対策で 959 → 390 件まで減る計算になる。効果の順位は
読み取り移行（−205）が最大で、`cd` 廃止（−163）、`echo` 廃止（−105）、
`verify`（−57）、`grep` 移行（−39）と続く。**この順位は当初の想定
（ツール化が主役）を否定するもので、読み取り移行が最優先**という結論に
なった。段階 1〜4 の並びはこの順位に従っている。

残り 390 件は `python3 -c` / `export` / `sed 's` / `curl -fsSL` など、
その場限りのコマンドで列挙では潰せない（段階 4 の対象）。

測定手順と標本の偏りは
[permission 適用範囲の穴](../research/opencode-permission-gaps.md)を参照。
**件数は測定時点でしか意味を持たない。**

### 設計を決めている実測結果

詳細と実験手順は各調査記録にある。ここには判断を動かした結論だけ置く。

| 結論 | 設計への影響 | 出典 |
| --- | --- | --- |
| V2 対応のサードパーティ製プラグインは 1 件も無い | 既製品に乗れない。自作する | [生態系](../research/opencode-plugins.md) |
| 設定の `deny` は hook を呼ばない | 静的 deny は代替案を返せない。既定 ask のまま hook で deny へ変える | [plugin API](../research/opencode-plugin-api-probe.md) |
| プラグインのロード失敗は fail-open | 故障時に無防備になる。段階 1 の静的 allow 縮小を先に済ませる | 同上 |
| `tool.execute.before` が生コマンドと `id` と `workdir` を持つ | cwd 相関はこの hook 単独で完結する。`e.resources` は変数代入を落とすので使わない | [相関と承認要求](../research/opencode-plugin-correlation.md) |
| plugin から `ask` を**作る** API は無い | カスタムツールは「無確認で安全な設計にする」か「作らない」の二択 | 同上 |
| plugin は `ask` を `allow` へ**引き上げられる** | 段階 2 以降の「機構で確認を回復する」構想が成立する | [allow の費用対効果と plugin ゲート](../research/opencode-shell-allow-and-plugin-gate.md) |
| `grep` / `glob` が `read` の deny を迂回する | 読み取りをツールへ移す際、保護を同時に入れる必要がある | [permission の穴](../research/opencode-permission-gaps.md) |
| `execute.after` で結果を濾せる | 検索は通しつつ出力だけ伏字化できる。確認を増やさずに塞げる | 同上 |
| 静的パターンはクォートと変数で回避できる | deny パターンは allow を残す口実にならない。`shlex` 正規化つきの plugin が要る | [plugin ゲート](../research/opencode-shell-allow-and-plugin-gate.md) |
| `codemode` 既定なら固定費 0 bytes | ツール化によるコンテキスト逼迫を理由に避ける必要はない | [ツールのコンテキストコスト](../research/opencode-tool-context-cost.md) |

現行 allow 14 件のうち 6 件（`find` / `gcc` / `g++` / `cmake -S` /
`cmake --build` / `uv sync` / `mise run`）が任意コード実行を含み、
`common.toml` のコメント「読み取り専用・冪等なものだけ」と乖離している。
うち `find` 以外は実測ヒット 0 で、落としても確認は増えない。

### まだ分からないこと

- Claude / Copilot も既定 ask にするか。Copilot は hook の `ask` が
  自動承認されるバグ（github/copilot-cli#3590）があるため効果が限定的。
  **OpenCode でも `--auto` 実行時は同じ構図が仕様として存在する**
  （[ask と並列バッチ](../research/opencode-ask-and-parallel-batch.md)）

## 評価基準

**必須:**

1. 段階 1 の完了時点で、Claude / Copilot / Codex / Gemini の生成物に diff
   が出ないこと（テストで固定）
2. **モード B（sandbox 無効）で**、保護対象のファイルを `cat` / `grep` /
   `head` で読んだ内容がモデルへ渡らないこと。素直な形で実測して判定する
3. 任意コード実行を含むコマンドが OpenCode の allow に 1 件も無いこと
4. プラグインがロードに失敗しても、危険側（無条件許可）に倒れないこと
5. **モード A（sandbox 有効）で**、難読化した形（`base64` / 変数展開 /
   `python3 -c`）でも保護対象へ到達できないこと

基準 2 と 5 で**要求水準を分けている**。モード B では文字列・出力の検査
しか手段が無く、符号化されるとすり抜けるため「境界」を要求できない
（[出力フィルタ](../research/opencode-output-filter-and-subagents.md)）。
モード A は OS の名前空間で効くので難読化に耐える（実測）。

基準 2 は 2 度書き換えている。当初の「確認減少数が総数の 6 割以上」は
**測定単位の誤り**で達成不能だった（下記「重要な更新」）。次に置いた
「難読化した形でも遮断」も**モード B では達成不能**と実測で判明したため、
モード A の基準 5 へ移した。

**モード B の伏字化は事故と素朴なプロンプトインジェクションへの安全網で
あって、意図的な持ち出しへの境界ではない。** この限界を認めた上で置く。

## 候補比較

段階 5（残り約 280 件への手当）の候補。段階 1〜4 の実績を見てから
判断する。「耐えられる頻度」なら何もしない選択もある。

sandbox は候補から**段階 3 へ昇格**した（[調査](../research/opencode-sandbox.md)で
成立を実測したため）。

| 候補 | 支持する根拠 | 不利な点・反証 | 未検証点 | 扱い | 次の確認 |
| --- | --- | --- | --- | --- | --- |
| saved approval の蓄積 | 対話で「常に許可」した内容が project 単位で永続化される | 学習された安全性ではなく人間が恒久的に権限を与えた状態になる | — | **未評価** | 段階 1〜4 の結果を見てから |
| session スコープの事前宣言（`ctx.permission.rules()`） | セッション内で完結し永続化しない | **2.0.10 に `ctx.permission.rules` が存在しない**（公式ドキュメントには記載あり） | API の追加待ち | **保留** | 実装されたら再評価 |
| `check_bash.py` への bridge | 既存の判定資産（4,913 行・1,782 テスト）を再利用できる | 承認エンジンにはせず、既知の危険の拒否・誘導のみに使う方針 | 統合方法 | **未評価** | 同上 |

## 次の調査・実験

| # | 減らしたい不確実性 | 方法 |
| --- | --- | --- |
| P3-1 | `read` ツールが `read` deny を実際に守るか（誘導先が本当に保護されているか） | 保護対象を `read` ツールで開かせ、deny されることを実測する |
| P3-2 | `grep` / `glob` ツールの保護を hook でどう自作するか | `execute.before` で `path` を検査する案と、`execute.after` で結果を濾す案を比較する |
| P3-3 | `shell` 差し替えが `terminal` 機能と MCP・子エージェントへ波及するか | ラッパーのログで呼び出し元を数える |
| P3-4 | macOS の `sandbox-exec` で同等のことができるか | **macOS 実機が要る**（Windows 実機検証と同じ扱い） |

**P3-1 が段階 2 の前提。** ここが崩れると「保護される層へ寄せる」という
誘導の根拠が消え、伏字化だけが残る。

決着済み（[出力フィルタと子エージェント](../research/opencode-output-filter-and-subagents.md)）:

| # | 結果 |
| --- | --- |
| P2-1 | **成立。** `execute.after` で shell の出力を書き換えられる。本体は `result.content[].text`（`result.output` は文字列ではない）。コマンドを難読化しても効く |
| P2-2 | **どちらも境界にならない。** 内容照合は `base64` / `tr` で、コマンド検査はクォート・変数ですり抜ける。伏字化は安全網として採用し、境界としては宣伝しない |
| P2-3 | **設定不要。** `continue_loop_on_deny: false` を明示しても `--auto` + plugin の deny ではループが続き、代替案どおり別コマンドを実行した |
| P2-4 | **子エージェントも共通の permission に従う。** 親の部分集合ではない。hook は子の呼び出しにも発火し `agent` に名前が入る。子エージェントの起動自体も `action:"subagent"` / `resource:"<名前>"` で deny できる。`primary_tools` は効果を確認できず、頼らない |

決着済み: P0-1 / P0-2（[plugin の相関と承認要求の可否](../research/opencode-plugin-correlation.md)）、
P1-3（[shell allow の費用対効果と plugin ゲート](../research/opencode-shell-allow-and-plugin-gate.md)）、
P1-4（[ask と並列バッチ](../research/opencode-ask-and-parallel-batch.md)）。

| # | 結果 |
| --- | --- |
| P0-1 | **解決。** `shell.create.before` は不要。`tool.execute.before` の `input.workdir` が cwd を持ち `id` 付きなので相関に迷いがない。`workdir` 省略時はセッションのディレクトリで確定する |
| P0-2 | **不可能。** plugin から承認要求を作る API が存在しない。`ctx.permission` は `hook` / `list` / `get` / `reply` のみで、新規作成の口が無い。ただし**既にある要求へ答えることはできる**（`reply` のスキーマを確定） |
| P1-3 | **決着。** allow は読み取り専用 7 件。任意コード実行を含む 6 件のうち 5 件は実測ヒット 0 で、落としても確認は 1 件も増えない。あわせて **plugin が `ask` を `allow` へ引き上げられること**を実測した（段階 2 の前提） |
| P1-4 | **前提が誤っていた。** `ask` は並列バッチを壊さない（承認待ち 4 秒でも兄弟 3 件が全て成功）。壊すのは**拒否**で、これは期待動作。代わりに「`ask` の実効はモードで変わる」という別の制約が判明した |

## 仕様への変更案

| 変更対象 | 変更前 → 変更後 | 理由・証拠 | 適用結果 |
| --- | --- | --- | --- |
| `common.toml.tmpl` | `[bash] allow` を共用 → `[opencode.shell] allow` を新設 | `[bash]` は 3 CLI 共通のため、ここを削ると効果の切り分けができない | 未着手 |
| `generate.py` | OpenCode の shell allow を `[bash]` から取得 → `[opencode.shell]` から取得 + 先頭に `{action:"shell", resource:"*", effect:"ask"}` を追加 | 既定を ask にする本体変更 | 未着手 |
| `test_generate_opencode.py` | （なし）→ 任意コード実行を含むコマンドが allow に無いことと、他 CLI の生成物に diff が出ないことを固定するテスト | 段階 1 の受入条件を機械的に担保する | 未着手 |
| `.opencode/plugins/` | （なし）→ 誘導 hook（deny + 代替案メッセージ） | 静的 deny は hook を呼ばず代替案を返せないため、既定 ask のままプラグインが deny へ変える構成にする | 未着手 |
| `claude_write_deny_globs` | （なし）→ `**/.opencode/opencode.json` / `.jsonc` を追加 | **プロジェクト設定はグローバルの deny に勝つ**（実測）。書けるとエージェントが自分で権限を広げられる | **未着手（要対応）** |
| AGENTS.md の検証コマンド表 | 5 コマンドの手打ち → `verify(target: "all" \| "agents" \| "templates" \| "docs" \| "shell")` ツール 1 個 | enum 引数 1 個に畳むとコンテキストコストが 3 倍違う | 未着手 |

## 実装・検証

### 実施計画

| 段階 | 内容 | 状態 |
| --- | --- | --- |
| 0 | `grep`/`glob` の穴と plugin API の実測、計測基盤の確立 | 完了 |
| 1 | `[opencode.shell]` 新設 + 既定 ask | **完了**（2026-09-21） |
| 2 | プラグイン基盤 + 読み取り経路の保護（モード B の本体） | **着手中**（基盤と `cd` 規則が完了） |
| 3 | sandbox（モード A。Linux 限定・このリポジトリは無効） | 未着手 |
| 4 | `verify` ツール | 未着手 |
| 5 | 残り約 280 件への手当 | 判断保留 |

段階 2 と 3 は**独立して価値がある**。2 はモード B（このリポジトリ）の
保護、3 は他プロジェクトでの境界。2 が先なのは、このリポジトリが
主な作業場所だから。

### 段階 1 の詳細

`common.toml.tmpl` に `[opencode.shell] allow` を新設する。`[bash]` には
触らない。理由は、`[bash] allow` が 3 CLI 共通のため、ここを削ると
Claude / Copilot にも影響して効果の切り分けができなくなるため。これは
以前合意した「ハーネスごとに作り込む」方針の最初の適用でもある。

変更対象は次の 3 つ。

- `home/dot_config/agents/common.toml.tmpl` に `[opencode.shell] allow`
  を新設
- `scripts/agents/generate.py` の `build_opencode_permissions()` で
  allow の取得元を切り替え、先頭に
  `{action:"shell", resource:"*", effect:"ask"}` を置く
- `test/agents/test_generate_opencode.py` に「任意コード実行を含む
  コマンドが allow に無いこと」「Claude / Copilot の生成物に diff が
  出ないこと」を固定するテストを追加

allow の選定基準は、副作用なし・冪等・任意コード実行を含まないこと。
実履歴での実測（[費用対効果の調査](../research/opencode-shell-allow-and-plugin-gate.md)）
と、その後の監査（[allow リスト監査](../research/opencode-allow-list-audit.md)）
にもとづき、次の 5 件に確定した。

```toml
[opencode.shell]
allow = [
  "git log", "wc", "grep -n",
  "uv pip list", "docker ps",
]
```

当初は `git diff` / `git status` も載せていたが、監査で**どちらも任意コード
実行の経路を持つ**と判明したため外した。`git diff` は `.git/config` の
`diff.<name>.command`（外部 diff）、`git status` は `core.fsmonitor` で
任意コマンドを起動する（いずれも実測）。あわせて `.git/config` /
`.git/hooks/**` / `~/.gitconfig` を write deny に追加した。

**allow に載せたコマンドは全て任意ファイル書き込みの手段にもなる。**
scanner はリダイレクトを分割せず resource に残すため、
`wc -l f.txt > path` が `wc *` に前方一致して無確認で通る（実測）。
この性質があるので、allow は最小に保つ以外の守り方が無い。

落とすのは `find` / `gcc` / `g++` / `cmake -S` / `cmake --build` /
`uv sync` / `mise run` と、上記 2 件。ビルド系 6 件は実測ヒット 0 なので
確認は増えない。`find` が +7 件、`git diff` / `git status` が +42 件
（合わせて約 2%）増えるが、段階 2 の選別器で回収する。

`find` に対して「`-exec` の付いた形だけを静的 deny する」案は採らない。
`find . -exe""c …` のようにクォートを挟むと deny を素通りし、
`find *` の allow に一致して**無確認で任意コード実行**になるため。
deny パターンは allow を残す口実にしかならない。

`uv pip list` と `docker ps` はヒット 0 だが、読み取り専用でリスクが無く、
他プロジェクトでの利用が見込めるため残す。

撤退方法は `[opencode.shell]` を削除するだけ。`[bash]` に触らないので
他 CLI へ影響しない。

#### 実施結果（2026-09-21）

| 検証 | 結果 |
| --- | --- |
| `test/agents/` | 1,793 passed, 7 skipped（変更前 1,782 から +11） |
| pre-commit 全 12 フック | 全て Passed |
| 他 CLI への波及 | 7 ターゲット中 6 つがバイト単位で同一 |
| 実機挙動 | allow は無確認、未掲載は `ask` |

他 CLI の無差分は目視ではなく、`HEAD` の worktree を立てて全ターゲットの
生成物を突き合わせて確認した。`opencode-config` だけが変わり、内訳も
意図どおりだった。

```text
- cmake --build *  - cmake -S *  - find *  - g++ *
- gcc *  - mise run *  - uv sync *
+ {"action":"shell","resource":"*","effect":"ask"}
read / edit は 50 / 52 件で変化なし（224 → 218 rules）
```

実機では `git status --short` が無確認で実行され、`echo HELLO` が `ask` に
落ちた。**変更前の `echo` は無条件許可だった**ので、狙った変化が出ている。

```json
{"res":["git status --short"],"effect":"allow"}
{"res":["echo HELLO"],"effect":"ask"}
```

この実機試験の過程で、それまでの調査記録が使っていた隔離手段
（`XDG_CONFIG_HOME` の差し替え）が**誤りだった**ことが判明した。
正しくは `OPENCODE_CONFIG_DIR`。過去の記録の結論は
いずれも有効（[試験環境の隔離方法](../research/opencode-test-isolation.md)）。

残作業は無し。2026-09-21 に `chezmoi apply` で実環境へ配備済み
（`~/.config/opencode/opencode.json` に 218 rules、先頭が
`{shell, *, ask}`、allow は 7 件）。

**ただし Orca 経由のセッションでは効かない。** Orca が
`OPENCODE_CONFIG_DIR` を overlay へ向けており、OpenCode v2 はこれを
global config の**置き換え**として扱う（upstream の既知の不具合
[#32825](https://github.com/anomalyco/opencode/issues/32825)、Open）。
overlay に `opencode.json` が無いため permission 層ごと消える。

対処として `shellenv.sh` に条件付きで `OPENCODE_CONFIG` を入れた
（2026-09-21）。`OPENCODE_CONFIG_DIR` があるときだけ働く。
`chezmoi apply` と Orca の再起動後、実環境で **218 rules が読まれ
`pip --version` が deny される**ことを確認済み
（[試験環境の隔離方法](../research/opencode-test-isolation.md)）。

なお `ask` は自動承認されて素通りし、`deny` だけが貫通を許さない。
段階 2 で「自動実行で止めたいものは `deny` に倒す」とした方針が、
配備後の実環境でも裏付けられた。

### 段階 2 の詳細

**モード B（sandbox 無効）でも秘密へ届かせないための層。** このリポジトリは
モード B で運用するので、ここが実質の防御になる。

`--auto` では `ask` が自動承認されるため、効くのは `deny` だけ。
確認回数は目的ではない（当初はそう設計していたが誤りだった。後述）。

プラグインの hook で判定する。静的 deny にしてはいけない（deny は hook を
呼ばないため代替案を返せない）。既定 ask のままにして hook が deny へ
変える構成にすると、プラグイン故障時は ask に縮退して安全側に倒れる。

#### 方針: 保護される層へ寄せ、残りに安全網を敷く

段階 1 の監査で見つかった穴は、どれも permission の `read` / `edit` を
**shell 経由で迂回**することに起因する
（[allow リスト監査](../research/opencode-allow-list-audit.md)、
[permission の穴](../research/opencode-permission-gaps.md)）。

| 経路 | `read` / `edit` の deny |
| --- | --- |
| shell の `cat` / `grep` / リダイレクト | **効かない** |
| `read` ツール | **効く**（deny glob 50 件） |
| `grep` / `glob` ツール | **効かない**（別の穴。hook で自作が要る） |

ここから 2 段構えにする。

1. **誘導**: shell の `cat` / `head` / `tail` を `deny` し、`read` ツールへ
   寄せる。**deny が効かない経路から、効く経路へ移す**のが目的
2. **伏字化**: それでも shell を通るものに `execute.after` で出力フィルタを
   かける。取りこぼしへの安全網

誘導は「確認回数を減らす施策」ではなく**保護の一部**。これが
[段階 2 を振り直した](#重要な更新)あとの中心的な変更点。

#### 塞ぐ対象

| 穴 | 例 | 手段 | 効き目 |
| --- | --- | --- | --- |
| 秘密ファイルの読み出し | `cat ~/.ssh/id_ed25519` | 誘導 → `read` ツール | **deny が効く** |
| 同上（誘導を抜けたもの） | `sed -n 1p ~/.aws/credentials` | `execute.after` で伏字化 | 安全網 |
| 検索での読み出し | `grep -r . ~/.aws` | `grep` ツールへ誘導 + hook で保護 | **保護は自作** |
| 保護パスへの書き込み | `echo x > ~/.config/opencode/opencode.json` | 文字列検査で `deny` | 限界あり |

伏字化は**成立する**（[実測](../research/opencode-output-filter-and-subagents.md)）。
本体は `result.content` の `[{type:"text", text}]` で、ここを書き換えると
モデルには伏字だけが届く。コマンドをクォートや変数で難読化しても、
出力に対して働くので効く。

ただし**境界ではない**。出力を `base64` や `tr` で変換されるとすり抜ける
（実測）。実行前のコマンド検査はクォートと変数ですり抜ける。
**どちらも一方向にしか効かず、組み合わせても迂回の費用を上げるだけ。**
境界が要るならモード A（段階 3）。

書き込み側は**完全には塞げない**。`printf` / `tee` / `python3 -c` と
経路が無数にある。文字列検査は境界にならない
（[静的パターンの回避](../research/opencode-shell-allow-and-plugin-gate.md)）。
費用対効果を見て、明らかな形だけ deny する。

#### 誘導の対象と、確認回数への副次効果

確認回数は目的ではないが、**過剰ブロックの判断材料**として測ってある
（466 呼び出しの実履歴）。

| 誘導対象 | 代替案 | 保護上の意味 | 確認の削減 |
| --- | --- | --- | ---: |
| `cat` / `head` / `tail` / `sed -n` | `read` ツール | **deny が効く経路へ移る** | 13 (2.8%) |
| `grep` / `rg` / `find` | `grep` / `glob` ツール | 保護は hook で自作 | 11 (2.4%) |
| `cd X && ...` | `shell` の `workdir` | 無し（作法） | 15 (3.2%) |
| 区切り用途の `echo "==="` | 不要 | 無し | **0 (0%)** |

**区切り `echo` は採用しない。** 保護上の意味が無く、確認も 1 件も
減らないうえ、deny は 1 往復を捨てさせる。出力が煩いのは作法の問題で
`AGENTS.md` の記述で足りる。

`cd` は保護上の意味が無いが採用済み（`workdir` のほうが素直で、
実機で即座に乗り換えた）。**保護目的ではないと明記しておく。**

`ls` は誘導しない。ディレクトリ一覧は `read` deny の対象ではなく、
移しても保護が増えないため。

判定は前方一致で足りるので `check_bash.py` の意味解析は要らない。
パターンと代替案メッセージの表を `[opencode.shell]` に書いて生成するのが、
単一ソースを保ちつつ最小の実装になる。

#### 過剰ブロックへの歯止め

誘導は `deny` なので、外すと作業が止まる。次を守る。

- `read` ツールで代替できない用途（`head -c` でのバイト取得、パイプの
  途中、`cat` でのファイル結合）は**誘導しない**。前方一致では区別が
  つかないので、リダイレクト・パイプを含む形は対象外にする
- 誘導は必ず**代替案を本文に書く**。実機で `cd` → `workdir` の乗り換えが
  1 ターンで起きることを確認済み
- 規則を足すたびに、実履歴 466 呼び出しへ当てて誤爆を数える

#### 配置と生成

plugin は `~/.config/opencode/guide-plugin/` に置き、生成した
`opencode.json` の `plugins` へ**絶対パス**で登録する。判定表は
`common.toml` の `[[opencode.shell.guide]]` から `rules.json` として生成し、
`index.js` はそれを読むだけにする（単一ソースを保つ）。

この形にしか選択肢が無い（[plugin のロード経路](../research/opencode-plugin-loading.md)）。

- 明示指定は**絶対パスのディレクトリ**でないと解決されない。単一ファイルも
  `~` も**黙って無視される**
- 自動探索は `OPENCODE_CONFIG_DIR` 基準なので、Orca セッションでは
  `~/.config/opencode/plugins/` が読まれない。overlay には Orca の
  `service.json` があるため、環境変数の上書きで対抗はできない
- ディレクトリ名に `plugin` / `plugins` を使わない（自動探索と明示指定で
  二重ロードになる）

#### plugin 全体に効く 2 つの規約

段階 1 の監査と bypass の実装で判明した制約を、選別器・誘導 hook の
両方に効く規約として先に置く。

**規約 1: すでに `allow` と判定されたものには触らない。**

```js
if (e.effect === "allow") return
```

`allow` でも `permission.evaluate` は発火するため、これを書かないと
[bypass エージェント](../research/opencode-bypass-agent.md)が誘導 hook に
引っかかって機能しない。bypass は全 action が `allow` になるので、
この 1 行がそのままエージェント識別の代わりになる（実測）。
誘導対象は allow の 5 件と重ならないので取りこぼしは無い。

**規約 2: リダイレクトを含むコマンドは `allow` へ引き上げない。**

```js
if (/[<>]/.test(cmd)) return   // ask のまま
```

scanner はリダイレクトを分割せず resource に残すため、引き上げると
`find . -name x > path` のような任意書き込みが無確認で通る
（[allow リスト監査](../research/opencode-allow-list-audit.md)）。
plugin は生コマンドを読むのでリダイレクトを検出できる。
`deny` 側（誘導）には当てない。止める方向に倒すのは常に安全。

#### `find` の選別器

段階 1 で `find` を allow から外した分を、ここで回収する。丸ごと deny には
**しない**。逃げ場が `python3 -c "os.walk(…)"` や `ls -R` になり、かえって
悪化するため。実測した 7 件は全てファイル列挙で、うち 3 件は深さ制限つきの
ワークスペース外の列挙（`find / -maxdepth 6 …`）なので `glob` では素直に
書けない。

3 分岐にする。

| 条件 | 判定 |
| --- | --- |
| 危険フラグ（`-exec` / `-execdir` / `-ok` / `-okdir` / `-delete` / `-fprint*`） | `deny` + `glob` への誘導メッセージ |
| `$` / バッククォートを含む（間接参照で静的に解決できない） | 触らない（`ask` へ落とす） |
| リダイレクトを含む（規約 2） | 触らない（`ask` へ落とす） |
| それ以外の列挙形 | `allow` |

**3 分岐目は対話利用でしか安全弁にならない。** `ask` の実効は実行モードで
変わるため（[ask と並列バッチ](../research/opencode-ask-and-parallel-batch.md)）。

| 実行 | 3 分岐目の実効 |
| --- | --- |
| 対話 | 意図どおり。ユーザに判断が出る |
| `opencode run --auto` | **自動承認される。**安全弁にならない |
| `opencode run`（`--auto` なし） | 自動拒否され、並列バッチごと落ちる |

`--auto` は「明示的に deny されていない permission を自動承認」する。
つまり自動実行では plugin の `deny` だけが効く。**自動実行で確実に
止めたいものは `ask` ではなく `deny` に倒す。**この案件は「できるだけ
全自動で走らせたい」が前提なので、3 分岐目に安全性を期待しない。

実装上の制約が 2 つある。

- **`e.resources` ではなく `tool.execute.before` の生コマンドを読む。**
  scanner が `;` で分割する際に変数代入を落とすため
  （`Z=--zap; echo hi $Z x` → `echo hi $Z x`）。`id` で相関する
- **`shlex` 相当の正規化を通す。** クォート除去をしないと
  `-exe""c` が素通りする。既存の `bashrules` へ橋渡しするのが筋だが、
  `check_find_dangerous` は `-exec rm` 系と `-delete` しか見ていないので、
  `-exec sh -c` と `-fprint*` の追加が要る

`ask` → `allow` の引き上げが効くことは実測済み
（[plugin ゲートの調査](../research/opencode-shell-allow-and-plugin-gate.md)）。
deny のメッセージが逐語で届き、エージェントが `glob` へ乗り換えて
タスクを完遂することも確認した。

### 段階 3 の詳細（sandbox / モード A）

bubblewrap で隔離する。段階 2 が「安全網」なのに対し、これは**境界**。
permission と出力フィルタを破った手口（`base64` / 変数展開 /
`python3 -c`）がいずれも止まることを実測済み
（[sandbox の調査](../research/opencode-sandbox.md)）。

#### 方式: `shell` 差し替えではなくプロセスごと隔離

当初は設定の `shell` をラッパーへ向ける案だったが、**設定で入れる保護は
設定で外せる**。`<project>/.opencode/opencode.json` に `"shell": "/bin/bash"`
と書けばラッパーは呼ばれない（実測）。permission も同じく上書きできる。

そこで `opencode` **自体**を bwrap の中で起動する。

| | `shell` 差し替え | プロセスごと隔離 |
| --- | --- | --- |
| 覆う範囲 | shell ツールのみ | **全ツール + MCP + plugin** |
| プロジェクト設定で外せるか | **外せる** | 外せない |
| 切り替え | 設定・環境変数 | **起動方法** |

後者は permission の穴（`grep` / `glob` が `read` deny を迂回する）と
MCP が sandbox の外という問題も同時に解決する。

覆うパスは `[sandbox] deny` を流用する。Claude / Copilot と同じ表から
生成でき、単一ソースが保てる。deny リスト型にする（allow リスト型は
`mise` / `uv` が見えなくなって成立しない。実測）。

#### 有効・無効

切り替えは**起動単位**になる。ラッパー経由で起動すれば有効、
直接起動すれば無効。

**このリポジトリは無効で運用する。** 理由は当初書いた「書き込み範囲」
ではなく、**`chezmoi` が snap 版で bwrap 内から起動できない**ため（実測）。
秘密だけ隠して書き込みを許す形にしても解決しない。

```console
$ bwrap … chezmoi status
snap-confine is packaged without necessary permissions and cannot continue
```

`mise` / `python3` / `git` / `uv` は動くので、`chezmoi` を使わない
プロジェクトなら有効にできる。

#### 制約

| OS | 扱い |
| --- | --- |
| Linux / WSL2 | `bwrap`。実測済み |
| macOS | `sandbox-exec` を自作。Apple が deprecated 扱い。**実機検証が要る** |
| Windows | 手段なし（Claude も非対応なので差は開かない） |

OS 差は「分岐」ではなく**ベンダーが持っていた責任を引き取る**話。
Claude / Copilot は Seatbelt / bubblewrap を内蔵しており、このリポジトリは
deny パスを宣言するだけで済んでいた。

sandbox 内でも**ワークスペースの破壊とネットワーク経由の持ち出しは
防げない**（書き込み可能にし、`--share-net` を付けるため）。
オーバーヘッドは 1 回 +24 ms。撤退は起動方法を戻すだけ。

### 段階 4 の詳細

`AGENTS.md` の検証コマンド表を
`verify(target: "all" | "agents" | "templates" | "docs" | "shell")` という
enum 引数 1 個のツールにする。ツールを 5 個作るのではなく 1 個に畳む
（コンテキストコストが 3 倍違うため）。`codemode` は既定（true）のまま
にして固定費を 0 にする。

ただし自動承認はしない。`verify(target:"all")` は `.pre-commit-config.yaml`
の local hook を起動するため、設定ファイルを書き換えれば任意コマンドが
動く。「エージェントは既にそのファイルを編集できるのだから権限は増えない」
という議論は成立しない（ファイルを書ける権限と、それをホストユーザー権限で
実行できる権限は別）。ゲートは `tool.execute.before` で自作する。

### 段階 5 の詳細

残り約 280 件はその場限りのコマンドで列挙では潰せない。

**第一候補は「何もしない」。** 段階 5 の目的は確認回数の削減だが、
**自動実行では `allow` と `ask` が等価**なので、効くのは対話時だけ。
この案件の前提は「できるだけ全自動で走らせたい」なので、優先度は低い。

sandbox（段階 3）を入れても**ここは楽にならない**。結果が有界になる
だけで、確認回数は変わらない。

他の手段の候補は上の「候補比較」を参照。

#### 既定を `allow` にしない理由

sandbox があれば shell の被害は有界になるので、既定を `allow` へ戻す案が
成り立つように見える。**採らない。**

| 理由 | 内容 |
| --- | --- |
| 得るものが無い | 自動実行では既に素通りしている。自動化率は上がらない |
| sandbox 内でも残る危険 | ワークスペースのファイル破壊、`--share-net` 経由の持ち出し |
| 故障時に危険側へ倒れる | macOS / Windows は未実装。Orca overlay のように設定が読まれない事故も実在する。評価基準 4 に反する |
| 元の状態への回帰 | 既定を変えても shell deny 85 件は残るので、実態は「その 85 件以外は無条件」＝この案件が最初に否定した状態 |

## 重要な更新

**2026-09-22 — sandbox が使えると分かり、2 モード前提へ組み直した。**

OpenCode に sandbox は内蔵されていないが、**`opencode` のプロセスごと
bubblewrap で隔離すれば被せられる**と実測で分かった
（[sandbox の調査](../research/opencode-sandbox.md)）。

これを受けて 5 点を変えた。

- **運用モードを明示した。** このリポジトリは sandbox を**無効**にする
  （`chezmoi` が snap 版で bwrap 内から動かないため）。したがって
  **弱いほうを基準に設計する**
- **誘導の位置づけを戻した。** 前回は「確認削減の効果が小さい」として
  格下げしたが、モード B では `cat` を `read` ツールへ寄せることが
  **deny の効かない経路から効く経路へ移す**保護そのものになる
- **評価基準をモード別にした。** モード B に「難読化にも耐える」ことは
  要求できない。難読化耐性はモード A の基準 5 へ移した
- **sandbox の方式を変えた。** 当初の `shell` 差し替えは
  **プロジェクト設定で外せる**（実測）。`opencode` のプロセスごと
  隔離する形にすると、設定では外せず、全ツールと MCP も覆える
- **既定を `allow` に戻さないと決めた。** sandbox があっても
  自動化率は上がらず、故障時に危険側へ倒れるため（段階 5 の詳細）

段階は 2（モード B の保護）と 3（モード A の境界）に分かれ、
**置き換えではなく併用**になる。

あわせて**プロジェクト設定がグローバルの deny に勝つ**ことが判明した。
`**/.opencode/opencode.json` への write deny が要る（未対応）。

**2026-09-21 — 確認回数の測定単位が誤っていた。段階 2 の目的を振り直す。**

**2026-09-21 — 確認回数の測定単位が誤っていた。段階 2 の目的を振り直す。**

計画は誘導対象を**セグメント単位**で数えていたが、permission は
**呼び出し 1 回につき 1 判定**（`echo A > b.txt; echo C` が 1 イベントで
`resources` 2 件になることを実測）。区切り `echo` のように他の作業と
同じ呼び出しに同居するものは、やめても確認が 1 件も減らない。

466 呼び出しの実履歴で測り直すと、誘導 hook 全体でも **8%**（39 件）。
評価基準の「6 割以上」は達成不能だった。

| 分類 | 旧（セグメント） | 新（呼び出し） |
| --- | ---: | ---: |
| `cd` | 163 | 15 |
| 区切り `echo` | 105 | **0** |
| 読み取り系 | 205 | 13 |
| 検索系 | 70 | 11 |

あわせて「自動実行では `allow` と `ask` が等価」という既に判明していた
性質を踏まえると、**確認削減は対話時にしか意味を持たない**。この案件の
前提は「できるだけ全自動で走らせたい」なので、段階 2 の目的を
**自動実行で効く deny（穴塞ぎ）**へ振り直した。評価基準 2 も差し替えた。

**2026-09-21 — allow の選定基準を既存リスト自身が満たしていなかった。**

段階 1 で「任意コード実行を含まない」を基準にビルド系と `find` を外したが、
その基準で残した `git diff` / `git status` が**どちらも任意コード実行の
経路を持っていた**（[allow リスト監査](../research/opencode-allow-list-audit.md)）。
基準の適用漏れで、Astra のレビューと実測で判明した。両方を allow から外し、
`.git/config` 等を write deny へ追加した。

あわせて 2 つの理解を訂正した。

- **`allow` を増やしても `deny` は弱まらない。** permission は多層防御では
  なく最終一致で決まる 1 つの判定で、deny は常に後ろにある。以前の
  「deny の前段が緩む」という記述は誤り
- **自動実行では `allow` と `ask` は等価。** したがって allow の増減は
  自動実行の権限境界を変えず、効果は対話時の確認回数だけ

さらに、**リダイレクトが resource に残る**ため allow 済みコマンドが
任意書き込みの手段になることが分かった（`wc -l f.txt > path` が
無確認で通る）。allow を最小に保つ以外の守り方が無い。

**2026-09-21 — 試験環境の隔離手段が誤っていた。**

段階 1 の実機試験で、生成した global config が読まれていないことに気付いた。
原因は **OpenCode が config dir の決定に `XDG_CONFIG_HOME` を使わない**こと。
正しくは `OPENCODE_CONFIG_DIR`
（[試験環境の隔離方法](../research/opencode-test-isolation.md)）。

過去の調査記録の**結論はいずれも有効**。global config に permission を
置いた実験が今日まで 1 件も無く、全てプロジェクト側の
`.opencode/opencode.json` を使っていたため。実環境への書き込みも発生して
いない。各記録の冒頭に訂正の注記を足した。

**2026-09-21 — 巻き添え中断の原因を取り違えていた（P1-4）。**

「並列バッチ内の 1 件が `ask` に落ちるとステップ全体が中断する」と記録して
いたが、原因は `ask` ではなく**拒否**だった。承認待ちを 4 秒作っても兄弟
3 件は全て成功する（[実測](../research/opencode-ask-and-parallel-batch.md)）。
拒否でステップが止まるのは期待動作なので、リスクではない。

代わりに別の制約が判明した。**`ask` の実効は実行モードで変わる。**
`--auto` では `ask` が自動承認されるため、段階 2 で「曖昧なら `ask`」と
する分岐は自動実行の安全弁にならない。止めたいものは `deny` に倒す。

**2026-09-21 — 段階 2 の実現性が確定した。**

plugin が `permission.evaluate` で `ask` を `allow` へ**引き上げられる**ことを
実測した（[調査](../research/opencode-shell-allow-and-plugin-gate.md)）。
本案件は「既定を ask にして、確認回数を機構で回復する」構想に全面的に
依存しているが、それまで deny 側しか実測していなかった。ここが通ったので
段階 2 以降は不確実性ではなく実装作業になった。

同時に、**並列バッチの巻き添え中断**という新しいリスクが見つかった。
「できるだけ全自動で走らせたい」という前提に直接効くため、既定 ask への
移行はこの性質とセットで評価する。

## 終了結果

（未終了）
