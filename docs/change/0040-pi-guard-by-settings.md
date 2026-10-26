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
4. `~/.pi/agent/settings.json`・`extensions/**`・`~/.config/pi/harness/**` を書き込み拒否にする（`mcp.json` は、モデルが書いてよいので拒否しない。警告の対象）。拡張は chezmoi から配る。`settings.json` を直接書く必要は小さい（生成器が持つキーは `[pi.settings]` が正本。ほかは pi 自身か `/settings`）。
5. Orca の状態表示の拡張は、設定へ名前で足す（印の確認はしない。書き込み拒否で補う）。
6. `pis --no-sandbox` は、差が解消するまでの移行用に残し、いずれ廃止する。

## 実測と調査

- 設定だけで、フラグ無しの `pi` が `pis --no-sandbox` と同じツール構成になる（Linux・pi 1.3.0）。`!extensions/**` で自動検出の拡張が外れる。
  `pis` 型のフラグとの併用は二重にならない。同じ拡張を設定と `-e` の両方で読むと衝突して起動に失敗する。
  拡張のパスが無いとツール無し（安全側）、`rules.json` が壊れていると起動に失敗する。
- 独立レビュー（`review`）の指摘のうち、信頼の拒否が保存済みの許可に負けること・`mcp.json` が判定の外であること・設定とコードの書き込み拒否が無いこと・Orca の拡張が外れることを、上の決定で扱った。
- Windows の調査（コードを読んだだけ。実機は未検証）: フルガードは `.chezmoiignore` で配られない／`rules.json` を Windows で生成したことがない／子エージェントが負の PID と `pi.cmd` に依存する／MSYS のパスの扱い（`rm.ts` ほか）／整形 hook が `bash` に依存する。
  境界を除いた要件（判定とツールだけ）では、見送りの理由のうち「子エージェント」「パス」「配備」が残る。

## 次の段（Windows）

- 配備の除外を外し、`rules.json` を生成する。`guarded_task`・隔離・`reconcileOnStart` は Windows では登録しない。
- MSYS のパス（`/c/Users/...`）の補正、整形 hook の `bash` の探し方。
- PowerShell ツールは `defaultTools = []` で登録されない。
- Windows 実機での通し（`pi` の起動、`guarded_bash` / `guarded_read`）。

## 未確認

- Orca・Zed の実機での起動と状態表示。
- `mcp.json` の警告・作業先の `.pi/` の警告の TUI での表示。
- 書き込み拒否が、シェルの経由で破られないか（Fence の無い素の `pi` ではガードだけ）。
