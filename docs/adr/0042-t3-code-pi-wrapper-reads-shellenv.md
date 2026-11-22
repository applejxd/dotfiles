# T3 Code が起動する pi には、shellenv.sh を読む wrapper（pi-t3）で環境変数を渡す

- **ステータス**: Accepted
- **日付**: 2026-11-22
- **決定者**: applejxd（2026-11-22 に、方針 (B)（wrapper が `shellenv.sh` を読む）の実装を、利用者がこのスレッドで指示した。t3code の保守側の調査で決めた方針を引き継いだもの）
- **関係**: [ADR-0031](0031-evaluate-existing-extensions-first.md)（自作は最後の手段。理由・維持費・撤去条件の記録と、利用者の承認）に従う自作 1 件。仕様は [シェル](../spec/shell.md#t3-code-から起動する-pi-の入口-pi-t3)。

## コンテキスト

- T3 Code（Windows のデスクトップが、WSL 内のサーバを起動する構成）が起動する pi の環境変数に、`~/.config/shell/userenv.sh` で export している `HF_HOME` が入らない（この機の pi で、`HF_HOME`・`LC_ALL` が unset、`LANG`・`DISPLAY`・`__MISE_DIFF` が set であることを 2026-11-22 に確認した）。
- 原因（t3code 側の調べ。この repo では未確認）:
  - デスクトップは `wsl.exe --exec env PATH=… <t3> --bootstrap-fd 0` でサーバを起動し、login シェルを通らない（`apps/desktop/src/backend/DesktopBackendConfiguration.ts` の `resolveWslStartConfig`）。
  - サーバが起動時に 1 回だけ `$SHELL -ilc` から取り込むのは `PATH`・`__MISE_DIFF`・`JAVA_HOME` だけ（`apps/server/src/os-jank.ts:35`）。
  - Pi の起動・状態確認・text generation は、いずれも `binaryPath || "pi"` をシェルを介さず直接起動する（`packages/provider-pi/src/server/adapter.ts` など）。
- 値の生成が、条件つきでシェル側にある。`shellenv.sh.tmpl:68-70` の `AWS_REGION` は `applejxd` 以外のユーザーだけ。CUDA の `LD_LIBRARY_PATH` は存在確認つきで、WSL の `/usr/lib/wsl/lib` は未登録なら足す。`userenv.sh` はマシン固有で chezmoi の管理外。
- 上流: [pingdotgg/t3code#16703](https://github.com/pingdotgg/t3code/issues/16703)（Open。WSL のサーバに、シェルのプロファイルで export した `NODE_EXTRA_CA_CERTS` が届かない、という報告。同じ原因）、[#12494](https://github.com/pingdotgg/t3code/pull/12494)（Closed。login シェルの全環境を取り込む案）。2026-11-22 取得。メンテナの見解は未確認。

## 検討した選択肢

ADR-0031 の順に評価した。pi の拡張・package は、pi が起動した後に動くので、pi の起動時の環境を作る用途には合わない（推測）。起動側の仕組みと、起動する実行ファイルで解く。

| 案 | 内容 | 判定 |
| --- | --- | --- |
| A | wrapper は `userenv.sh` だけを読む | `LC_ALL`・`AWS_REGION`・`LD_LIBRARY_PATH` が欠ける。`userenv.sh` はマシン固有の薄い層で、環境の本体は `shellenv.sh` にある |
| **B（採用）** | wrapper が `shellenv.sh`（`wslenv.sh`・`userenv.sh` を含む）を読んでから `exec pi "$@"` する | この機の非対話 bash での実測では、stdout・stderr とも 0 B、約 5 ms、トークン類の名前なし、`userenv.sh` が足すのは `HF_HOME` のみ（T3 経由は未確認）。新しい定義を持たない |
| C | 非対話の起動専用の入口ファイル（`agentenv.sh`）を作る | `shellenv.sh` と定義が二重になって乖離する。B に問題が出ていない |
| D | T3 のプロバイダのインスタンス環境変数（`packages/contracts/src/providerInstance.ts:79`、`packages/provider-core/src/server/instanceEnvironment.ts` の `mergeProviderInstanceEnvironment`）へ写す | **採らない**。静的な値だけで、ユーザー別（`AWS_REGION`）・存在確認つき（CUDA）の値を表せない。機ごとに手で二重管理になり、`userenv.sh` を変えるたびに写す |
| E | t3code の fork に、変数名を固定して取り込むパッチ | upstream の追従コストが増える |
| F | t3code の fork に、login シェルの全環境を取り込むパッチ（#12494 相当） | 同上。必要な変数だけにするよう求められた経緯がある（t3code 側の調べ） |
| G | Windows の環境変数 + `WSLENV` | 値が Windows 側の二重管理になり、条件つきの値を表せない |

## 決定事項

選択肢 B を採用する。`home/dot_local/bin/executable_pi-t3`（`~/.local/bin/pi-t3`。Linux / WSL のみ）は、`#!/bin/bash -p` で、`shellenv.sh` を `. "$_f" >&2 </dev/null` で読んでから `exec pi "$@"` する。

- stdout・stdin は pi との RPC なので、読み込みの出力は stderr へ逃がし、stdin は読み込みに渡さない。`-p` で、継承した `BASH_ENV`・`SHELLOPTS` を無視する（`pib-shell` と同じ）。`set -e` は付けない（`userenv.sh` が非 0 を返しうる）。`HOME` が空・相対のときは読まない。
- PATH の重複を除く処理は足さない（pi の起動ごとにサーバの環境から作り直すので累積せず、実害は軽微）。恒久策は、別件として `shellenv.sh` を冪等にすること。
- T3 側の設定は利用者が行う（Pi インスタンスの binary path に、`$HOME/.local/bin/pi-t3` を展開した絶対パスを指定する。戻すときは空にする）。fork にパッチは当てない。
- 範囲は Pi だけ。T3 経由で Claude Code や Codex を使うときは、同様の wrapper が別に要る。

**維持費**: スクリプト 12 行、試験 12 ケース（`test_shell_startup.py` の `test_pi_t3_*`）と除外の試験 1 件、`verify.py` の規則への 1 パス、docs の 1 節。`shellenv.sh` は読むだけなので、その変更には追随しなくてよい。

**撤去条件**: T3 が login shell から任意の変数を取り込むようになったとき（上流の #16703 や #12494 に当たる修正が入ったとき）。撤去するもの: `executable_pi-t3`、`test_pi_t3_*`、`test_pi_t3_is_linux_only`、`.chezmoiignore.tmpl` の 1 行、`verify.py` の 1 パス、`shell.md` の節と契約表の 1 行、この ADR を Superseded にする。利用者は T3 の binary path を空に戻す。

**未確認**（決定は変えない）: T3 が wrapper を実際にどう起動するか（`--version` の stdout の扱いなど）。T3 のインスタンス環境変数と `shellenv.sh` が同じ名前を持つときの優先順位（推論は `shell.md` に記録）。

## 決定の確認方法

- [x] 偽の pi で、exec・引数と終了コードの素通し・stdout が pi のものだけ・`HF_HOME`/`LC_ALL` が届く・出力が stderr へ回る・stdin を env ファイルへ渡さない・継承した `BASH_ENV`/`SHELLOPTS` を無視する・`userenv.sh` が非 0 でも起動する・`shellenv.sh` が無くても起動する・空/相対の `HOME` では読まない・読み込み後の PATH で pi を探す・pi が無いとき 127、を確かめた（`test_pi_t3_*`。壊した wrapper 8 通りで落ちることも確かめた）。Windows と macOS で配らないことも確かめた（`test_pi_t3_is_linux_only`）。
- [x] `shellenv.sh` を非対話の bash から読むと、stdout・stderr とも 0 B で、約 5 ms だった（2026-11-22 の実測。`shell.md` に記録）。
- [ ] T3 で、Pi の状態確認（バージョン検出）が通る・1 ターン実行できる・pi に `HF_HOME` と `LC_ALL` を出力させる・text generation が通る（利用者が行う。結果をこの ADR に反映する）。

## 結果

### ポジティブな結果

- `userenv.sh` の変数を含め、`shellenv.sh` が作る環境を、wrapper が pi に渡す（偽の pi で確認。T3 経由は未了）。機ごとの手作業と、静的な二重管理が要らない。
- fork にパッチを当てない。upstream が直れば、wrapper を外せる。

### ネガティブな結果

- bash では `shellenv.sh` が冪等でないため、T3 が取り込み済みの PATH に重複が 4 要素できる（実害は軽微）。
- 利用者が、T3 の Pi インスタンスの binary path を機ごとに 1 回設定する。
- `LC_ALL` など、T3 から起動する pi の環境が、対話シェルから起動した pi に近づく（意図した変化）。mise の shims が PATH の先頭に移る。

### 中立的な結果

- wrapper は、T3 が pi を起動するたびに `~/.config/shell/{shellenv,wslenv,userenv}.sh` を実行し、読み込み後の PATH（`~/bin`・mise の shims が先頭側）で `pi` を探す。対話シェルや agent のシェルがすでに読むファイルだが、T3 の起動の経路にも同じ信頼が及ぶ。これらが pi の `path_write` の deny に無いのは既存の穴（別件）。wrapper 自身は deny 済みの `~/.local/bin` に置かれる。

## 関連 ADR

- [ADR-0031](0031-evaluate-existing-extensions-first.md): 既存の機能の評価を先にし、自作は理由・維持費・撤去条件を記録する。
