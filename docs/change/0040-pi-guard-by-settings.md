# CHG-0040: pi のフルガードを設定で載せ、pis をサンドボックス専用に寄せる

- **状態**: Exploring
- **更新日**: 2026-10-26
- **基準**: pi 1.3.0。設定（`~/.pi/agent/settings.json`）での読み込みは Linux で実測

## 背景

`pis` が、フラグ（`--no-approve -nbt -ne -e builtin:mcp` と `-e` でフルガード）で pi にフルガードを載せていた。
素の `pi`（Orca・Zed・PowerShell）はガード無しで、起動の入口が 2 つに分かれ、説明も複雑だった。
利用者の要望は「`pis` はサンドボックスだけを残し、サンドボックス無しの操作は `pi` に統一する」。

## 決めたこと（利用者の決定、2026-10-26）

1. **Unix を先に統一し、Windows は次の段で。**
2. 素の `pi` に、`~/.pi/agent/settings.json` でフルガードを載せる（`extensions`・`defaultTools = []`）。`pis` のフラグは変えない（`-ne` が設定を無効にするので二重にならない）。
3. **作業先の信頼（project trust）は、素の `pi` では既定の確認のまま使う。** 拒否は `pis` の `--no-approve` に寄せる。信頼したときに読まれる `.pi/` の拡張・MCP・設定と、`mcp.json` のサーバは、**止めずに警告する**。作業先のスキルは警告しない（多用するため）。
4. `~/.pi/agent/settings.json`・`mcp.json`・`extensions/**`・`~/.config/pi/harness/**` を書き込み拒否にする。（一度は `mcp.json` を書き込み可にしたが、サーバの `command` は次の起動でガードの外で動くため、ガードを外せる制御ファイルとして拒否に戻した。2026-10-26）拡張は chezmoi から配る。`settings.json` を直接書く必要は小さい（生成器が持つキーは `[pi.settings]` が正本。ほかは pi 自身か `/settings`）。
5. Orca の状態表示の拡張は、設定へ名前で足す（印の確認はしない。書き込み拒否で補う）。
6. `pis --no-sandbox` は、差が解消するまでの移行用に残し、いずれ廃止する。

## 実測と調査

- 設定だけで、フラグ無しの `pi` が `pis --no-sandbox` と同じツール構成になる（Linux・pi 1.3.0）。`!extensions/**` で自動検出の拡張が外れる。
  `pis` 型のフラグとの併用は二重にならない。同じ拡張を設定と `-e` の両方で読むと衝突して起動に失敗する。
  `rules.json` が壊れている・無いと起動に失敗する（終了コード 1。`pi -ne` で拡張無しに起動できる）。
  （訂正）当初は「拡張のパスだけが無いときはツール無しで起動する」と書いたが誤り。`defaultTools = []` は組み込みツールだけを無効にするので、自作の拡張の `bg_run`（shell）が判定なしに残る。独立レビューで見つかり、印 `globalThis.__PI_FULL_GUARD__` が無いと `bg_run` と `task` を実行しないようにした。
- 独立レビュー（`review`）の指摘のうち、信頼の拒否が保存済みの許可に負けること・`mcp.json` が判定の外であること・設定とコードの書き込み拒否が無いこと・Orca の拡張が外れることを、上の決定で扱った。
- Windows の調査（コードを読んだだけ。実機は未検証）: フルガードは `.chezmoiignore` で配られない／`rules.json` を Windows で生成したことがない／子エージェントが負の PID と `pi.cmd` に依存する／MSYS のパスの扱い（`rm.ts` ほか）／整形 hook が `bash` に依存する。
  境界を除いた要件（判定とツールだけ）では、見送りの理由のうち「子エージェント」「パス」「配備」が残る。

## 次の段（Windows。下の「Windows」節で実装済み。実機は未検証）

- 配備の除外を外し、`rules.json` を生成する。`guarded_task`・隔離・`reconcileOnStart` は Windows では登録しない。
- MSYS のパス（`/c/Users/...`）の補正、整形 hook の `bash` の探し方。
- PowerShell ツールは `defaultTools = []` で登録されない。
- Windows 実機での通し（`pi` の起動、`guarded_bash` / `guarded_read`）。

## 未確認

- Orca・Zed の実機での起動と状態表示。
- `mcp.json` の警告・作業先の `.pi/` の警告の TUI での表示。
- 書き込み拒否が、シェルの経由で破られないか（Fence の無い素の `pi` ではガードだけ）。

## Windows（2026-10-26、実装。実機は未検証）

- 設定で載せる（Unix と同じ `extensions`・`defaultTools = []`）。`guarded_task`・隔離・`reconcileOnStart`・Landlock は Windows では無効（`platform.ts`）。読み取り専用の `task`（subagents 拡張）は明示ロード。
- 整形 hook は Git Bash を探す（WSL の `System32\bash.exe` は選ばない。見つからなければ 1 回だけ知らせる）。`~\` を展開する。判定器は MSYS（`/c/Users/...`）と Windows 形式のホームを同じものとして扱う。
- MCP は Unix と同じく `rules.json` から登録する（`mcp.json` へ書く `pi-mcp` は廃止。`mcp.json` 由来のサーバは判定の外なので、書かず、書かせない）。
- `bash` は Git Bash（PowerShell ツールは登録しない）。PowerShell のコマンドは bash から呼ぶ形になる。
- **載るもの**: 判定・ガードツール・伏字化。自作の拡張（`activity`・`ask`・`btw`・`delegate-nudge`・`notify`・`plan`・`todo`）も settings で明示ロードする。`commit-confirm` は settings から外した（フルガードに `git commit` の確認があるため。Unix も同様）。`pis` と ocs は Windows に配らない。
- **`task` の子はフルガード付きで起動する**（役割 reader）。置き場 `~/.config/pi/harness` が読めなければ、子を起動せず理由つきで失敗する。親に印が無ければ `task` を実行しない。`activity` の `bg_run` も印が無ければ実行しない。`bg_run` は `spawn(shell:true)`（Windows では cmd）で、`taskkill` で止める。
- **パス**: win32 では MSYS・WSL 形式（`/c/...`・`/cygdrive/c/...`・`/mnt/c/...`）、Windows 形式（`C:\Users\x`・`C:/Users/x`）、`~`、`$HOME` を同じホームとして、ホーム固定の deny glob と `rm` のホーム全削除に当てる。非 win32 の判定は変えていない。bash コマンド内のパスの deny は別の表（`judge/rules_files.ts`・`sensitive.ts`）で、形式に依らず検出する設計だが、実機での最終判定は未確認。
- **制御ファイル**は、ファイルツールの `write_deny_globs` に加えて、bash 経由（リダイレクト・`mv` / `cp` / `rm` / `tee`・インラインコード）の書き込みも拒否する（`judge/rules_guard.ts` の `GUARD_TARGETS`。試験は `test_pi_control_files_bash.py`）。`mcp.json` のサーバは判定の外なので、利用者が端末で足したものは起動時に警告する（`harness/unguarded.ts`）。
- **残る限界**: 境界（Fence）が無くサンドボックスの保護は付かない（判定・ツール・伏字化だけ）、シェルは Git Bash（PowerShell は bash から呼ぶ）、`guarded_task` と隔離は無い（次の段）、実機は未検証。
- **未確認（実機）**: `chezmoi apply` 後の `rules.json` の生成（`py -3`）、フラグ無しの `pi` で `guarded_*` だけが出ること、`task` の動作とフルガード付きの子の起動、Git Bash の探索、整形 hook、`bg_run` の cmd での動作と `taskkill`、MSYS・Windows パスの deny、ガードを欠いた起動で `bg_run` / `task` が拒否されること。確認項目の一覧は [pi-guard の実機で確認する項目](../spec/guard/pi-guard.md#実機で確認する項目)。

## 実機で確認する項目（旧 pi-guard.md から移設）

> `docs/spec/guard/pi-guard.md#実機で確認する項目` から移した。移設時点で再確認していない。Windows の項目は、このチェックリストが現行の確認先。

自動試験では確かめられず、実機の pi で見るもの。確かめたらチェックを入れ、結果と日付を添える。
すべて `chezmoi apply` して新しいセッションで確かめる。

- [ ] **ジョブ終了のフィードバック**（`activity`、`20507a0`）: 2026-10-20 に実機（`pis`、このセッション）で、アイドル時の自動再開と、
  作業中に終わった分がそのターンの後に届くことを確認した。さらに同日、RPC の使い捨てセッション（実モデル 4 つ、[B1](../research/agents/pi-bg-experiments.md)）で、
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
- [ ] **`review` のモデル**: `guarded_task` の `review` が実際に親と違うモデル（Copilot なら `second_opinion` の `gpt-6.1-terra`。2026-10-27 に `gpt-6-sol` から変えた）で
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

### Windows（すべて未確認）

Windows 実機（PowerShell）で次を確かめる。WSL では描画・静的な試験・Node のドライバ試験しかできない。

- [ ] `chezmoi apply` 後に `~/.config/pi/harness/rules.json` が生成される（`py -3`）。`~/.pi/agent/settings.json` に `extensions`（subagents を含む）と `defaultTools = []` が入る
- [ ] フラグ無しの `pi` で、モデルに見えるツールが `guarded_*` と自作の拡張のものだけ（組み込みの `bash` などが出ない）
- [ ] `task`（読み取り専用の子）が動く。子がフルガード付きで起動し、置き場が読めないときは理由つきで失敗する
- [ ] Git Bash の探索: 標準の場所と、PATH 上の `git.exe` から導く場合。WSL の `System32\bash.exe` を選ばない。見つからないとき 1 回だけ知らせる
- [ ] 整形 hook が Git Bash の `bash.exe` で動く（`~\` の展開を含む）
- [ ] `bg_run` が cmd で動き、`bg_kill` の `taskkill` でプロセスの木ごと止まる
- [ ] MSYS（`/c/Users/x`）・Windows（`C:\Users\x`）形式のパスと `~`・`$HOME` が、ホーム固定の deny glob と `rm` のホーム全削除の検出に当たる。bash コマンド内の `.ssh` / `id_rsa` が検出される
- [ ] 制御ファイル（`settings.json`・`mcp.json`・`extensions/**`・`harness/**`）への bash 経由の書き込みが拒否される
- [ ] ガードを欠いた起動（ガードのパスが無い設定）で、`bg_run` と `task` が拒否される
- [ ] MCP が `rules.json` から登録され、`mcp.json` のサーバは起動時に警告される
- [ ] `pi mcp add` など `mcp.json` を書く操作が、モデルからは拒否される
