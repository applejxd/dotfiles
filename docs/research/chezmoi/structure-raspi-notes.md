# Raspberry Pi 向け導入の観測メモ（clang の標準ヘッダ）

> `docs/spec/structure.md` の次の節から移した記録。移設時点で再測定していない。現在の仕様は各節（下記）を参照。

- **観測日**: 2026-10-01 / 2026-10-05（各節の本文の日付が正）
- **問い**: clang が C++ の標準ヘッダを見つけられなかった状態と、gcc の triplet から版を推測する方式を採らない理由は何か
- **根拠**: 各節の本文（元の文のまま。URL・コマンドを含む）

## gcc の triplet から版を推測する方式を採らない理由（conda の gcc）

元の節: `docs/spec/structure.md` の「ruby…clang が C++ の標準ヘッダを見つけられるようにする」

gcc の triplet から `/usr/lib/gcc/<triplet>/` の最新版を推測する方式は採りません。
clang の選択と一致する保証が無く、conda の gcc が PATH の先にあると
`gcc -dumpmachine` が `x86_64-conda-linux-gnu` を返して存在しないディレクトリを
探すためです（2026-10-05 に観測）。

## 標準ヘッダが見つからない状態の観測

元の節: `docs/spec/structure.md` の「clang が C++ の標準ヘッダを見つけられるようにする」

2026-10-01 に WSL（Ubuntu 24.04）で観測しました。`libgcc-14-dev` があり
`libstdc++-14-dev` が無い状態で、Ubuntu の clang 18 も同じエラーを出しました。
