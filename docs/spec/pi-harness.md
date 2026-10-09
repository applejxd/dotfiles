# pi のハーネス

pi（earendil-works/pi）の拡張として、ツールの実行を判定 API（[`decide`](pi-decide.md)）に通す仕組み。
OpenCode のハーネス（permission の生成・guide plugin）の後継で、移行の計画と経緯は
[CHG-0020](../change/0020-pi-migration.md)、設計の根拠になった試作の観測は
[pi のハーネスの試作](../research/agents/pi-harness-spike.md)（E1〜E4）。

> **位置づけ**: ハーネスは `pis` で起動したときだけ効く。**Orca と Zed が呼ぶ素の `pi` は、ハーネス無しで動く**
> （利用者の判断。保護が要る作業は `pis` か `pis --boundary` で起動する）。`pis` は利用者が自分で起動するとき用で、
> 優先度は低い（[CHG-0020](../change/0020-pi-migration.md)）。

## 起動

```bash
pis                 # 実装役で起動する
pis --bypass        # 確認 (ask) を確認なしで通す。deny と誘導は効く
pis --role reader   # 役割を選ぶ ([pi.profiles] の名前)
pis --boundary      # Fence で囲って起動する (Ubuntu / WSL のみ。境界を参照)
pis -c              # pi の引数はそのまま渡る (例: 直前のセッションを続ける)
```

`pis`（`~/.local/bin/pis`）は次の形で pi を起動する。素の `pi` はハーネス無しで動くので、普段使いの切り替え
（CHG-0020 の段 6）までは `pis` を使う。

```bash
pi --no-approve -nbt -ne -e builtin:mcp -e ~/.config/pi/harness …
```

- `--no-approve`: 作業先の `.pi/`（MCP・設定・skills）を読まない（project trust を拒否する）。
  `AGENTS.md` は読む
- `-nbt`（`--no-builtin-tools`）: 組み込みのツールを使わない。ツールはハーネスが登録したものだけになる
- `-ne`（`--no-extensions`）: ほかの拡張を読まない。判定の後に入力を書き換える拡張を入れないため
- `-e builtin:mcp`: `-ne` で外れる組み込みの MCP 対応だけを戻す。サーバはハーネスが登録する（[MCP](#mcp)）
- ハーネス（`index.ts` と `rules.json`）が無い、または `~/.pi/agent/mcp.json` にサーバがあるときは起動しない
- 子エージェントの印（`PI_HARNESS_CHILD`）など、外から入った内部の環境変数は外す

## Windows

Windows（PowerShell）では**素の `pi` だけ**を使う。ハーネス・`pis`・境界は Unix だけ（判定器が bash の hook と
Fence に依る。Windows 版は未着手で、優先度は低い）。

| 配るもの | 方法 |
| --- | --- |
| pi 本体 | `314_agent_cli.ps1` が `npm install -g --ignore-scripts @earendil-works/pi-coding-agent`。公式の `install.ps1` は Node.js・Git Bash・PATH の確認を `Read-Host` で聞き、apply では答えられないので使わない。Node.js 22.19 以上が要る |
| `~/.pi/agent/settings.json`・`keybindings.json`・`AGENTS.md` | Unix と同じ（`.chezmoiignore` で戻している） |
| `/fleet`（`prompts/`） | **配らない**。`guarded_task` はハーネスが登録するので、素の `pi` では働かない |

- pi の `bash` ツールと `!` は Git Bash を使う（Git for Windows が要る。無ければ pi が探した場所を示す）。
  PowerShell をモデルに使わせるなら `defaultTools` を変える（[Run Pi on Windows](https://pi.dev/docs/windows)）。
  今は管理していない
- 素の `pi` なので、権限・秘密の保護は効かない（Orca・Zed と同じ。[位置づけ](#起動)）
- Windows 実機では未検証（WSL からは `chezmoi` の描画と静的な試験だけ）

## ハーネス以外の機能

OpenCode のハーネスにあった機能のうち、pi へ移したもの。仕分けと経緯は
[CHG-0020](../change/0020-pi-migration.md#段-5-の仕分け2026-10-09)。

### 圧縮（旧 checkpoint）

`session_before_compact` で、圧縮の要約の依頼に**引き継ぎの指示**（Next Steps は手順と合格条件まで書く・
略語を展開する・未作成の文書は「未作成」と書く・制約と却下済みの方針を残す）を足す。pi の要約はセッションに
残り、`pi -c` で再開しても消えないので、外部ファイル・skill・注入の印は作らない。

- `compact()` を `ctx.modelRegistry.streamSimple` 経由で呼ぶ。認証の解決結果の `baseUrl` をモデルへ反映する
  （Copilot はトークンごとに違う。pi 自身も同じ。反映しないと 401 になった）
- 失敗したら標準エラーへ理由を出して、pi の既定の圧縮に任せる（指示は補助で、圧縮は止めない）
- 指示は履歴の要約にだけ入る。分割されたターンの前半の要約（`Turn Context`）には入らない（pi の仕様）
- 別名のツールで触ったファイルは、これまでどおり要約のファイルの一覧に足す

### `git commit` の確認

`git commit -m …` の確認の本文に、件名・本文・追加するパスを出す。OpenCode の guide plugin と同じ純関数
（`~/.config/opencode/guide-plugin/commit-message.js`）を取り込み、表示の幅と行数は
`[opencode.ask_description.commit]` を使う。読み込めなくても出さないだけでハーネスは止めない。
段 6 で OpenCode を外すときに、`commit-message.js` をハーネスの置き場へ移す。

### 整形

`guarded_edit` / `guarded_write` の後に、`[[hooks]]` の PostToolUse（`markdownlint.sh`・`format-file.sh`。
Claude / Copilot と同じスクリプト）を宣言順に呼ぶ。ファイルの書き込みの順番待ち（`withFileMutationQueue`）の
中で行う。整形は黙って済ませ、markdownlint が残した違反（hook が exit 2 で返す警告）だけを結果の末尾に足して
モデルへ返す。失敗しても編集は成功のまま。

### fleet

`/fleet <依頼>`（`~/.pi/agent/prompts/fleet.md`）が、依頼を並列に動かせる作業に分け、`guarded_task`（`worker`）を
1 回の応答に並べて起動させる。指示文は `[pi.commands.fleet]` から作る。pi は 1 つの返答に並んだ tool call を
並列に実行する。`-ne` でもプロンプトテンプレートは読まれる（試験済み）。

### キーバインド

`~/.pi/agent/keybindings.json` は `[pi.keybinds]` の中身そのもの（ファイルごと生成器の持ち物）。今は
`app.interrupt` に Ctrl+C を足し、`app.clear` を外し、Ctrl+D で終了する（今の OpenCode の設定と同じ操作）。

### 共通の指示

`~/.pi/agent/AGENTS.md` は、Claude Code・Codex・Copilot と同じ共通の指示（`agent-instructions.md`）。

### Orca・Zed

- **Orca**: Orca は pi を起動するとき、ステータス表示の拡張を `~/.pi/agent/extensions/orca-agent-status.ts` に
  置く。`pis` は `-ne` で拡張を読まないので、Orca から起動したとき（`ORCA_AGENT_HOOK_PORT` がある）に限り、
  Orca の印（`@orca-managed-pi-extension`）がある拡張だけを `-e` で足す。境界の内側は `~/.pi/agent` を読めない
  ので使えない（状態表示は出ない）。Orca が `pi` と `pis` のどちらを起動するかは Orca 側の設定による
- **Zed など RPC で起動するクライアント**: 確認は `extension_ui_request` として届き、応えないと永久に待つので、
  TUI 以外では確認に 5 分の期限を付け、期限が来たら拒否する。クライアントが確認の要求（`confirm`）に
  対応していなければ、ask になる操作は拒否される

## 境界

`pis --boundary` は、`ocs --harness pi` へ引き継いで pi を Fence で囲って起動する。境界の組み立て・危険な
起動場所の拒否・起動前の退避・`--check` は OpenCode の隔離起動と共通（[OpenCode 隔離起動](opencode-sandbox.md)）。
pi だけの部分は `~/.local/share/ocs/pi.py`。`--no-backup` / `--check` は `ocs` が解釈するので、pi には渡らない。

| 項目 | 内容 | 理由 |
| --- | --- | --- |
| 設定の置き場 | 境界用の **agent 置き場**を起動ごとに `~/.local/share/pi-sandbox/agent-*` へ作り、`auth.json`・`models-store.json`・`settings.json` を写す。`settings.json`・`trust.json`・`mcp.json`・`extensions/` は書き込みを塞ぐ | pi は設定と認証を読むときにも隣へ `.lock` を作るので、置き場は書ける必要がある。本物の `~/.pi/agent` を入れると、内側で作られた拡張を外の通常の pi が読む（E4） |
| セッション | `--session-dir` で本物の `~/.pi/agent/sessions/--<作業ディレクトリ>--` だけを開ける | 外の `pi -c` で再開できる（試験済み）。`--session-dir` は渡した場所へそのまま置くので、pi が使う置き場の名前をそろえる |
| 認証 | 写しの中で更新された認証のうち、**有効期限が本物より新しいプロバイダの分だけ**を、終了後に本物へ戻す（pi と同じ `auth.json.lock` を取る。取れなければ戻さない） | OpenAI は OAuth（期限 47 分）で、更新のたびにリフレッシュトークンが入れ替わりうる。写しの中だけで更新すると、本物が失効する |
| 後始末 | pi を子プロセスとして動かし、終了・SIGTERM・SIGHUP（端末を閉じた）のどれでも、認証を戻して置き場を消す。Ctrl-C は子が受ける | `execve` で置き換えると終了後の処理ができず、認証の写しが残る。SIGKILL や電源断では残るので、3 日たった置き場は次の起動が捨てる |
| 判定器 | `PI_HARNESS_BOUNDARY=1` を渡す（判定器はまだ使っていない） | 境界の中の既定は段 5 で決める |
| 設定の出所 | 共有のキーは `[opencode.sandbox]`、pi の追加分は `[pi.sandbox]`（読み取り: ハーネス・判定器・`~/.config/agents`・`~/.claude/hooks`・pi 本体） | 段 6 で OpenCode を撤去するとき、共有キーを `[pi.sandbox]` へ移す |
| 作業先ごとの追加 | OpenCode と同じ `.opencode/sandbox.toml` | 名前は段 6 で決める |

`~/.config/agents`（判定器が `common.toml` を読む）は読めるが書けない。内側から判定の規則を書き換えられない。
OpenCode 用の読み取り先（`~/.opencode` など 3 件）も共有キーに入っているので、pi からも読める
（秘密を含まない道具の置き場）。

## pi の設定

`~/.pi/agent/settings.json` のうち次のキーだけを `generate.py --target pi-settings` が持つ（所有の規則。
宣言から外したキーは消す）。ほかのキー（pi 自身が書く `lastChangelogVersion` や、`/settings` で変えた
ほかの設定）は残す。素の `pi` もこの設定を読む。

| キー | 出所 |
| --- | --- |
| `defaultProvider` / `defaultModel` | `[opencode.model]` の `default` 階層（[モデルの割り当て](agent-config-generation.md#モデルの割り当て)） |
| `defaultThinkingLevel` / `skills` / `enabledModels` | `[pi.settings]`（書いたものだけ） |

今は `defaultThinkingLevel = "medium"`、`skills = ["~/.claude/skills"]`。`~/.agents/skills` は pi が元から読む。

## 置き場

| 実体 | 配置先 | 役割 |
| --- | --- | --- |
| `home/dot_config/pi/harness/index.ts` | `~/.config/pi/harness/index.ts` | 拡張の本体 |
| `home/dot_config/pi/harness/modify_rules.json.py.tmpl` | `~/.config/pi/harness/rules.json` | `generate.py --target pi-harness` が作る。判定器の場所・伏字化の規則・シェルへ入れる環境変数・子エージェント・MCP・役割ごとのツール |
| `home/dot_local/bin/executable_pis` | `~/.local/bin/pis` | 起動の入口（[起動](#起動)） |
| `home/dot_local/share/ocs/pi.py` | `~/.local/share/ocs/pi.py` | 境界の pi 用の部分（[境界](#境界)） |
| `home/dot_pi/agent/modify_keybindings.json.py.tmpl`・`AGENTS.md.tmpl`・`prompts/fleet.md.tmpl` | `~/.pi/agent/keybindings.json`・`AGENTS.md`・`prompts/fleet.md` | [ハーネス以外の機能](#ハーネス以外の機能) |
| `home/dot_pi/agent/modify_settings.json.py.tmpl` | `~/.pi/agent/settings.json` | `generate.py --target pi-settings` が持ち物のキーだけを書く（[pi の設定](#pi-の設定)） |
| `home/.chezmoitemplates/agent-cli-install.sh.tmpl` の `install_pi` | `~/.pi/agent/install`・`~/bin/pi` | pi 本体を公式インストーラーで入れる（[AI CLI の導入](structure.md#ai-cli-の導入)） |

## 環境変数

| 変数 | 既定 | 意味 |
| --- | --- | --- |
| `PI_HARNESS_ROLE` | `implementer` | 判定器へ渡す役割（`[pi.profiles]` の名前） |
| `PI_HARNESS_BYPASS` | 無し | `1` なら判定器へ `bypass` を渡す（ask だけを allow にする） |
| `PI_HARNESS_BOUNDARY` | 無し | `1` なら判定器へ `boundary` を渡す（判定器はまだ使っていない） |
| `PI_HARNESS_CHILD` | 無し | `1` なら子エージェントとして動く（`guarded_task` を登録しない）。ハーネスが子を起動するときに付ける |
| `PI_HARNESS_TEST_CHILD_EXT` | 無し | 試験だけが使う。子にも読ませる拡張（偽のモデル）のパス |

## しくみ

| 項目 | 内容 | 理由 |
| --- | --- | --- |
| ツール | `guarded_bash` / `guarded_read` / `guarded_edit` / `guarded_write` / `guarded_grep` / `guarded_find` / `guarded_ls`。中身は pi の組み込みの定義。**役割の `tools` に無いものは登録しない**（モデルに見せない。判定は判定器が別に行う）。役割が `rules.json` に無ければ何も登録しない | **組み込みと同じ名前にしない。** `/reload` でハーネスが抜けると、直前に有効だったツールの名前が組み込みの定義に解決され、判定なしで動く（E1）。別名ならツールが 0 個になる |
| 判定 | `tool_call` で判定器を呼ぶ。deny は止め、ask は確認画面を出す（UI が無ければ拒否）。**最終の判定は各ツールの `execute()` の中**で行う | `tool_call` の後に別の拡張が入力を書き換えても止めるため（E1）。`execute()` は、`tool_call` のときと同じ入力なら判定を使い回し、違えば判定し直す |
| 判定器の異常 | 起動できない・異常終了・タイムアウト（15 秒）・形の正しくない応答は deny | 空の応答を allow と読まない |
| 確認 | 1 件ずつ順に出す | TUI の確認画面は 1 枠を共有し、後の確認が先の確認を置き換える。codemode の中で並べた呼び出しで、先の確認が永久に止まった（E3） |
| 伏字化 | `guarded_bash` の `execute()` の中で、途中経過・最終結果・長い出力の退避ファイルを伏せる。伏せるのは `content`・`structuredContent`・`details`。ハーネスが持たないツール（MCP など）は `tool_result` で、例外を投げずに結果ごと差し替える | `details` はモデルへ送られないが、セッションと画面に残る（`details.truncation.content` に生の出力。E3）。`tool_result` の例外は無視されて生の結果が残る |
| 出力ごと伏せる | 保護対象のパス（`[file] read_deny_globs` から作る）を参照したコマンドは、出力を全部伏せる | OpenCode の guide plugin と同じ（[shell 出力の伏字化](agent-config-generation.md#shell-出力の伏字化)） |
| read などは伏せない | `guarded_read` などの結果には伏字化を掛けない | 伏せた本文を元に edit されると、ファイルへ伏字が書き込まれる |
| 圧縮 | `session_before_compact` で、`guarded_read` / `guarded_edit` / `guarded_write` が触ったファイルを圧縮のファイルの一覧に足す | pi の既定の圧縮は `read` / `edit` / `write` の名前でしか拾わない（E2） |
| シェルの環境変数 | `[agent_env]` を、未設定のときだけ bash の環境へ入れる | git の入力待ちを防ぐ（[shell ツールの環境変数](agent-config-generation.md#shell-ツールの環境変数)） |
| `rules.json` | 読めない・形が違うときは、拡張の読み込みごと失敗させる | 起動は止まり、`/reload` ではツールが無くなる（どちらも判定なしでは動かない） |

## 子エージェント

`[pi.agents.<名前>]` に宣言し、親の `guarded_task` ツール（引数 `agent` と `task`）で起動する。
子は同じハーネスを付けた別の pi プロセス（`--mode json -p --no-session -nbt -ne -e builtin:mcp`
の形）で、判定は子のハーネスが子の役割で行う。

| キー | 意味 |
| --- | --- |
| `profile` | 子の役割（`[pi.profiles]` の名前）。`task` を持つ役割は使えない（入れ子にしない） |
| `tier` | モデルの階層。今は `[opencode.model.tier.<プロバイダ>]` から引き、`#variant` を pi の思考の強さ（`:medium` など）に読み替える。無ければ親と同じモデル |
| `inherit_bypass` | 真なら、親が bypass のとき子も bypass で動く。ask に `git commit` などが残る役割には付けない |
| `description` / `system` | 親のツールの説明に出す説明と、子のシステムプロンプトに足す指示（`--append-system-prompt`） |

今の宣言（`common.toml.tmpl`）:

| 名前 | 役割 | 階層 | bypass を継ぐ | 今の OpenCode での相当 |
| --- | --- | --- | --- | --- |
| `explore` | `reader` | 親と同じ | 継ぐ | `explore` |
| `review` | `reader` | `second_opinion` | 継ぐ | `review` |
| `commit` | `committer` | `routine` | 継がない | `commit` |
| `worker` | `worker` | `worker` | 継ぐ | `fleet-worker` / `bypass-fleet-worker` |

- 子は会話を見られないので、親は必要なことを全部 `task` に書く
- **子の結果**: 子の JSON のイベントから、承認されなかった呼び出し（理由が `not approved:` で始まる。
  ハーネスが付ける）・ほかのツールのエラー・最後の返答を拾う。承認されなかった呼び出しがあれば
  `blocked`（承認待ちで未完了）として、親のツールの結果をエラーにする。子は UI を持たないので、子の
  ask は bypass を継がない限り `blocked` になる
- 親を中断すると、子をプロセスグループごと止める
- 子の返答の本文にも伏字化を掛ける
- 起動の前に、親の判定器で `task` を判定する（`tool_call` と `execute()` の両方）

## MCP

`[[mcp]]` のうち `clis` に `pi` を含むものを、ハーネスが起動のたびに `registerMcpServer` で登録する。
ハーネスが抜ければ登録も消える。MCP のツール（`mcp__<サーバ>__<ツール>`）は、実装役の `tools` の
`mcp__*` に当たり、規則が無いので既定（確認）になる。読み取り役などには出ない。

**`~/.pi/agent/mcp.json` には書かない。** そこのサーバはハーネスと関係なく繋がるので、ハーネスが
抜けたときに判定なしで残る（`pi mcp add` はそこへ書く）。

## pi の内部の挙動に頼る点

公開の約束ではないので、pi の版を上げたら `test/agents/test_pi_harness.py` を回して確かめる。

1. `/reload` は、直前に有効だったツールを名前で有効にし直す（`test_reload_without_harness_leaves_no_tools`）
2. `session_before_compact` の `preparation` が、既定の要約にそのまま渡る
3. bash の `details.truncation.content` に生の出力が入る（`test_bash_output_is_redacted_everywhere`）
4. 設定と認証を読むときにも agent 置き場に `.lock` を作る（境界で効く。CHG-0020 の段 4）

## 試験

`test/agents/test_pi_harness.py`。偽のモデル（`test/agents/pi/faux.ts`）で、決まった tool call を
通信なしに出させる。pi が無い環境では skip する。

- 宣言されるツールが `guarded_*` だけ
- 判定（allow・deny・UI の無い ask）・bypass・読み取り役・判定器の異常・`rules.json` の欠落
- `/reload` でハーネスが抜けるとツールが 0 個になる（構文エラーと削除の 2 通り）
- 判定の後に別の拡張（`test/agents/pi/mutator.ts`）が入力を書き換えても実行しない
- 伏字化（JSON のイベント・退避ファイルに生の秘密が残らない）と、保護対象のパスを参照したコマンド
- 子エージェント: 入れ子にならない・読み取り役に bash を出さない・子の ask が `blocked` で返る・
  bypass を継ぐ・役割の `shell_deny` が bypass でも効く・`commit` が確認なしで git を読む
- MCP: ハーネスから登録され、実装役では確認になる（`test_pi_harness.py`）
- 境界（`test_pi_boundary.py`）: 生成・境界用の置き場・セッションの置き場・認証の戻し（新しい分だけ・ロック・壊れた写し）・
  実際の Fence での境界チェック（Fence・bwrap・pi が無ければ skip）
- 誘導: `cat` が read ツールへの案内で止まる
- 圧縮（指示が履歴の要約の依頼に入る・ファイルの一覧）、`git commit` の確認の本文（RPC で確認の要求を受け取る。期限が付く）、
  整形（ruff・markdownlint）、`/fleet` の展開、キーバインドと共通の指示の生成、Orca の拡張の読み込み条件

## 未対応

- 子エージェントの階層のモデルは、Copilot で確かめただけ。Bedrock のモデル ID が pi でそのまま通るかは未確認
- 境界の中での判定の変え方（`boundary`。段 5）、Windows・macOS の境界
- 判定 1 回に 0.1 秒ほどかかる（Python の起動）。`tool_call` と `execute()` で同じ入力なら 1 回にしている
