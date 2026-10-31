# pi のガード

pi（earendil-works/pi）の拡張として、ツールの実行を判定器（TypeScript の `judge/`。[`decide`](pi-decide.md)）に通す仕組み。
OpenCode のガード（permission の生成・guide plugin）の後継で、移行の計画と経緯は
[CHG-0020](../../change/0020-pi-migration.md)、設計の根拠になった試作の観測は
[pi のハーネスの試作（旧称。現在のフルガード）](../../research/agents/pi-harness-spike.md)（E1〜E4）。

> **位置づけ**: **Unix（Ubuntu・WSL・macOS）では、素の `pi` もフルガード付きで起動する**（`~/.pi/agent/settings.json` が読み込む。
> [pi の設定](#pi-の設定)）。Orca・Zed が呼ぶ `pi` も同じ。`pis` は「`pi` を Fence のサンドボックスの中で起動する」ものに絞る（標準）。
> `pis --no-sandbox` は、素の `pi` との差（下の表）を解消するまでの移行用に残す。
> **Windows ネイティブの `pi` も、設定でフルガード（判定・ガードツール・伏字化）付きで起動する**。ただし**境界（Fence）は無く、実機は未検証**（[Windows](#windows)）。`pis` と ocs は Windows に配らない。
> 経緯は [CHG-0040](../../change/0040-pi-guard-by-settings.md)。

## 話題別の文書

この文書は、起動・設定・Windows・MCP を扱う。話題ごとの仕様は次の文書にある（2026-10-26 に、1 つの長い文書から分けた）。

| 話題 | 文書 |
| --- | --- |
| 拡張の方針・`guarded_action`・ツールの拡張・圧縮・commit の確認・整形・`/fleet`・Orca・Zed | [pi の拡張と補助機能](pi-extensions.md) |
| `guarded_task`・job・worktree 隔離・Windows の `task` | [pi の子エージェント](pi-subagents.md) |
| `pis` の agent 置き場・通信・緩和のゲート | [pis のサンドボックス](pi-sandbox.md) |

## 用語

このリポジトリでは、pi 本体を含む仕組み全体を「ハーネス」と呼ぶ（一般の用法と同じ）。
pi に足す判定の層、および起動の形を、次のように呼び分ける
（旧称は過去の案件・調査記録・ADR に残り、それらは書き換えない。[CHG-0023](../../change/0023-guard-terminology.md)）。

| 用語 | 指すもの | 旧称 |
| --- | --- | --- |
| ガード | ツール呼び出しを判定し、allow / ask / deny に振り分ける層 | ハーネス（拡張の意味のとき） |
| フルガード | 素の `pi`（Unix）と `pis` で効く、役割・確認（ask）・伏字化まで含むガード（`~/.config/pi/harness`） | ハーネス |
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
pis --new           # 新しいセッションで始める (既定は、この作業ディレクトリの直近のセッションがあればそれを開く)
```

- **既定で、この作業ディレクトリの直近のセッションを開く**（`--continue` を先頭へ足す。無ければ pi が新しいセッションを作る）。`--new` で新しいセッションにする。`-c`・`-r`・`--resume`・`--session`・`--session-id`・`--session-dir`・`--fork`・`--no-session`・`-p`（`--print`）・`--mode`・`--export`・`--list-models`・`--help`・`--version`・`--check` を渡したときは足さない（別のセッションの選び方・非対話・情報だけの指定を優先する）。素の `pi`（Orca・Zed が呼ぶもの）は変えない。試験: `test_pi_boundary.py`

- **サンドボックスが標準**。サンドボックスを張れない OS（macOS）では、`pis` は起動せず `--no-sandbox` を案内する（Windows ネイティブには `pis` を配らない）（黙って弱い守りに落とさない）。
  `--boundary` は互換の別名（標準と同じ意味）
- サンドボックスの検査に落ちたとき・起動場所が危険なときも起動しない。制御ファイル・フルガードの編集、復旧、Orca・Zed は `--no-sandbox` で行う
- 設計の根拠は [CHG-0023](../../change/0023-guard-terminology.md#設計原則決定2026-10-14利用者)

**素の `pi`（Unix）**は、`settings.json` の設定だけで、下の `pis` と同じツール構成になる（`extensions` にフルガードと自作の拡張を足し、自動検出の拡張を外し、`defaultTools = []`）。
役割・bypass は環境変数 `PI_HARNESS_ROLE` / `PI_HARNESS_BYPASS` で変えられる（既定: 実装役、bypass なし）。
**Windows の素の `pi`** も同じ設定でフルガードが載るが、サンドボックス（Fence）は無く、`task`（読み取り専用）だけを足して `guarded_task` は使えない（[Windows](#windows)）。上の表のうち、Windows は「素の `pi`（Unix）」の列に近い（実機は未検証）。

| | 素の `pi`（Unix） | `pis --no-sandbox`（移行用） | `pis`（標準） |
| --- | --- | --- | --- |
| フルガード | 設定で載る | フラグで載る | フラグで載る |
| サンドボックス（Fence） | なし | なし | あり |
| 作業先の `.pi/`（拡張・MCP・設定・スキル） | **信頼の確認に従う**（許可すると読む） | 常に読まない（`--no-approve`） | 常に読まない |
| 作業先のスキル（`.agents/skills`） | 信頼したときに読む | `--skill` で足す | `--skill` で足す |
| `mcp.json` のサーバ | **警告だけ**（[判定の外で動くもの](#判定の外で動くもの)） | 起動しない | 起動しない |
| Orca の状態表示の拡張 | 名前で足してある（印の確認はしない） | 印を確認して足す | 印を確認して足す |

**復旧の入口**: 設定ごと外して起動するには `pi -ne --tools read,bash,edit,write`（ガードも境界も無い。ガードの故障時だけ）。
`rules.json` が壊れている・フルガードが無いときは、pi が起動に失敗し、`pi -ne` を案内する。拡張のパスだけが無いとき（フルガードの読み込みに失敗した起動）は、組み込みのツールは無効だが、**自作の拡張が残る**。そのうち実行を伴う `bg_run`（`activity`）と `task`（`subagents`）は、フルガードが立てる印 `globalThis.__PI_FULL_GUARD__` が無いと実行しない（[判定の外で動くもの](#判定の外で動くもの)）。

`pis --no-sandbox`（`~/.local/bin/pis`）は次の形で pi を起動する（サンドボックスの内側も、同じフラグ `BASE_FLAGS` で起動する）。`-ne` が設定の拡張を無効にするので、設定と二重にならない。

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
- `-ne`（`--no-extensions`）: 拡張を自動では読まない。審査していない拡張が混ざらないようにするため（方針は[拡張の方針](pi-extensions.md#拡張の方針)）
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
- 関連: gitflow-lite の develop / main での直接作業を止める制限（`/gitflow-allow` による逃がし口を含む）は、2026-10-31 に撤去した。今は指示だけで運用する（[CHG-0050](../../change/0050-slim-guarded-action.md)、[ADR-0021](../../adr/0021-conventions-as-instructions-slim-guarded-action.md)）
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

## Windows

Windows ネイティブの pi にも、**設定（`~/.pi/agent/settings.json`）だけで**フルガード（判定・ガードツール・伏字化）を載せる（[CHG-0040](../../change/0040-pi-guard-by-settings.md)）。
**境界（Fence）は Windows に無い**ので、サンドボックスの保護は付かない。`pis` と ocs は Windows に配らない。**Windows 実機は未検証**（WSL からは `chezmoi` の描画・静的な試験・Node でのドライバ試験だけ）。

| 配るもの | 方法 |
| --- | --- |
| pi 本体 | mise の `aqua:earendil-works/pi`（バイナリ版。node 不要）。`313_mise` が入れ、`314_agent_cli.ps1` が旧 npm 版を外して起動を確かめる（[Windows の pi](../cli-management.md#windows-の-pi)）。公式の `install.ps1` は `Read-Host` で確認を聞き、apply では答えられないので使わない |
| `~/.pi/agent/settings.json`・`keybindings.json`・`AGENTS.md` | Unix と同じ（`.chezmoiignore` で戻している）。`extensions` はフルガード・自作の拡張・`!extensions/**`・subagents（`+extensions/subagents/index.ts`。Windows だけ）・組み込み拡張の除外、`defaultTools = []`（[pi の設定](#pi-の設定)） |
| `~/.config/pi/harness/`・`rules.json` | Unix と同じ（`landlock_exec.py` だけ除外。`rules.json` は `py -3` で生成） |
| 自作の拡張（`activity`・`ask`・`btw`・`delegate-nudge`・`notify`・`plan`・`speed`・`todo`） | Unix と同じく配り、settings で明示ロードする |
| `/fleet`（`prompts/`） | **配らない**（`guarded_task` を前提にするため） |
| 子エージェント `task`（読み取り役だけ） | `~/.pi/agent/extensions/subagents/`（[下記](pi-subagents.md#windows-の子エージェント)） |
| `commit-confirm` | settings から**外した**（フルガードに `git commit` の確認があるため。拡張本体の配備は残るが、Windows の settings は読まない。[commit の確認](pi-extensions.md#commit-の確認-素の-pi)） |

- **載せ方**: 素の `pi`（Unix）と同じ設定で、`pi` を起動するだけでフルガードが付く。`defaultTools = []` は pi の**組み込みツールだけ**を無効にするので、モデルに見えるのは `guarded_*` と自作の拡張のツールになる
- **Windows で無効なもの**: `guarded_task`（子エージェント。Unix のプロセスグループと `pi.cmd` に依る）、隔離（`isolation:"worktree"`。Landlock）、`reconcileOnStart`。代わりに読み取り専用の `task` を明示ロードする
- **コマンドは Git Bash 経由**: PowerShell ツールは `defaultTools = []` で登録されない。PowerShell のコマンドは bash から呼ぶ（`powershell.exe -Command ...`）。整形 hook の `bash` は Git for Windows の `bash.exe` を探す（標準の場所と、PATH 上の `git.exe` から導く。**WSL の `System32\bash.exe` は選ばない**。見つからなければ 1 回だけ知らせて整形を省略する）。`~\` も展開する
- **判定器のパス**: win32 のとき、MSYS・WSL 形式（`/c/Users/x`・`/cygdrive/c/...`・`/mnt/c/...`）、Windows 形式（`C:\Users\x`・`C:/Users/x`）、`~`、`$HOME` を同じホームとして扱い、ホーム固定の deny glob（`~/.pi/agent/settings.json` など）と `rm` のホーム全削除の検出に当てる。非 win32 の判定は変えていない。bash コマンド内のパスの deny は別の表・正規表現（`judge/rules_files.ts`・`sensitive.ts`）で、パスの形式に依らず `.ssh` や `id_rsa` を検出する設計だが、**Windows 実機での最終判定は未確認**
- **MCP は Unix と同じく `rules.json` から**（フルガードが `registerMcpServer` で登録する）。`~/.pi/agent/mcp.json` へ書く経路（`generate.py --target pi-mcp`）は廃止した（[MCP](#mcp)）
- **自作の拡張の `activity`**: `bg_run` は `spawn(shell:true)`（Windows では cmd）で、`taskkill` で止める。実機は未確認
- **フルガードを欠いた起動では実行しない**: フルガードは起動時に印 `globalThis.__PI_FULL_GUARD__` を立てる。`bg_run`（`activity`）と `task`（`subagents`）は、印が無いと実行しない（[判定の外で動くもの](#判定の外で動くもの)）
- **残る限界**: 境界が無い（Fence・Landlock の代わりは無い）、Git Bash というシェルを経由する、`guarded_task` が無い（次の段）、実機未検証。守りが強く要る作業は WSL の `pis` で行う
- 調査記録: [pi-isolation-options](../../research/agents/pi-isolation-options.md)（過去の判断。Windows に載せる前の記録）

**Windows 実機で確認する項目**は、[実機で確認する項目](#実機で確認する項目)の Windows の節にまとめた。

## pi の設定

`~/.pi/agent/settings.json` のうち次のキーだけを `generate.py --target pi-settings` が持つ（所有の規則。
宣言から外したキーは消す）。ほかのキー（pi 自身が書く `lastChangelogVersion` や、`/settings` で変えた
ほかの設定）は残す。素の `pi` もこの設定を読む。

| キー | 出所 |
| --- | --- |
| `defaultProvider` / `defaultModel` | `[opencode.model]` の `default` 階層（[モデルの割り当て](../agent-model-assignment.md#モデルの割り当て)） |
| `defaultThinkingLevel` / `skills` / `enabledModels` | `[pi.settings]`（書いたものだけ） |
| `extensions` / `defaultTools` | `[pi.settings]`。**非 Windows**: フルガード・自作の拡張（`[pi] own_extensions`。除外の直後に `+extensions/<名前>/index.ts` で足す）・`!extensions/**`（自動検出の拡張を外す）・Orca の状態表示（`+extensions/orca-agent-status.ts`）・組み込みの `codemode` / `tool-search` / `llama.cpp` の除外、`defaultTools = []`。**Windows**: 非 Windows と同じ（Orca の状態表示を含む）に、subagents（`+extensions/subagents/index.ts`）を足す。`commit-confirm` はどちらにも含めない |

今は `defaultThinkingLevel = "xhigh"`（2026-11-01 に `medium` から上げた。根拠は [記録 M5](../../research/agents/subagent-model-assignment.md)）、`skills = ["~/.claude/skills"]`。子は、階層に `#variant` が無い役割（`explore`・`review`）だけがこの既定を継ぐ。`~/.agents/skills` は pi が元から読む。

`defaultProjectTrust` は設定しない（既定の `ask`）。作業先の信頼の拒否は、`pis` の `--no-approve` が担う。
この設定だけで、フラグ無しの `pi` のツールが `guarded_*` と自作の拡張だけになり、agent 置き場の `extensions/` に置いた未審査の拡張は読まれない。設定と同じ拡張を `-e` でも読むと、ツール名の衝突で起動に失敗する（試験は `test_pi_settings_launch.py`）。

### 判定の外で動くもの

素の `pi`（Unix・Windows）には Fence が無く、次のものはフルガードの判定の外で動く。**止めずに、起動時（TUI）に警告する**（`harness/unguarded.ts`。`pis` は起動しない・読まないので出ない）。

| もの | 理由 |
| --- | --- |
| `~/.pi/agent/mcp.json` のサーバ | pi が直接つなぐ。`pi mcp add` はここへ書く。読めない JSON も警告する |
| 信頼した作業先の `.pi/extensions/`・`.pi/mcp.json`・`.pi/settings.json`（`extensions` / `packages` / `defaultTools` のキー） | 読み込み時のコードは判定の外。設定で `defaultTools` を変えられると、素の `bash` が戻りうる |

作業先のスキル（`.agents/skills`・`.pi/skills`）は指示を読むだけなので、警告しない。
**書き込みの拒否**: `~/.pi/agent/settings.json`・`mcp.json`・`extensions/**`・`~/.config/pi/harness/**` は、判定器が書き込みを拒否する（`[file] write_deny_globs`）。素の `pi` は Fence で凍結できないため。変更は chezmoi の source 側（このリポジトリ）で行い、`chezmoi apply` で入れる（`settings.json` の生成器が持つキーは `[pi.settings]` が正本で、直接書いても戻る。拡張は chezmoi から配る）。`mcp.json` も拒否する（モデルが書いたサーバは、次の起動でガードの外で動くため）。
**bash 経由でも拒否する**: 上の制御ファイルへの書き込みは、ファイルツールの `write_deny_globs` に加えて、bash のリダイレクト・`mv` / `cp` / `rm` / `tee`・インラインコードでの書き込みも拒否する（`judge/rules_guard.ts` の `GUARD_TARGETS`。試験は `test_pi_control_files_bash.py`）。ただし**ガードは OS の隔離ではない**（シェルの経由などの抜け道は、サンドボックスで塞ぐ）。
`defaultTools = []` は境界ではなく、`pi --tools …` で戻せる（利用者が意図して選ぶ経路）。
**フルガードの読み込みに失敗した起動で、判定なしの実行が残らないようにする**: フルガードは起動時に印 `globalThis.__PI_FULL_GUARD__` を立てる。実行を伴う自作の拡張の `bg_run`（`activity`）と `task`（`subagents`）は、印が無いと実行しない。ガードのパスが無いとき、`defaultTools = []` は組み込みツールだけを無効にするので、自作の拡張の `bg_run`（shell）が残るためである（独立レビューで見つかった）。`rules.json` が壊れている・無いときは pi が起動に失敗する（終了コード 1。`pi -ne` で拡張無しに起動できる）。

## 置き場

| 実体 | 配置先 | 役割 |
| --- | --- | --- |
| `home/dot_config/pi/harness/index.ts` | `~/.config/pi/harness/index.ts` | 拡張の本体 |
| `home/dot_config/pi/commit-confirm/index.ts` | `~/.config/pi/commit-confirm/index.ts` | 素の pi の `git commit` の確認（[補助](pi-extensions.md#commit-の確認-素の-pi)）。配備は残すが、`settings.json` の `extensions` には入れていない |
| `home/dot_config/pi/harness/modify_rules.json.py.tmpl` | `~/.config/pi/harness/rules.json` | `generate.py --target pi-harness` が作る。判定器の設定（`judge`: `common.toml` の `[bash]` / `[file]` / `[pi]` と `tables.toml`）・伏字化の規則・シェルへ入れる環境変数・子エージェント・MCP・役割ごとのツール |
| `home/dot_local/bin/executable_pis` | `~/.local/bin/pis` | 起動の入口（Python。`~/.local/share/ocs/pis.py` を絶対パスで読み込む。[起動](#起動)） |
| `home/dot_local/share/ocs/pis.py` | `~/.local/share/ocs/pis.py` | `pis` の本体。引数の解釈・サンドボックス（標準）の引き継ぎ・`--no-sandbox` の素の起動。起動フラグ（`BASE_FLAGS`）と拡張の一覧は、サンドボックスの `pi.py` と共有する。ライブラリは macOS にも置く（`pis` が読むため） |
| `home/dot_local/share/ocs/pi.py` | `~/.local/share/ocs/pi.py` | サンドボックスの pi 用の部分（[サンドボックス](pi-sandbox.md#サンドボックス)） |
| `home/dot_local/share/ocs/relay.py` | `~/.local/share/ocs/relay.py` | プロキシ必須の環境での通信の中継（[プロキシ必須の環境での通信](pi-sandbox.md#プロキシ必須の環境での通信)）。単独の部品で、ほかのモジュールを読まない |
| `home/dot_pi/agent/modify_keybindings.json.py.tmpl`・`AGENTS.md.tmpl`・`prompts/fleet.md.tmpl` | `~/.pi/agent/keybindings.json`・`AGENTS.md`・`prompts/fleet.md` | [ガード以外の機能](pi-extensions.md#ガード以外の機能) |
| `home/dot_pi/agent/modify_settings.json.py.tmpl` | `~/.pi/agent/settings.json` | `generate.py --target pi-settings` が持ち物のキーだけを書く（[pi の設定](#pi-の設定)） |
| `home/.chezmoitemplates/agent-cli-install.sh.tmpl` の `install_pi` | `~/.pi/agent/install`・`~/bin/pi` または `~/.local/bin/pi`（インストーラーが PATH を見て選ぶ。`pis` は両方と PATH を探す） | pi 本体を公式インストーラーで入れる（[AI CLI の導入](../cli-management.md#ai-cli-の導入)） |

## 環境変数

| 変数 | 既定 | 意味 |
| --- | --- | --- |
| `PI_HARNESS_ROLE` | `[pi] default_role` | 判定器へ渡す役割（`[pi.profiles]` の名前） |
| `PI_HARNESS_BYPASS` | 無し | `1` なら判定器へ `bypass` を渡す（ask だけを allow にする）。起動時の値で、起動後は [`/bypass`](#bypass-の切り替え) で変える |
| `PI_HARNESS_BOUNDARY` | 無し | `1` は「サンドボックスの内側のはず」という期待の表明。判定器の緩和は、カナリアの実測が通ったときだけ効く（[緩和のゲート](pi-sandbox.md#緩和のゲート)） |
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
| 出力ごと伏せる | 保護対象のパス（`[file] read_deny_globs` から作る）を参照したコマンドは、**実行せず**、出力を全部伏せた結果を返す | OpenCode の guide plugin と同じ（[shell 出力の伏字化](../opencode-config-generation.md#shell-出力の伏字化)） |
| read などは伏せない | `guarded_read` などの結果には伏字化を掛けない | 伏せた本文を元に edit されると、ファイルへ伏字が書き込まれる |
| 圧縮 | `session_before_compact` で、`guarded_read` / `guarded_edit` / `guarded_write` が触ったファイルを圧縮のファイルの一覧に足す | pi の既定の圧縮は `read` / `edit` / `write` の名前でしか拾わない（E2） |
| シェルの環境変数 | `[agent_env]` を、未設定のときだけ bash の環境へ入れる | git の入力待ちを防ぐ（[shell ツールの環境変数](../agent-config-generation.md#shell-ツールの環境変数)） |
| `rules.json` | 読めない・形が違うときは、拡張の読み込みごと失敗させる | 起動は止まり、`/reload` ではツールが無くなる（どちらも判定なしでは動かない） |

## MCP

> **`pis` では、`exposure` が `codemode`（既定）・`deferred` のサーバのツールは、モデルから呼べない。**
> `-ne` が組み込みの拡張（`builtin:codemode`・`builtin:tool-search`）も外すため、`Tool … not found` になる
> （偽のモデルで実測。[E6](../../research/agents/pi-extension-under-harness.md#記録-e6--2026-10-11)）。
> **対策済み**: `[[mcp]]` の `exposure` を省略すると、生成器（`pi_mcp_servers`）が `direct` を出す
> （[仕様](../mcp-servers.md#mcp-サーバ)）。`codemode` を使いたいときは `-e builtin:codemode` を足す（+680 トークン）。
> 実機の `pis`（Unix）では未確認

`[[mcp]]` のうち `clis` に `pi` を含むものを、フルガードが起動のたびに `registerMcpServer` で登録する。
フルガードが抜ければ登録も消える。MCP のツール（`mcp__<サーバ>__<ツール>`）は、実装役の `tools` の
`mcp__*` に当たり、規則が無いので既定（確認）になる。読み取り役などには出ない。

**`[[mcp]]` の `requires_env` が空の機では、登録しない。** 認証や URL が無い機（家の `agentcore-websearch`）で、動かないサーバを起動し続けない（`rules.json` の各項目に `requires_env` が出る。値が空白だけでも空とみなす）。

**MCP の出どころは、Unix も Windows も `rules.json` に統一する**（Windows にもフルガードを載せたため、`mcp.json` に書く経路（`--target pi-mcp`）は廃止した）。`agentcore-websearch` のラッパーは、使えない機では空のサーバになるので、家の Windows でも失敗の通知は出ない。

**`~/.pi/agent/mcp.json` には書かない。** そこのサーバはフルガードと関係なく繋がるので、フルガードが
抜けたときに判定なしで残る（`pi mcp add` はそこへ書く）。**モデルからの書き込みは拒否する**（サーバの `command` は次の起動で、ガードの外で実行される。起動時の警告は事後なので、書かせない）。`pis` はサーバがあると起動しない。素の `pi` は止めず、起動時に警告する（[判定の外で動くもの](#判定の外で動くもの)）。利用者が端末で `pi mcp add` したものは残る。

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
>
> 確認項目の一覧は [CHG-0040](../../change/0040-pi-guard-by-settings.md#実機で確認する項目旧-pi-guardmd-から移設) へ移した（チェックの進捗は案件で管理する）。**Windows 実機の確認項目は、現行の確認先として CHG-0040 を見る**。

## 未対応

- 子エージェントの階層のモデルは、Copilot で確かめただけ。Bedrock のモデル ID が pi でそのまま通るかは未確認
- Windows・macOS のサンドボックス
