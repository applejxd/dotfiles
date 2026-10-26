# OpenCode のガードの仕様（保留中のレガシー）

> OpenCode 専用（撤去予定。CHG-0020 段 6 は保留中）。pi の判定は [判定 API](pi-decide.md) と [コマンド・ファイルの判定](agent-command-policy.md)。

OpenCode の guide plugin（`guide-plugin`）が出す誘導・deny の説明・allow したコマンドの書き込み形の仕様。OpenCode の撤去のとき、この文書ごと消せる。

## OpenCode の pip 誘導と rm の誘導

> OpenCode 専用（撤去予定。CHG-0020 段 6 は保留中）。pi の仕様は [判定 API の評価の順番](pi-decide.md#評価の順番)。

OpenCode では `[[opencode.shell.guide]]`（`common.toml.tmpl`）が、生のコマンド文字列への
正規表現で deny と誘導文を返す。Claude / Copilot の hook（上の `check_rm_root_guard`
など）とは別実装で、**止める具体例だけ**に限る（決定は
[ADR-0013](../../adr/0013-opencode-shell-guard-inside-ocs.md)）。

> [!WARNING]
> **うっかり防止であり、完全な保護ではない。** 正規表現は変数・サブシェル・
> `sudo` / `command` 等の前置・スクリプト経由・別名を見ない。bypass エージェントにも同じに効く
> （[ADR-0014](../../adr/0014-bypass-as-ask-upgrade.md)）が、
> `rules.json` が読めないと効かない。止めたいときの本命は境界（ocs）と退避である。

| 規則 | 止める例 | 止めない例 |
| --- | --- | --- |
| pip | `pip install x`, `pip3 ...`, `python -m pip ...`, `python3 -mpip ...`, `uv run python -m pip ...` | `uv pip install x`, `poetry add`, `pipenv install`, `echo "pip install"` |
| `.git` | `rm -rf .git`, `rm -rf .git/objects`, `rm f sub/.git/HEAD` | `rm .gitignore`, `rm -rf .github`, `git rm file` |
| `~` / `$HOME` / `/` | `rm -rf ~`, `~/`, `$HOME`, `"$HOME"`, `/`, `/*` | `rm -rf ~/.cache/x`, `rm -rf /tmp/x` |
| 作業ディレクトリ全体 | 再帰フラグ付きの `.` / `..` / `*` / `./` / `.*` | `rm -rf .tmp/x`, `./build`, `node_modules`, `build/*`, `rm -f *.pyc` |
| `find` | `/` `~` `$HOME` `.git` を起点にした `-delete` / `-exec rm` | `find . -name '*.pyc' -delete`, `find .tmp -delete`, `find /tmp/x -delete` |

- pip の誘導先は目的で分ける（依存追加は `uv add`、環境への導入は `uv pip install` / `uv sync`、
  単発 CLI は `uvx`）。poetry / pipenv は止めない
- 規則は行頭・`;` `&` `|` 改行の直後のコマンドにだけ当てる。引用中の文（`echo "rm -rf ."`）や
  `grep -r 'rm -rf' .` は止めない。`$(rm …)` のように `(` の直後のものも当たらない（承知の穴）
- `git commit -m` / `gh … --body` の本文は `unless` で外す。外すのはコマンド全体が git / gh の
  1 コマンドだけのとき（区切り・`$`・バッククォート・括弧・リダイレクトを引用の外に含まない。
  引用内の `$(cat <<'EOF' … EOF)` は認める）に限る。（以前の `unless` の穴は[経緯](../../research/agents/command-policy-design-notes.md#opencode-の-unless-の以前の穴)）
  heredoc の誘導と伏字化（`deny_path_unless`）は全体に当てる形のまま（承知の割り切り）
- **ocs の内側にも効く。** `ocs` が捨てるのは permission（`drop_shell`）で guide 規則ではなく、
  同じ `rules.json` を plugin が読む。permission を捨てて既定 allow にした設定でも、
  上の例が deny されることを実機（`opencode:probe`）で確認した
- **静的 deny の pip にも前段で誘導文を付ける。** 通常版の `pip` / `pip3` は共通 deny
  （`[bash]` の deny から生成）で、静的 deny の呼び出しは plugin の `evaluate` に届かず、
  そのままだと `Permission denied: shell` のみになる。そこで pip の規則に `early = true` を付け、
  plugin が `tool.execute.before`（permission より前に走る）で同じ `pattern` / `unless` を判定し、
  当たれば例外を投げて `message` をモデルへ届ける。静的 deny は変えないので、plugin が無い・
  `rules.json` が壊れているときは従来どおり静的 deny が止める。bypass エージェントにも効く
  （[ADR-0014](../../adr/0014-bypass-as-ask-upgrade.md)）。
  実機で確認した（[記録](../../research/opencode/permission/early-guard.md)）。前段で止めるのは
  `early` を付けた規則だけで、他の規則は従来どおり `evaluate` で判定する
- 検査は `test/agents/test_guide_pip_rm.py`（止める例と止めない例の両方を、生成した
  `rules.json` を plugin に通して判定する）と、前段の停止を見る `test/agents/test_guide_early_pip.py`

## OpenCode の allow したコマンドの書き込み形

> OpenCode 専用（撤去予定。CHG-0020 段 6 は保留中）。pi の仕様は [判定 API の評価の順番](pi-decide.md#評価の順番)。

`[pi.shell] allow` は前方一致なので、載せたコマンドの書き込み形も確認なしに通る。
guide 規則は effect が allow でも走るので、allow を保ったまま書き込み形だけを deny する
（`common.toml.tmpl` の `[[opencode.shell.guide]]`）。

| 規則 | 止める例 | 止めない例 |
| --- | --- | --- |
| リダイレクト（[CHG-0002 段階 4a](../../change/closed/0002-opencode-ask-by-default.md)） | `git log > ~/.bashrc`、`wc f 2>&1 > f` | `git log 2>&1 \| head`、`wc -l a 2>/dev/null` |
| `git log --output`（[CHG-0017 段 5](../../change/closed/0017-builtin-agent-restrictions.md)） | `git log -1 --output=f`、`git log --output f`、`git log -p --output=f`、`ls && git log --output=f`（`;` `\|\|` `\|` `(` も） | `git log -1 --oneline`、`git log --stat`、`git log --output-indicator-new=+`、`git commit -m 'git log --output=x'`、`echo --output` |

- **allow を足すときは、リダイレクトだけでなく引数でファイルへ書けるオプションも点検する。**
  `git log --output=<パス>` は確認なしに、作業ツリーの外にも書けた
  （[記録 E2](../../research/opencode/permission/builtin-agent-override.md#記録-e2--2026-10-08)）。
  点検の結果、内容と書き込み先の両方を引数で決めて書けるのは `git log` だけだった
- `--output` の規則は `git log` で始まる部分（次の `;` `&` `|` 改行まで。引用の中は飛ばす）
  だけに当てる。`*--output*` を全体で deny すると、コミットの本文や正当な `--output` まで止まる。
  `unless` は使わない（コマンド全体に当たり、連結した後ろの書き込みまで見送るため）
- 承知の穴: 引用の中の `;` の後ろの `git log --output`（`git commit -m "x; git log --output=y"`）は
  誤って止める。`then` / `do` の直後、`git -c x=y log` / `git --no-pager log` のような前置きは
  見ない（前置きの形は allow の `git log *` に当たらず確認になる）
- `early` は付けない。穴は静的な allow なので `evaluate` に届く。bypass の ask→allow より前に
  止まり、ocs（既定が allow）でも同じに効く
- **Claude / Copilot には足さない。** どちらも OS の sandbox で shell の書き込みが作業ディレクトリと
  許可した場所に限られ、起動ファイルなどは `claude_write_deny` / Copilot の deny-by-default で
  塞がる（[sandbox](../sandbox/agent-sandbox.md)）。作業ディレクトリの中は、既定の権限モード
  （Claude の `auto`、Copilot の `assisted`）で編集もできるので、`--output` で書けても新しい
  権限にならない。OpenCode の通常版は shell に OS の境界が無いため、ここだけで塞ぐ。
  ただし Claude で sandbox の外で実行させる形（unsandboxed コマンド）に `git log` の allow が
  どう効くかは未確認
- 検査は `test/agents/test_guide_git_log_output.py`（リダイレクトは `test_generate_opencode.py`）

## OpenCode の deny の説明（前段停止）

> OpenCode 専用（撤去予定。CHG-0020 段 6 は保留中）。pi の仕様は [判定 API の評価の順番](pi-decide.md#評価の順番)。

V2 は静的 deny に当たると plugin の `evaluate` を呼ばず、モデルへは `Permission denied: shell` だけが
返る（理由も代替も伝わらない）。pip で実証した前段停止（上、
[記録](../../research/opencode/permission/early-guard.md)）を `[bash] deny` の全項目へ広げ、
**説明文を返す**。静的 deny は一切変えない（plugin が壊れても静的 deny が止める）。bypass エージェントにも
同じに効く（[ADR-0014](../../adr/0014-bypass-as-ask-upgrade.md)）。

### 分類（正本は `common.toml.tmpl` の `[bash.deny_guide]`）

deny の**全項目**が次のどれか 1 つに属さなければ、`generate.py` が生成を止める（漏れ・重複・
deny に無い項目・`elsewhere` を止める early 規則が無い、のいずれも）。deny を足したら分類も足す。

| 分類 | 宣言 | 説明文の中身 | 項目 |
| --- | --- | --- | --- |
| A 代わりの手段がある | `[[bash.deny_guide.alternative]]`（`commands` + `message`） | 代替の手段 | `npm install -g`（→ chezmoi のソースの `home/dot_config/mise/config.toml.tmpl` へ追記して `chezmoi apply`。chezmoi 管理外なら `mise use -g npm:<pkg>`。`mise use -g` だけでは次回の apply で失われうる）、`uv self update` / `chezmoi upgrade`（→ 導入元のパッケージマネージャで更新。mise か winget かは OS で違うので特定しない）、`rustup self update`（→ 利用者に依頼）、`git config` の書き込み系 8 件（→ `home/dot_gitconfig.tmpl` を編集して `chezmoi apply`）、`docker * prune` 5 件（→ 対象を指定した `docker rm` / `docker rmi`。どちらも ask）、`npm cache clean` / `yarn cache clean` / `pnpm store prune`（→ 必要なら利用者に依頼） |
| B 利用者に頼む | `user_only`（共通の `user_message`） | 迂回せず、実行してほしいコマンドと理由を利用者に示す | 上記以外の全部（`sudo`、`git push` / `reset --hard` / `rebase` / `filter-branch` など、`crontab` / `at` / `batch`、`systemctl` 系、`mkfs` 系、`socat` / `ncat` / `telnet` / `ssh`、DB クライアント、`gh` のリモート操作、秘密ストア、`scp` / `rsync` など）。迷ったらここ |
| 別規則 | `elsewhere` | — | `pip` / `pip3`（[上](#opencode-の-pip-誘導と-rm-の誘導)の `early = true` の guide 規則が止める。二重にしない） |

`generate.py`（`opencode_deny_guide_rules`）が分類から `rules.json` の `deny_guide`（`pattern` /
`unless` / `message`）を作り、`index.js` が `tool.execute.before` で当てる。evaluate 側の `guide` には
混ぜない（混ぜると、隔離版やエージェントの allow など**静的 deny に無い場面**でも止めてしまう）。
Claude / Copilot の生成物は変わらない。

スキルのスクリプトのリダイレクトの静的 deny（`[pi.skill_scripts]`）も同じ `deny_guide` に出す
（説明は `redirect_message`。範囲は [スキルのスクリプト](../agent-config-generation.md#スキルのスクリプト)）。
`[bash.deny_guide]` が無くても生成する。

### 前段で止めるのは静的 deny の部分集合だけ

OpenCode の静的照合は、scanner が分割した各セグメントに `cmd` / `cmd *` のワイルドカードを当てる
（[分割の観測](../../research/opencode/permission/allow-list-audit.md)）。前段は生のコマンド文字列への
正規表現なので、一致集合がずれうる。そこで**確実に部分集合になる保守的な形**にしている。

- **セグメント先頭だけ**: 行頭と `&&` `||` `;` `|` 改行の直後で、コマンド名（`git push` などは単一の空白でつなぐ）
  の後ろが単一の空白・区切り・末尾のときだけ当てる。`at` が `atop` / `at<TAB>x` / `cat` に、`ssh` が
  `ssh-keygen` に、`mkfs` が `mkfs.btrfs` に当たらない（静的な `cmd *` も当たらない形）
- **引用符（`'` `"`）・バッククォート・括弧（`$(` を含む）・`#`・`\`・ヒアドキュメント（`<<`）・
  単語としての `{` を含むコマンドは前段で止めない。** 区切り文字が引用符の中やコメント・ヒアドキュメントの本文・
  継続行にあると、scanner の分割と食い違う。その場合は静的 deny が（説明なしで）止める。
  例: `git config --global user.name "x"` は説明が付かない
- **エージェントの規則が静的 deny を覆す項目は、そのエージェントでは止めない**（`except_agents`。
  エージェントの規則は全体の規則の後ろに付いて後勝ち。今の宣言には該当するエージェントが無い）。V2 の `permissions` と V1 の `permission`
  （`bash` / `shell` / `*` キー、文字列も）の両方から算出し、読めない形は覆すものとして扱う。
  ただし `restate_global_deny` に `shell` を含むエージェント（`plan`）は、全体の shell の deny が
  エージェントの規則の後ろに写されて覆されないので、`shell * ask` があっても例外にしない
  （[子エージェント](../opencode-config-generation.md#子エージェント)）
- **対象は生成器が permission を把握しているエージェントだけ**（`rules.json` の `deny_guide_agents`。
  宣言済み + 組み込みの `build` / `plan` / `general` / `explore`）。宣言外のエージェント（利用者が
  `opencode.json` に直接書いたもの）や `agent` が分からないとき、隠しエージェント（`title` など）は止めない
- **`rules.json` の形が不正なら節ごと無効にする。** `deny_guide` は各項目の `pattern` / `unless` /
  `message`（非空文字列）、`not_isolated`（真偽値）、`except_agents`（文字列配列）、`deny_guide_agents`
  （文字列配列）を検証し、1 件でも不正（全一致に近い `pattern` を含む）なら全体を止めない（静的 deny に任せる）。
  `guide` 節も同じ検証をする（経緯は[設計メモ](../../research/agents/command-policy-design-notes.md#opencode-前段停止の過去の穴)）
- **通常版と隔離版（ocs）で、それぞれの最終的な静的 deny から決める。** `rules.json` は両者で共有
  なので、ocs が `drop_shell` で捨てた項目には `not_isolated` を付け、plugin が `OCS_ISOLATED` で見分けて
  ocs では止めない（`sudo`・`systemctl`・`git config --global` / `--system`・`npm install -g`・
  `docker * prune` など。`git push` や `git config --local` は ocs でも残るので止める）
- 部分集合の性質は `test/agents/test_guide_deny_early.py` が固定する。静的照合を模擬し
  （分割 + 後勝ちの `cmd` / `cmd *`）、deny の全項目 × 34 の形（引用符・コメント・継続行・ヒアドキュメント・
  置換など）+ 止めてはいけない例を、通常版・ocs × 4 エージェントで plugin に通して「前段で止まる ⇒ 静的にも deny」を検査する

実機での観測は [early-guard の追記](../../research/opencode/permission/early-guard.md#追記-deny-全体への拡張2026-10-03)。

**既知の限界**（静的 deny の部分集合を保てない場面。静的 deny は変えないので安全側には倒れるが、
説明が付かないか、まれに過剰に止まる）:

- プロジェクト設定（`.opencode/opencode.json` など）や利用者が `opencode.json` に直接書いた
  permission での上書きは、plugin が実効設定を取得できないため考慮しない。plugin の `ctx` に
  設定を返す API は文書化されておらず（`opencode api config.get` は CLI 側）、使っていない。
  宣言外のエージェントは対象外にして被害を狭めるが、組み込み（`build` など）を利用者が上書きした場合は
  検知できない。[ADR-0012](../../adr/0012-ocs-boundary-for-accidents.md) の非目的
  「利用者自身の明示的な上書き」と同じ扱い
- 引用符などを含むコマンドには説明が付かない（上記）
bypass-fleet-worker 固有の deny（`git add` / `commit` など）は対象外。
