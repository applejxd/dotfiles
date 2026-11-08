# ツール隔離（pi はホストに残し、ツールの実行だけを隔離）の実現性

- **日付**: 2026-11-08（読み取りだけの調査。プロトタイプは着手前に中止した）
- **対象**: pi 1.5.0 の公式の API・例と、私たちのフルガードのハーネス（`home/dot_config/pi/harness/`）。
- **方法**: `explore` の子 2 本（pi の公式 API と例／ハーネスのローカル前提）。原本は [archive](../archive/2026-11-agent-stack/README.md) の `tool-isolation/`。
- **関連**: [CHG-0065](../../change/0065-agent-stack-freeze.md)・[ADR-0030](../../adr/0030-freeze-agent-stack-return-to-stock-pi.md)

## 結論

**実現可能。** pi の公式文書（`docs/containerization.md`）が、「pi をホストに残し、選んだツールを隔離環境へ流す」方式（Gondolin の microVM・SSH の例 `examples/extensions/ssh.ts`）を載せている。ハーネス側の最小の挿入点は `harness/index.ts` の `definitions`（約 690〜705 行）で、規模の見積りは新規 300〜450 行＋既存の編集約 100 行（実測ではない）。

## pi の公式 API（要点）

- 7 ツール（bash・read・write・edit・grep・find・ls）に `operations` がある（`create*ToolDefinition(cwd, { operations })`）。**grep だけは `operations` で検索の実行先を変えられず**、自作の `execute` が要る（Gondolin もそうしている）。
- 順序は `tool_call`（拒否・入力の書き換え）→ `execute`（`operations`）→ `tool_result`。**フルガードの判定は実行より先**に効く。
- `!` コマンド（`user_bash`）は `tool_call` を通らない。自作の `guarded_*` ツールと、隔離を使わない拡張ツールは**ホストで動く**。
- SSH の例は、差し替えるのが 4 ツールだけ・環境変数は遠隔のまま・パスの変換は単純な置換・書き込みは base64 を引数に載せる（大きいファイルは書けない）。Gondolin の例は 7 ツールすべてを差し替えるが、**ホストの環境変数が箱に見える**（認証の境界にならない。公式の注意）。
- 公式の限界: ホストの pi 本体と隔離を使わない拡張は制約されない。

## ハーネスのローカル前提（要点）

- **鍵は「鏡写し cwd」**: ホスト側の cwd を、遠隔の絶対パスと同じ文字列の空ディレクトリにする。判定器（`judge/`）は文字列比較が中心なので、ほぼ無改造で成り立つ。kcage の shared モードはホストと同じパスで重ねるので、変換が要らない。
- **壊れる・要判断**: `guarded_action`（`git_commit` など。ローカルの git 前提）・`guarded_task`（子の pi。`isolation: "worktree"`・Landlock・cwd）・`guarded_pr_summary`・作業台帳（既定で `<cwd>/.tmp/work`。`PI_JOURNAL=0` 推奨）・`bg_run`（ローカルで spawn）・`post_edit` の整形・`readBodyFile`（ローカルの fs）・外部のスキルの read（ホストの絶対パス）。
- 環境変数: bash の env はホストの全部と `PI_SESSION_*` が入る。**実行先へは許可リスト方式**（`PATH`・`LANG`・`AGENT_ENV` など）にする。篩う規則は `pi.py` の `DROP_ENV`・`SECRET_ENV` に既にある。
- 子エージェント: 子は `pi --mode rpc … -e builtin:mcp -e HERE` で起動し、環境は親から継承する。遠隔の指定を**環境変数**にすれば子へ継承される（`registerFlag` は継承されない）。
- 変えてはいけないもの: 判定の入力の形（`decide.ts` の `Request`）・`guarded_` の接頭辞・golden（`judge_golden.mjs`・`decide_golden.jsonl`）と、ソース文字列を固定している試験。

## 設計上の要点（`kcage exec` のような実行先向け）

- 子プロセスは配列の引数で起こし、シェル文字列を連結しない。cwd は位置引数で渡す（`sh -c 'cd "$1" && exec bash -c "$2"' sh <cwd> <cmd>`）。
- read・write は stdin・stdout の `cat` で、バイナリも通せる。write は一時ファイルに書いて `mv`。ls は `readdir` を 1 回で取って `stat` をキャッシュする。
- 中断・時間切れで、箱の中の子プロセスまで止まるかは**要実測**（止まらない恐れ）。pty が無いので、対話的なコマンドは動かない。ツール呼び出しは既定で並列なので、実行先への同時起動数に上限を設ける。
- `user_bash` は、実行先へ流すか拒否する（ホストで素通しにしない）。実行先が実行できないツールは、組み込みのローカル実行へ**黙ってフォールバックしない**（fail-closed）。

## 弱点

ホストの pi が、ツールの出力（外部の内容）で注入を受けうる。箱の中に pi を置く方式より、ホスト側の力が大きい。`pis` の Fence・ホスト側ツールの最小化・フルガードに頼ることになる。遠隔の symlink とホストの home 基準の deny glob は、判定器では検出できない。

## 次の候補（再開するなら）

1. 鏡写し cwd 方式で、read・write・edit・bash だけの PoC（約 150 行。原本の `spike-brief.txt` が依頼文）。
2. `gitSync` と `Git` の注入点の抽象化。
3. `bg_run` の扱い（無効化か遠隔化か）。
