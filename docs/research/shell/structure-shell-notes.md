# シェル・VS Code まわりの経緯メモ（structure.md から移設）

> `docs/spec/structure.md` の次の節から移した記録。移設時点で再測定していない。現在の仕様は各節（下記）を参照。

- **観測日**: 2026-10 ほか（各節の本文の日付が正）
- **問い**: シェルの起動契約・code-exam・VS Code の拡張で、採らなかった案と廃止の経緯
- **根拠**: 各節の本文（元の文のまま。URL・コマンドを含む）

## シェルの起動契約で採らなかった案

元の節: `docs/spec/structure.md` の「シェルの起動契約」

参考にした記事（tellme.tokyo の AI-first dotfiles）のうち、Nix 化・`rm` を `gomi`
に差し替える alias・`is_human` による人間判定は採らない。それぞれ、導入物の管理を
mise に統一している方針と合わない、標準コマンドの意味を変えない方針（3）と
合わない、判定を環境変数の列挙に頼るため（2）である。

## VS Code の拡張導入スクリプトを廃止した理由

元の節: `docs/spec/structure.md` の「VS Code の拡張」

拡張導入スクリプト（旧 `112` / `340`）を廃止した理由:
拡張の一覧が Linux 約 30 個・Windows 約 10 個で食い違い、実際に使う拡張（ある WSL で 53 個）と
大きくずれていた。112 は WSL と Raspberry Pi では動かず（`110_native/` を除外）、
ネイティブ Ubuntu のデスクトップだけが対象だった。最近 VS Code を使うことも減った。

## code-exam で `--user-data-dir` を採らない理由

元の節: `docs/spec/structure.md` の「コーディング試験の練習用 VS Code（code-exam）」

- `--user-data-dir` で設定ごと分ける案は採らない。WSL の `code` は
  remote CLI を経由し、`user-data-dir` を Windows 側へ渡さずに捨てる
  （VS Code の `src/vs/server/node/server.cli.ts` の `isSupportedForCmd`）。
  `Code.exe` を直接呼べば回避できるが、VS Code の内部の起動手順に依存する。
  `--profile` は WSL からも渡る
