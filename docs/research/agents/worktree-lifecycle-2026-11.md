# worktree の運用の記録（2026-11）

観測日 2026-11-23。`feature-orchestration` の工程 9（後始末）と、置き場所の方針の根拠。手順は [スキル](../../../.agents/skills/feature-orchestration/SKILL.md)、権限・子の事実は [pi-facts](../../../.agents/skills/feature-orchestration/references/pi-facts.md)。

## 失ったもの

- Sandbox の検証用スクリプト（`.tmp/sandbox-probe/probe.ps1`）。feature の worktree の `.tmp/` に置き、`git worktree remove`（`--force` なし）で、ほかの git の対象外のファイル（`.venv`・`.tmp/review/`）と一緒に、警告なしで消えた。`git flow feature finish` の自動削除も、同じ `git worktree remove` 相当で、束ね用の worktree を消した。
- 原因は、置き場所ではなく、(1) 再利用するものを使い捨てと分類した判断と、(2) `git worktree remove` が git の対象外のファイルを守らないこと。ネット上には「ignore のファイルがあると止まる」とする記事もあるが、実際は止まらなかった。「ignore でない未追跡のファイルがあると止まる」とする記事 <https://teebe.io/guides/git-worktree-remove/>（取得 2026-11-23）が実態に合う。

## 採らなかった置き場所の案

| 案 | 採らない理由 |
| --- | --- |
| `TMPDIR` を本体の `.tmp` に向ける | worktree の中の子は、作業ツリーの外への書き込みが確認なしで拒否される。囲い（`pib`）の中は、作業ツリーだけが書き込み可。`TMPDIR` は一部のプログラムしか見ない。並列の子が同じ場所を使って衝突する |
| `/tmp` に一本化する | 囲いの中の `/tmp` は空の tmpfs で、コマンドごとに消える（[囲いの仕様](../../spec/sandbox/pi-sandbox-runner.md)の記述。実測は未確認）。再起動でも消える |
| 共通の git ディレクトリ（`git rev-parse --git-common-dir`）の下 | 作業ツリーの外なので、1 つ目と同じ問題。git の管理領域に私物を置くことにもなる |

採った案: 置き場所は変えず、消す前に `git clean -ndX` で一覧し、`.tmp/keep/` を本体へ写す（子の境界を変えない）。ネットで見つけた `.worktreeinclude`（Claude Code。<https://code.claude.com/docs/en/worktrees>、取得 2026-11-23）は、新しい worktree へ ignore のファイルを写す仕組みで、削除時の保護ではない。

## 統合・反映で分かったこと

- `git flow feature finish` は、`develop` が `origin/develop` より遅れていると拒否する（`--force` で回避できるが、古い base へのマージになる）。
- `git flow * finish*` と `chezmoi apply` は、確認が出る。誰も答えないと 5 分（300 秒）で拒否され、コマンドは実行されない。
- `chezmoi apply` は、スクリプトが sudo のパスワードを要ると、端末が無くて失敗する。`chezmoi apply --exclude=scripts` でファイルだけ反映できる。
