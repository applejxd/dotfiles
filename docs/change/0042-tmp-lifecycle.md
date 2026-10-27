# CHG-0042: `.tmp/` をセッションごとの置き場に分け、終わりに消す（取り込むものは残す）

- **状態**: Exploring
- **更新日**: 2026-10-27
- **基準**: pi 1.4.0、コミット `f78dd6c`。`.tmp/` の実態は 2026-10-27 に実測した（掃除前 31 GB・930 件）。pi の終了イベントと `TMPDIR` の経路は、探索の子がコードを読んだ結果に加え、**使い捨ての拡張と pi の RPC モードで、実機（Linux、モデルを使わない）で確かめた**（「現在地」の「実験の結果」）

## 目的と非目的

**目的**: 作業ツリーの `.tmp/`（git の管理外の、使い捨ての置き場。`.gitignore` 済み）に、残骸が溜まり続けるのをやめる。実際に、掃除する仕組みが無く、1 か月ほどで **31 GB** になった（OpenCode の実験が 26.7 GB、テストの一時が約 6 GB）。ただし、`.tmp/` には、**後でリポジトリの `docs/` などへ取り込むもの**（調査の原文、`review-loop` の台帳、実験の記録）も置くので、「古いものを一律に消す」のでは、取り込む前に失う。そこで、**セッションごとの置き場を分け、そのセッションの終わりに、その置き場だけを消す**。取り込むものは、置き場の外に置く。

**非目的**:

- `.tmp/` 以外（`~/.cache`、`/tmp`、`~/.local/state` など）の掃除
- Windows の対応（`TMPDIR` の代わりに `TEMP` を使うなど。段 3 の後に別に扱う）
- Claude Code・Copilot の終了時の掃除（それぞれの hook が別物。段 5 で、起動時の年齢による掃除だけ検討する）
- `.tmp/` に置くものの内容や形式の変更（運用が決めた場所 `research/`・`review-loop/` などは、そのまま）

## 実施計画

この文書で使う段のラベルを、ここで定義する。

| 段 | 解決したいこと | 内容 | 状態 |
| --- | --- | --- | --- |
| 1 | 方針を実装の前に決める | この案件の起草と、`review` による指摘の反映 | 進行中（起草済み） |
| 2 | 自動で消してよいものだけを、確実に消せるようにする（セッションの仕組みとは独立の安全網） | `scripts/tmp_clean.py`（既にある）を、**自分で作ったと確かめられるものだけを自動で消す**形に直す: (1) `s/` の、持ち主の死亡を確証できたもの（U3） (2) 再生成できる名前（テスト・導入の一時。コード内の一覧）。**それ以外の未知の直下の項目は、一覧を出すだけで消さない**（消すのは、`mise run tmp:clean --all` の手動の確認のとき）。保護: `keep/`・運用の置き場。試験・`mise run tmp:clean`・docs | 完了（2026-10-27。`tmp_clean.py` を `home/dot_config/pi/harness/` へ移し、自作のものだけを自動で消す形に直した。`test_tmp_clean.py` 27 件・`mise run tmp:clean`・verify の規則） |
| 3 | セッションの終わりに、自分の置き場を消す | pi のハーネス（`harness/index.ts`）が、`session_start` で `.tmp/s/<セッション ID の末尾 8 文字>/` を排他的に作り（`.owner` に持ち主を記録）、`process.env.TMPDIR` をそこへ向ける。**`session_shutdown` の `reason` が `quit` のときだけ**、停止要求した子・`bg_run` の終了を確かめてから、**この実行が作った置き場をすべて**消す（`new`・`resume`・`fork`・`reload` では消さない。U2）。`pis` の内側・子（隔離子は `/tmp` のまま）では何もしない。起動時に、`s/` の死亡所有者の回収を呼ぶ | 完了（2026-10-27。`harness/session-tmp.ts`・`index.ts` の配線・`activity` の `bg_log` がログのパスを保持。`test_pi_session_tmp.py`。**実機の対話モード（`quit`・`/new`・`/resume`・`/fork`・`reload`）は未確認**） |
| 4 | 残骸の発生源を直す | `tools_ext_driver.mjs` の後始末・`agents_config_dir` の `atexit` 頼みをやめる・pytest の `basetemp` と保持数 | 完了（2026-10-27。`tools_ext_driver.mjs` の後始末・`agents-config-*` を `pytest_sessionfinish` で消す（xdist のワーカーは `os._exit` で `atexit` が走らなかった）・pytest の保持を落ちた分だけ。`test/agents` を実行した後の `.tmp` の残骸は 0、`pytest-of-*` は 4 KB（以前 5 GB）） |
| 5 | 他の CLI | Claude Code・Copilot は、起動時の年齢による掃除（段 2）だけを、hook から呼べるか検討 | 保留（再開条件: 段 3 の運用後に、他の CLI の残骸が問題になったとき） |
| 6 | エージェントと判定器が置き場を守る | 共通の指示（`home/.chezmoitemplates/agent-instructions.md`）に、「スクラッチは、書き込める場所の `$TMPDIR`（`pis` の内側・隔離子は従来どおり）」「取り込み待ちは `.tmp/keep/`」を書く。**判定器**: `.tmp` 自体・`.tmp/keep`・運用の置き場を巻き込む削除（`rm -rf .tmp`・`find .tmp -delete` など）は、scratch 免除から外して ask にする（U13）。**`.zshenv`**: 子の zsh が、`TMPDIR` が既に `<repo>/.tmp` の配下なら、そのまま維持する（U14）。**段 2 の自動削除の前に行う**（保護の前提） | 進行中（共通の指示と `.zshenv`（U14）は 2026-10-27 に完了。**判定器（U13）は未着手: 下の U13 に、実装で分かった衝突と、利用者の判断が要る点を書いた**） |

状態: 未着手 / 進行中 / 完了 / 保留 / 見送り / 消滅

## 現在地

**置き場の構成（提案）**:

```text
.tmp/
  s/<セッション ID>/       そのセッションの一時 (TMPDIR の向き先)。終了時に消す。中に .owner (pid・起動時刻)
  keep/<話題>/            取り込み待ち。自動では消さない
  research/ review-loop/ away-shift/ subagents/ worktrees/ checkpoint-*   運用が決めた場所 (今のまま。保護)
  (その他の直下)           年齢が古ければ tmp_clean が消す (安全網)
```

**確かめた事実**（探索の子が、コードを読んだ結果。実機では未確認）:

- **`pis` の内側の `TMPDIR` は、`/tmp`（内側の tmpfs）に固定される**。`inner_command` が `env TMPDIR=/tmp` を付ける（`home/dot_local/share/ocs/pi.py:678`）。`.tmp` が書けるのは、作業ツリー全体が `allowWrite` だから（`boundary.py:244`）。つまり、**`pis` の内側の一時は、セッションごとに消える**。残骸が溜まっていたのは、`pis` の外（普通のシェルで走らせたテストなど）
- **リポジトリの中では、`TMPDIR` が `<repo>/.tmp` を指す**。zsh の `home/dot_zshenv:30-75`（`_tmpdir_repo_local_update`）が誘導する（`docs/spec/shell.md:19`）。これが、本来 `/tmp` に作られて OS が消す一時物を、`.tmp/` に集めている。**この誘導をやめない**（Claude Code の sandbox は `/tmp` に書けないことがあり、`.tmp` へ誘導する前提で動いているため。理由は `docs/spec/sandbox/agent-sandbox.md` の `/tmp` の節）
- **pi の `session_shutdown` は、`reason`（`quit` / `reload` / `new` / `resume` / `fork`）を渡す**（`dist/core/extensions/types.d.ts:638-641`）。セッション ID は `ctx.sessionManager.getSessionId()`（`session-manager.d.ts:246-247`）
- **正常終了と SIGTERM・SIGHUP では、ハンドラを await してから終了**する（対話・`-p`・RPC のどれも。`interactive-mode.js:3430-3478,3540-3550`、`print-mode.js:32-40,142`、`rpc-mode.js:578-595`）。タイムアウトは見当たらない。**SIGKILL・クラッシュ（uncaughtException）・端末の消失・2 回目のシグナルでは呼ばれない**（`interactive-mode.js:3482-3528`）
- 自作の拡張の `session_shutdown` の書き方は、そのまま使える（`harness/index.ts:205`、`activity/index.ts:173-188`、`delegate-nudge/index.ts:126-129`。冪等にして、`safe` で包み、同期的に済ませる形）。自作の拡張では、セッション ID は、まだ使っていない
- **bash ツールを起動するときの環境は、`spawnHook` で上書きできる**（`harness/index.ts:348-350`。今は `AGENT_ENV` を足している）。`guarded_task` の子の環境は `{...process.env}` を基にする（`index.ts:816-819`）。ただし、`process.env.TMPDIR` を書き換えると、bash・`bg_run`・子が受け取るかは、**実機で未確認**
- **実験の結果**（2026-10-27、Linux、モデルを使わない。`.tmp/exp_tmpdir.mjs`・`.tmp/exp_shutdown/`。使い捨ての拡張と、pi の RPC モード `--mode rpc -ne -e <拡張> --no-session --offline -na`）:
  - **bash の子は、`process.env.TMPDIR` の書き換えを受け取る**。pi の bash ツールは、呼び出しごとに `getShellEnv()`（`process.env` が基）から環境を作る（`dist/core/tools/bash.js:136`、`utils/shell.js:147-155`）。`spawnHook` で、`PI_SESSION_ID` から決めても受け取る。**ハーネスの現行の形 `{...AGENT_ENV, ...spawn.env}` では、`spawn.env` が後勝ち**なので、`AGENT_ENV` に `TMPDIR` を足しても効かない。`bg_run` は `env` を指定せずに `spawn` するので（`activity/index.ts:216`）、`process.env` を書き換えれば同じく受け取る
  - **pi の bash ツールは、`PI_SESSION_ID` と `PI_SESSION_FILE` を、子の環境へ渡す**（`bash.js:142-146`）。セッション ID を、子のプロセスが読める
  - **`session_shutdown` は、stdin の終了（EOF）・SIGTERM・SIGHUP で、`reason=quit` で呼ばれ、置き場が消えた**（終了コードは 0・143・129）。**SIGKILL では呼ばれず、置き場が残った**。**SIGINT（RPC モード）は、ハンドラ無しで、プロセスが死に、呼ばれず、残った**（対話モードの Ctrl+C は、キー入力として処理され、`quit` に至る。コードを読んだ結果で、実機では未確認）
  - **セッション ID は UUIDv7 で、先頭 8 文字は時刻（約 65 秒ごとにしか変わらない）**。5 つの別のプロセスが、同じ先頭 8 文字 `01a17a78`（後の実行では `01a17a79`）になった（`--no-session` でも通常でも）。**置き場の名前に、先頭ではなく、末尾（ランダムな部分）の 8 文字を使う**。同じ名前が既にあり、持ち主の pid が生きているときは、末尾を伸ばす
- **残骸の発生源**（`test/agents/` の試験）:
  - `tools-ext-*`（約 35 件・各約 35 MB）: `test/agents/pi/tools_ext_driver.mjs:17` の `mkdtempSync(join(tmpdir(), "tools-ext-"))`。**後始末が無い**（`rmSync` も `finally` も無い）
  - `agents-config-*`（63 件）: `test/agents/agents_common.py:86-87`。`atexit` だけに頼るので、中断されると残る
  - `pytest-of-*`（5 GB）: `pyproject.toml` に `basetemp` や `tmp_path_retention_count` の設定が無い
  - `.tmp/opencode/`（26.7 GB）: OpenCode の実験の隔離環境（DB・XDG のコピー）。場所を決めるコードは無く、docs が実験ごとに書いている。消す仕組みも世代管理も無い
- **世代管理があるのは `.tmp/subagents/*.md` だけ**（50 件かつ 7 日。`index.ts:563-564`、`953-964`）。`research/`・`review-loop/`・`away-shift/`・`worktrees/` は、自動では消えない。`checkpoint` は、意図的に消さない（`docs/spec/checkpoint.md:168`）
- **取り込みの慣習**: 結論と実測値だけを `docs/research/` に書き、生の記録は `.tmp/` に残す（`docs/research/opencode/shared-db.md:120`、`fence.md:97,155`）。**`.tmp` を消すと、その再現の手段が失われる**（実際に、2026-10-27 の掃除で `.tmp/opencode/` を消した。docs の本文は、記録なので書き換えない）

## 未解決点

| 問い | 暫定の答え | 再開条件・決める場 |
| --- | --- | --- |
| U1: 子エージェント（`guarded_task`・`task`）の置き場 | **非隔離の子は、親の `TMPDIR` を継承する**（`PI_HARNESS_CHILD=1` のとき何もしない）。**隔離子は、既存の「`TMPDIR` がリポジトリと重なるときは `/tmp`」のまま**（`index.ts:756-763`。親の置き場を書込許可にしない。隔離子の一時物は、親の `s/` の終了時の削除の対象外）。レビュー R1-7 | 段 3 |
| U2: どの `reason` で消すか | **`quit` のときだけ消す**。`new`・`resume`・`fork` では、会話が続き、**旧置き場の中のパスを会話が参照し続ける**（pi が切り詰めた bash 出力の全文を置くファイルのパスを会話に返す。`bg_log` が現在の `tmpdir()` からログを探す）ため、消さない。代わりに、**この実行（プロセス）が作った置き場をすべて記録し、`quit` で全部消す**。`reload` は、同じセッションが続くので消さない。クラッシュ・SIGKILL で残った旧置き場は、次の起動での死亡所有者の回収（U3）が消す。**`activity` の `bg_log` は、完了したジョブの実際のログのパスを記録に保持する**（`tmpdir()` から再構成しない）。レビュー R1-6 | 段 3 の実機の確認 |
| U3: 持ち主の死亡の判定と、掃除の排他 | **自動で消す `s/` は、持ち主の死亡を確証できたものだけ**: 同じホスト・同じ PID namespace（`/proc/self/ns/pid`）で、`.owner` の pid が存在しない、または `/proc/<pid>/stat` の開始時刻が `.owner` の記録と違う（pid の再利用）。**確証できないとき（別の namespace・権限エラー・`.owner` が無い・不完全）は残す。年齢だけでは `s/` を消さない**（生きている長期セッションを消すため。旧案の「7 日より古いもの」は撤回）。生成は `mkdir` の排他（既に有れば別の名前）、掃除は `.tmp/.sweep.lock` で排他（生成の途中の置き場は、`.owner` が不完全なので残る）。`session_shutdown` が主、起動時の回収が保険（SIGKILL・SIGINT（RPC）・クラッシュ。実験で確認）。レビュー R1-2 | 段 2・3 |
| U4: 同じリポジトリの並行するセッション | 置き場は、セッションごとに別。起動時の掃除は、**持ち主が死んでいるものだけ**消す（生きている他のセッションの置き場は消さない） | 段 2 |
| U5: Unix ソケットのパス長（上限 108 バイト前後） | 置き場の名前は短く（セッション ID の**末尾** 8 文字。先頭は時刻で衝突する）。`<repo>/.tmp/s/<8 文字>` が 80 文字を超えるときは、置き場を作らず、今の `TMPDIR` のままにする | 段 3 |
| U6: `.tmp/` がシンボリックリンクのとき | 掃除は、拒否（`tmp_clean.py` は実装済み）。置き場も作らない | 段 2・3 |
| U7: 「取り込み待ち」と「使い捨て」を、エージェントが守るか | **指示で守らせる**（段 6）。守られなくても、被害は、「`s/` に置いた取り込み待ちが、終了で消える」に限る。重要なものは、`keep/` へ置く規則と、`research/`・`review-loop/` などの既存の置き場 | 段 6 |
| U8: `process.env.TMPDIR` を書き換えるか、`spawnHook` だけで足すか | **`process.env` の書き換えを主にする**（実験で、bash が受け取ることを確認。`bg_run` と子は `process.env` を基にするので、書き換えが要る）。`spawnHook` は、不要（ハーネスの現行の形では `spawn.env` が後勝ちで、足しても効かない）。**`session_start` のたびに書き換える**（`new`・`resume` で ID が変わる） | 済（実験 1）。段 3 の実装で、子・`bg_run` を確認 |
| U9: `.tmp/opencode/` のような、巨大で、取り込み待ちかもしれない実験の置き場 | **自動では消さない**（未知の名前は一覧だけ。U1 の原則）。今後、巨大な実験は、`s/` の中で行う（`quit` で消える）か、取り込み待ちなら `keep/` に置く。手動の `mise run tmp:clean --all` で、年齢つきの一覧を見て消す（2026-10-27 に消した `.tmp/opencode/` は、docs に実測値を残してある） | 段 6 |
| U10: 他のリポジトリ | `tmp_clean.py` は、共通の場所に配る（chezmoi）。pi のハーネスは、どの作業ツリーでも、同じ規則で動く。**自動で消すのは、自分が作った `s/` と、既知の再生成できる名前だけ**なので、リポジトリごとの設定は要らず、他のリポジトリの未知の `.tmp/` を壊さない（レビュー R1-1）。年齢による一括の削除は、手動のときだけ | 段 2・3 |
| U11: Windows | `TMPDIR` の代わりに `TEMP`・`TMP`。段 3 の後に別に扱う | 段 3 の後 |
| U12: 終了の待ち合わせ | `closeAll()`・`bg_run` の停止は、SIGTERM を送って管理から外すだけで、終了を待たない（`activity/index.ts:53-65,173-181`、`children.ts:566-568`）。**置き場を消す前に、停止要求した子・ジョブのプロセス群の終了を最大 3 秒待ち、生き残りがいれば、その置き場を消さない**（死亡所有者の回収が、後で消す）。拡張のハンドラの実行順が決まっていないので、ハーネスが `activity` の停止を明示的に呼ぶか、待ち合わせを自前で持つ。レビュー R1-3 | 段 3 |
| U13: `.tmp` を巻き込む削除の許可 | 判定器は今、`rm -rf .tmp`・`find .tmp -delete` を scratch 免除で通す（`docs/spec/guard/agent-command-policy.md:334-336,366-378`、`judge/shared.ts:275-283`）ので、`keep/` と運用の置き場が一緒に消える。**実装で分かった衝突**: 免除の判定（`resolvesIntoScratch`／Python 版 `_resolves_into_scratch`）は、`.tmp` 自身も配下も同じ「scratch の中」として扱い、`find .tmp -name '*.log' -delete` のような頻出の形も同じ関数を通る。**`.tmp` 自身を対象にする削除を ask にすると、`find .tmp ... -delete` も止まる**（`keep/` の中の同名のファイルを消す形と、コマンドの解析では区別できない）。選択肢: (a) `.tmp` 自身・`keep` 配下を対象に含む削除を ask にし、`find .tmp ... -delete` の頻出の形も止める（確実。使い勝手が下がる） (b) `rm -rf .tmp`（`-r` で `.tmp` 自身を指定）だけを ask にし、`find` は許す（`keep/` の個別の削除は残る） (c) 判定器は変えず、`keep/` を `.tmp` の外（例: リポジトリごとの `.git/info/` の隣など）へ置く。**判断が要る**（Python 版と TS 版の両方・試験・golden の更新が要る）。レビュー R1-4 | 段 6（利用者の判断待ち） |
| U14: 子の zsh が `TMPDIR` を戻す | `.zshenv` の `_tmpdir_repo_local_update` が、子の zsh でも `TMPDIR` を `<repo>/.tmp` に設定し直す（`home/dot_zshenv:55-78`）。**`TMPDIR` が既に `<repo>/.tmp` の配下なら、そのまま維持する**。bash ツールは bash なので影響は小さいが、zsh を起動するコマンドで差が出る。レビュー R1-8 | 段 6 |
| U15: 自動削除の境界（置き場の祖先のリンク・検査後の置換・マウント） | 自動で消すのは、`.tmp/s/<名前>` と、既知の名前の直下の項目だけ。**`shutil.rmtree`（Linux では fd を使う安全版）を使い、`.tmp`・`s`・対象自身がシンボリックリンクなら拒否し、`.tmp` と別のデバイス（マウント）は降りない**。`chmod` の再試行は、対象の中に限る。検査できない環境では、自動削除をしない。レビュー R1-5 | 段 2 |

## 次の調査・実験

1. （済）**`TMPDIR` の受け渡し**（U8）: bash は受け取る（「現在地」の「実験の結果」）。**未確認**: `bg_run`・`guarded_task` の子が、実際に受け取るか（コードの上では受け取る）
2. （一部済）**`session_shutdown` の実機**: EOF・SIGTERM・SIGHUP・SIGKILL・SIGINT は、済。**未確認**: 対話モードでの `quit`（Ctrl+C・Ctrl+D・`/quit`）・`/new`・`/resume`・`/fork`・`reload`（`reason` の値と、置き場の消える・残るの切り替え）、`-p` の子
3. **`pis` の内側で、何もしないこと**（`PI_HARNESS_BOUNDARY=1`）を確かめる。内側の `TMPDIR=/tmp` が、そのままであること
4. **テストの残骸**（段 4）: `tools_ext_driver.mjs` を直したあとの、`.tmp/` の件数の増減を、`mise run verify:all` の前後で数える

## 評価基準

**必須**:

1. **`quit`** で、そのセッション（この実行）が作った `.tmp/s/<ID>/` が、すべて消える。**`reload`・`new`・`resume`・`fork` では消えない**（会話が旧置き場のパスを参照し続けるため）
2. 異常終了（SIGKILL・クラッシュ）の後の次の起動で、**持ち主の死亡を確証できた** `s/<ID>/` だけが消える。生きているセッション・確証できないもの・`.owner` が不完全なもの・7 日を超えても生きている持ち主のものは、消さない。同時に起動した 2 つのセッションが、互いの置き場を消さない
3. `.tmp/keep/` と、運用の置き場（`research/`・`review-loop/`・`away-shift/`・`subagents/`・`worktrees/`・`checkpoint-*`）は、自動の掃除でも、エージェントの `rm -rf .tmp`・`find .tmp -delete` でも、確認なしには消えない（判定器の試験。U13）。**未知の名前は、自動では消えない**（一覧に出るだけ。U1・U9）
4. 非隔離の子は親の `TMPDIR` を使い、自分で `s/` を作らない。隔離子は `/tmp`（既存の境界）のまま。親の置き場は隔離子に書込許可されない。`quit` の削除は、停止要求した子・`bg_run` のプロセス群の終了を確かめてから行い、生き残りがいれば消さない（U12）
5. `pis` の内側では、置き場を作らず、`TMPDIR=/tmp` のまま
6. `mise run verify:all` の前後で、`.tmp/` の直下の件数・容量が増えない（テストの残骸が無い）
7. `tmp_clean.py` の自動の削除は、`.tmp`・`s`・対象自身がシンボリックリンクなら拒否し、マウント境界を降りず、`.tmp` の外へ出ない（検査後の置換・外側の番兵ファイルで試験。U15）

**望ましい**: 他のリポジトリでも、配備だけで動く。掃除の結果（件数・容量）が、起動時に 1 行で見える

## 候補比較

| 候補 | 支持する根拠 | 不利な点・反証 | 未検証点 | 扱い | 次の確認 |
| --- | --- | --- | --- | --- | --- |
| A: 年齢だけで消す（起動時・タイマー） | 実装が単純。`tmp_clean.py` で既にできる | 取り込む前のものが、年齢で消える。今回の 31 GB は、持ち主が分からない残骸の蓄積だった | — | 段 2 の安全網としてだけ採用 | — |
| B: 持ち主（セッション）の置き場を分け、終了時に消す + 起動時の保険 | 持ち主が明確。取り込むものは外へ。終了で消えるので、溜まらない | `TMPDIR` を向け直す実装が要る。pi 以外の CLI には効かない | `TMPDIR` の受け渡し・`session_shutdown` の実機 | **有望（提案）** | 次の調査・実験 1〜3 |
| C: `.zshenv` の `TMPDIR` の誘導をやめ、`/tmp`（OS の掃除に任せる） | 残骸が OS の掃除に任される | Claude Code の sandbox は `/tmp` に書けないことがある。誘導の理由が失われる | Claude の挙動 | 見送り | — |
| D: systemd タイマー・タスクスケジューラで巡回 | 取りこぼしが無い | 常駐の仕組み・対象の一覧・Windows 対応が要る。年齢だけで消す（A と同じ弱点） | — | 見送り | — |
| E: 掃除は手動（`mise run tmp:clean`）のみ | 副作用が無い | 忘れると溜まる（今回の 31 GB の実績） | — | 段 2 の補助として採用 | — |

扱い: 未評価 / 検証中 / 有望 / 採用 / 保留 / 見送り

## 仕様への変更案

| 変更対象 | 変更前 → 変更後 | 理由・証拠 | 適用結果 |
| --- | --- | --- | --- |
| `docs/spec/guard/pi-extensions.md`（または pi-guard.md の該当節） | `session_shutdown` で `.tmp/s/<ID>/` を消す・`TMPDIR` の向きを書く | 段 3 | 未適用 |
| `docs/spec/shell.md`（zsh の `TMPDIR` の誘導） | pi のセッションの中では、`.tmp/s/<ID>/` に向き直ることを追記 | 段 3 | 未適用 |
| `docs/spec/guard/agent-command-policy.md`（使い捨てディレクトリ `./.tmp` の削除） | `s/` と `keep/` の区別を追記 | 段 6 | 未適用 |
| `home/.chezmoitemplates/agent-instructions.md` | 「スクラッチは `$TMPDIR`」「取り込み待ちは `.tmp/keep/`」 | 段 6 | 未適用 |
| `docs/spec/development.md`（`mise run tmp:clean`） | タスクの一覧に追記 | 段 2 | 未適用 |

## 実装・検証

（採用が決まった段から具体化する。段 2 の原型 `scripts/tmp_clean.py` は、2026-10-27 に、実際に 573 件・28.5 GB を消した。dry-run が既定で、保護の規則・シンボリックリンクの拒否を持つ）

## 重要な更新

| 日付 | 更新 | 理由・証拠 |
| --- | --- | --- |
| 2026-10-27 | 案件を起票 | `.tmp/` が 31 GB に膨らんでいた。利用者が、「取り込むものがあるので、セッションの終わりに掃除する方がよい」「フォルダ分けは良い方針」と判断した。探索の子 3 本が、`TMPDIR` の経路・pi の終了イベント・`.tmp/` に書く主体を調べた |
| 2026-10-27 | **`review`（`gpt-6.1-terra`。改善案つき）の 1 回目を反映した**。BLOCKER 2・MAJOR 6・MINOR 1 | **(R1-1) 自動で消すのは、自分が作ったと確かめられるものだけ**（確証できる `s/` と、再生成できる名前）に変え、未知の名前は一覧だけにした。**(R1-2) `s/` を年齢だけで消す規則を撤回**し、死亡の確証（同じ PID namespace・pid の不在または開始時刻の違い）に限った。排他は `mkdir` と `.sweep.lock` **(R1-3)** 終了前に、停止要求した子・ジョブの終了を待つ（U12）**(R1-4)** `rm -rf .tmp` が `keep/` を巻き込まないよう、判定器を直す（U13）**(R1-5)** 自動削除の境界（U15）**(R1-6) `quit` のときだけ消す**に変え、`new`・`resume`・`fork` では消さない（会話が旧パスを参照し続けるため）。`bg_log` は実際のログのパスを保持する **(R1-7)** 隔離子は `/tmp` のまま（U1）**(R1-8)** 子の zsh の `TMPDIR`（U14）・指示の条件つき化 **(R1-9)** 回収は、毎起動の `s/` のみ。年齢の一括の削除は手動 |
| 2026-10-27 | **段 2・3・4・6（一部）を実装した**（未コミット） | 段 4: 残骸の発生源を直し、`test/agents` を実行した後の `.tmp` に残骸が 0（以前は 63 + 約 35 件、`pytest-of-*` 5 GB）。段 2: `tmp_clean.py` を、自作のものだけを自動で消す形に作り直し（`s/` は死亡を確証できたものだけ・未知の名前は一覧のみ・`.sweep.lock`・リンク非追跡・別デバイスに降りない・読み取り専用の中身も消す）、試験 27 件。段 3: `session-tmp.ts` と配線（`quit` のときだけ消す・生き残りを待つ・起動時の回収）、`activity` が完了したジョブのログのパスを保持、試験（表試験 9 項目）。段 6: 共通の指示（`$TMPDIR`・`.tmp/keep/`）と `.zshenv`（試験 5 件）。**実装で分かったこと**: node の型除去（strip-only）は、コンストラクタの引数プロパティ（`private readonly x`）を扱えない。ハーネスの試験の幾つかは、ハーネスのファイルを 1 つずつコピーするので、新しいファイルの追加で全部落ちた（`session-tmp.ts` を追加）。判定器（U13）は未着手 |
