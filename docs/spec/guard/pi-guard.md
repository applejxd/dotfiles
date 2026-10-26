# pi のガード

pi（earendil-works/pi）の拡張として、ツールの実行を判定器（TypeScript の `judge/`。[`decide`](pi-decide.md)）に通す仕組み。
OpenCode のガード（permission の生成・guide plugin）の後継で、移行の計画と経緯は
[CHG-0020](../../change/0020-pi-migration.md)、設計の根拠になった試作の観測は
[pi のハーネスの試作（旧称。現在のフルガード）](../../research/agents/pi-harness-spike.md)（E1〜E4）。

> **位置づけ**: フルガードは `pis` で起動したときだけ効く。**Orca と Zed が呼ぶ素の `pi` は、フルガード無しで動く**
> （利用者の判断。保護が要る作業は `pis` で起動する。標準でサンドボックスの中）。`pis` は利用者が自分で起動するとき用で、
> 優先度は低い（[CHG-0020](../../change/0020-pi-migration.md)）。素の `pi` には**ガードを付けない**（簡易ガードは廃止。CHG-0023 の段 3f）。
> 付くのは `git push` の拒否と `git commit` の確認だけ（[commit の確認](#commit-の確認-素の-pi)）。

## 用語

このリポジトリでは、pi 本体を含む仕組み全体を「ハーネス」と呼ぶ（一般の用法と同じ）。
pi に足す判定の層、および起動の形を、次のように呼び分ける
（旧称は過去の案件・調査記録・ADR に残り、それらは書き換えない。[CHG-0023](../../change/0023-guard-terminology.md)）。

| 用語 | 指すもの | 旧称 |
| --- | --- | --- |
| ガード | ツール呼び出しを判定し、allow / ask / deny に振り分ける層 | ハーネス（拡張の意味のとき） |
| フルガード | `pis` で効く、役割・確認（ask）・伏字化まで含むガード（`~/.config/pi/harness`） | ハーネス |
| 簡易ガード（廃止） | 素の `pi` に付いていた、deny と伏字化だけのガード。段 3f で廃止した | 素の pi のガード |
| サンドボックス | Fence による OS レベルの隔離（`pis` の標準）。ガードとは別の層 | 境界 |

コードの識別子（`PI_HARNESS_*`・`~/.config/pi/harness`・`test_pi_harness*.py`・`--boundary`（互換の別名））は旧称のまま変えない。

## 起動

```bash
pis                 # 実装役で、サンドボックス (Fence) の中で起動する (標準。Ubuntu / WSL のみ)。bypass は既定でオン
pis --no-bypass     # bypass をオフにして起動する (確認 (ask) を出す)
pis --no-sandbox    # サンドボックス無しで起動する (守りはフルガードだけ。bypass は既定でオフ。起動時に警告、フッターに常時表示)
pis --bypass        # 確認 (ask) を確認なしで通す。deny と誘導は効く。**confirm (外部への送信・公開) は bypass でも確認する** (サンドボックス無しでもオンにできる)
pis --role reader   # 役割を選ぶ ([pi.profiles] の名前。省略すると [pi] default_role)
pis -c              # pi の引数はそのまま渡る (例: 直前のセッションを続ける)
```

- **サンドボックスが標準**。サンドボックスを張れない OS（macOS・Windows ネイティブ）では、`pis` は起動せず `--no-sandbox` を案内する（黙って弱い守りに落とさない）。
  `--boundary` は互換の別名（標準と同じ意味）
- サンドボックスの検査に落ちたとき・起動場所が危険なときも起動しない。制御ファイル・フルガードの編集、復旧、Orca・Zed は `--no-sandbox` で行う
- 設計の根拠は [CHG-0023](../../change/0023-guard-terminology.md#設計原則決定2026-10-14利用者)

`pis --no-sandbox`（`~/.local/bin/pis`）は次の形で pi を起動する（サンドボックスの内側も、同じフラグ `BASE_FLAGS` で起動する）。素の `pi` はフルガード無しで動く。

```bash
pi --no-approve -nbt -ne -e builtin:mcp -e ~/.config/pi/harness …
```

- `--no-approve`: 作業先の `.pi/`（MCP・設定・拡張・skills）を読まない（project trust を拒否する）。
  `AGENTS.md` は読む
- **作業先のスキルは `--skill` で足す**: 作業先から git ルートまでの `.agents/skills`（`pi.py` の `skill_args`。git ルートが無ければ足さない。
  `~/.agents/skills` は pi が元から読むので重ねない）。`--no-approve` のままなので、拡張・MCP・設定は信頼済みでも読まない。
  サブエージェントは親の `--skill` をそのまま引き継ぐ（判断は起動側の 1 か所）
  - **契約**: スキルを読むのは**指示を読む許可**で、実行の許可ではない。スクリプトの実行は判定器とサンドボックスが決める。
    `AGENTS.md` と同じ種類の入力として、作業先を使う時点でユーザーが信頼している前提で許容する（脅威モデルは「うっかり防止」。[ADR-0018](../../adr/0018-pis-sandbox-default-relax-only-when-proven.md)）。
    他人のリポジトリを調べるために開いたときも、そのスキルが読まれる点は許容している
  - 同名のスキルは**グローバルが勝つ**（`--skill` は後に載る）。作業先のスキルが `commit` などを乗っ取れない（[pi-upstream の表 B の 14](../pi-upstream.md#b-明示が無いここに書く)）
  - 起動後に足したスキルは `/reload` で読める（表 B の 15）
  - 素の `pi`（Orca・Zed・Windows）でこのリポジトリ（とその配下）を開くと、`.agents/skills` があるため **project trust の確認が出る**。
    `pis` は `--no-approve` なので出ない。TUI を tmux で有効にする試験は `--no-approve` を付ける（確認画面がキー入力を食う）
  - **スキルの一覧**: pi 自身は、フルガードの下で一覧をシステムプロンプトへ入れない（`read` / `bash` が宣言されないため）。フルガードが `before_agent_start` で同じ形の一覧を足す（`guarded_read` で読む旨。表 B の 16）。`/skill:<名前>` でも呼べる
- `-nbt`（`--no-builtin-tools`）: 組み込みのツールを使わない。ツールはフルガードが登録したものだけになる
- `-ne`（`--no-extensions`）: 拡張を自動では読まない。審査していない拡張が混ざらないようにするため（方針は[拡張の方針](#拡張の方針)）
  - 明示した `-e` は `-ne` でも読まれる（Orca の拡張がその例）。足した拡張のツールも判定と伏字化を通り、同名ツールの差し替えは pi が止めるが、
    **拡張の読み込み時の処理は囲えない**（[実測](../../research/agents/pi-extension-under-harness.md)）
- `-e builtin:mcp`: `-ne` で外れる組み込みの MCP 対応だけを戻す。サーバはフルガードが登録する（[MCP](#mcp)）
- フルガード（`index.ts` と `rules.json`）が無い、または `~/.pi/agent/mcp.json` にサーバがあるときは起動しない
- 子エージェントの印（`PI_HARNESS_CHILD`）など、外から入った内部の環境変数は外す

> pi の公式仕様に頼る箇所と、実測して頼っている挙動の一覧は [pi の公式仕様と実測の棚卸し](../pi-upstream.md)。pi を更新したときは、そこの手順で確かめる。

### bypass の切り替え

`pis` の起動後に、利用者が `/bypass [on|off]`（引数なしはトグル）で bypass を切り替えられる。起動時の値は `--bypass` / `--no-bypass`（`PI_HARNESS_BYPASS`）で、
省略すると**サンドボックスでの起動はオン、`--no-sandbox` はオフ**（利用者の決定、境界の内側でこそ確認なしで通す。守りがガードだけのときは確認を残す）。

- **利用者専用**: スラッシュコマンドとして登録し、モデルが呼べるツールは作らない。`bypass` の名前のツールは存在しない
- **ON は確認を出す**。サンドボックスの内側（証明済み）なら「deny とサンドボックスは有効のまま」、無いときは「deny だけが守り」と文言を変える。**確認が要る外部への送信・公開（`gh` の投稿など。[confirm](pi-decide.md#confirm)）は、bypass でも確認する**とも書く。確認を出せない（UI が無い）ときは ON にならない。**OFF は確認なし**
- **表示**: フッターのステータス行（起動モード・ToDo の行）に `⚡ bypass`（警告色）を出す。`--bypass` で起動したときも出る。サンドボックスの表示（`🔒 sandbox` / `⚠ no sandbox`）とは別のキー。行は中くらいの幅（80 列前後）に収まるよう、ToDo のタイトルは表示幅で切る
- **保持しない**: セッションには残さない。`-c` で再開しても起動時の指定 (既定を含む) どおりから始まる
- 効くのは判定器の ask だけで、deny・誘導・秘密の保護は変わらない（[評価順](pi-decide.md)）。切り替え時は、`tool_call` で下した判定の使い回し（`decided`）を捨てる
- 子エージェントへは、**起動した時点の値**を `inherit_bypass` の子にだけ渡す。動いている子には後からの切り替えが届かない
- サンドボックスの切り替えはできない（Fence は外側から囲うので、内側から外せない。再起動する）
- 試験: `test_pi_harness.py` の `test_bypass_command_*`（RPC で `/bypass` を送る。TUI の表示そのものは未確認）

### confirm の確認

判定器が `mustConfirm` の ask を返したとき（[confirm](pi-decide.md#confirm)）、ハーネス（`index.ts`・`confirm-view.ts`）が、bypass でも次の確認を出す。

- **見出し**は「⚠ bypass でも確認が要る操作 (外部への送信・公開)」。**本文**は、コマンドの**全文**（切り詰めない。ANSI エスケープなどの制御文字は
  `\x1b` のように可視化し、`\n` と `\t` は残す）と、`gh pr|issue` の `--title`/`--body`/`--body-file`/`--base`/`--head`/`-R` などの**参考表示**
  （「解析結果。実際に実行されるのは上のコマンド」。解釈できない形は省く）
- **`--body-file <path>`**: ハーネスがそのファイルを読んで本文に出す（32 KiB まで。`read` の判定が allow のときだけ）。読めない・`-`（標準入力）・上限超えは、
  確認を出さず拒否。承認後にファイルが差し替えられないよう、`execute()` で再読みして内容が違えば拒否する。タイトルと本文の合計が 8,000 字を超えるときも、
  確認を出さず拒否（短くするか、利用者が自分で実行する）
- **無反応は deny**: `[pi.confirm] timeout_seconds`（既定 300）を、TUI でも `confirm` の `timeout` に渡す。期限は確認画面を出してから数える。
  結果は、承認・拒否・時間切れ・取消・UI 無し・abort を区別して、拒否の理由に反映する（`not approved:` の接頭辞は保つ。子の `blocked` の分類のため）。
  時間切れは「再試行せず、利用者の新しい指示を待つ」、拒否は「同じ操作をくり返さない」
- **UI が無い実行は deny**: print モードと子（RPC。親が UI 要求を取り消す）は、確認できないので拒否する（`inherit_bypass` の子でも通らない）。`bg_run` の `--body-file` は
  `execute()` で再読みできないので、一律に拒否する
- **`/bypass`**: description・ON の確認の本文・説明に、「確認が要る外部への送信・公開は、bypass でも確認する」を書く
- **未確認**: 実際の TUI での表示（残り秒数、長い本文のスクロール）は、実機で見ていない（試験は RPC と print）。確認の誤入力の防止（表示直後の確定キーの無視）は未実装

## 拡張の方針

**拡張は自作を基本とする**（[ADR-0016](../../adr/0016-pi-extensions-own-first.md)）。外部の拡張は、**どうしても必要で、自前実装が困難で、振る舞いを十分に確認したもの**だけを、
例外として導入する。手順は ADR-0016 の「例外の手順」（審査・版の固定・偽のモデルでの試験・配備・記録）。

- `pis` は `-ne` を維持し、足す拡張は必ず `-e <パス>` で明示する（自動発見はしない）
- 足した拡張のツールも判定と伏字化を通る。拡張の読み込み時の処理は囲えないので、審査と版の固定で下げる
- 素の `pi`（Windows・Orca・Zed）は拡張を自動で読むが、この方針は**このリポジトリが配る拡張**に適用する

### 入口の選び方

機能の入口は、**必要な能力を満たす最小のもの**を選ぶ。中核を CLI にして、上に MCP や拡張を薄く被せる形も取れる。

| 観点 | skill + CLI | MCP | 拡張（自前） |
| --- | --- | --- | --- |
| 常駐するコンテキスト | skill の名前と説明だけ。本文は必要時に読む | `codemode`（既定）はツール定義を宣言せず、サーバ名の 1 行。`direct` ならツール定義が常駐 | ツール定義が常駐（動的な有効化もできるが、ツール集合が変わる） |
| キャッシュへの影響（見込み。実測は未） | ツール集合が変わらないので小さい | `codemode` は小さい。接続後に概要が追記されることがある | ツールを足すと先頭側の固定部分が変わる（最小のスキーマで入力 +36 トークン、偽のモデルの見積もり） |
| 使える CLI | `bash` と skill を持つものすべて（pi、Claude Code、OpenCode、Copilot） | MCP を持つもの（登録の経路は CLI ごとに違う） | **pi 専用**（TypeScript、pi の API に依存） |
| フルガードとの整合 | `guarded_bash` の判定と伏字化を通る。許可の規則をサブコマンドで絞る | `mcp__*` として判定（既定は確認）、結果は `tool_result` で伏字化。`mcp.json` は `pis` と共存できない | 判定と伏字化は通る（[E5](../../research/agents/pi-extension-under-harness.md)）。読み込み時のコードは囲えない |
| 機能の深さ | 呼び出しと標準出力まで。UI・イベント・状態は持てない | 型付きのツール、構造化された結果、**常駐サーバでの状態保持** | **pi の内部に介入できる**（イベントのフック、スラッシュコマンド、UI、システムプロンプト、子エージェントの起動、圧縮、独自のプロバイダ） |
| 試験のしやすさ | 手で実行でき、単体テストも簡単 | 中（プロトコルの層が増える） | 偽のモデルが要る（フルガードの試験の仕組みはある） |
| 開発・保守のコスト | 最小 | 中（サーバ・登録・配布） | 中〜大（pi の版に追従する） |
| 1 回の使用の手間 | skill を読む往復が 1 回増える。以後は `bash` を呼ぶだけ | 型付きで呼べる。`codemode` だと間接が増える | 直接呼べる |

- **単純な要求と応答**（検索・取得）→ skill + CLI。コンテキストと保守が最小で、どの CLI でも同じ
- **構造化した結果・常駐した状態・複数の CLI で共有する標準の入口**（ブラウザの操作、認証つきの長いセッション、DB への接続など）→ MCP
- **pi の内部への介入**（`task` の子エージェント、フルガード、Orca の状態表示）→ 拡張。他の 2 つでは代えられない
- 検索は拡張でしかできないこと（フック・UI・プロンプトの書き換え）を要さず、拡張は pi 専用・読み込み時のコードを囲えない・pi の版に結びつく。拡張は「不利」ではなく、検索には過剰

### 外部の拡張

導入済みの外部の拡張の記録。ここに無い外部の拡張は、導入していない。

| 名前 | 版 | ハッシュ | 必要な理由 | 自作が困難な理由 | 審査日 |
| --- | --- | --- | --- | --- | --- |
| （無し） | | | | | |

### 自作の拡張: todo / plan / btw

`~/.pi/agent/extensions/{todo,plan,btw,activity,ask,notify}/index.ts`（実体は `home/dot_pi/agent/extensions/`）。pi 同梱の例（`examples/extensions/todo.ts`・`plan-mode`）を参考に、必要な部分だけ自作した。全 OS に配る。

| 拡張 | 中身 |
| --- | --- |
| `todo` | `todo` ツールと `/todos`。**リストは 1 つで、勝手には消さない**（同じ目標のための別目標は同じリストへ足していく）。ツールの操作は `list`（`all` で完了・中止も）/ `add`（`text` か `texts` で複数）/ `set`（`id` と `status`: `pending`・`in_progress`・`blocked`・`done`・`cancelled`。何度呼んでも同じ結果で、旧 `toggle` の取り違えが起きない）/ `update`（`text` か `note`）/ `remove` / `clear` / **`batch`**（`ops` に操作の配列。順に適用し、1 件でも失敗したら全体を適用せず、失敗した `ops[i]` を返す）/ **`replace`**（`items` でリスト全体を置き換える。`id` を付けた項目は引き継ぎ、載せない既存の項目は消える。Claude Code の `TodoWrite` 相当）。項目には**メモ `note`**（完了の根拠・引き継ぎ。80 字まで表示）を付けられる。変更の結果としてモデルへ返すのは、**変更の要約と、未完了の先頭 3 件・件数だけ**（全件は `list`）。`list` が返す一覧は未完了だけで、完了・中止は件数にたたむ。`in_progress` は同時に 1 件までが指示で、超えると結果に注意を出すが止めない。**`blocked`（`[~]`）は、ジョブ・子・利用者の返答など外部の完了待ち**で、未完了には数えるが、`in_progress` の同時 1 件の数と終了時のリマインドの対象には入れない。note なしで `blocked` にすると、待ち先を書く旨の注意を返す（拒否はしない）。**`in_progress` が残ったまま応答を終えようとしたとき、`agent_before_settle` で確認を促すメッセージ（`custom_message`）を足して続行を 1 回だけ要求する**（利用者の発言ごとに 1 回。中断・エラーで終わったときは出さない。切るには環境変数 `PI_TODO_NO_REMINDER=1`）。子の完了は `guarded_task` の `todo` で項目へ反映できる。`/todos` は全件を表示し、`/todos tidy`（完了・中止を片付ける）・`/todos clear` は**利用者専用**（モデルは呼べない）。状態はツール結果の `details` と、利用者の操作の custom エントリ（`todo-state`）に持つので、分岐・再開・圧縮のあとも、その時点に戻る（旧形式 `{ id, text, done }` も読む）。フッターに `📋 完了/全体 ▶ 作業中の項目`（全部完了なら `✅`）を出す |
| `plan` | `/plan` で切り替え。計画中は **`edit` / `write` / `bash` / MCP などのツールを外し**、`read` / `grep` / `find` / `ls` / `todo` / `task` だけを残す（`guarded_` 付きも同じ）。計画の指示を毎ターン注入し、番号付きの手順で終わったら「実行する / 続ける / 直す」を尋ねる。「実行する」でツールを戻し、実行を依頼する |
| `btw` | `/btw [--plain] <質問>`。いまの会話（user / assistant の本文とツール呼び出しの要約）を文脈に答える。**既定は、読み取り専用の子（`explore`）が、必要ならファイルを読んで確かめてから答える**（会話は新しい側 2 万文字まで。子の起動は、フルガードか Windows の `subagents` 拡張が `globalThis.__piAskReadChild` に置く入口を使い、上限は 3 分）。`--plain` は、ツールなしで**現在のモデル**が 1 回だけ答える（速い。会話は新しい側 6 万文字まで、上限 2 分）。**子が失敗したときは、理由を表示して終わる**（調べていない推測を答えとして出さない。ファイルを見ずに答えさせるなら `--plain`）。子の入口が無いときだけ `--plain` と同じ動きになる。答えは、端末の高さに合わせて**本文の窓だけを描くスクロールできる表示**に出し（↑↓ / j k で 1 行、Space / b で 1 ページ、g / G で先頭・末尾、Enter / Esc / q で閉じる。位置と閉じる案内は最下行）、会話履歴にもモデルの文脈にも残さない。返信はどの経路でも **2 万文字**で切り、「省略あり」を末尾に書く。子と `--plain` の指示は「画面 1 枚（約 20 行）に収める」。エージェントの応答中でも使える |
| `ask` | `ask` ツール。利用者へ選択肢つきの質問を**最大 4 問まとめて**尋ねる（`questions`: `question`・`header`・`options` 2む4 個（`label` と `description`）・`multi`）。画面は、**TUI では自前のパネル**（`ctx.ui.custom()`。問が複数のときは問ごとのタブと最後の「確認」タブ（Tab / Shift+Tab で移動。回答は保持して戻って直せる。確認タブで未回答を警告し、Enter で送信。Esc は全体の中止）。問が 1 つだけならタブも確認も無く、答えたらすぐ送る。選択肢と説明を縦に並べ、カーソルは ❯。複数選択は Space でカーソルを動かさずに切り替え、Enter で確定（チェックしたまま Tab で離れても回答として扱う）。`Type something.` はその行の下でその場で書き、Enter で確定（複数選択でもこの Enter で、チェックと自由記述をまとめて確定する）・Esc で一覧へ戻る。数字キーで行へ移動。IME のためフォーカスをエディタへ渡す）、**RPC（Orca・Zed）では 1 問ずつの `select` / `input`**（選択行は「1. ラベル」の 1 行だけで、説明は質問文の下に番号つきの一覧として出す。表示幅 64 カラムで自前に折り返して字下げし、選択肢の間に空行を入れる。RPC の複数選択は、チェックを切り替えるたびにカーソルが 1 個目に戻る）。長い行の折り返しで境界とカーソルが分からなくなったため）（TUI と RPC で共通。Orca と Zed でも動く）。全問に自由記述の行 `Type something.` を自動で足す（空の入力は記録せず選択肢へ戻る）。`Other` / `Type something.` / `Next` は選択肢のラベルに使えない（`reserved_label`。ほかに `no_questions`・`too_many_questions`・`duplicate_question`・`empty_options`・`duplicate_option_label`・`no_ui`）。**推奨の検査**: 各質問は推奨の選択肢をちょうど 1 つ（multi は 1 つ以上）持ち、先頭に置く。印は label の末尾の `(推奨)` か `(recommended)`（直前に空白を置く。全角括弧・大文字小文字可。label に残り、答えもそのまま返す）。違反は `missing_recommended`・`multiple_recommended`（multi 以外で 2 つ以上）・`recommended_not_first` で、違反した質問を全部 1 つのエラーにまとめ、直し方を添えて返す（形の検査の後。label は 60 字までなので短くする）。試験は `test_pi_harness.py` に足したが未実行。戻りは `answers`・`unanswered`（0 始まりの番号）・`cancelled`。中断や時間切れのところから先は未回答として返る。**1 回の画面の待ち上限は 5 分**（試験用に `PI_ASK_TIMEOUT_MS`）。**UI が無い実行（print・子エージェント）では、`before_agent_start` でツールを外す**。`plan` 中も残る。設計は公開拡張（`rpiv-ask-user-question`・`pi-ask-user`）の README を参考にした（[調査 P3・P4](../../research/agents/pi-public-extensions-survey.md)）。タブ画面・プレビュー・メモは作らない（`ctx.ui.custom()` が必要で、RPC では出せない） |
| `notify` | **利用者の入力を待つとき、端末へ BEL（`\x07`）を 1 回送る**。送るのは、作業が完全に終わったとき（`agent_settled`。`agent_end` ではない）、フルガードの確認（`confirmInOrder`）を出す直前、`ask` の質問を出す直前。Zed の Terminal Threads は、フォーカス外の端末の BEL を通知にする（[Terminal Threads](https://zed.dev/docs/ai/terminal-threads)、2026-10-21）。**TUI（`ctx.mode === "tui"`）のときだけ書く**。RPC では stdout が JSON 行の通信なので汚さない。試験は `test_the_bell_is_written_only_in_the_tui_not_in_print_mode`（鳴らさないことだけ。鳴ること自体は未確認）。ACP 経由の Zed（pi-acp）には効かない（[Z1・Z2](../../research/agents/zed-orca-pis-integration.md)） |
| `activity` | 動いている子エージェント（`task` / `guarded_task`）とバックグラウンドジョブの数を、入力欄の下の専用の 1 行（ウィジェット。起動モード・ToDo のステータス行とは別の行）に `🤖 2 subagents / ⚙️ 1 jobs` の形で常時出す（0 件の側は出さず、どちらも 0 なら消す）。1 秒ごとに数え直し、表示が変わったときだけ `setStatus` する。子は起動する側（`subagents` とフルガード）が `globalThis.__piChildren` に登録し、ジョブは `bg_run` が `globalThis.__piJobs` に登録する。ツールは `bg_run`（コマンドを切り離して起動し、ID を返す（ログのパスは見せない。`read_deny_globs` で読めないので、教えるとモデルが行き止まる。[実験 B1 の F4](../../research/agents/pi-bg-experiments.md)））・`bg_log`（状態とログの末尾と総行数。ID なしで一覧）・`bg_kill`（プロセスの木ごと止める）。pi の終了時には動いているジョブも止める。**ジョブが終わると `pi.sendMessage`（`triggerTurn: true`、`deliverAs: "followUp"`）で LLM へ終了を知らせる**（ID・exit・コマンド・ログ末尾 20 行）。 **2.5 秒の間に終わった分は 1 通にまとめる**（2 件以上は各ログの末尾 5 行。同時に終わる 12 件で 12 ターンになっていた。[B1 の F3](../../research/agents/pi-bg-experiments.md)）。 **終了後に `bg_log` で読んだジョブは通知から外し、全部が読み済みならターンを起こさない**（画面の通知だけ。B1 の F2）。 親が作業中は届けず、「まとめる窓が閉じた」と「`agent_settled`（`agent_end` ではない。再試行・圧縮・続行がその後に続くことがある）」の両方を満たしてから、読み済みを除いて届ける。アイドルなら、窓が閉じたときにすぐターンを起こす。 試験は `test_jobs_that_finish_together_wake_the_agent_once` / `test_a_job_read_with_bg_log_after_it_finished_does_not_wake_the_agent` / `test_a_job_not_read_still_wakes_the_agent_after_the_turn`（外すと落ちることを確認）。 ないとジョブ待ちで止まったターンが再開しない。`bg_kill` で止めたときと終了時の停止では送らない。一覧のコマンドは作らない（数だけ）。**待ち方の案内はツール側に置く（AGENTS.md には書かない）**: `bg_run` の `description` / `promptGuidelines` / 戻り値と、実行中のジョブの `bg_log` の戻り値に、「終了すると自動で通知が届く。`sleep` や `bg_log` の連打で待たず、他の作業を進めるか応答を終える」を入れた（2026-10-25。`sleep 9; sleep 9; …` の連結や `bg_log` の連打で待った実例から。連結はガードの既知の限界のまま）。試験は `test_bg_run_and_a_running_bg_log_tell_the_model_not_to_wait_by_sleeping_or_polling`。旧 `/agents` はこれに置き換えた |
| `delegate-nudge` | 親が委譲を忘れない契機の第一歩として、**通知なしで統計だけを取る**試作（N1a）。利用者の発言ごとに、読み取り系ツール（`guarded_read` / `guarded_grep` / `guarded_find` / `guarded_ls`、素の pi の `read` / `grep` / `find` / `ls`）の呼び出し回数・結果の行数と文字数・エラー数・ツール名ごとの回数、`guarded_task` の新規の子の起動数（agent ごと。status・steer・追加依頼は数えない）、それ以外のツール呼び出しの数を、`appendEntry("delegate-stats", …)` でセッションに 1 件残す（モデルの文脈には入らない）。**読んだ内容・パス・引数は入れない**。通知もツール結果の変更もしない（ハンドラは常に `undefined` を返し、例外は黙って無視する）。**子（`PI_HARNESS_CHILD=1`）では動かず**、`PI_DELEGATE_NUDGE=0` で止められる。`/delegate-stats` で直近 10 発言の要約と合計を出す。案件は [CHG-0031](../../change/0031-delegate-nudge.md)。**`own_extensions` に登録済み**（`common.toml.tmpl`、N1a のコミット d8d0769）。試験は `test_pi_harness_extensions.py` の `test_delegate_nudge_*`（5 件。2026-10-25 の同ファイルの実行で通過） |

- **モデルに存在を知らせる**: `todo` / `bg_run` / `bg_log` / `bg_kill` にも `promptSnippet`（と `todo` / `bg_run` の `promptGuidelines`）を付けた。無いと「Available tools」に載らず、モデルが使い忘れる（[子エージェント](#子エージェント)と同じ対処）。試験は `test_todo_and_activity_tools_are_listed_in_the_system_prompt`
- `pis` は `-ne` なので、`-e` で明示して足す。素の `pi` は自動発見で読む
- **自作の拡張の一覧は `common.toml` の `[pi] own_extensions` の 1 か所**。生成器が `rules.json` の `extensions` へ出し、`pis` と `ocs` の `pi.py`（サンドボックス）が同じ一覧を読む。`[pi.sandbox] read` の拡張の分もこの一覧から生成する。拡張を足すときは一覧へ名前を足すだけ。`rules.json` に一覧が無い（配り直していない）と、`pis` は起動しない
- フルガードの役割は、`implementer` の `tools` に `todo` を足してある（判定器は `todo` を allow）。`plan` はツールを登録しないので判定に関わらない
- 計画中は shell が無いので、`git log` などの調査もできない。必要なら `/plan` を終えて調べる
- `pis --boundary` も同じ一覧を `-e` で足す。読み取りは拡張ごとに開ける（`~/.pi/agent/extensions/<名前>`。一覧に無い `orca-agent-status` などは開けない）。実機で `todo`・`plan`・`btw` の認識を確認した
- `activity` の実測（Linux、偽の pi API でツールを直接動かした）: `bg_run` で ID を返し、`🤖 2 subagents / ⚙️ 1 jobs` が出る。`bg_log` が出力の末尾を返し、`bg_kill` でジョブが消えて通知が出て、子もジョブも 0 になると表示が消える。**未確認**: 実機の TUI でのフッター表示、フルガード（`pis`）の下での `bg_run` の確認（拡張のツールなので既定で確認になる想定だが未実測）、Windows の `taskkill` での停止、終了通知が実機の TUI で見えること（RPC の実モデルでは、通知でターンが再開することを確認済み。[B1](../../research/agents/pi-bg-experiments.md)）
- **フルガード（`pis`）の下では、`bg_run` のコマンドを bash と同じ判定（`decide`）に通す**。deny は止め（bypass でも外れない）、ask は確認画面を出し（画面に「バックグラウンドで実行」と出る）、役割の `shell_deny` / `shell_allow` と誘導も効く。役割が `bash` を持たなければ `bg_run` も使えない。`bg_log` / `bg_kill` はジョブの確認と停止だけなので、`bash` を持つ役割には allow。素の `pi` では、Unix ではガードが同じ判定を掛ける（Windows は判定なしで動く）
- `btw` は、`--plain` では `ctx.modelRegistry.complete()` を 1 回呼び、既定では `explore` の子を 1 つ起動する。どちらもトークンを消費する（セッションの合計には入らない）
- **子の入口 `__piAskReadChild`**: 利用者のコマンドが起こす操作なので、`/agent` と同じく判定器は通さない。そのかわり、起動できる役割を**読み取り専用（`reader` / `explorer`）に限る**（`worker` / `commit` は拒否）。答えには伏字化を掛ける（Windows の入口には伏字化も読み取り禁止も無いので、`btw` は開始の通知に「ガードなし」を出す。子の出力の貯め込みは 8 MB で止める）。試験は `test_ask_read_child_entry_runs_only_read_only_agents`・`test_btw_asks_an_explore_child_by_default_and_plain_does_not`、表示の部品（上限・窓・スクロールのキー）は `test_btw_view.py`。**実測**（2026-10-21、tmux の pi 1.3.0）: 窓なし（全文を Container に入れる）だと、120 行の返信で画面に収まる約 28 行だけが表示され、末尾と閉じる案内が見えなかった。窓を入れたあとは 130 行を「1-32 / 130 行」で表示し、`End` / `G` で末尾に届く。**PgUp / PgDn はこの端末では効かなかった**（pi 本体が先に取ると見られる。理由は未確認）ので、Space / b を当てた。**未確認**: Windows の素の `pi` での子の起動、全画面モード、端末幅の変更時の再描画
- 実測: `btw` は print モードで、直前の会話の内容（合言葉）を踏まえて答え、セッションファイルの行数が増えないことを確認した（オーバーレイ表示は TUI でしか出ず未確認）。Git Bash では `/btw` が `C:/Program Files/Git/btw` に変換されるので、試すときは `MSYS_NO_PATHCONV=1`
- 実測: `todo` は、書き換え前の版（`toggle` 方式）で実際のモデル（`claude-sonnet-5.5`）の add / toggle / list が通った。書き換え後の版は偽のモデルでの試験（`test_pi_harness.py` の `test_todo_*`・`test_todos_*`。圧縮と再開をまたぐ復元、旧形式の読み込み、利用者の操作の永続化、フッター）までで、**実際のモデルが `set` / `texts` / `cancelled` を使い分けるかと、TUI の表示は未確認**。`plan` は読み込みまで（切り替えと確認画面は TUI でしか動かず、未確認）

### guarded_action（承認つきの外部操作）

`git commit` と `gh issue comment` を、**1 回の承認で、ハーネスが組み立てた argv を、シェルを通さずに実行する**ツール（[CHG-0038 段 G11](../../change/0038-guard-reclassification.md)）。通常の ask（コマンドを見せて判断）と違い、内容を見せて承認を取り、承認した内容がそのまま使われる。
ガードは境界ではなく「うっかり防止」なので、**誤った経路（bash の直接実行）へ行かないよう寄せる**仕組みであって、経路の強制ではない（Python や curl 経由は迂回できる。強制が要る GitHub 操作は、トークンの権限側で行う）。

- **操作の表**: `common.toml` の `[[pi.actions]]`（`id`・`label`・`argv`・`fields`・`replaces`・`preview`）。生成器が検証して `rules.json` の `judge.common.pi.actions` へ出す。操作の追加は、表に項目を足すだけ（ツールは増えない）。今は `gh_issue_comment`（`repo`・`number`・`body`）と `git_commit`（`message`）。
- **ツール**: `guarded_action`（引数 `action` と `params`）。登録されるのは、役割の `tools` に `action` がある親の役割（`implementer`）だけ。子エージェント・読み取り役・探索役には無く、実行時にも拒否する。判定器は `action` を役割の許可だけで通し、**汎用の ask・確認は出さない**（確認は `execute()` が 1 回だけ行う）。
- **確認**: `select` で「承認して実行 / 編集して承認 / 拒否」。内容（`content` のフィールド）の全文、プレビュー、**実行する argv** を表示する（表示と実行は同じ配列）。無反応（`[pi.confirm] timeout_seconds`）・取消・UI 無し・子は拒否（`not approved:`）。bypass でも省略できない。「編集して承認」は `editor`（timeout が無いので、選んだ後にだけ開く）、「拒否」は `input` で理由を任意に取る。
- **同一性**: `git_commit` は、プレビューで HEAD・ブランチ・index の識別子（`git ls-files -s -z` の sha256。書き込みを伴わない）を取り、**実行の直前に再取得して照合**する。不一致なら実行せず、もう一度呼ぶよう返す。ステージ済みが空ならエラー。プレビューのコマンドは、設定ではなくコードの許可リスト（`git_staged`・`none`）に限る。hook（pre-commit）による実行中の変更までは保証しない。
- **実行**: `execFile`（シェル無し）、cwd は `ctx.cwd`、環境変数は継承（ブローカー経由の `gh` のため）、120 秒。本文は 0700 のディレクトリへ 0600・排他的作成で書き、承認後に再読みせず、`finally` で消す。値は型（`repo` の正規表現・`int`・`text` の長さと NUL）で検証し、`-` 始まりは通らない。終了コードが 0 でなければ、出力を返してエラーにする。
- **誤った経路を寄せる**: `replaces`（`git commit`・`gh issue comment`）に当たる bash は、`action` を持つ役割では **deny**（ask にしない）。評価の位置は `[[pi.guide]]` の直後、`shell_deny` の前（bypass でも外れない）。理由に、`guarded_action` の呼び出し例（`-R` と番号が分かれば候補として入れる）を入れる。`action` を持たない役割・他の CLI は従来どおり（`git commit` は ask）。ツールの説明、`guarded_bash` の説明、`ask` の説明にも同じ境界を書く。
- **指示**: グローバル指示と `commit` スキルは、`guarded_action` が使えるときは事前に `ask` で承認を取らず、bash で実行しない、と書く（ツールが無い環境は従来どおり）。
- **計測**: `.agents/skills/friction-review/scripts/measure_routing.py`（導入前の基準: 71 セッションで投稿・コミットの bash の直接実行 275 回、うち直前に `ask` で承認を取ったもの 60 回）。導入後に同じスクリプトで、bash の直接実行の割合と `guarded_action` の呼び出し数を比べる。
- **試験**: `test_pi_actions.py`（生成器・判定器・TS/Python の同一性）、`test_pi_actions_harness.py`（確認が 1 回・実行・拒否・時間切れ・UI 無し・子・引数の検証・同一性・本文ファイル・編集）。
- **未確認**: 実際の TUI での確認画面の表示（3 択、長い本文、editor の操作）。サンドボックス内でのブローカー経由の `gh` の実機。`git commit` の hook が失敗したときの再試行の運用。**段階 3**（表の一般化と、`gh pr create`・`gh issue create`・`gh pr comment` などの追加）は、実測の後。

### ツール引数の JSON を壊さない設定

モデルが出すツール引数の JSON が壊れる問題（`Invalid arguments for tool … Expected ',' or ']' … in JSON`。`friction-review` の集計で、`guarded_edit` 16 件・`ask` 6 件）への対処。pi 本体が引数の JSON を解析できないと、ツール側では救えない（`toolCall.argumentsError`）。

- **原因の候補（公式文書で確認）**: Anthropic の細粒度ツールストリーミング（`eager_input_streaming`）は、サーバー側でバッファリングも JSON の検証もせず、不完全・不正な JSON が届き得る（<https://platform.claude.com/docs/en/agents-and-tools/tool-use/fine-grained-tool-streaming>）。pi の Anthropic 経路は、既定で全ツールにこれを付ける（`supportsEagerToolInputStreaming ?? true`）。**実測**（pi の `before_provider_request` で送信直前のペイロードを記録。Copilot 経由の Sonnet 5）: 既定では全ツールに付く（20/20）。
- **設定**: `models.json` の `providers.github-copilot.compat.supportsEagerToolInputStreaming: false`（プロバイダー単位。モデルの一覧を持たない）。配るファイルは `home/dot_pi/agent/models.json`。実測: 設定すると送られなくなり（Sonnet 5・Haiku 5.5 で確認）、呼び出しは正常。戻すときは、設定を外す。副作用は、ツール引数が完成するまで画面に出ないこと。
- **`pis` の内側**: agent ディレクトリは本物の `models.json` を写さず、**`providers.*.compat` だけ**を写す（`ocs/pi.py` の `_copy_provider_compat`。`apiKey`・`baseUrl`・`headers`・`models` は写さない許可リスト）。ブローカーの `baseUrl` とは合成される。
- **採用しなかった（今は）: `strict`（厳密な JSON スキーマ）**。実測: pi は既定で Copilot の Claude に `strict` を送らない（`supportsStrictTools` が `github-copilot` のモデルに無い）。`compat.supportsStrictTools: true` で送ると、Copilot は受け付けた（40/40）が、**強制するかは未確認**（公式文書・報告が見つからない）。さらに、Anthropic の strict が対応しないキーワード（`maxItems`、`minItems`（0・1 以外）、`minLength`/`maxLength` など。公式文書による）がスキーマにあると、pi は黙って通常の呼び出しにフォールバックする（`ask` のスキーマが該当）。必要になれば、`ask` のスキーマからそれらを外し（個数などは自前の検証に任せる）、再検討する。
- **効果の測定**: 実験室では、壊れた JSON を再現できなかった（現状の設定で 0/40（通常のプロンプト）、0/20（引用符・バックスラッシュ・複数行を多用するプロンプト））。実使用の発生率は約 1.7%（`guarded_edit` の 940 回中 16 回）で、数百回の比較は費用に見合わない。**数日使った後に、`friction-review` の集計で `Invalid arguments` の件数を比べる**。
- **Bedrock 経由の環境**（pi のソースと AWS の公式文書で確認。2026-10-25）: **同じ対処は要らず、効きもしない**。pi の Bedrock 実装は ConverseStream だけを使い、`eager_input_streaming` も `fine-grained-tool-streaming` のベータ指定も送らない（`anthropic_beta` に入るのは interleaved-thinking と thinking-binding だけ）ので、既定で検証つきのバッファ済みになる。`compat` の項目は `supportsStrictMode`（既定は偽。`toolSpec.strict` を付ける）だけで、`supportsEagerToolInputStreaming` は効かない。Bedrock で JSON が壊れるなら、原因は別（`max_tokens` 到達による途中切れ、`additionalModelRequestFields` へ fine-grained のヘッダーを足す拡張・ゲートウェイ、確定時の `parseToolCallArguments` の失敗）。**まず、送信ペイロードを `before_provider_request` で見て、`anthropic_beta` に fine-grained が入っていないか確かめる**。実機（Bedrock 経由の環境）での発生率は未測定（`friction-review` の集計を、その環境で実行して比べる）。strict の AWS 側の対応とスキーマの制約は未確認。
- **未確認**: Copilot が `eager_input_streaming` を実際に尊重しているか（送らなくなったことは確認したが、サーバー側の挙動は未確認）。他のモデル（GPT・Gemini）。
- **調べた範囲**（2026-10-25）: Anthropic の strict tool use の公式文書（<https://platform.claude.com/docs/en/agents-and-tools/tool-use/strict-tool-use>）、pi の issue（#9643 旧版の壊れた JSON、#10502・#9953 strict の 400）、他のエージェントの報告（Claude Code は `StructuredOutput` に `strict` を付けず `eager_input_streaming` を付ける、OpenRouter で不正な JSON の報告）。反例: Bedrock などで `strict` を送ると 400 になった報告。

### ツールの拡張（`guarded_read` / `guarded_write` / `guarded_bash` の使いやすさ）

誘導の deny（[誘導](pi-decide.md#誘導)）が多発する原因は、代替が同等でないことと、ツール定義の説明が弱いこと
（[CHG-0038](../../change/0038-guard-reclassification.md) 段 G8。他の製品の調査は
[記録](../../research/agents/tool-design-survey.md)）。ハーネスは、pi の組み込みの定義を `...def` で展開して
`guarded_*` として登録し、`tools-ext.ts` で次を足す（pi 本体を import しない純関数。node で単体試験できる）。

- **説明の上書き**: `guarded_bash` は「実行（ビルド・テスト・git・`grep`/`find`/`ls`）に使い、ファイルの内容を読む・作る・変える用途に
  使わない」と、具体的な言い換え（`cat`/`head`/`tail`/`sed -n` → `guarded_read`、`echo >`・`cat > f <<EOF` → `guarded_write`、
  `sed`/`awk` → `guarded_edit`）、複数ファイルは並列の `guarded_read`、長い待ちは `bg_run` を書く。組み込みの snippet にあった、
  ファイル操作の `ls, grep, find` を勧める文は外した。`guarded_read`・`guarded_write`・`guarded_edit` にも、使い分けとトークン効率を書く
- **`guarded_read` の `tail`**: 末尾から N 行（`offset` と同時に指定するとエラー、`limit` は無視、32 MiB 超は不可）。総行数を数えて
  `offset`・`limit` に直し、組み込みの `read` を呼ぶ。判定は `path` に従来どおり掛かる
- **`guarded_write` の `append`**: 既存の末尾へ、`content` をそのまま連結（改行は自動で足さない）。組み込みの write の mutation queue・
  親ディレクトリの作成・整形・判定（`edit` の deny・ask・bypass）はそのまま
- **読みの失敗のヒント**: offset が範囲外のとき有効な範囲、存在しないとき同じディレクトリの似た名前（最大 3 件。`read_deny_globs` に
  当たるもの・`decide` が allow でないものは出さない）
- **拒否メッセージの言い換え**: 誘導の deny（読み取り・書き込みの 4 規則）の理由の末尾に、該当の断片と具体的な言い換え
  （`sed -n 'A,Bp' f` → `guarded_read {path, offset, limit}`、`tail -n N f` → `{tail: N}`、`cat >> f <<EOF` → `guarded_write {..., append: true}` など）
  を機械的に足す。パイプ・リダイレクト・`$`・グロブ・引用の閉じ忘れを含む断片、パースできない形には付けない。**deny の判定は変えない**
  （再試行のコストを下げる変更）
- **`guarded_edit` の失敗のヒント**（`friction-review` の集計: 呼び出し 940 件のうち 118 件（約 12.5%）が失敗。内訳は、oldText が見つからない 50、結果が同一 36、引数の不正 16、複数一致 9、重なり 3）: 失敗した結果の末尾に、次の一手を追記する（元のメッセージは消さない。`tool_result` で扱う。引数の不正は `execute` に届く前に起きるため）。見つからない → 最も近い箇所（行番号と、違う行の期待と実際。空白・タブ・改行コードの違いの可能性）。結果が同一 → newText がすでにあれば「適用済みの可能性（行 N）」。複数一致 → 一致した行番号と直前の行。引数の不正 → 編集を小さく分ける、全体の書き換えは `guarded_write`。重なり → 1 つにまとめる。ファイルが読めない・512 KiB 超・バイナリ・読み取り拒否のときは、ヒントを省く（本文は最大 3 行の抜粋）。実機で確認（oldText の空白を間違えた呼び出しで、行 2 の違いが返る）。純関数は `tools-ext.ts`、試験は `test_pi_tools_ext.py`。
- **`ask` の引数の正規化**（失敗 11 件: 壊れた JSON 6、`question` が要素の外 5）: `prepareArguments`（スキーマ検証の前に呼ばれる）の純関数 `normalizeAskArgs`（`extensions/ask/normalize.ts`）で、よくある形の間違い（`question`・`options` がトップレベル、`question` が要素の外、`question` が無く `header` がある、`options` が文字列、`questions` が JSON 文字列、`multi` が文字列、`description` が無い）を直す。**意味を変える補完（推奨の自動付与など）はしない**。壊れた JSON は pi 本体が解析できず、ツール側では救えないので、説明に正しい例と「文字列に半角の `"` を入れない」を足して発生率を下げる（効果は未測定）。自前のエラー文にも正しい例を添える。`constrainedSampling`（プロバイダー側の厳密なスキーマ）は、`guarded_edit` で JSON の不正が出ていることから、今の経路では効かない可能性が高いと見て見送った。
- **しないこと**: 複数ファイルの一括読み（並列の呼び出しで足りる）、`stdin` の引数（pi の bash は `command` と `timeout` しか受けない）、
  透過実行、`executable`

## Windows

Windows（PowerShell）では**素の `pi` だけ**を使う。フルガード・`pis`・サンドボックスは Unix だけ（サンドボックスが Fence に依る。判定器は TS で動くが、フルガードの Windows 版は未着手で、優先度は低い）。

| 配るもの | 方法 |
| --- | --- |
| pi 本体 | mise の `aqua:earendil-works/pi`（バイナリ版。node 不要）。`313_mise` が入れ、`314_agent_cli.ps1` が旧 npm 版を外して起動を確かめる（[Windows の pi](../structure.md#windows-の-pi)）。公式の `install.ps1` は `Read-Host` で確認を聞き、apply では答えられないので使わない |
| `~/.pi/agent/settings.json`・`keybindings.json`・`AGENTS.md` | Unix と同じ（`.chezmoiignore` で戻している） |
| `~/.config/pi/commit-confirm` | Unix と同じ（[commit の確認](#commit-の確認-素の-pi)） |
| `/fleet`（`prompts/`） | **配らない**。`guarded_task` はフルガードが登録するので、素の `pi` では働かない |
| 子エージェント `task`（読み取り役だけ） | `~/.pi/agent/extensions/subagents/`（[下記](#windows-の子エージェント)） |

- pi の `bash` ツールと `!` は Git Bash を使う（Git for Windows が要る。無ければ pi が探した場所を示す）。
  PowerShell をモデルに使わせるなら `defaultTools` を変える（[Run Pi on Windows](https://pi.dev/docs/latest/windows)）。
  今は管理していない
- 素の `pi` なので、権限・秘密の保護は効かない（Orca・Zed と同じ。[位置づけ](#起動)）。`git commit` の確認だけは補助の拡張が出す
- **Windows ネイティブの `pi` は、信頼できる環境でだけ開く（ガードは付けない）。** 守りが要る作業は WSL の `pis` で行う。フルガードの Windows 移植は見送り（[調査記録](../../research/agents/pi-isolation-options.md)）
- Windows 実機では未検証（WSL からは `chezmoi` の描画と静的な試験だけ）

### Windows の子エージェント

フルガードの無い素の `pi` でも、読み取り役の子エージェントだけは使える。判定器が無いので、shell・編集を持つ役割は出さない。

- 拡張 `index.ts`（`task` ツール）と `agents.json`（`[pi.agents]` から生成。`generate.py --target pi-subagents`）を Windows にだけ配る（Unix は `.chezmoiignore` で除外）
- 出すのは `read` `grep` `find` `ls` だけの役割（今は `explore` と `review`）。子は `<実行中の pi>（node 版は node + cli.js、バイナリ版は pi.exe） --mode json -p --no-session -ne --tools read,grep,find,ls` で起動する（`pi.cmd` のシェルを通さない）
- 判定器と伏字化が無いので、`read_deny_globs` の保護は効かない。子は読むだけで書けないが、秘密ファイルは読める
- 子のモデルは `second_opinion` が `github-copilot/gpt-6-sol`。OpenCode の階層の `gpt-6-astra` は pi の Copilot 経由で `model_not_supported`（2026-10 実測）なので、`[pi.model.tier.github-copilot]` で上書きする（Unix のフルガードにも効く）

### 二つの task を別物にしている理由

Windows の `task`（`subagents` 拡張。120 行）とフルガードの `guarded_task`（`registerTask` と `children.ts`。約 1,200 行）は、統合せず別物のままにしている（調査と判断は [調査 P3](../../research/agents/pi-public-extensions-survey.md)、採点の訂正）。

- **重なるのは約 50 行**（答えの取り出し・プロセスの起動と停止・役割一覧の整形・`promptSnippet`）。子の一覧 `globalThis.__piChildren` を `activity` が読む点だけが共有
- **子の実行方式が違う**: `subagents` は 1 回だけ実行する `--mode json -p`、`guarded_task` は常駐できる `--mode rpc`（`Job`。並列・背景・`keep`・`steer`・`abort`）。後者の子はハーネスを `-e` で読み、`PI_HARNESS_*` を前提にする
- **Windows にはフルガードが無い**（`pis` は Unix 専用。簡易ガードは廃止）。`Job` を流用すると、判定器なしで shell を持つ子を出せてしまう。だから `subagents` は読み取り専用に限る
- **共通モジュールにしない**: ハーネスは `~/.config/pi/harness`、拡張は `~/.pi/agent/extensions` にあり、別の場所からの import は配置とサンドボックスの許可の点で脆い
- **ずれは試験で止める**: 宣言は同じ `[pi.agents]` から出る。名前・モデル・読み取り専用の役割の説明と指示が食い違わないことを `test_pi_subagents.py::test_declarations_stay_in_step_with_the_full_guard_agents` が確かめる（`plain_description` を宣言した役割だけ、意図して違う）

## ガード以外の機能

OpenCode のガードにあった機能のうち、pi へ移したもの。仕分けと経緯は
[CHG-0020](../../change/0020-pi-migration.md#段-5-の仕分け2026-10-09)。

### 圧縮（旧 checkpoint）

`session_before_compact` で、圧縮の要約の依頼に**引き継ぎの指示**（Next Steps は手順と合格条件まで書く・
略語を展開する・未作成の文書は「未作成」と書く・制約と却下済みの方針を残す）を足す。pi の要約はセッションに
残り、`pi -c` で再開しても消えないので、外部ファイル・skill・注入の印は作らない。

- `compact()` を `ctx.modelRegistry.streamSimple` 経由で呼ぶ。認証の解決結果の `baseUrl` をモデルへ反映する
  （Copilot はトークンごとに違う。pi 自身も同じ。反映しないと 401 になった）
- 失敗したら標準エラーと通知（端末の幅で切れないよう全文）へ理由を出して、pi の既定の圧縮に任せる（指示は補助で、圧縮は止めない）
- **`compact()` に、セッションの思考レベル（`pi.getThinkingLevel()`）と、一時的な失敗の再試行方針（pi の既定値。利用者の `retry` 設定は拡張から読めないため、設定にかかわらず既定値に固定）を渡す**。
  渡さないと「thinking: disabled」で送られ、それを受け付けないモデル（Copilot の `claude-sonnet-5.5` など）が 400 を返して、
  **どの PC でも指示つきの圧縮が失敗して既定に落ちた**（実測 [表 B の 19](../pi-upstream.md#b-明示が無いここに書く)）。
  思考レベルが `off` で同じ 400 になったときは、思考を `minimal` にして 1 回だけやり直す（pi の既定の圧縮は、同じ指定で失敗して全く圧縮できない）
- `/compact <焦点>` の引数（`event.customInstructions`）は、引き継ぎの指示に【利用者の指定】として合わせる（自作の圧縮が成功すると既定の圧縮には進まないので、合わせないと捨てられる）
- 要約が出力の上限（`reserveTokens` の 0.8 倍）で切れたとき（`Summarization failed: generation hit the token cap …`。切れた要約は pi が保存しない）だけ、
  `reserveTokens` を倍にして **1 回だけ**やり直す。実際には起きていない（今回の原因ではない）が、公開の報告にある失敗の型
- 指示は履歴の要約にだけ入る。分割されたターンの前半の要約（`Turn Context`）には入らない（pi の仕様）
- 別名のツールで触ったファイルは、これまでどおり要約のファイルの一覧に足す

### `git commit` の確認

`git commit -m …` の確認の本文に、件名・本文・追加するパスを出す。フルガードの置き場の純関数
（`~/.config/pi/harness/commit-message.js`）を取り込み、表示の幅と行数は
`[opencode.ask_description.commit]` を使う。読み込めなくても出さないだけでフルガードは止めない。
OpenCode の guide plugin には同じ内容の写しがあり（`test_pi_commit_confirm.py` が一致を確かめる）、
OpenCode の撤去（CHG-0020 の段 6）で写しごと消す。フルガードは OpenCode の置き場を読まない（CHG-0023 の段 3g の前半）。

### commit の確認 (素の pi)

素の `pi`（Orca・Zed・Windows）にはフルガードが無いので、bash の git は素通りになる。その補助として、
小さな拡張 `~/.config/pi/commit-confirm` を `settings.json` の `extensions`（`[pi.settings]`）から読ませる。
**保護ではなく補助**で、別名・スクリプト越しの git は検出しない。`!git commit`（利用者が手で打つ）も対象外。

| コマンド | 扱い |
| --- | --- |
| `git push`（`-C dir`・`sh -c '…'`・`commit && push` も） | **確認せずに拒否**する。push は完全手動。連結した commit も実行しない |
| `git commit` | 構造にして見せて確認する（下） |
| それ以外 | 何もしない |

検出は、引用符の外のコマンドの先頭だけを見る小さな字句解析（`parse.ts`）。引用符の中の文字列
（`echo "git commit"`）や `git commit-tree`・`git stash push` は拾わない。

#### 確認の表示

事実は git から取り、メッセージだけコマンドから読む（`describe.ts`）。生のコマンドは出さない。

```text
リポジトリ: https://github.com/applejxd/dotfiles.git
ブランチ:   main  → origin/main (1 ahead, 0 behind)

対象:       2 ファイル  +2 −1
  M a.txt (+2 −0)
  D c.txt (+0 −1)
  (含まれない未ステージの変更: 2 ファイル)

メッセージ:
  feat(pi): 構造化表示を作る
  - 本文…

注意:
  --no-verify: コミットの hook を飛ばす
```

- リポジトリは origin の URL（`https://user:token@…` の認証情報は出さない。origin が無ければパス）
- 対象は、**実行したらコミットされる内容**を一時のインデックスに再現して数える。通常はインデックス、`-a` は
  `add -u`、`add … &&` は追加後、`git commit <パス>` は土台にそのパスの今の内容を足したもの。`--amend` は
  直前のコミットの親との差。HEAD・本物のインデックス・作業ツリーは変えない（`GIT_OPTIONAL_LOCKS=0`）
- メッセージは `-m`（複数も）、`-F file`、`-F - <<'EOF'`、**`-m "$(cat <<'EOF' … EOF)"`**（エージェントの定番）を読む。
  本文は 72 桁・8 行まで、件名は切らない
- `--no-verify`・`--amend`・`-S`・`--allow-empty` は「注意」に出す。コミットする変更が無いときも書く
- **読めない形は「読めない」と言う**。`VAR=値 git commit`・`sudo git commit`・連結（`&&` 以外・`add`/`cd` 以外が付く）・
  パイプ・リダイレクト・`$VAR`・`$(…)`・`-e`（エディタ）・メッセージ無しは、
  「解釈できない形のコマンドです。次がそのまま実行されます:」と生のコマンドを（12 行まで）見せる。
  構造化の表示が、後ろに付いた操作を隠さないための規則
- **並んだ commit の限界**: pi は同じ応答の全呼び出しの `tool_call` を終えてから実行を始めるので、2 件目の表示は、1 件目の確認が済んだ後に組むが、1 件目のコミットはまだ入っていない（2 件目は 1 件目の対象も含めて見せる）。実行の終わりを待つ案は、全呼び出しの確認が終わるまで実行が始まらないため、安全弁の時間まで止まって採れなかった
- 確認で実行する `git add` は一時のインデックスに対してだけ動くが、`.gitattributes` の clean filter は走る
  （`git commit` を承認すれば同じものが走る）。`core.fsmonitor` は切り、diff は `--no-ext-diff`

#### 時間切れと退避

確認が取れなかったとき（時間切れ・不在・画面なし）は、**コミットせず、内容を退避して作業を続けさせる**。

- 期限は TUI が **15 分**（画面に残り秒が出る）、RPC など（Zed）が **5 分**。時間切れは拒否と同じ `false` で返るので、
  経過時間で見分ける。利用者が拒否したときは退避しない（「拒否した。続け方を確認する」と返す）
- 退避は、コミットの**オブジェクトだけ**を作り（`write-tree` → `commit-tree`）、`refs/pi/pending/<時刻>` に置く。
  ブランチ・HEAD・インデックス・作業ツリーは動かない。hook は呼ばれず、`commit.gpgsign` に左右されない。
  `user.name` が無い環境では代わりの身元を渡す
- 直前の保留を親にして**鎖**にする（2 つ目の差分は 1 つ目からの増分）。その間に本物のコミットがあれば、HEAD から
  始め直す。ref 名の順で先頭を選ぶ（`creatordate` は同じ秒で崩れる）
- モデルには「コミットは実行していない。内容は `refs/pi/pending/…` に退避した。**再試行しない**。コミットが要らない
  作業を続け、最後に『保留したコミット』として ref・件名・対象を報告する」と返す。実際のモデルで、`b.txt` を作り、
  ref を報告し、`--no-verify` や plumbing での迂回をしないことを確かめた
- **不在**: 時間切れの後は、利用者の入力（`input` イベント。拡張が起こしたものを除く）があるまで、次の確認で待たずに
  退避する。1 回の応答に並んだ commit も、先の確認が時間切れなら後ろを待たない
- **連結したコマンド**（`git commit … && 別の操作`。モデルがよく書く）はコマンド全体を止める。退避は最初の
  `git commit` から**近似**する（今ステージされている内容と、そのメッセージ。連結の他の操作は再現しない）。
  理由に「連結していた他の操作も実行していないので、commit と分けて実行し直す」と書く。変数入りのメッセージなど、
  最初の commit も読めないものは退避できない（その旨を返す）
- `--amend` は退避できない（直前のコミットの書き換えは HEAD の子として表せない）

後から見る・取り込む:

```sh
git log --oneline refs/pi/pending/<名前>          # 保留したコミット (鎖の全体)
git reset --soft refs/pi/pending/<最後の名前>     # HEAD だけ進める。作業ツリーは変わらない
git for-each-ref --format='%(refname)' refs/pi/pending/ | xargs -n1 git update-ref -d   # 全部捨てる
```

試験の期限は `PI_COMMIT_CONFIRM_TIMEOUT_MS` で縮める（本番では使わない）。

- `pis` は `-ne` で外れるので、フルガード自身の確認と二重にならない（試験済み）
- Windows にも配る。`.chezmoiignore` は `.config/pi/` を戻したうえで `harness` を改めて除外する
  （`!` は除外より先に効く。実物の `chezmoi` で確かめた）。Windows 実機は未検証
- 試験: `test_pi_commit_parse.py`（解釈・表示・退避。node で直接）、`test_pi_commit_confirm.py`
  （pi + 偽のモデル。RPC・非対話・TMUX の TUI）

### 整形

`guarded_edit` / `guarded_write` の後に、`[[hooks]]` の `post_edit`（`markdownlint.sh`・`format-file.sh`）を宣言順に呼ぶ。ファイルの書き込みの順番待ち（`withFileMutationQueue`）の
中で行う。整形は黙って済ませ、markdownlint が残した違反（hook が exit 2 で返す警告）だけを結果の末尾に足して
モデルへ返す。失敗しても編集は成功のまま。

### fleet

`/fleet <依頼>`（`~/.pi/agent/prompts/fleet.md`）が、依頼を並列に動かせる作業に分け、`guarded_task`（`worker`）を
1 回の応答に並べて起動させる。指示文は `[pi.commands.fleet]` から作る。pi は 1 つの返答に並んだ tool call を
並列に実行する。`-ne` でもプロンプトテンプレートは読まれる（試験済み）。

### stepback

`/stepback [質問]`（`~/.pi/agent/prompts/stepback.md`）が、質問から具体的な固有名・数値・状況を取り除いた**ステップバック質問**（背景にある原理・概念・上位の問い。1〜3 個）を作って利用者へ示し、先にそれへ答えてから、その答えを根拠に元の質問へ答えさせる
（ステップバック・プロンプティング）。指示文は `[pi.commands.stepback]` から作る。

- **引数を省略した `/stepback`**: 会話の直前の利用者の質問と、それへの直近の回答を対象にし、「この回答をもっと俯瞰して見直す」依頼として扱う。
  直前の回答がどの粒度・前提で答えたかを踏まえてステップバック質問を作り、答え直しでは「直前の回答と何が変わるか」を示す。
  対象の決め方は、`$ARGUMENTS` が空かどうかをモデルが文面で判断するだけで、拡張のコードは無い。直前のやり取りが無いときは、対象を利用者に尋ねて止まる

- 利用者が打ったときだけ展開されるプロンプトテンプレートで、モデルが呼べるツールは作らない。ツールを増やさないので、ガードの判定・伏字化は変わらない
- 確かめるときは読み取りだけにし（状態を変えない）、確かめていないことは「未確認」「推測」と書かせる。元の質問が変更・実行の依頼でも、答え（方針）を出すところまでで止め、作業に進むかは利用者に確かめさせる
- ツール名に依らない文面なので、役割（`reader` など）を問わず使える。配る範囲は `/fleet` と同じ（Unix のフルガード側。Windows は `.chezmoiignore` で `prompts/` ごと除外）
- 試験: `test_pi_harness.py` の `test_stepback_prompt_template_*`（偽のモデルで、引数が `質問:` に入り本文が届くことまで。モデルが実際にどう答えるかは未確認）

### キーバインド

`~/.pi/agent/keybindings.json` は `[pi.keybinds]` の中身そのもの（ファイルごと生成器の持ち物）。今は
`app.interrupt` に Ctrl+C を足し、`app.clear` を外し、Ctrl+D で終了する（今の OpenCode の設定と同じ操作）。

### 共通の指示

`~/.pi/agent/AGENTS.md` は、Claude Code・Codex・Copilot と同じ共通の指示（`agent-instructions.md`）。

### Orca・Zed

- **Orca**: Orca は pi を起動するとき、ステータス表示の拡張を `~/.pi/agent/extensions/orca-agent-status.ts` に
  置く。`pis` は `-ne` で拡張を読まないので、Orca から起動したとき（`ORCA_AGENT_HOOK_PORT` がある）に限り、
  Orca の印（`@orca-managed-pi-extension`）がある拡張だけを `-e` で足す。サンドボックスの内側は `~/.pi/agent` を読めない
  ので使えない（状態表示は出ない）。Orca が `pi` と `pis` のどちらを起動するかは Orca 側の設定による
- **Zed など RPC で起動するクライアント**: 確認は `extension_ui_request` として届き、応えないと永久に待つので、
  TUI 以外では確認に 5 分の期限を付け、期限が来たら拒否する。クライアントが確認の要求（`confirm`）に
  対応していなければ、ask になる操作は拒否される

## サンドボックス

`pis`（標準）は、`pi.py` の `run_sandboxed` が pi を Fence で囲って起動する（`ocs` のコマンドは経由しない。CHG-0023 の段 3c）。
サンドボックスの組み立て・危険な起動場所の拒否・起動前の退避・検査は、OpenCode の隔離起動と共通のモジュール
（`boundary.py`・`backup.py`・`check.py`。[OpenCode 隔離起動](../sandbox/opencode-sandbox.md)）を使い、Fence の設定の書き出しの補助だけ `cli.py` から借りる
（OpenCode の撤去で、共通の部分を中立のモジュールへ移す）。pi だけの部分は `~/.local/share/ocs/pi.py`。
`--no-backup` / `--check` は `run_sandboxed` が解釈するので、pi には渡らない。

| 項目 | 内容 | 理由 |
| --- | --- | --- |
| 設定の置き場 | サンドボックス用の **agent 置き場**を起動ごとに `~/.local/share/pi-sandbox/agent-*` へ作り、`auth.json`・`models-store.json`・`settings.json`・`AGENTS.md`（共通の指示）・`keybindings.json`・`prompts/`（`/fleet`）を写す（`AGENTS.md` などが無いと、サンドボックスの中だけ指示・プロンプトが消える。2026-10-15 に実機の試験で見つけた）。`settings.json`・`trust.json`・`mcp.json`・`AGENTS.md`・`keybindings.json`・`extensions/`・`prompts/` は書き込みを塞ぐ（本物に無いときは空で作る）。`bin/` は本物の `~/.pi/agent/bin`（`fd`・`rg`。読み取りだけ許可済み）を指すリンクにする（pi は `<agent 置き場>/bin` に無いとダウンロードするので、起動のたびに `fd` を取得していた。2026-10-15 に実機で見つけた） | pi は設定と認証を読むときにも隣へ `.lock` を作るので、置き場は書ける必要がある。本物の `~/.pi/agent` を入れると、内側で作られた拡張を外の通常の pi が読む（E4） |
| セッション | `--session-dir` で本物の `~/.pi/agent/sessions/--<作業ディレクトリ>--` だけを開ける | 外の `pi -c` で再開できる（試験済み）。`--session-dir` は渡した場所へそのまま置くので、pi が使う置き場の名前をそろえる |
| 認証 | 写しの中で更新された認証のうち、**有効期限が本物より新しいプロバイダの分だけ**を、終了後に本物へ戻す（pi と同じ `auth.json.lock` を取る。取れなければ戻さない） | OpenAI は OAuth（期限 47 分）で、更新のたびにリフレッシュトークンが入れ替わりうる。写しの中だけで更新すると、本物が失効する |
| 後始末 | pi を子プロセスとして動かし、終了・SIGTERM・SIGHUP（端末を閉じた）のどれでも、認証を戻して置き場を消す。Ctrl-C は子が受ける | `execve` で置き換えると終了後の処理ができず、認証の写しが残る。SIGKILL や電源断では残るので、3 日たった置き場は次の起動が捨てる |
| 判定器 | `PI_HARNESS_BOUNDARY=1` を渡す（判定器はまだ使っていない） | サンドボックスの中の既定は段 5 で決める |
| 設定の出所 | 共有のキーは `[opencode.sandbox]`、pi の追加分は `[pi.sandbox]`（読み取り: フルガード・自作の拡張 4 つ・判定器・`~/.config/agents`・`~/.claude/hooks`・pi 本体） | 段 6 で OpenCode を撤去するとき、共有キーを `[pi.sandbox]` へ移す |
| 作業先ごとの追加 | OpenCode と同じ `.opencode/sandbox.toml` | 名前は段 6 で決める |

### プロキシ必須の環境での通信

ホストにプロキシの環境変数（`HTTPS_PROXY` / `https_proxy` / `HTTP_PROXY` / `http_proxy`）がある機械では、
`pi.py` が起動のあいだだけ、小さな中継（`relay.py`、`pis` と同じ処理のスレッド）を `127.0.0.1` の空きポートで動かす。
変数が無い機械は何も変わらない。
Fence は許可リスト（`allowedDomains`）に当たる通信を直接つなぐので、プロキシが必須の機械では許可済みの宛先にも届かない
（[調査](../../research/agents/corp-proxy-boundary.md)）。

| 項目 | 内容 | 理由 |
| --- | --- | --- |
| 設定の変え方 | Fence へ渡す設定だけ、`allowedDomains` を空にし `defaultAction: "proxy"`・`upstreamProxy: http://127.0.0.1:<中継>` を足す。`deniedDomains` は Fence に残す | Fence の上流プロキシは、許可リストにも拒否リストにも当たらない通信にしか使われない |
| 中継の動き | 許可リストと照合し、当たる宛先だけをプロキシへ `CONNECT` する。当たらなければ 403 を返し、プロキシへは何も送らない | 許可リストの効きを Fence の外へ移しても保つ |
| 通すもの | `CONNECT`（HTTPS）だけ。平文の HTTP は 403 | 平文は 1 本の接続で別の宛先へ続けて送れ、照合をすり抜ける |
| 許可リストの書き方 | Fence と同じ。`*.x` は `x` 自身を含まない。`host:port` も書ける | 切り替えても挙動が変わらないようにする |
| `NO_PROXY` | 当たる宛先はプロキシを通さず直接つなぐ（ホスト名・ドメイン接尾辞・CIDR・`*`） | 内部の宛先へプロキシ越しにつなげない機械がある |
| 認証 | プロキシの URL の `user:pass@` を `Proxy-Authorization: Basic` にする。設定・ログには出さない | Fence の設定は `0600` のファイルに書かれるが、平文を残さない |
| 使わない場合 | 許可リストが空・`*` を含む・プロキシが `https://` など `http://` 以外 | `*` は Fence が直接の通信を許す形で、照合を移す意味が無い。`http://` 以外は Fence も未対応（警告を出して従来どおり） |
| 境界チェック | 元の許可リストで検査先を引く。事前検査の記憶の鍵に「中継の有無」を含める | 中継の有無で同じ記憶を使い回さない |

- **`pis` だけが対象。** OpenCode の `ocs` は `execve` で置き換えるので、中継のスレッドが残らない。`ocs` は撤去予定のため対応しない
- 待ち受けは `127.0.0.1` だけで認証が無い。同じ機械のプロセスは、許可リストの宛先に限ってプロキシ越しに通信できる
- プロキシが NTLM / Kerberos などの認証を要求する場合は未対応（Basic だけ）
- 切り分けは `sh scripts/diagnose-corp-proxy.sh`（何も書き換えない。認証情報は伏せて出力する）

### 拒否リスト型の通信

`[pis.network] mode = "denylist"` のとき、`deny` に入れた宛先**以外の公開宛先**へ、内側から HTTPS でつなげる（許可リスト型は、許可したドメインにしか届かない）。
既定は `allowlist`（従来どおり）。`pis --allowlist` で一時的に戻せる。
経緯と実測は [CHG-0037](../../change/0037-pis-usability-and-telemetry.md)（候補 E1'）。

| 項目 | 内容 | 理由 |
| --- | --- | --- |
| 仕組み | 上の中継（`relay.py`）を、プロキシ必須でない機械でも動かす。Fence へ渡す設定は `allowedDomains: []`・`deniedDomains: <deny>`・`defaultAction: "proxy"`・`upstreamProxy: <中継>`。拒否に当たらない通信は中継が**直接つなぐ** | `deniedDomains` は Fence が hard 403 にする（中継へ届かない）。`allowedDomains: ["*"]` は直接接続を許すので使わない |
| 隔離 | ネットワーク名前空間の隔離は保つ。プロキシを使わない通信（`--noproxy`・直接のソケット）と DNS は、従来どおり内側からは届かない | `*` 方式と違い、拒否のすり抜けではなく「そもそもつながらない」。実測（2026-10-26、Fence 0.1.67） |
| 宛先のアドレス | 中継が名前解決し、結果の**どれか 1 つでも**公開アドレス（`is_global`）でなければ 403。検査したアドレスそのものへつなぐ（再解決しない）。IPv4-mapped は IPv4 として見る。ループバックだけ `allow_loopback` で開けられる（既定は閉） | 拒否リスト型では中継が境界の穴になる（ホストのループバック・LAN・クラウドのメタデータ・ULA・共有アドレス空間）。DNS の細工（公開と内部の混在）も塞ぐ |
| 直接接続 | IPv4 を先に、1 アドレス 4 秒・全体 15 秒で試す | IPv6 が届かない環境で、アドレスごとに長く待って 502 になった（実測。youtube.com で 26 秒） |
| `NO_PROXY` | 安全の判断に使わない（拒否リスト型では無視する） | 中継は常に宛先のアドレスを検査する |
| 通すもの | `CONNECT`（HTTPS）だけ。平文の HTTP は 403 | 方針の「GET は無条件」は、**HTTPS の接続を拒否ドメイン以外へ許す**に読み替える。トンネルの中のメソッドは見えず、POST の制御はネットワークの層ではできない（判定器側の事故防止）。平文を通すには、リクエストごとに宛先を照合する HTTP プロキシが要り、攻撃面が増えるので入れない |
| 拒否の書き方 | `deny` は `host` または `*.host`（`*.x` は `x` 自身を含まない。中継が Fence と同じ規則で照合する）。拒否はドメイン名の照合で、IP リテラルや別名で同じサーバーへつなぐ経路は防げない（事故防止の水準） | 「数サイトを確実に遮断」とは言わない |
| 適用の条件 | **ホストにプロキシの環境変数が無い**（直接つなげる）機械だけ。**Copilot ブローカーが有効**のときだけ（内側へ本物の認証を渡さない前提）。満たさなければ許可リスト型で起動し、注意を 1 行出す | プロキシ必須の機械では、上流が名前を解決するので中継がアドレスを検査できない（`review`） |
| 認証 | 拒否リスト型のときは、`auth.json` から、ブローカーを持たない他のプロバイダーの認証も写さない（空にする） | 任意のホストへ送れるので、内側に本物の認証を残さない（ブローカーのあるものはダミーだけ） |
| `local_ports` | 内側からホストの `127.0.0.1` のこのポートへつなげる（Fence の `allowLocalOutboundPorts`。ブローカーのポートと合わせる） | 内側の `NO_PROXY` は localhost を外すので、`allow_loopback` を真にしても「内側から localhost を読む」にはならない。ホストのローカルのサービスへは、ポートを明示して開ける |
| 設定の検査 | `rules.json` の `network` が壊れていたら起動を拒否する（開く側にも閉じる側にも倒さない）。`mode` は `allowlist` / `denylist` のみ | 設定の破損で境界が緩まないように |
| マシン専用の設定 | **chezmoi 管理外の `~/.config/agents/local.toml`** に書く。`[pis.network]` と、`[pi.sandbox]`（`read`・`network_allow`・`deny_read` の追記だけ。`write`・`protected`・`control_dirs` は受け付けない）、`[pis.broker]`（認証の出どころ・有効と無効を置き換える。PAT の出どころは片方を書くともう片方を消す）。`[pis.network]` では、`deny`・`local_ports` を追記し、`mode`・`allow_loopback` を置き換える。無いキーは警告して無視、型違いや範囲外は生成を止める。共有側の `deny` は消せない | `common.toml.tmpl` を直接直すと apply で上書きされる。`local.toml` は管理外で apply しても残り、`~/.config/agents` は内側から書けない（エージェントが自分で緩められない） |
| 境界チェック | 公開の宛先（`github.com`）が通り、`deny` の先頭が落ちることを確かめる（`deny` が空なら拒否は検査しない）。事前検査の記憶の鍵に `network` を含める | 許可リスト型の検査は「許可外が落ちる」前提で、拒否リスト型には使えない |

- **未確認**: SOCKS（`ALL_PROXY=socks5h`）を優先するクライアントの挙動、大きな転送の速度、実機の `pis` 全体（Fence の起動・ブローカーとの併用）での通し、Windows。
- **残る限界**: 作業ディレクトリの `.env` などは OS の層では読める（`read_deny_globs` は Fence の `denyRead` に渡らない。判定器の層だけが守る）。拒否リスト型ではこれが送信可能になるので、既定にする前に塞ぐ（CHG-0037）。環境変数は除外方式で、名前に `TOKEN` / `SECRET` / `PASSWORD` を含まないものは残る。
- **試験**: `test_relay.py`（アドレスの分類・混在応答・拒否・フォールバック）、`test_pi_network.py`（設定の生成と破損）。実際の Fence での確認は `.tmp/exp-denylist/` の使い捨ての手順（コミットしない）で行った。

### 緩和のゲート

**基準は保守的**（サンドボックス無しの動き: 確認は全部出す）。サンドボックスの内側と**証明できたときだけ**、次の緩和が効く。

| | サンドボックス無し（基準） | サンドボックスの内側（証明済み） |
| --- | --- | --- |
| 日常の shell（どの規則にも当たらず、役割の既定の ask になったもの） | 確認 | 確認なし（`sandboxed: true`） |
| 作業ツリーの外の読み取り・書き込み | 確認 | OS が開けた場所なら allow、外は**理由つきの deny** |
| `[bash] ask`・意味解析の ask・誘導・deny、`git commit`・MCP の確認、秘密の読み取りの deny、伏字化、役割 | そのまま | **変えない** |

- **証明**: 起動したホストが、内側から見えてはいけないファイルと、書けてはいけない場所を用意し、パスを環境変数で渡す（`PI_HARNESS_CANARY_READ` / `PI_HARNESS_CANARY_WRITE`）。
  フルガード（`canary.ts`）が**自分で**読み・書きを試し、読めた・書けた・書き込み先が既にあった（拒否の証明にならない）ときは**起動しない**。通ったときだけ判定器へ `boundary: true` を渡す
- `PI_HARNESS_BOUNDARY=1` は「内側のはず」という期待にすぎない。環境変数だけを立てても、許可の一覧（`PI_HARNESS_ALLOWED`）とカナリアが揃わなければ起動せず、緩和もされない。
  期待していなければ（変数が無ければ）、緩和は一切効かない
- **許可の一覧**（`PI_HARNESS_ALLOWED`）は、起動時に実際に Fence へ渡した `allowRead` / `allowWrite`。判定器は、作業ツリーの外のパスをこれと照合する。
  実際の OS の許可とずれても、OS が拒否するだけで安全側（拒否の理由が判定器と OS で食い違う場合がある）
- **内側へ渡さない環境変数**: 固定の一覧（`GH_TOKEN`・`SSH_AUTH_SOCK`・`AWS_*` など）に加え、名前に `TOKEN`・`SECRET`・`PASSWORD`・`PASSPHRASE` を含むものと `ORCA_PANE_KEY`（Orca が起動時に入れる資格情報）を、パターンで落とす（実機で `ORCA_AGENT_HOOK_TOKEN` が内側に見えたため。2026-10-15）。プロバイダの API キーを環境変数で渡す使い方（`*_API_KEY`）は、今は落とさない（**検索 API の 4 種（`BRAVE_API_KEY`・`EXA_API_KEY`・`TAVILY_API_KEY`・`OPENALEX_API_KEY`）だけは、名前を指定して落とす**。2026-10-25）
- 子エージェントは、同じ環境変数を引き継いだ同じ Fence の中で動き、子もカナリアで確かめる
- **起動前の事前検査**（`ocs --check` と同じ検査。通信・保護対象・秘密の不可視）は、同じ設定・Fence の版・検査スクリプトで合格した記憶（`~/.local/state/opencode-sandbox/preflight/`、7 日）があれば省く。
  **合格だけを覚え**、落ちたら起動しない（`--no-sandbox` を案内）
- フッターのステータス行に「🔒 sandbox」（証明済み）または「⚠ no sandbox」（警告色）を出す。**目印であり、安全の根拠ではない**
- 試験: `test_pi_judge_ts.py`（緩和の範囲）、`test_pi_harness.py`（カナリアが読める・書ける・既にある・自己申告だけ・証明済み）、`test_pi_boundary.py`（事前検査の記憶）

`~/.config/agents`（判定器が `common.toml` を読む）は読めるが書けない。内側から判定の規則を書き換えられない。**その中の検索 API の鍵 `websearch-keys.json` は、`[pi.sandbox] deny_read` で隠す**（内側からは `/dev/null` に見え、読むと許可がない。**`test -r` は真になる**ので、可否の確認は実際に読むこと。実測 2026-10-25: 内側から読むとエラー、ホストでは 201 バイト）。検索は今、内側から使えない（プロバイダーが許可リストに無い）。内側で使うには、ブローカー（[CHG-0033](../../change/0033-sandbox-build-value-assessment.md) の棚卸し）が要る
OpenCode 用の読み取り先（`~/.opencode` など 3 件）も共有キーに入っているので、pi からも読める
（秘密を含まない道具の置き場）。

## pi の設定

`~/.pi/agent/settings.json` のうち次のキーだけを `generate.py --target pi-settings` が持つ（所有の規則。
宣言から外したキーは消す）。ほかのキー（pi 自身が書く `lastChangelogVersion` や、`/settings` で変えた
ほかの設定）は残す。素の `pi` もこの設定を読む。

| キー | 出所 |
| --- | --- |
| `defaultProvider` / `defaultModel` | `[opencode.model]` の `default` 階層（[モデルの割り当て](../agent-config-generation.md#モデルの割り当て)） |
| `defaultThinkingLevel` / `skills` / `enabledModels` | `[pi.settings]`（書いたものだけ） |

今は `defaultThinkingLevel = "medium"`、`skills = ["~/.claude/skills"]`。`~/.agents/skills` は pi が元から読む。

## 置き場

| 実体 | 配置先 | 役割 |
| --- | --- | --- |
| `home/dot_config/pi/harness/index.ts` | `~/.config/pi/harness/index.ts` | 拡張の本体 |
| `home/dot_config/pi/commit-confirm/index.ts` | `~/.config/pi/commit-confirm/index.ts` | 素の pi の `git commit` の確認（[補助](#commit-の確認-素の-pi)）。`settings.json` の `extensions` から読む |
| `home/dot_config/pi/harness/modify_rules.json.py.tmpl` | `~/.config/pi/harness/rules.json` | `generate.py --target pi-harness` が作る。判定器の設定（`judge`: `common.toml` の `[bash]` / `[file]` / `[pi]` と `tables.toml`）・伏字化の規則・シェルへ入れる環境変数・子エージェント・MCP・役割ごとのツール |
| `home/dot_local/bin/executable_pis` | `~/.local/bin/pis` | 起動の入口（Python。`~/.local/share/ocs/pis.py` を絶対パスで読み込む。[起動](#起動)） |
| `home/dot_local/share/ocs/pis.py` | `~/.local/share/ocs/pis.py` | `pis` の本体。引数の解釈・サンドボックス（標準）の引き継ぎ・`--no-sandbox` の素の起動。起動フラグ（`BASE_FLAGS`）と拡張の一覧は、サンドボックスの `pi.py` と共有する。ライブラリは macOS にも置く（`pis` が読むため） |
| `home/dot_local/share/ocs/pi.py` | `~/.local/share/ocs/pi.py` | サンドボックスの pi 用の部分（[サンドボックス](#サンドボックス)） |
| `home/dot_local/share/ocs/relay.py` | `~/.local/share/ocs/relay.py` | プロキシ必須の環境での通信の中継（[プロキシ必須の環境での通信](#プロキシ必須の環境での通信)）。単独の部品で、ほかのモジュールを読まない |
| `home/dot_pi/agent/modify_keybindings.json.py.tmpl`・`AGENTS.md.tmpl`・`prompts/fleet.md.tmpl` | `~/.pi/agent/keybindings.json`・`AGENTS.md`・`prompts/fleet.md` | [ガード以外の機能](#ガード以外の機能) |
| `home/dot_pi/agent/modify_settings.json.py.tmpl` | `~/.pi/agent/settings.json` | `generate.py --target pi-settings` が持ち物のキーだけを書く（[pi の設定](#pi-の設定)） |
| `home/.chezmoitemplates/agent-cli-install.sh.tmpl` の `install_pi` | `~/.pi/agent/install`・`~/bin/pi` または `~/.local/bin/pi`（インストーラーが PATH を見て選ぶ。`pis` は両方と PATH を探す） | pi 本体を公式インストーラーで入れる（[AI CLI の導入](../structure.md#ai-cli-の導入)） |

## 環境変数

| 変数 | 既定 | 意味 |
| --- | --- | --- |
| `PI_HARNESS_ROLE` | `[pi] default_role` | 判定器へ渡す役割（`[pi.profiles]` の名前） |
| `PI_HARNESS_BYPASS` | 無し | `1` なら判定器へ `bypass` を渡す（ask だけを allow にする）。起動時の値で、起動後は [`/bypass`](#bypass-の切り替え) で変える |
| `PI_HARNESS_BOUNDARY` | 無し | `1` なら判定器へ `boundary` を渡す（判定器はまだ使っていない） |
| `PI_HARNESS_CHILD` | 無し | `1` なら子エージェントとして動く（`guarded_task` を登録しない）。フルガードが子を起動するときに付ける |
| `PI_HARNESS_TEST_CHILD_EXT` | 無し | 試験だけが使う。子にも読ませる拡張（偽のモデル）のパス |

## しくみ

| 項目 | 内容 | 理由 |
| --- | --- | --- |
| ツール | `guarded_bash` / `guarded_read` / `guarded_edit` / `guarded_write` / `guarded_grep` / `guarded_find` / `guarded_ls`。中身は pi の組み込みの定義。**役割の `tools` に無いものは登録しない**（モデルに見せない。判定は判定器が別に行う）。役割が `rules.json` に無ければ何も登録しない | **組み込みと同じ名前にしない。** `/reload` でフルガードが抜けると、直前に有効だったツールの名前が組み込みの定義に解決され、判定なしで動く（E1）。別名ならツールが 0 個になる |
| 判定 | `tool_call` で判定器を呼ぶ。deny は止め、ask は確認画面を出す（UI が無ければ拒否）。**最終の判定は各ツールの `execute()` の中**で行う | `tool_call` の後に別の拡張が入力を書き換えても止めるため（E1）。`execute()` は、`tool_call` のときと同じ入力なら判定を使い回し、違えば判定し直す |
| 判定器の異常 | 設定が壊れて判定に失敗した・形の正しくない応答は deny（判定器は同じプロセスで動き、プロセスの起動に失敗することは無い） | 空の応答を allow と読まない |
| 確認 | 1 件ずつ順に出す | TUI の確認画面は 1 枠を共有し、後の確認が先の確認を置き換える。codemode の中で並べた呼び出しで、先の確認が永久に止まった（E3） |
| 伏字化 | `guarded_bash` の `execute()` の中で、途中経過・最終結果・長い出力の退避ファイルを伏せる。伏せるのは `content`・`structuredContent`・`details`。フルガードが持たないツール（MCP など）は `tool_result` で、例外を投げずに結果ごと差し替える | `details` はモデルへ送られないが、セッションと画面に残る（`details.truncation.content` に生の出力。E3）。`tool_result` の例外は無視されて生の結果が残る |
| 出力ごと伏せる | 保護対象のパス（`[file] read_deny_globs` から作る）を参照したコマンドは、**実行せず**、出力を全部伏せた結果を返す | OpenCode の guide plugin と同じ（[shell 出力の伏字化](../agent-config-generation.md#shell-出力の伏字化)） |
| read などは伏せない | `guarded_read` などの結果には伏字化を掛けない | 伏せた本文を元に edit されると、ファイルへ伏字が書き込まれる |
| 圧縮 | `session_before_compact` で、`guarded_read` / `guarded_edit` / `guarded_write` が触ったファイルを圧縮のファイルの一覧に足す | pi の既定の圧縮は `read` / `edit` / `write` の名前でしか拾わない（E2） |
| シェルの環境変数 | `[agent_env]` を、未設定のときだけ bash の環境へ入れる | git の入力待ちを防ぐ（[shell ツールの環境変数](../agent-config-generation.md#shell-ツールの環境変数)） |
| `rules.json` | 読めない・形が違うときは、拡張の読み込みごと失敗させる | 起動は止まり、`/reload` ではツールが無くなる（どちらも判定なしでは動かない） |

## 子エージェント

`[pi.agents.<名前>]` に宣言し、親の `guarded_task` ツールで起動する。子は同じフルガードを付けた別の pi プロセスで、
**RPC モード**（`--mode rpc --no-session --no-approve -nbt -ne -e builtin:mcp -e <フルガード>`。`pis` と同じ保護条件）で
動かし、親の拡張が job として保持する（`children.ts`）。判定は子のフルガードが子の役割で行う。

| キー | 意味 |
| --- | --- |
| `profile` | 子の役割（`[pi.profiles]` の名前）。`task` を持つ役割は使えない（入れ子にしない） |
| `tier` | モデルの階層。今は `[opencode.model.tier.<プロバイダ>]` から引き、`#variant` を pi の思考の強さ（`:medium` など）に読み替える。無ければ親と同じモデル |
| `inherit_bypass` | 真なら、親が bypass のとき子も bypass で動く。ask に `git commit` などが残る役割には付けない |
| `description` / `system` | 親のツールの説明に出す説明と、子のシステムプロンプトに足す指示（`--append-system-prompt`） |

今の宣言（`common.toml.tmpl`）:

| 名前 | 役割 | 階層 | bypass を継ぐ | 今の OpenCode での相当 |
| --- | --- | --- | --- | --- |
| `explore` | `explorer`（`reader` + `wc` と読み取り専用の git） | 親と同じ | 継ぐ | `explore` |
| `review` | `explorer`（`explore` と同じ） | `second_opinion` | 継ぐ | `review` |
| `commit` | `committer` | `routine` | 継がない | `commit` |
| `worker` | `worker` | `worker` | 継ぐ | `fleet-worker` / `bypass-fleet-worker` |

`explore` に `tier` を付けていないのは、**確認した上での現状**（2026-10-09）。`tier` が無いと生成される `model` が
`null` になり、フルガードは親の現在のモデル（`ctx.model`）で子を起動する（`index.ts` の `agent.model ??`）。
親が `default` のままなら Copilot は `claude-sonnet-5.5`、Bedrock は `us.anthropic.claude-sonnet-5-5` で、
`/model` で親を変えると `explore` も追従する。

- `routine` にする案: 読むだけの探索なので軽くてよいが、今の Copilot は `routine` も `default` も
  `claude-sonnet-5.5` で差が出ない。差が出るのは Bedrock の `#low` だけ。**今は変えない**
- 未確認: 子へ `settings.json` の `defaultThinkingLevel`（今は `medium`）が実際に効いているか

- 子は会話を見られない。**転写や差分の全文を渡すのではなく、意図と問いを渡す**（[review への依頼の書き方](#review-への依頼の書き方)）
- **モデルに存在を知らせる**: 自作ツールは `promptSnippet` が無いと system prompt の「Available tools」に載らず、
  モデルは関数定義の一覧に埋もれた `guarded_task` に気付きにくい（実際に「子が無い」と誤認した）。
  `registerTask` は `promptSnippet` と、`review` を使う場面の `promptGuidelines` を付ける。
  Windows の `subagents` 拡張の `task` も同じ（`todo` / `activity` も同様に対処済み）。試験は `test_task_tool_is_listed_in_the_system_prompt`
- **子の結果**: 子の RPC のイベントから、承認されなかった呼び出し（理由が `not approved:` で始まる。
  フルガードが付ける）・ほかのツールのエラー・最後の返答を拾う。承認されなかった呼び出しがあれば
  `blocked`（承認待ちで未完了）として、親のツールの結果をエラーにする。RPC の子は UI があるものとして確認要求
  （`extension_ui_request` の `confirm` / `select` / `input` / `editor`）を出すので、親は**即座に `cancelled`
  を返す**（親モデルは承認できない）。ask は bypass を継がない限り `blocked` になる
- 親を中断すると、子をプロセスグループごと止める
- 子の返答の本文にも伏字化を掛け、その後に 20000 文字で切り詰める
- 起動の前に、親の判定器で `task` を判定する（`tool_call` と `execute()` の両方）

### review への依頼の書き方

`review` は、親とは別系統のモデルに、親の判断を step back して検証させる役。**親が全部書く方式だと、親の解釈と取捨選択が混ざる**
（不利な事実が落ちる・前提ごと引き継ぐ）ので、親は意図と問いを書き、客観的な事実は子が自分で取りに行く。

| 親が書く | 子が自分で取る |
| --- | --- |
| 目的と制約 / 確かめたことと未確認のこと / 退けた案と理由 / 暫定の結論（最後に「疑う対象」と明記）/ 聞きたいこと | 差分（`git diff`・`git log`・`git show`）・対象のファイル・関連する `docs/` |

- `review` を `explorer` 役にしたのは、差分を親が貼らずに済ませるため（2026-10-21、利用者の判断）。以前は `reader` で `git` を使えず、差分を依頼文へ入れる必要があった
- 子の指示（`[pi.agents.review] system`）は、先に目的だけから自分の案を考え、そのあと親の結論と比べる順にして、anchoring を避ける。親の「確認済み」は検証対象で、依頼文に無い関連箇所と不利な事実も探させる。材料が足りなければ推測で埋めず、何があれば判断できるかを返させる
- 親への指示は、フルガードの `promptGuidelines`（`harness/index.ts`）と `AGENTS.md` の「別モデルへの相談」に書いた。Windows の素の `pi` は `git` が無いので、差分は依頼文へ貼る（`plain_system`）
- **既知の限界**: `git <サブコマンド> -- <パス>`（`git diff -- <パス>`・`git show <rev> -- <パス>`・`git log -- <パス>`）は通る。正規化後の先頭語が `git` のときだけ、`--` の後ろを別コマンドとして抽出しないため（`judge/normalize.ts`・`command_policy.py`。抽出を抑えるだけで、deny / ask / allow の判定は従来どおりコマンド全体に掛かる）。それ以外のコマンドの `--` の後ろ（`mise exec -- CMD`・`kubectl exec p -- git push` など）は従来どおり別コマンドとして評価される。試験は `test_double_dash_decisions`（`test_decide.py`）
- **未確認**: 実際のモデルで、依頼文の型が守られ、`review` の指摘の質が変わるか（試験は設定の整合と、子が `wc` と読み取り専用の git を使えることまで）

### 子を保持して追加依頼する（job）

`guarded_task` は 1 つのツールで 3 形式を持つ。形の排他は、スキーマではなく **`execute()` が確かめる**
（tool の最上位に `anyOf` を置くと拒む提供元がある。判定器は名前と役割だけを見る）。
**`false` / `""` / `[]` / `0` / `null` は「指定なし」として扱う**。厳格なスキーマのモデル（`gpt-6-sol`）は、使わない省略可能な引数もこれらで埋めて送る。
`agent` はスキーマがエージェント名の列挙なので、`""` も列挙に加えている（無いと `execute()` に届く前に pi の検証で拒まれる）。
この扱いが無いと `` `list` must be true `` で 5 回連続で拒まれた（[実験 B1 の F5](../../research/agents/pi-bg-experiments.md)。試験は `test_task_input_ignores_unused_arguments_filled_with_empty_values` と
`test_task_input_forms_accept_empty_fillers_but_still_reject_real_conflicts`）。

| 形式 | 入力 | 動き |
| --- | --- | --- |
| 新規 | `{agent, task, keep?}` | 子を起動して 1 往復を待つ。`keep` が無ければ完了で子を止める（従来と同じ）。`keep=true` なら idle で残し、`jobId` を返す |
| 追加依頼 | `{jobId, task}` | 残した子へ、履歴を保ったまま次の依頼を送る。`agent` `keep` `close` は付けられない |
| 停止 | `{jobId, close:true}` | 子を止める（冪等。無ければ「既に無い」を成功で返す） |

- **往復の終わり**は `agent_settled`（自動リトライ・圧縮の回復まで終えた境界）。`prompt` の応答の `disposition` が
  `started` でなければ失敗にする（前回の答えを返さない）。終了コードは使わない
- **最終状態**の優先順: 親の停止・中断・時間切れ（`closed` / `limit`）→ `not approved:` があれば `blocked` →
  最後の assistant の `stopReason`（`stop` / `toolUse` は `done`、`length` `error` `aborted` と未知の値・
  assistant 無しは `failed`）。途中のツールエラーはモデルが回復して `done` なら失敗にせず、件数だけ返す
- `done` 以外になった job は、その場で止めて**再利用しない**（未実行の操作を完了済みとみなした履歴から続けないため）
- 同じ job への依頼は 1 つずつ。`running` 中の追加依頼は待たせず `busy` で断る。`running` 中の `close` は即停止し、
  待っていた呼び出しには `closed` を返す。`jobId → 所有確認 → running` は await の前に同期で確定する
  （並列のツール呼び出しで競合しないため。`guarded_task` を逐次実行にしないこと）
- 生かしておく子の上限は 4（`running` も含む）。上限では追い出さず、新しい起動を断って jobId の一覧を返す。
  枠は spawn の前に同期で確保する。1 往復の待機は 15 分まで（超えたら `limit` で止める）
- job は起動時の cwd と役割を持ち、別の cwd・役割からの追加依頼は断る。`jobId` は乱数だが認証手段ではなく、
  所有の確認が本体
- **止まる契機**: `close`・`keep` 無しの完了・`done` 以外・セッションの終了と切り替えと `/reload`（`session_shutdown`）・
  `/bypass` の切り替え（起動時の bypass を持ち越させない）・親プロセスの終了。TTL は無い
  （忘れた job は上限のエラーの一覧で気付く）。止め方は stdin を閉じ、3 秒で終わらなければプロセスグループを SIGKILL
- モデルへは `promptGuidelines` で「後続が見込まれるときだけ `keep`」「追加依頼は返った `jobId` にだけ」
  「終わったら `close`」「消えたら要約を添えて新規にやり直す」を伝える
- 子が質問して止まり、回答で再開する形は**未対応**。子から親への通信は無い（結果の返却と、バックグラウンドの完了通知だけ）

### 子の操作: バックグラウンド・状態・steer・並列・モデル・ToDo

`guarded_task` に、引き続き 1 つのツールで次の形を足した（排他は `execute()` で確かめる。[調査 P2](../../research/agents/pi-public-extensions-survey.md)）。
見た目はフッター 1 行とテキストだけ。ウィジェットは作らない。

| 形 | 入力 | 動き |
| --- | --- | --- |
| バックグラウンド | `{agent, task, background: true}`（追加依頼も同じ） | ID をすぐ返す。完了は `pi.sendMessage`（`triggerTurn`・`followUp`）で親へ知らせ、ターンが再開する（`activity` の `bg_run` と同じ方式）。親の中断には縛られない。`keep` なしなら完了で子を止める |
| 状態 | `{jobId, status: true}` / `{list: true}` | 状態・経過時間・最後のツール・呼び出し数・トークン（子の assistant メッセージの `usage` の合計） |
| steer | `{jobId, steer: "..."}` | RPC の `steer`。子の今のターンのツール呼び出しが終わったあと、次の LLM 呼び出しの前に届く |
| abort | `{jobId, abort: true}` | RPC の `abort`。**今の往復だけ**止め、子は残す（状態 `aborted`。履歴は途中までで、`keep` なら追加依頼で続けられる）。`done` 以外で job を止める原則の例外（親が明示した中断だから） |
| 並列 | `{tasks: [{agent, task, model?}, ...]}`（最大 12） | 上限 4 は維持し、超えた分は断らず空きを待つ。結果は順に連結。上限は「生かしておく子」を数えるので、空きが 0 なら断る |
| モデル | `model: "provider/id"` | 選べるのは、宣言済みの役割が使うモデルと、親と同じモデルだけ（階層の範囲内） |
| ToDo | `{agent, task, todo: <id>}` | 子が `done` で終わればその項目を `done` にし、結果を `note` へ。それ以外はメモだけ（`todo` 拡張が `globalThis.__piTodoUpdate` を置く）。**`todo` ツールが有効な実行では、新しい子を起動する単発の形（`explore` / `review` / `worker`）に `todo` が必須**で、無いと `todo is required for <agent>: add a todo item for this work and pass its id as \`todo\`` を `error`で返し、子は起動しない（`commit`は任意。追加依頼・状態・steer・abort・close と、`tasks`の並列は対象外。項目の存在は確かめず、`todo`は整数かだけをスキーマで見る）。`todo` ツールが無い実行（todo 拡張を読み込まない試験など）では要求しない。試験は `test_task_requires_todo_*` ほか（未実行） |

- **結果の形**: 見出し行（`child <役割>: <状態> [時間, 呼び出し数, トークン, 費用]`）→ 承認待ち → 警告（子のツールエラー。同じものは 1 つにし、5 件まで）→ job → `answer:` の順。
  エラーを答えに混ぜない
- **結果の保持と通知の見出し**: 完了した往復の結果（redact 済みの全文）は、30 分・最大 20 件（`FINISHED_TTL_MS`・`MAX_FINISHED`）だけ親のプロセス内に残し、`{jobId, status: true}` で引ける（`keep` なしで自動で消えた子も対象。引くときの切り詰めは 2 万字で、切ったことを示す）。`close` した job の分は消える。
  バックグラウンドの完了通知（`child-finished`）の見出しには `(#通番 起動 HH:MM:SS / 完了 HH:MM:SS)` を足す（通番は pi セッション内で 1 から）。結果の全文は cwd 基準の `.tmp/subagents/<通番>-<job id>.md` にも書き、通知の末尾に `結果の全文: <パス>` を 1 行で示す。
  保存先の `.tmp/subagents` がシンボリックリンクなら書かず、ファイルは排他的に作る（既存なら書かずに警告）。保存のたびに、`.tmp/subagents` の `*.md` を新しい順に 50 件だけ残し、更新時刻が 7 日より古いものを消す（失敗は警告しない）。`close` した job の結果は、往復の完了が遅れて届いても再び登録しない。生きた job が無いときの `close` は、保持結果の cwd と役割が同じときだけ消し、違うときは「存在しない」と同じ応答にする。batch の見出しに載せる依頼文の先頭は伏字化してから切り、保存ファイルは各子の全文を 2 万字まで書く。警告文に入れる例外の message も伏字化する。
   完了した往復の結果には、答えがあるとき、job 行の前に `- calls: <ツール名×件数>` の 1 行（事実。`guarded_` を除き、多い順）を足す。ツール名だけを数え、引数と出力は残さない（上限 500 件）。答えに標準形の見出し（結論・根拠・未確認・次の候補）が欠けていれば、tool errors の警告の後に `format check (...)` と `- missing: ...` を足す。見出しは行頭の記号を無視した前方一致で見る。警告にとどめ、結果の本文は変えず、拒否もしない。「通った」などの主張語の検出は、実例のほとんどが否定・引用・仮定で誤検出が多いため入れない（`audit.ts`）。
  既知の限界: セッションをまたいだ参照の境界は cwd と役割までで、セッション識別子は無い。
  保存・通知の配信・ToDo 反映の失敗は握りつぶさず、UI があれば `ctx.ui.notify`、無ければ stderr に警告する（通知は止めない）。試験は `test_finished_result_can_be_read_with_status_until_the_job_is_closed` / `test_background_notification_has_sequence_and_times_and_the_result_is_saved`（親が実行して通った。2026-10-22）
- **時間の上限**: 1 往復は 15 分。上限の 80% で、子へ steer で「まとめに入れ」を送る（途中の結果を残すため。送ったかの直接の試験は無い）
- **利用者コマンド**: `/agents`（一覧）、`/agent <名前> <依頼>`（子を直接起動。完了はチャットに表示するだけで、モデルのターンは起こさない）。モデルは呼べない
- **フッター**: `activity` が、動いている子が 3 件以下なら `🤖 explore 12s, review 40s`、それより多ければ件数
- **やらないこと**: プロジェクト内の定義ファイルからの役割（`--no-approve` と衝突）、子から子（入れ子）
- **worktree 隔離は実装済み**: `guarded_task` の `isolation: "worktree"`（opt-in。単独の新規 `worker` のみ）。仕様は [CHG-0029](../../change/0029-worktree-isolation.md)。S5（実機の通し確認）の後に、この文書へ移す

### worktree 隔離の場所と承認

- **場所**: `<リポジトリ根>/.tmp/worktrees/pi-agent-<job id>`。`.tmp/` が `.gitignore` で除外されていなければ起動を拒否する。回収は `refs/pi-agent/<job id>` と `.tmp/subagents/<通番>-<job id>.patch`、記録は `.tmp/subagents/worktrees/`。掃除・回収のやり直しは利用者専用の `/worktrees`（モデルは呼べない）
- **隔離の worktree の作成と回収は、ハーネスが内部で `git` を実行する**（判定器を通らない）。子の書込範囲は Landlock で、その worktree・共有 `.git` の `worktrees/pi-agent-<id>`・`objects` などに狭める
- **親（`pi` 本体）が worktree のファイルを編集するときの承認**は、通常の書き込みと同じ。そこが作業ツリーの中（`cwd` の実体パスの下。`decide.py` の `_inside`。`.tmp/worktrees/…` を含む）なら allow、外（`~/worktrees/…` など）なら ask（境界つきでは、開けていない場所は deny）
- **親が `git worktree` を `bash` で直接実行したとき**（2026-10-26、`decide.py` を `implementer` で実行して確認）: `add` / `list` / `prune` は規則に当たらず ask（`source: default`。`pis` で境界が証明されたセッションでは、[手順 4'](pi-decide.md) の緩和で allow）。`remove` は `[bash] deny`（作業内容を失うため）

## MCP

> **`pis` では、`exposure` が `codemode`（既定）・`deferred` のサーバのツールは、モデルから呼べない。**
> `-ne` が組み込みの拡張（`builtin:codemode`・`builtin:tool-search`）も外すため、`Tool … not found` になる
> （2026-10-11、偽のモデルで実測。[E6](../../research/agents/pi-extension-under-harness.md#記録-e6--2026-10-11)）。
> **対策済み**: `[[mcp]]` の `exposure` を省略すると、生成器（`pi_mcp_servers`）が `direct` を出す
> （[仕様](../agent-config-generation.md#mcp-サーバ)）。`codemode` を使いたいときは `-e builtin:codemode` を足す（+680 トークン）。
> 実機の `pis`（Unix）では未確認

`[[mcp]]` のうち `clis` に `pi` を含むものを、フルガードが起動のたびに `registerMcpServer` で登録する。
フルガードが抜ければ登録も消える。MCP のツール（`mcp__<サーバ>__<ツール>`）は、実装役の `tools` の
`mcp__*` に当たり、規則が無いので既定（確認）になる。読み取り役などには出ない。

**`~/.pi/agent/mcp.json` には書かない。** そこのサーバはフルガードと関係なく繋がるので、フルガードが
抜けたときに判定なしで残る（`pi mcp add` はそこへ書く）。

## pi の内部の挙動に頼る点

公開の約束ではないので、pi の版を上げたら `test/agents/test_pi_harness.py` を回して確かめる。

1. `/reload` は、直前に有効だったツールを名前で有効にし直す（`test_reload_without_harness_leaves_no_tools`）
2. `session_before_compact` の `preparation` が、既定の要約にそのまま渡る
3. bash の `details.truncation.content` に生の出力が入る（`test_bash_output_is_redacted_everywhere`）
4. 設定と認証を読むときにも agent 置き場に `.lock` を作る（サンドボックスで効く。CHG-0020 の段 4）

## 試験

`test/agents/test_pi_harness.py`。偽のモデル（`test/agents/pi/faux.ts`）で、決まった tool call を
通信なしに出させる。pi が無い環境では skip する。

- 宣言されるツールが `guarded_*` だけ
- 判定（allow・deny・UI の無い ask）・bypass・読み取り役・判定器の異常・`rules.json` の欠落
- `/reload` でフルガードが抜けるとツールが 0 個になる（構文エラーと削除の 2 通り）
- 判定の後に別の拡張（`test/agents/pi/mutator.ts`）が入力を書き換えても実行しない
- 伏字化（JSON のイベント・退避ファイルに生の秘密が残らない）と、保護対象のパスを参照したコマンド
- 子エージェント: 入れ子にならない・読み取り役に bash を出さない・子の ask が `blocked` で返る・
  bypass を継ぐ・役割の `shell_deny` が bypass でも効く・`commit` が確認なしで git を読む・
  `keep` した子が履歴を保って追加依頼に答える・入力 3 形式の排他・上限 4・`busy`・時間切れ・親より長生きしない
- MCP: フルガードから登録され、実装役では確認になる（`test_pi_harness.py`）
- サンドボックス（`test_pi_boundary.py`）: 生成・サンドボックス用の置き場・セッションの置き場・認証の戻し（新しい分だけ・ロック・壊れた写し）・
  実際の Fence でのサンドボックスチェック（Fence・bwrap・pi が無ければ skip）
- プロキシ越しの中継（`test_relay.py`）: 許可リスト・`NO_PROXY`・プロキシの URL の読み方、許可した宛先だけが上流へ届く・許可外と平文 HTTP は上流へ何も送らない・認証ヘッダ・上流の拒否が 502 になる、設定が必要なときだけ変わる
- 誘導: `cat` が read ツールへの案内で止まる
- 圧縮（指示が履歴の要約の依頼に入る・ファイルの一覧）、`git commit` の確認の本文（RPC で確認の要求を受け取る。期限が付く）、
  整形（ruff・markdownlint）、`/fleet` の展開、キーバインドと共通の指示の生成、Orca の拡張の読み込み条件

## 実機で確認する項目

自動試験では確かめられず、実機の pi で見るもの。確かめたらチェックを入れ、結果と日付を添える。
すべて `chezmoi apply` して新しいセッションで確かめる。

- [ ] **ジョブ終了のフィードバック**（`activity`、`20507a0`）: 2026-10-20 に実機（`pis`、このセッション）で、アイドル時の自動再開と、
  作業中に終わった分がそのターンの後に届くことを確認した。さらに同日、RPC の使い捨てセッション（実モデル 4 つ、[B1](../../research/agents/pi-bg-experiments.md)）で、
  `bg_kill` で止めたときに再開しないこと、完了のたびに次を起動する連鎖が 3 回で止まること（無限ループにならない）を確認した。
  **未確認**: TUI での見え方、承認を拒否したとき、Windows。
  元の確認項目: `bg_run` で `sleep 5` を起動して応答を終えさせる。アイドルのまま LLM が自動で再開するか。作業中に終わったときはそのターン後に届くか。
  `bg_kill` で止めたときは再開しないか。終了メッセージが画面に出て、ログ末尾が入っているか
- [ ] **フッター表示**（`activity`）: TUI で `🤖 N subagents / ⚙️ N jobs` が出て、どちも 0 になると消えるか
- [ ] **圧縮（実際のモデル。pi・既定モデルの更新のたびと、定期的に）**: `uv run --with pytest --with pyyaml --no-project python3 scripts/pi-harness-spike/compact-real.py`
  （使い捨ての作業場所で、実際のモデルへ `/compact` をかけ、**既定の圧縮に落ちた警告が無いか**を見る。`COMPACTS=2` で 2 回目も。
  `scripts/pi-harness-spike/compact-matrix.sh` はモデルと思考レベルの組を順に回す）。偽のモデルは、実モデルが拒む指定を再現できない。
  2026-10-20: `claude-sonnet-5.5`（`low`・`medium`・`high`・`off`）、`claude-haiku-5.5`、`gemini-3.8-flash`、`grok-4.7`、2 回続けて、で警告なしを確認。`gpt-5.5` は Copilot 側で利用不可で未試験
- [ ] **`pis` の下の `bg_run`**: 確認画面が出るか。deny のコマンドが始まらないか
- [ ] **Windows の `taskkill`**: `bg_kill` でプロセスの木ごと止まるか
- [ ] **`review` のモデル**: `guarded_task` の `review` が実際に親と違うモデル（Copilot なら `gpt-6-sol`）で
  動いているか。子に聞いても答えられないので、`pi -p --model` の直接呼び出しと見比べるか、
  子の一覧（`__piChildren` の `model`）を見る
- [ ] **「別モデルに聞いて」の指示**（`d9085e2`）: 実際に `review` を先に使い、名指しのときだけ CLI を呼ぶか。
  使う前にどちらにしたかと理由を伝えるか
- [ ] **Bedrock のモデル ID**: 子エージェントの階層のモデル ID が pi でそのまま通るか（下の「未対応」と同じ）
- [ ] **スキルの一覧とモデルの自動選択**（`index.ts` の `before_agent_start`）: `pis` で、システムプロンプトにスキルの一覧が載り、
  description に合う依頼でモデルが `guarded_read` でスキルを読むか（偽のモデルでは、プロンプトに載るところまで）
- [ ] **`.agents/skills` の読み込みと `/reload`**: 作業先の `.agents/skills/<名前>/` が `pis` で読まれ（`/skill:<名前>`）、
  起動後に足したスキルが `/reload` で出るか（tmux の TUI で `--skill` の追加は確認済み。`pis` 越しは未確認）
- [ ] **子の steer / abort の実機**: 実際のモデルの子に `steer` を送って方針が変わるか、`abort` のあと `keep` の子へ追加依頼で続けられるか
  （偽のモデルでは、`steer` が追加の返答を起こし、`abort` が `aborted` を返すところまで）
- [ ] **子の進捗の表示**: TUI のフッターに `🤖 explore 12s` の形で出て、`/agents` と `/agent <名前> <依頼>` が動くか
  （RPC のイベントでの確認まで。TUI の見た目は未確認）
- [ ] **時間上限の手前の「まとめに入れ」**（`WRAP_UP_MESSAGE`）: 実際に長い子で、上限の 80% で送られて、途中の結果が返るか（試験は無い）
- [ ] **`todo` のリマインド**: 実際のモデルで、`in_progress` を残して応答を終えたときに 1 回だけ促され、無限に続かないか
- [ ] **`ask` の TUI パネル**: tmux と偽のモデルで、表示・行内の自由記述・複数選択を確かめた（2026-10-20）。未確認: 狭い端末・Esc と時間切れ・IME の候補窓の位置。RPC の複数選択はカーソルが戻るのを直していない（`select` に初期位置の指定が無い）
- [ ] **`ask` の実機**: TUI の選択画面の見え方、実際のモデルが「分岐のときだけ・独立した質問は 1 回で」使うか、使いすぎないか。Windows。待ち上限 5 分の妥当性（試験は RPC の応答まで）

## 未対応

- 子エージェントの階層のモデルは、Copilot で確かめただけ。Bedrock のモデル ID が pi でそのまま通るかは未確認
- サンドボックスの中での判定の変え方（`boundary`。段 5）、Windows・macOS のサンドボックス
- 判定 1 回に 0.1 秒ほどかかる（Python の起動）。`tool_call` と `execute()` で同じ入力なら 1 回にしている
