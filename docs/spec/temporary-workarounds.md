# 一時対処の一覧

上流（外部ソフトウェア・プラットフォーム）の不具合を避けるために入れた、**いずれ消す**対処の台帳。
一時対処はここに 1 件ずつ登録し、撤去の条件を必ず書く。

## 約束

- コード側の対象（スクリプト・設定・テスト）には `TEMP-REMOVE` を付ける。
  棚卸しは `grep -rn TEMP-REMOVE .`（`.git` を除く）で一覧できる
- 一時対処を足したら、この文書に行と小節を足す。詳細（原因・出典・実測・撤去手順）は小節が正本で、
  コードのコメントは `TEMP-REMOVE` とこの文書への参照だけにする
- 上流が直ったか、不要になったら、コード・テスト・この文書の行と小節を全て消す

## 一覧

| 項目 | 対象 | 撤去の条件 |
| --- | --- | --- |
| [pwsh 7.6.x の更新通知クラッシュ](#pwsh-76x-の更新通知クラッシュ) | `300_windows/run_after_351_pwsh_update_check_off.ps1` | 修正版の pwsh が出て、通知が出ても落ちないと確認できたとき |
| [pi-permission-system の cd 先の誤判定](#pi-permission-system-の-cd-先の誤判定) | `agent-instructions-stock.md` の「確認（ask）」の 1 行（`cd` は絶対パスで書く） | `@gotgenes/pi-permission-system` の修正版が出て、再実験で `cd ~/…` の誤判定が消えたと確認できたとき |

## pwsh 7.6.x の更新通知クラッシュ

PowerShell 7.6.6 は、新版（7.6.7）の更新通知を出すときに `PadRight` の幅が負になり、起動直後に落ちます
（`totalWidth ('-10') must be a non-negative value`）。日本語・中国語ロケールで起きます。落ちると
chezmoi の `.ps1` も走らず、プロファイルも読まれません。

`351_pwsh_update_check_off` が User の環境変数 `POWERSHELL_UPDATECHECK=Off` を設定します（冪等）。
これは更新通知だけを止め、pwsh の更新は止めません。起動済みのプロセスには効かないため、
Zed などは完全に再起動します。既に落ちる PC では、`powershell.exe`（5.1）で `setx POWERSHELL_UPDATECHECK Off` を
1 回実行してから `chezmoi apply` します。

- 出典（2026-10-21 取得）: <https://github.com/PowerShell/PowerShell/issues/28131>（ja-JP の報告と回避策）、
  [#28235](https://github.com/PowerShell/PowerShell/issues/28235)、
  [#28239](https://github.com/PowerShell/PowerShell/issues/28239)
- 実測: 家の PC（ja-JP、pwsh 7.6.6）で、`setx` 後に起動できることを確認。chezmoi スクリプトとしては Windows 実機で未検証
- 反例・未確認: 修正された版は未確認（7.6.7 のソースにも同じ計算が残るという報告が #28237 にある）
- **撤去**: `home/.chezmoiscripts/300_windows/run_after_351_pwsh_update_check_off.ps1`、
  `test_windows_assets.py` の `test_pwsh_update_check_is_disabled`、この小節と一覧の行を削除する。
  各 PC に残る User 環境変数は `[Environment]::SetEnvironmentVariable('POWERSHELL_UPDATECHECK', $null, 'User')` で消す

## pi-permission-system の cd 先の誤判定

`@gotgenes/pi-permission-system` 42.0.0 は、`cd` の行き先を `~`（`cd ~/…`）や変数（`cd "$DIR"`・`cd $W`）で書くと、
行き先を「不明」として扱い、後続の相対パスをセッションの cwd に結合して判定します。結果は 2 つです。

- **誤った確認（ask）**: cwd に結合した実在しないパスが、作業ツリーの外と判定される。
  `cd ~/<プロジェクト>/docs && ls ../README.md` は、`<プロジェクトの 1 つ上>/README.md` について確認が出る
- **判定の見落とし**: 相対パスが `path` 規則の候補から落ちる。絶対パスで書いた deny（`~/.pi/agent/auth.json` など）は、
  `cd ~/.pi/agent && cat auth.json` では適用されない可能性がある。`cd` の行き先自体は外部ディレクトリとして確認が出るが、
  YOLO が入っていると自動承認になる。pib の囲い（`runner.toml` の `hide`）が同じ秘密を隠す設計だが、囲いが効いているかは未確認。
  名前だけの規則（`*.env` など）は、候補に残った表記（`.env`・`./config.env`）には適用されるが、
  素の名前（`config.env`）は候補から落ちる

対処は、`agent-instructions-stock.md` の「確認（ask）」に「`cd` は絶対パスで書く（または `git -C`）」の 1 行を足したことだけです。
パッケージは改造しません。配備先 `~/.pi/agent/npm/` は書き込みが deny で、版を上げると上書きされ、維持費が見合わないため
（[ADR-0031](../adr/0031-evaluate-existing-extensions-first.md)）。

- 分類: `cd ~/…` は上流がバグと認めている（修正は PR で提案済み・未マージ）。`cd "$VAR"` は上流の docs が
  「意図して解決しないもの（deliberately does not resolve）」と書く現行の仕様で、修正の予定は出典から読み取れない
- 出典（2026-11-14 取得）:
  [#1083](https://github.com/gotgenes/pi-packages/issues/1083)（2026-10-24 起票、11/1 に `bug`、open）、
  [PR #1084](https://github.com/gotgenes/pi-packages/pull/1084)（open・未マージ。コメント 0 件）、
  同じ症状の報告 [perrin4869/dotfiles#6857](https://github.com/perrin4869/dotfiles/issues/6857)、
  拡張の docs の configuration.md の「What it deliberately does not resolve」。npm の最新は 42.0.0（2026-10-28 公開）で、手元と同じ
- 実測（2026-11-14、YOLO を切った実際のゲート。cwd はプロジェクトの根）:

  | 条件 | コマンド（要点） | 結果 |
  | --- | --- | --- |
  | A | `cd <絶対パス>/docs && ls ../README.md` | 実行された |
  | B | `cd ~/…/docs && ls ../README.md` | 確認が出た（対象は実在しない `…/README.md`） |
  | C | `cd ~/…/docs && ls index.md` | 実行された（素の名前は判定の入力から落ちるため、外部とも判定されない） |
  | D | `cd <絶対パス>/docs && ls ~/.config/opencode` | 確認が出た（`cd` ではなく別のパスが原因） |
  | E | `W=<絶対パス>/docs; cd $W && ls ../README.md` | 確認が出た（B と同じ誤ったパス） |

- 実測（オフライン）: 下の再実験で、`cd <絶対パス> && cat auth.json` の候補は `[<絶対パス>, 'auth.json']`、
  `cd ~/.pi/agent && cat auth.json` の候補は `['~/.pi/agent']` だけだった。
  `cd ~/…/home` の後は、`.env`・`./config.env` は候補に残り、`config.env`・`index.md`（素の名前）は落ちた
- 反例・未確認: A・C は実行されたことだけを見た（確認が出なかったかは、レビューログで未確認）。
  deny が実際に効かないかは、ゲート全体では実行していない（候補から落ちるところまで）。
  Windows・macOS など他の機械での挙動は未確認

### 再実験

拡張の内部 API を読み込むだけで、コマンドは実行しない（版が変わって動かなければ、実際のゲートで確かめる）。

```js
// node repro.mjs（YOLO の状態に関係なく動く）
const H = process.env.HOME;
const root = `${H}/.pi/agent/npm/node_modules/@gotgenes/pi-permission-system/`;
const { createJiti } = await import(`${H}/.pi/agent/npm/node_modules/jiti/lib/jiti.mjs`);
const jiti = createJiti(root + "src/index.ts", { interopDefault: true, alias: { "#src": root + "src" } });
const { BashProgram } = await jiti.import(root + "src/access-intent/bash/program.ts");
const { PathNormalizer } = await jiti.import(root + "src/path/path-normalizer.ts");
const { posixPathFlavor } = await jiti.import(root + "src/path/path-flavor.ts");
const norm = new PathNormalizer(posixPathFlavor, process.cwd());
for (const c of [`cd ${H}/.pi/agent && cat auth.json`, "cd ~/.pi/agent && cat auth.json"]) {
  const p = await BashProgram.parse(c, norm);
  console.log(c, "→", p.pathRuleCandidates().map((x) => x.token));
}
```

直った印は、2 行目の候補に `auth.json` が載ること。実際のゲートでは、`cd ~/<プロジェクト>/docs && ls ../README.md` が確認なしで実行されること。

- **撤去**: 上流の CHANGELOG に #1083 の修正が入った版が出たら、その版を `pi-stock-packages` で上げて、上の再実験で直ったことを確かめる。
  その後、次を消す。
  - `home/.chezmoitemplates/agent-instructions-stock.md` の `TEMP-REMOVE` の行。ただし `cd "$VAR"` は上流の仕様として残る
    （確認が出るだけで誤りではない）ので、行ごと消すか `$VAR` の注意だけに縮めるかは、そのとき利用者に確認する
  - `test/test_pi_stock_config.py` の `test_stock_agents_md_asks_for_absolute_cd_until_upstream_fix`
  - `agent-config-generation.md` の「確認で待たせない方針」④の括弧書き
  - この小節と一覧の行
