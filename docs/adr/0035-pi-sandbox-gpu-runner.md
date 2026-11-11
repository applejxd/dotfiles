# GPU を使う作業向けに、pi の sandbox 拡張へ設定つきの runner を足す

- **ステータス**: Accepted（2026-11-12。利用者の統合の指示による）
- **日付**: 2026-11-12
- **決定者**: applejxd（実装は利用者の依頼。[ADR-0031](0031-evaluate-existing-extensions-first.md) の 3(d)「自作の承認」は、利用者が統合を指示した 2026-11-12 に得た）
- **関係**: [ADR-0027](0027-isolation-unit-is-environment.md)（隔離の単位は環境）を**置き換えない**。docker・compose を使う開発は従来どおり環境の側で扱い、ここは「ホストで GPU を使う作業」の守りを足す。[ADR-0030](0030-freeze-agent-stack-return-to-stock-pi.md)（stock の pi。隔離は自分の判断）と [ADR-0031](0031-evaluate-existing-extensions-first.md)（自作の条件）に従う。

> **注記（2026-11-12）**: 責務の分担を [ADR-0036](0036-pi-sandbox-shell-wrap-and-tool-policy.md) で整理した。実装が入ったら、この ADR は置き換える（拡張を外し、`shellPath` の囲いにする）。それまでは、この ADR が現行。以下の本文は決定当時のまま残している。

## コンテキスト

- **要件**: GPU の利用が最優先。そのうえで、LLM の認証などの秘密をエージェントから隠し、手間を増やさない。worktree での開発（feature ごとの worktree）を妨げない。守る水準は「うっかり防止」（[ADR-0012](0012-ocs-boundary-for-accidents.md)）。
- **実機の比較**（[調査記録](../research/agents/pi-gpu-sandbox-2026-11.md)。WSL2・Ubuntu 24.04・rootless Docker・RTX 3070）:
  - `pi-safe`: GPU が通らず、docker 経由で HOME に書け、worktree で commit できない。
  - `@yuru7/pi-sandbox`: 書き込みは cwd・git・`/tmp` に絞れ、worktree で commit できる。GPU は通らず、秘密は読め、通信は無制限。
  - `pi-permission-modes`: 秘密を隠し、通信を許可リストで絞り、docker も遮断する。GPU を通す設定項目が無い（同梱の sandbox-runtime が `--dev /dev` を固定）。
  - `@trim21/personal-pi-extensions`: `extraArgs` があるが `--dev /dev` の前に置かれ、GPU が通らない。他の 7 つの拡張にも、GPU・デバイスの記述は見つからなかった。
  - Docker（`pi-less-yolo` のフラグ）: `--gpus all` で GPU は通る。rootless では `--user` の指定が合わず、認証をマウントするため内側から読める。
- **GPU は、bwrap に `--dev-bind /dev/dxg` を足せば通る**（実測。CUDA カーネルが動く）。ただし `--dev /dev` より後ろに置く必要がある。
- **同じ手口が通例**: Claude Code（[#13108](https://github.com/anthropics/claude-code/issues/13108)、Open）・Codex（[#19676](https://github.com/openai/codex/issues/19676)）など、本家が未対応のため、各自がラッパーで `--dev-bind` を注入している。

## 検討した選択肢

### 案 A: 作らない（既存のまま使う）

- `pi-permission-modes` を使い、GPU を使う作業だけ sandbox の外で承認して実行する、または隔離なし（stock の権限確認だけ）。
- **利点**: 自作が無い。**欠点**: GPU の作業が、sandbox の保護を受けない。承認の手間が増える。

### 案 B: 自前の拡張（pi 公式の `createBashTool` の `spawnHook` / `BashOperations`）

- bwrap で包む拡張を自作する。公式の拡張点なので、`@yuru7` の内部の並びに依存しない。
- **欠点**: `write` / `edit` の防護・承認の流れ・worktree の git の扱い・試験・pi の API への追従を自前で持つ。`@yuru7/pi-sandbox` は同じものを約 5,500 行で持つ。自作基盤の凍結（ADR-0030）と逆向き。**却下**。

### 案 C: ツール委譲型（pi はホスト、read / write / edit / bash を専用環境へ送る。公式の例 `examples/extensions/ssh.ts`）

- GPU・compose・apt を専用環境が持ち、認証は pi（ホスト）に残る。bwrap の細工が要らない。
- **欠点**: 環境の作成・同期・運用が要る（ADR-0027 の P3 の領分）。`ssh.ts` は read・write・edit・bash の 4 つだけを差し替える（grep・find・ls はホスト）。未試験。**将来の評価**（[ツール隔離の実現性](../research/agents/tool-isolation-feasibility-2026-11.md)）。

### 案 D（採用）: `@yuru7/pi-sandbox` の `runnerCommand` に、設定つきの小さな runner を差す

- 拡張の公開の設定項目（`runnerCommand`）に、bwrap の引数へ GPU・隠蔽・docker 遮断・git 保護を足すラッパーを差す。方針は設定ファイル（リストとオン・オフ）に置き、引数の並びはコードに固定する。
- **利点**: 実拡張で GPU・docker 遮断・worktree の commit・hooks の保護が揃う（実測）。自作は小さい。
- **欠点**: 引数の並びという、拡張の内部の挙動に依存する（版の固定と更新時の確認で下げる）。自作の部品が増える。

### 案 E: 上流（`@yuru7/pi-sandbox`）へデバイスの受け渡しを提案する

- 採用されれば runner が要らなくなる。**並行して検討する**。外部への書き込みなので、利用者の承認が要る（この ADR の範囲外）。

## 決定

**案 D を採る。** 案 E は並行して検討し、案 C は将来評価する。

- 部品は、runner（`home/dot_local/bin/executable_pi-sandbox-runner`）、設定（`home/dot_config/pi-sandbox/runner.toml`）、拡張の設定（`home/dot_pi/agent/create_pi-sandbox.json.tmpl`）、実機の確認（`scripts/pi_sandbox_selftest.py`）、試験。仕様は [pi-sandbox-runner](../spec/sandbox/pi-sandbox-runner.md)。
- **設定にするのは、リストとオン・オフだけ。** 引数の並び（GPU → git → 隠蔽 → docker）はコードに固定する。任意の追加引数は作らない。設定は利用者の階層だけを読み、壊れていれば bwrap を起動しない（fail-closed）。
- **Linux（Ubuntu / WSL）専用。** 他の OS へは配らない。
- **拡張の package 自体（`@yuru7/pi-sandbox`）は、この決定では `pi-stock-packages` に入れない。** 入れると、全機・全セッションの bash が sandbox に入り（mac・Windows を含む）、昇格のたびに自動レビューの LLM 呼び出しが増え、`pi-permission-system` と重なる。既定にするかは別に決める。使うときは `pib`（`pi -e npm:@yuru7/pi-sandbox@0.5.0` を呼ぶ。runner が未配備なら起動しない）。

### 自作の記録（ADR-0031 の 3）

| 項目 | 内容 |
| --- | --- |
| (a) 既存で満たせない理由 | 調べた拡張 10 個のうち、設定だけで GPU を通せるものが無い（上の「コンテキスト」。全ソースの精読ではない） |
| (b) 維持費の見込み | runner 約 280 行（コメントと docstring を含む）・設定・試験・自己確認。追従が要る上流は `@yuru7/pi-sandbox` の引数の並び 1 点。更新で並びが変わると GPU が黙って消えるので、版を固定し、更新前に並びと自己確認を見る（[手順](../spec/sandbox/pi-sandbox-runner.md#版の固定と更新)） |
| (b) 撤去の条件 | 上流がデバイスの受け渡し（と秘密の隠蔽）を設定で持ったとき／ツール委譲型（案 C）へ移ったとき／`@yuru7/pi-sandbox` を使わなくなったとき。撤去は runner・設定・拡張の設定・自己確認・試験・この ADR の置き換え |
| (c) 最小性 | pi の内部には触れず、拡張の公開の設定項目だけを使う。runner は標準ライブラリの Python 1 ファイル |
| (d) 承認 | 実装は利用者の依頼。統合の指示（2026-11-12）をもって承認 |

## 結果

- **得るもの**: sandbox の内側で GPU が使える（CUDA カーネルを実測）。docker 経由の書き込み制限の突破を塞ぐ。worktree で commit でき、`.git` の hooks・config は読み取り専用。`auth.json`・`~/.ssh` などを内側から隠せる。
- **失うもの・限界**:
  - **通信は無制限**（許可リスト型の `pi-permission-modes` とは逆）。
  - **compose は内側で使えない**（docker を塞ぐ）。
  - **GPU のデバイスをさらす**ため、内側のコードにドライバの入口が開く（攻撃面は広がる。推測）。
  - **gh・aws などは、内側では使えない**（隠す一覧の既定。外側で実行するか、短命のトークンを渡す。[認証情報の扱い](../spec/sandbox/pi-sandbox-runner.md#認証情報の扱い)）。環境変数の鍵は隠さない。
  - **git の保護は既存の `hooks`・`config` だけ**（無いものは内側から作れる。[限界](../spec/sandbox/pi-sandbox-runner.md#保証しないこと限界)）。環境変数の鍵は隠さない。
  - 拡張は 0.x の個人製で、`/tmp` はホストと共有。
  - 守りは「うっかり防止」の水準。

## 見直しの条件

- 上流の拡張が、デバイスの受け渡しと秘密の隠蔽を設定で持ったとき（runner を撤去）。
- 拡張の更新で、引数の並びが変わり、自己確認が落ちたとき。
- 通信の絞り込みが要るようになったとき（許可リスト型の拡張との併用を再評価）。
- GPU・compose を内側で使う開発が主になったとき（案 C・ADR-0027 の P3 へ）。

## 関連

[仕様: pi-sandbox-runner](../spec/sandbox/pi-sandbox-runner.md)・[調査記録](../research/agents/pi-gpu-sandbox-2026-11.md)・[ツール隔離の実現性](../research/agents/tool-isolation-feasibility-2026-11.md)・[同種の OSS の評価](../research/agents/oss-sandbox-evaluations-2026-11.md)
