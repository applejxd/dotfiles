# CHG-0002: OpenCode の permission を既定 ask にし、自動化率を機構で回復する

- **状態**: In progress
- **更新日**: 2026-09-21
- **基準**: OpenCode V2

## 目的と非目的

**目的**: AI CLI の permission 設計から「LLM classifier への委譲」を廃止し、
OpenCode の既定を `ask` にする。そのうえで確認回数を機構（hook / 構造化ツール）
で減らし、実用的な自動化率を保つ。

**非目的**: Claude Code / Copilot CLI の設計変更。今回は OpenCode V2 のみを
対象にする。

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
2. 段階 2 の完了時点で、**自動実行のまま**、保護対象のファイルを
   `cat` / `grep` / `head` で読んだ出力がモデルへ渡らないこと（伏字化）。
   素直な形で実測して判定する
3. 任意コード実行を含むコマンドが OpenCode の allow に 1 件も無いこと
4. プラグインがロードに失敗しても、危険側（無条件許可）に倒れないこと

基準 2 は 2 度書き換えている。当初の「確認減少数が総数の 6 割以上」は
**測定単位の誤り**で達成不能だった（下記「重要な更新」）。次に置いた
「難読化した形でも遮断」も**達成不能**と実測で判明した。出力を符号化
されると内容照合をすり抜けるため
（[出力フィルタと子エージェント](../research/opencode-output-filter-and-subagents.md)）。

**伏字化は事故と素朴なプロンプトインジェクションへの安全網であって、
意図的な持ち出しへの境界ではない。** 境界には OS レベルの隔離が要る。
OpenCode V2 に sandbox は**内蔵されていない**が、設定の `shell` を
ラッパーへ向けると外から bubblewrap を被せられる
（[sandbox の調査](../research/opencode-sandbox.md)）。これは段階 2 の
範囲外とし、候補比較で扱う。

## 候補比較

段階 2 の範囲外にした手段と、段階 4（残り約 280 件への手当）の候補。
前者は**境界を作る**話、後者は**確認回数を減らす**話で目的が違う。
段階 1〜3 の実績を見てから判断する。「耐えられる頻度」なら何もしない
選択もある。

| 候補 | 支持する根拠 | 不利な点・反証 | 未検証点 | 扱い | 次の確認 |
| --- | --- | --- | --- | --- | --- |
| **`shell` 差し替えによる sandbox** | **唯一の境界。** permission 層と出力フィルタを破った手口（`base64` / 変数展開 / `python3 -c`）がいずれも止まる。ファイルが存在しなくなるため。オーバーヘッドは 1 回 +24 ms。プロジェクト単位・環境変数の 2 通りで無効化できる（いずれも実測） | ベンダーが持っていた責任を引き取る。macOS は `sandbox-exec` のプロファイル自作が要り、Apple が deprecated 扱い。shell ツールにしか効かず、`read` / `grep` / MCP は外側 | macOS 実機。`terminal` 機能への波及。子エージェントと MCP が `shell` を継承するか | **有力** | Linux 限定で入れるかを判断する |
| saved approval の蓄積 | 対話で「常に許可」した内容が project 単位で永続化される | 学習された安全性ではなく人間が恒久的に権限を与えた状態になる | — | **未評価** | 段階 1〜3 の結果を見てから |
| session スコープの事前宣言（`ctx.permission.rules()`） | セッション内で完結し永続化しない | **2.0.10 に `ctx.permission.rules` が存在しない**（公式ドキュメントには記載あり） | API の追加待ち | **保留** | 実装されたら再評価 |
| `check_bash.py` への bridge | 既存の判定資産（4,913 行・1,782 テスト）を再利用できる | 承認エンジンにはせず、既知の危険の拒否・誘導のみに使う方針 | 統合方法 | **未評価** | 同上 |

## 次の調査・実験

| # | 減らしたい不確実性 | 方法 |
| --- | --- | --- |
| （なし） | P2-1 〜 P2-4 は決着。段階 2 の実装待ち | — |

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
| AGENTS.md の検証コマンド表 | 5 コマンドの手打ち → `verify(target: "all" \| "agents" \| "templates" \| "docs" \| "shell")` ツール 1 個 | enum 引数 1 個に畳むとコンテキストコストが 3 倍違う | 未着手 |

## 実装・検証

### 実施計画

| 段階 | 内容 | 状態 |
| --- | --- | --- |
| 0 | `grep`/`glob` の穴と plugin API の実測、計測基盤の確立 | 完了 |
| 1 | `[opencode.shell]` 新設 + 既定 ask | **完了**（2026-09-21） |
| 2 | プラグイン基盤 + 誘導 hook | **着手中**（基盤と `cd` 規則が完了） |
| 3 | `verify` ツール | 未着手 |
| 4 | 残り約 280 件への手当 | 判断保留 |

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

目的は**自動実行で危険を止めること**であって、確認回数を減らすことでは
ない。`--auto` では `ask` が自動承認されるため、効くのは `deny` だけ。
確認回数が意味を持つのは対話時だけで、そこでの削減余地も小さい（後述）。

プラグインの hook で判定する。静的 deny にしてはいけない（deny は hook を
呼ばないため代替案を返せない）。既定 ask のままにして hook が deny へ
変える構成にすると、プラグイン故障時は ask に縮退して安全側に倒れる。

#### 塞ぐ対象

段階 1 の監査で見つかり、まだ塞がっていない穴。どちらも permission の
`read` / `edit` を **shell 経由で迂回**する
（[allow リスト監査](../research/opencode-allow-list-audit.md)、
[permission の穴](../research/opencode-permission-gaps.md)）。

| 穴 | 例 | 手段 |
| --- | --- | --- |
| 秘密ファイルの読み出し | `cat ~/.ssh/id_ed25519` / `grep -r . ~/.aws` | `execute.after` で**出力を伏字化** |
| 保護パスへの書き込み | `echo x > ~/.config/opencode/opencode.json` | 文字列検査で `deny`（限界あり） |

読み出し側の伏字化は**成立する**（[実測](../research/opencode-output-filter-and-subagents.md)）。
本体は `result.content` の `[{type:"text", text}]` で、ここを書き換えると
モデルには伏字だけが届く。コマンドをクォートや変数で難読化しても、
出力に対して働くので効く。

ただし**境界ではない**。出力を `base64` や `tr` で変換されると内容照合を
すり抜ける（実測）。実行前のコマンド検査はクォートと変数ですり抜ける。
**どちらも一方向にしか効かず、組み合わせても迂回の費用を上げるだけ。**
根本原因は permission 層が shell の内側を見ないことで、本当の境界には
sandbox が要る。内蔵は無いが、設定の `shell` をラッパーへ向ければ
外から被せられる（[sandbox の調査](../research/opencode-sandbox.md)）。
段階 2 では扱わず、候補比較へ送る。

したがって位置づけは**事故と素朴なプロンプトインジェクションへの
安全網**とする。確認回数を増やさないので自動実行と相性が良い。

書き込み側は**完全には塞げない**。`printf` / `tee` / `python3 -c` と
経路が無数にある。文字列検査は境界にならない
（[静的パターンの回避](../research/opencode-shell-allow-and-plugin-gate.md)）。
費用対効果を見て、明らかな形だけ deny する。

#### 誘導（優先度を下げる）

当初は確認削減の本命として設計したが、**測定単位を誤っていた**。
正しく呼び出し単位で測ると効果は小さい（466 呼び出しの実履歴）。

| 誘導対象 | 代替案 | 呼び出し丸ごと消える | allow へ反転 | 実質 |
| --- | --- | ---: | ---: | ---: |
| `cd X && ...` | `shell` の `workdir` | 0 | 15 | **15 (3.2%)** |
| `cat` / `head` / `tail` / `ls` / `sed -n` | `read` ツール | 13 | 0 | **13 (2.8%)** |
| `grep` / `rg` / `find` | `grep` / `glob` ツール | 10 | 1 | **11 (2.4%)** |
| 区切り用途の `echo "==="` | 不要 | 0 | 0 | **0 (0%)** |

区切り `echo` は**採用しない**。確認が 1 件も減らないうえ、deny は
1 往復を捨てさせるので差し引きマイナス。出力が煩いのは作法の問題で、
機構で強制する筋ではない（`AGENTS.md` の記述で足りる）。

`cd` は採用済み。`read` / `grep` / `glob` への誘導は、上の穴塞ぎと
同じ hook で扱えるため、そちらの設計が固まってから入れる。

判定は前方一致で足りるので `check_bash.py` の意味解析は要らない。
パターンと代替案メッセージの表を `[opencode.shell]` に書いて生成するのが、
単一ソースを保ちつつ最小の実装になる。

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

### 段階 3 の詳細

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

### 段階 4 の詳細

残り約 280 件はその場限りのコマンドで列挙では潰せない。手段の候補は
上の「候補比較」を参照。

## 重要な更新

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
