# AI CLI を pi に一本化し、判定器を TypeScript に移してハーネスのプロセスの中で動かす

- **ステータス**: Accepted
- **日付**: 2026-10-13
- **決定者**: applejxd

## コンテキスト

このリポジトリは、Claude Code・Copilot CLI・OpenCode・pi の 4 つの AI CLI の権限・hook・sandbox を、
`common.toml` から生成して配っている。pi への移行（[CHG-0020](../change/0020-pi-migration.md)）は進んでいて、
段 1〜5（判定 API・ハーネス・配布・境界・ハーネス以外の機能）は終えた。残りは段 6（OpenCode の撤去、任意・優先度低）だった。

2026-10-09 に、利用者は「判定器を Claude Code / Copilot CLI と共有する」と決めていた。判定器（`decide.py`、
中身は `bashrules` と `command_policy.py`）が Python なのは、Claude / Copilot の hook が外部プロセスで、同じ判定を共有するためだった。

2026-10-13 に、次のことが分かった・決まった。

- 利用者は、**他のハーネスを使わず pi に一本化して最適化する**と決めた
- pi 本体には承認（permission）の機能が無い。公式は、承認の画面ではなく OS・コンテナ・仮想マシンの境界で守る立場を取る
  （[調査記録](../research/agents/pi-isolation-options.md)）
- 判定器を外部プロセスとして毎回起動する構成は、Windows で壁になる（`python3` が無い、プロセス起動の遅さ、
  `spawnSync` が pi のイベントループを止める）。OpenCode は判定を本体の仕組みの中（Node）で完結させていたので、OS の差がほとんど出なかった
- 判定器を TS に移す安全網がある。段 1c で、`check_bash.py` の試験の 1,041 件で hook と判定が一致することを固定済み

## 決定

1. **AI CLI は pi に一本化する。** Claude Code・Copilot CLI・OpenCode は、今後の保守・最適化の対象にしない。
   OpenCode は段 6 で撤去する。Claude / Copilot の生成・hook の扱い（残すか畳むか）は、一本化の実際の運用を見て別に決める。
   **更新（2026-10）**: Claude / Copilot への hook の登録は撤去した（`[[hooks]]` は pi の編集後の整形だけ。判定の hook は `retired_hooks` へ）。Python 版の判定器本体の撤去は、実機での観察の後に行う
2. **判定器は TypeScript に移し、ハーネスのプロセスの中で関数として呼ぶ。** Python 版（`decide.py`）は、移植が全件一致するまで正解（オラクル）として残し、
   一致したら外す。**2026-10-09 の「Claude / Copilot と判定を共有する」は、この決定で覆る**（その前提が、一本化で消えるため）
3. **移植は、挙動を変えずに写す。** Python 版の判定結果を正解データ（JSONL）にして、TS 版との全件一致を完了条件にする。
   構文解析の堅牢化は、そのあとの別の変更にする
4. **判定器は呼び出しの間で状態を持たない。** 呼び出しごとの文脈（`Ctx`）に必要な値を置く。Python 版には、前の入力が後の入力の検査を緩める
   プロセス内の記録があった（[仕様](../spec/pi-decide.md#判定が前の呼び出しに依存していた修正済み)）。TS 版へ写さない
5. **Windows ネイティブの `pi` は、信頼できる環境でだけ開き、ガードは付けない。** 守りが要る作業は、WSL の `pis`（ハーネス ＋ 境界）で行う。
   ハーネスの Windows への移植は、判定器を TS に移したあとに、需要が増えたら再検討する

## 検討した選択肢

### 判定器の言語

| 選択肢 | 評価 |
| --- | --- |
| **TypeScript（採用）** | pi の拡張は TS。プロセス内の関数呼び出しになり、起動の費用・失敗の形（タイムアウト、不正な応答）・Windows の壁が消える。試験も偽のモデルの枠で書ける |
| Python のまま外部プロセス | 共有の利点は一本化で消える。Windows の壁と起動の費用が残る |
| Rust（別プロセスの単体バイナリ、または WASM） | 判定は数ミリ秒以下で足りるので速度の利点は無い。OS ごとのビルド・配布の手間と、プロセス起動の費用が残る。WASM は鎖が増えるだけで得るものが少ない |
| Python / Go の常駐サーバ | 起動の費用は消えるが、死活・再読込・並列の管理が増える。TS のほうが単純 |

### Windows の守り

| 選択肢 | 評価 |
| --- | --- |
| **信頼できる環境でだけ、ガードなし（採用）** | 移植の費用が大きく（子の起動・停止、パス、`pis` の PowerShell 版）、境界が無いので保護として売れない（`!`・拡張・MCP が判定の外に残る）。割り切って使える場面を限る |
| ハーネスを Windows へ移植 | 判定器が TS になれば壁は減るが、境界が無い残余リスクは残る。需要が増えたら再検討する |
| Windows でも pi 全体を隔離（Windows Sandbox・Hyper-V・専用ユーザー） | 使える手段はあるが、永続性・使い勝手・ライセンスのどれかを諦める。必要な用途が出たら個別に決める |

### スキルのスクリプト（`.py` / `.sh`）の言語

| 選択肢 | 評価 |
| --- | --- |
| **Python / bash のまま（採用）** | chezmoi の `modify_*.py.tmpl`・`generate.py`・テスト・pre-commit・`uv` の単一ファイルが Python なので、スキルを TS にしても Python 依存は消えない。書き換えの費用と回帰（許可規則 `[pi.skill_scripts]` が `python3 …` の形に固定されている）に見合わない |
| TS へ一括で移す | 得るものが無い。一括では行わない |
| 個別に TS 化 | 次のどれかが出たときだけ検討する。① TS のコード（判定器・伏字化）を共有したい ② Windows で Python なしに動かしたい ③ 起動の速さが問題になる。直すとき `[pi.skill_scripts]` の許可と `runners` を一緒に変える。`node script.ts` は型除去（node 22.18 以上）に依る |

### Claude / Copilot から TS の判定器を呼ぶ道（作らない）

Claude Code と Copilot CLI の hook は、外部コマンドに標準入力で JSON を渡し、標準出力の JSON を読む形式で、コマンドの言語は問われない。
そのため **原理的には**、`node <判定器を呼ぶ薄い CLI>.ts` を hook に登録すれば、TS の判定器をそのまま使える
（`check_bash.py` と `agent_compat.py` が担う「入力 JSON → 判定 → 出力 JSON」の変換だけを TS で書く）。

- **作らない**。Claude / Copilot は保守の対象外で、hook の登録も撤去した（上の決定 1）
- 必要が出たら、薄い CLI を 1 本足す。条件は ① node 22.18 以上 ② 型除去の警告を出さない（`NODE_NO_WARNINGS=1` か `--disable-warning=ExperimentalWarning`。
  hook の stderr を汚さない）③ 判定の設定は `rules.json` の `judge`（`common.toml` の `[bash]` / `[file]` / `[pi]` と `tables.toml` を JSON にしたもの）を読む
- **未検証**: hook の仕様に基づく見立てで、実際に Claude / Copilot から TS の hook を動かしてはいない。作るときは、まず小さな試験で確かめる

## 結果

- **得るもの**: 保守の対象が減る（OpenCode の plugin・生成、Claude / Copilot の判定の共有）。判定が速く単純になり、Windows の壁が減る
- **払うもの**: 単一のツール（pi）への依存。pi は 1.x で若く、ハーネスが内部の挙動 4 点に頼る（[CHG-0020](../change/0020-pi-migration.md) の「引き継ぐ前提」）。
  版の固定と、更新のときの試験で抑える。移植の工数（約 5,600 行、数日規模）
- **進め方**: [仕様: TS 版への移植](../spec/pi-decide.md#ts-版への移植)。層ごとに正解データとの一致で進捗を測る
- **見直す条件**: pi が止まる・方針が大きく変わる、移植が全件一致に届かない、Windows でガード付きで使う需要が増える、Claude / Copilot を再び使う（TS の判定器を呼ぶ薄い CLI を足す。上の選択肢）
