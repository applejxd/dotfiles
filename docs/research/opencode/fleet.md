# OpenCode V2 で Copilot CLI の `/fleet` 相当を組む

<!-- 現在の総合判断は docs/change/ の候補比較表が正本。
     ここは「いつ何を観測したか」を積む場所 -->

> **現行の仕様**: [並列作業（/fleet）](../../spec/agent-config-generation.md#並列作業fleet)

## 結論

- コマンドの指示文と作業役の子エージェントだけで、`/fleet` 相当が動く（plugin は要らない）
- **1 回の応答で `subagent` ツールを並べて呼ぶと、子は同時に走る**（2 回とも実行時間が重なった）。
  完了を待つ形なので、波の全員が終わってから次へ進む
- 当初の指示は `background` を求めたが、取りまとめ役は使わなかった。指示文を
  実際のやり方に合わせた（記録 E2）
- 作業役は割り当てた階層のモデル（Copilot では `claude-opus-5.5#medium`）で動いた
- 作業役がシェルを使う作業と、TUI での確認の扱いは未確認

## 記録 E1 — 2026-09-29

- **対象バージョン**: opencode v2.0.14
- **環境**: WSL2 Ubuntu / 基準コミット `3adef69` に `/fleet` と `fleet-worker` の定義を加えた作業ツリー

### 問い

`/fleet` コマンドと `fleet-worker` で、独立した作業が並行して進むか。

### 事前の予想

取りまとめ役は指示どおり `background: true` で作業役を起動し、通知を待って結果を
まとめる。作業役の実行時間は重なる。

### 方法・条件

- [commit / review エージェントの実機確認](commit-review-agents.md)と同じ試験環境
  （試験用 DB・生成した `opencode.json`・`http.request` を記録する plugin）。
  使い捨てのリポジトリ（`.tmp/opencode/scratch`）で実行した
- 作業役のシェルは無人の実行では承認待ちで止まるので、題材はファイルの作成だけにし、
  確認は read ツールで行うよう依頼に書いた

```console
$ opencode run --standalone --auto --log-level error \
    '/fleet notes/ ディレクトリに one.md / two.md / three.md の 3 ファイルを新しく作り、
     それぞれに「# One」「# Two」「# Three」の見出しと、その数を英語で説明する 1 文を書く。
     3 つは互いに独立している。確認は read ツールで行い、シェルは使わないこと'
```

- 並行したかは、試験用 DB の `session_v2` の `time_created` / `time_idle` で見た。
  起動の仕方は親セッションの `subagent` 呼び出しの入力で見た

### 結果

```text
✓ Create notes/one.md    Fleet-Worker Agent
✓ Create notes/two.md    Fleet-Worker Agent
✓ Create notes/three.md  Fleet-Worker Agent
→ Read notes/two.md / notes/one.md / notes/three.md
```

| 子セッション | モデル | 開始 | 終了 | 結果 |
| --- | --- | --- | --- | --- |
| 1 | `claude-opus-5.5` / `medium` | +0.0 s | +9.5 s | succeeded |
| 2 | `claude-opus-5.5` / `medium` | +1.6 s | +10.2 s | succeeded |
| 3 | `claude-opus-5.5` / `medium` | +3.0 s | +15.2 s | succeeded |

- 親の `subagent` 呼び出しは 3 件とも `background` の指定なし（完了を待つ形）で、
  同じ応答の中に並んでいた
- 送信したリクエスト: 親（`build`）3 回、作業役 9 回
- 親は作成後に 3 ファイルを read で確かめ、コミットせずに報告した

### 考察

- 予想の一部が外れた。指示では `background` を求めたが、取りまとめ役は完了を待つ形で
  並べて呼んだ。それでも作業役は並行した
- 完了を待つ形なら、波の全員が終わってから次の波へ進むことが仕組みとして保たれる。
  指示文をこちらの形に合わせた（記録 E2 で確かめ直す）
- 作業役がシェルを使う題材は試していない。無人の実行では承認待ちで止まる
  （[commit / review エージェントの実機確認](commit-review-agents.md)）

### 次の問い

- TUI で、並行する作業役のシェルの確認が表に出て答えられるか。未確認
- 並行する作業役の 1 つで確認を拒否したとき、ほかの作業役も止まるか。未確認
  （同じ手番の並列呼び出しは、1 件の拒否で全体が中断する:
  [ask と並列バッチ](ask-and-parallel-batch.md)）

### 参照

> The `/fleet` slash command in Copilot CLI is designed to take an implementation plan and break it down into
> smaller, independent tasks that can be executed in parallel by subagents.

出典: <https://docs.github.com/en/copilot/concepts/agents/copilot-cli/fleet>

> Foreground calls wait for the result. `background: true` returns immediately and notifies the parent when the
> child finishes. [...] Only subagent-mode agents can be used, and the default nesting depth is one.

出典: <https://opencode.ai/v2/docs/tools/>

## 記録 E2 — 2026-09-29: 指示文を「並べて呼ぶ」形に直したあと

- **対象バージョン**: opencode v2.0.14
- **環境**: 記録 E1 と同じ。`/fleet` の手順 4 を「1 回の応答の中で subagent ツールを
  並べて渡す」に書き換えた

### 問い

指示文を記録 E1 で観測したやり方に合わせても、並行して動くか。

### 事前の予想

E1 と同じく、並べて呼び、並行して動く。

### 方法・条件

記録 E1 と同じ依頼を、`notes/` を消してから同じ試験環境で実行した。

### 結果

| 子セッション | モデル | 開始 | 終了 | 結果 |
| --- | --- | --- | --- | --- |
| 1 | `claude-opus-5.5` / `medium` | +0.0 s | +10.8 s | succeeded |
| 2 | `claude-opus-5.5` / `medium` | +2.3 s | +10.7 s | succeeded |
| 3 | `claude-opus-5.5` / `medium` | +3.6 s | +10.5 s | succeeded |

親の `subagent` 呼び出しは 3 件とも `background` の指定なしで、3 ファイルが作られた。
親は `notes/` の一覧を read で確かめて報告した。

### 考察

予想どおり。指示文とやり方が一致した。作業役がシェルを使う題材と、TUI での確認の
扱いは引き続き未確認。
