# コマンド判定器の公開実装の調査（我々のケースで役に立つ考え方）

<!-- 現在の運用の正本は docs/spec/guard/pi-decide.md（判定器）。ここは「いつ何を読み、何が分かったか」を積む場所 -->

## 記録 C1 — 2026-11-05

- **問い**: AI コーディングエージェントが実行する bash コマンドを、実行前に allow / ask / deny へ判定する層（コマンド判定器）の公開実装・資料に、
  **我々の判定器（pi のフルガード）で役に立つ考え方**はあるか。特に、独立 review で繰り返し指摘された 4 つの穴の型を減らせるか
- **穴の型**: ①コマンドごとの引数の知識（読み取り専用の一覧・書き込みオプションの一覧を手で持つ。`-oPATH`・`--output`・束ねた短いオプション）
  ②ラッパー（`env`・`timeout`・`xargs`・`bash -c`。ラッパー自身の値つきオプション）③パスの解釈（symlink の後ろの `..`・`cd`・`@` 接頭辞・Windows のドライブ表記）
  ④展開（変数・コマンド置換・glob・引用の除去）
- **方法**: 公開ソース・公式 docs・issue / PR / advisory を、子（worker）が `websearch.py fetch` と `gh` の読み取りで取り、
  原文を `.tmp/research/cmd-judge/sources/` に保存して読んだ（**git 管理外**。ノートは同 `*-note.md`）。**対象コードは実行していない**。
  読んだ範囲と読んでいない範囲は各ノートに分けて書いてある。**この記録は、ノートの要約を親が束ねたもの**で、
  各主張の行番号つきの根拠はノート側にある。要約サービス（DeepWiki 等）と解説記事は入口にだけ使い、根拠にしていない
- **ライセンス**: 読んだ範囲では、コードの取り込みは無い（考え方だけを借りる）。explainshell・bashlex は GPL-3.0 で取り込めない
- **前提の訂正**: 「パーサを前提にした公開の判定器は無い」は誤り。**パーサを使うものは複数ある**（下の表）。
  ただし、**エージェントに依存しない汎用の判定器ライブラリ**と、**展開の後の文字列を扱う判定**は、調べた範囲（検索は網羅ではない）では見つからなかった

## 結論（先頭）

1. **公開実装は「パーサで分解して、コマンドごとの許可表に当てる」が主流で、穴の型 1 は、どの実装も完全には閉じていない**。表は人手で、
   フラグまで見るのは「過去に突破が出たコマンド」だけ。試験は例の表（table test）が中心で、fuzz・実 bash との差分試験はほぼ無い（clai だけが 393 入力を実 bash で走らせる）
2. **Codex は、許可表そのものを廃止した**（PR #39630、2026-08-20 マージ）。今は、人が書く前置詞の規則・危険コマンドの拒否表・OS のサンドボックスの 3 本。
   廃止前の許可表には、我々と同型の穴があった（basename だけで通る `./cat`、`sort -o`・`find -fprintf`・`rg --pre`・awk の `system()`・`xargs ./prog.sh` の見落とし、束ねた `rg -iz`）。
   **公式の Claude Code も、Bash 規則は「境界ではない。境界はサンドボックス」と明言**している。我々の「判定器はうっかり防止、本命は境界」と整合する
3. **展開（型 4）の本命は「静的に 1 つの文字列に決まる語だけを通し、それ以外は fail-closed」で、我々の Plan と同じ結論に、独立に着いている実装がある**
   （claude-bash-approve、Codex の `bash.rs`）。逆に、**生の原文を照合する実装は、展開で突破される**（GuardFall。opencode の旧方式）
4. **誤拒否（誤 ask）を増やすと、利用者は bypass へ流れる**。pi 向けの bash-approve は、誤拒否に耐えきれず、未知のコマンドとパース失敗を「確認なしで実行」に倒した（PR #53）。
   Claude Code 自身も、厳格化が回帰して 2 回差し戻されている（2.1.232→2.1.233、2.1.268→2.1.273）。**厳格化は、誤 ask の件数を測りながら進める**必要がある
5. **我々の判定器に、公開の突破から見て足りないものが、少なくとも 2 つある**: 実行の入口になる環境変数の名指し（`PS4`・`PROMPT_COMMAND`・`BASH_ENV`・`ENV`・`LD_PRELOAD` など。
   `home/` 全体を検索して 0 件）と、Windows での保護（公式のサンドボックスも native Windows に無く、判定器が唯一の層になりうる）

## 調べた実装の比較

| 実装（版） | 解析 | 許可の根拠 | 未知のコマンド・フラグ | 展開の扱い | 試験 |
| --- | --- | --- | --- | --- | --- |
| **Codex CLI**（`rust-v0.166.0`、SHA `6ff1e1ca`） | tree-sitter-bash。`bash -lc` を分解するのは「単純なコマンドの列」だけ | 人が書く前置詞の規則（Starlark）＋危険コマンドの拒否表＋サンドボックス。**許可表は廃止** | 規則に当たらなければ確認（既定） | 変数・glob・リダイレクト・置換・制御構文があれば、**分解せず全文を 1 コマンドとして規則に当てる**。「解析は safe の証明に使うな」とソースに明記 | 規則に `match`/`not_match` の例を埋め込む（`execpolicy`） |
| **claude-bash-approve**（Claude 向け hook。SHA `49c80d83`、MIT） | mvdan/sh の構文木。語を実 bash の引数相当に**デコード**して照合 | パターン表（コマンド名＋検証子）。フラグまで見るのは過去に突破が出たコマンドだけ | **意見なし**（次の判定に委ねる）。pi 向けは意見なしを**実行**に倒す | 静的に決まる語だけ解く。`ParamExp`・算術・未知の置換はデコード不可→原文へ落として fail-closed。`echo`・`printf`・`realpath` などの置換は静的に評価する | Go の table test 約 20 ファイル。fuzz・実 bash 差分は見当たらない。判定をすべて SQLite に記録（テレメトリ） |
| claude-code-auto-approve（廃止。`1350075`）・claude-warden（`8f7f2a4`） | shfmt / bash-parser の構文木 | 利用者の `Bash(cmd *)` 前置詞／YAML の規則表 | fall through／パース失敗は ask | 解かない（変数は文字列化）。**構文木から Redirs を捨てて突破**（#4 など） | bats 97 件／vitest |
| **opencode**（v1.19.5 / dev `a3bcf750`） | v1.19.5: tree-sitter。**各ノードの生の原文**を許可パターンに照合。dev: 手書きの走査器（`shell/scan.ts`）へ替え、非 literal の語は `"$"` に置換、読めない入力・`PS4`・動的実行は全体を失敗にする | パターン＋引数の個数（arity） | 動的なら判定をやめる（v1.19.5） | v1.19.5 は解かない。GuardFall が突破した型 | — |
| **gemini-cli**（`v0.67.0`、`dc6602ce`） | tree-sitter で分解し、サブコマンドごとに再帰 | 読み取り専用の許可表は**手書きのコード**（`commandSafety.ts`）。TOML の規則にシェルの許可は無い | 解析失敗は ask（非対話は deny） | コマンド置換の中の禁止語は deny | 構造ごとの対（許可なし→ASK／許可あり→ALLOW）11 件＋置換 4 件。突破の入力そのものは無い |
| **Claude Code**（公式 docs・changelog・GHSA。コードは非公開） | （非公開） | 規則（`Bash(cmd *)`）。**境界ではないと明言** | — | — | 2.1.229〜2.1.318（約 3 か月）で、取りこぼしの修正が約 21 件、誤 ask と回帰が約 6 件 |
| **clai** PR #247 | tree-sitter-bash | 許可リスト | `PS4`・`PROMPT_COMMAND`・`BASH_ENV`・`ENV` を**名指しで Unparsed**。読めない入力は deny でなく ask | 393 入力を**実 bash で走らせ**、実際に走るコマンドが判定に見えることを CI で確かめる | `bash_runs.json` |

## 我々の穴の型ごとの示唆

- **型 1（引数の知識）**: 完全に閉じる方法は、見つからなかった。公開データ（Fig の補完スペック、MIT・2025-05 で更新停止・Amazon Q へ移管）は、「値を取るか・パスか・ラッパーの次がコマンドか」を持つが、
  **「書き込み先か」の印が無く**、`git log --output`・`find -fprint -delete` は宣言が無い（`git log --follow` は「値を取る」と誤って宣言）。`timeout`・`nice`・`nohup`・`stdbuf` のスペックは固定した版で 404。
  ＝手書きの表の置き換えには使えない。**向きを変える**（フラグの許可集合を明示し、集合外は ask。Codex・gemini・Claude Code の直し方の傾向）と、
  **表の限界を宣言する**（shguard の「表現できないコマンドは常に Ask」）のが、公開の実装に共通する対処
- **型 2（ラッパー）**: opencode・gemini は一般解を持たず、claude-bash-approve は正規表現の前置詞を繰り返し剥がす（値つきオプションは PR #34・#35 で後から直した）。
  **我々の `unwrapCommand`（`rules_guard.ts`）が先行**している。Fig のスキーマ（「フラグごとの値の有無＋最初の非フラグ引数が次のコマンドか」）の形だけ借りられる
- **型 3（パス）**: claude-bash-approve は、symlink を `Lstat` で確認し、`cd` は「repo と worktree の下だけ」を許す。TOCTOU は自己申告で未解決。
  **構文木を使っても、リダイレクトの書き込み先を落とすと穴になる**（auto-approve・warden）。Claude Code の advisory に、`.git` という名前の worktree・symlink・存在しないファイル（保護されておらず、sandbox の中から作られた）がある
- **型 4（展開）**: **許可に使う literal と、拒否の照合に使う復号を分ける**のが、公開実装の最も整った形（claude-bash-approve）。
  Codex は、literal でなければ分解を諦めて全文を規則に当てる。GuardFall の A（引用の除去による結合）・B・C は、Plan が設計上は閉じる。D（base64 を `sh` へパイプ）・E（`find -delete` など）は Plan の範囲外
- **失敗談の共通点**: 突破は「列挙の見落とし」（型 1）に集中する。直し方は、列挙を増やす→許可リストへ反転→解析できなければ ask の順。
  ただし `sed` と `find` は、許可リストへ替えた後も繰り返し突破された。**列挙は、完全にはならない**

## 採用・見送りの候補（決定はしない。優先度は私の見立て）

| # | 考え方（出典） | 効く型 | 費用・代償 | 見立て |
| --- | --- | --- | --- | --- |
| I1 | **実行の入口になる環境変数の名指し**（`PS4`・`PROMPT_COMMAND`・`BASH_ENV`・`ENV`・`LD_PRELOAD`・`BASH_FUNC_*`、`alias =`・`compgen -C/-F`・`set -k`）が出たら拒否側へ（clai #247、opencode dev） | 4 | 小さい（規則と試験）。名前を実行時に組み立てる形（`${x}S4`）は抜ける | **先に入れる**。tighten-only で追加できる |
| I2 | **回帰試験に公開の突破を足す**: GuardFall の A〜E（`r''m`・`$(echo rm)`・引用内 `$()`・`base64 -d \| sh` は golden に同形が無い）、Claude Code の型（`sort --compress-program`・`rg --pre`・`man --html`・`git` の略記・`xargs -t`・`$IFS`・`${x@P}`） | 1〜4 | 小さい | **先に入れる** |
| I3 | **許可に使う literal と、拒否に使う復号を分ける**（claude-bash-approve）。拒否の照合では、動的な語を悲観的に扱う。literal に足すのは、引用つきの `printf '%s'` と `$'…'`・`\x`・`\0NNN` の復号だけ（`echo`・`realpath`・`go env` の置換は、実行シェル・ファイル・外部コマンドに依存するので採らない） | 4・3 | Plan を判定に接続するときの設計の柱。中程度 | **Plan 接続の前に設計へ入れる** |
| I4 | **誤 ask の件数を指標にする**: shadow の `would_tighten` と golden で、厳格化のたびに誤 ask を数える（Claude Code の 2 回の差し戻し、bash-approve の pi 版の方針転換が根拠） | 全体 | 小さい（集計の追加） | **G1(b)（`analyze` の失敗を deny へ）の前提にする** |
| I5 | **実 bash との差分試験**（clai の `bash_runs.json`。bashlex #99 の heredoc 終端のような、パーサと bash の食い違いを拾う）。Plan の literal 定義を実挙動で裏づける | 4 | CI に bash が要る（Windows 不可）。中程度 | 検討。Linux だけで始められる |
| I6 | **規則に例を同居させる**（Codex の `match`/`not_match`）。我々の golden は規則と離れているので、穴ごとの回帰を規則の隣に置く運用 | 1・2 | 中程度（`tables.toml` の形の拡張） | 検討 |
| I7 | **許可表を増やす投資をやめ、サンドボックスの届く範囲を広げる**（Codex の廃止、Claude Code の明言）。我々の ADR-0022（containment-first）と整合 | 1・2 | 方針の確認が要る。bypass 運用ではサンドボックスが唯一の強制になる（Codex #39973） | 方針として確認する |
| I8 | **判定器の失敗は deny**（公式の hook は、起動失敗・タイムアウト・不正 JSON で素通りする）。**確認済み**: 我々の Claude 向け hook は、読み込み失敗と判定の例外で deny に倒す（`executable_decide.py`・`lib/decide.py`）。pi 側は review で「例外は deny」を確認済み。**未確認**: 子プロセスのタイムアウト | — | — | タイムアウトだけ点検 |
| I9 | **Windows**: 判定器が唯一の層になりうる。公式の hook も Windows で素通りした修正が 3 件。我々は Windows のドライブ表記（`/c/…`）を台帳の保護の候補に含めていない | 3 | 実機が要る | 実機での検証を、優先度を上げて起票 |
| I10 | **「意見なし」を第一級の結果にする**（claude-bash-approve）＝我々の tighten-only（旧を権威に残す）と同じ。テレメトリ（全判定の記録）＝我々の shadow。**方向は同じで、取り入れは不要** | — | — | 現状維持 |
| I11 | 公開データ（Fig など）から表を生成して同梱する | 1・2 | 鮮度・誤り・版差。上の通り「書き込み先」が無い | **見送り**。表に無いフラグの目録の差分を、試験側で見る使い方だけ（費用 小） |
| — | 見送り: Starlark・tree-sitter の導入、osh の実行、判定器が外部コマンドを実行する設計（bash-approve の `go env` 置換）、変数と `for` の追跡（古い値が残る恐れ）、外部パーサ（GPL の `bashlex`） | | | |

## 我々のコードで確かめた事実（親が確認。実行はしていない）

- `home/` 全体に `BASH_ENV`・`PS4`・`PROMPT_COMMAND`・`LD_PRELOAD`・`BASH_FUNC` の名指しは**無い**（`guarded_grep`）。`HOOK_ENV_RE`（`rules_guard.ts`）は `AGENTS_CONFIG_DIR`・`PYTHONPATH`・`CLAUDE_*HOOK*` だけ
- 同梱の `mvdan-sh` 0.10.1（JS）は **`syntax` パッケージだけ**で、`expand`・`interp` を含まない（`index.js` の `$packages` を検索）。展開の意味論（`expand.Literal` の fail-closed 設定）を借りる場合は、自前で書くことになる
- Claude 向け hook（`executable_decide.py`）は、判定器の読み込み失敗で deny、`lib/decide.py` の例外でも安全側（deny）に倒す

## 未確認・次に読むもの

- **Claude Code の bypass 下で、hook の deny が止めるか**は、どの公式資料にも明文が無い。実機の統合試験で確かめる（我々の運用は bypass が既定）
- GuardFall の probe（再現用の入力）の公開場所は見つからなかった。A〜E は報告本文の例から突き合わせた
- Codex の fuzz・shadow・差分試験の有無（全文検索はしていない）、サンドボックスの実装、Windows の判定。claude-bash-approve の `sed.go`・`tee.go`・`abspath.go`・`cd` の cwd の更新・変数の無効化。
  opencode dev の変更履歴（GuardFall への対応かは断定しない）。clai の差分。MMI・Dippy・dcg（余力の対象）。sandbox-runtime の Windows（alpha）の節
- 疑いのまま（コードを読んだだけ）: claude-bash-approve の `X=$(…)` で古い値が残る可能性、`for x in a /etc/passwd; do tee $x` で最初の項目だけを検査する可能性
- 数字は日付つきの取得値。changelog の件数は、版 2.1.229〜2.1.318 の範囲で、advisory・issue の日付からの推定

## 出典（取得日 2026-11-05。写しは `.tmp/research/cmd-judge/sources/`）

- Codex: `openai/codex` `rust-v0.166.0`（SHA `6ff1e1ca3b30fc8b914720681fcf5fe62e95f856`）の `execpolicy`・`shell-command/src/bash.rs`・`command_safety`・`core/src/exec_policy.rs`。廃止前の `is_safe_command.rs`（PR #39630 の親 `9ca99b51713066681cce211184c0ff9035496979`）。
  issue #37078・#28732・#54172・#39973・#8394、PR #39630・#20305・#9109。公式 docs `developers.openai.com/codex/rules`・`/codex/security`
- claude-bash-approve `49c80d838e2b9dc2ef09ae6ea2ff2bc84278d117`（MIT）の `hooks/bash-approve/main.go`・`packages/pi-bash-approve/`・`docs/pi-runtime-contract.md`、issue #18・#19・#34・#35・#53。claude-code-auto-approve `1350075`、claude-warden `8f7f2a4`
- opencode v1.19.5（`810c0eba1a73…`）と dev（`a3bcf75042522f035ef00d7390a2f806aaea9f11`）、gemini-cli `v0.67.0`（`dc6602cec4a6e823aa33937144245dc421e5165f`）、clai PR #247、PilotDeck PR #637・#654
- Adversa AI「GuardFall」（<https://adversa.ai/blog/opensource-ai-coding-agents-shell-injection-vulnerability/>、2026-06-30。二次: OrcaRouter の紹介記事）
- Claude Code の公式 docs（`code.claude.com/docs/en/{permissions,hooks,sandboxing,changelog}`）、GHSA（xq4m・q728・x56v・qgqw・7mv8・mhg7・66q4・4q92・ff64・7835・qxfv）、Flatt Security「Pwning Claude Code in 8 Different Ways」（報告者の記事）、
  `anthropic-experimental/sandbox-runtime` README
- Fig `withfig/autocomplete` `aef52acff84c45edde61ae610cc2c964802b9a38`、explainshell `827ebe38…`、bashlex `3f6b76c4…`、carapace-spec `f8719076…`、usage `e3c41674…`、`mvdan/sh` `expand` `5943e49d40d22467e60056a0f39ba58fb8fc767a`、Oils のドキュメント、ShellCheck wiki、tldr-pages

## 公開の突破の回帰試験の結果（2026-11-05）

試験 `test/agents/test_pi_public_bypasses.py`。公開の突破の入力 54 件（＋素の形の対照 2 件）を、bypass あり・役割 `implementer` で判定器へ渡して測った（実行はしない）。判定は変えていない。

- **型ごとの内訳（deny / known_gap）**: 引数の知識 22（3 / 19）・ラッパー 9（7 / 2）・パス 7（6 / 1）・展開 16（14 / 2）。合計 deny 30・known_gap 24。
- **known_gap（止まらない）**: 引数の知識 — `sort -o`・`sort --compress-program`・`find -fprint(f)`・`rg --pre`・`git log/diff --output`・`git` の略記オプション・`man --html`/`-H`・`sed` の `e` フラグ・`less -o`・`git -c core.pager/sshCommand`・`find -exec`・`tar --to-command`・`xargs ./prog.sh`（理由: 引数の意味を知らず、書き込み・実行のオプションを見ない）。ラッパー — `xargs -t touch echo`・`xargs rm`（理由: 本体を取り出して判定しない）。パス — `./cat`（理由: basename の扱い）。展開 — `rm${IFS}…`・`${x@P}`（理由: 展開を解かず語の形で見る）。
- **読み方**: `deny` は回帰したら失敗する。`known_gap` は `xfail(strict)` で、塞がれると XPASS で失敗する（表を `deny` へ直す合図）。
- **限界**: 破壊系は素の形が deny の対象（`rm -rf ~`）で測っており、deny の一部は「対象が危険」で止まった可能性がある（ラッパー・パス・展開の deny は、本体の解読による止まりとは断定できない）。
- **入力の出どころの限界**: 入力は、調査で読んだ公開資料の記述（型・コマンド名）から組んだもので、**原文の逐語ではない**。試験の出典の列は資料名の粒度（`codex-54172`・`claude-advisory`・`claude-flatt` など）で、入力ごとに原文の行まで突き合わせてはいない。突破の成立そのものを再現したものではなく、「この形を判定器がどう扱うか」の測定である。
- **傾向**: ①最大の穴は型 1（19/22）。コマンドごとの危険オプションを知らず、`/tmp` 以外への書き込みや任意実行が bypass で通る。②ラッパー・パス・展開は、危険な対象の語（`rm -rf ~`）が見える形ではほぼ止まる一方、対象が危険に見えない実行（`xargs`・`./cat`）は通る。③パイプで `sh` へ渡す形（base64・curl・printf）は全て止まる。④`${IFS}` 区切りと `${x@P}` は語の形が崩れるため通る。
