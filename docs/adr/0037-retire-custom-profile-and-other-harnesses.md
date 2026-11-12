# 旧 custom プロファイルと、pi 以外のハーネスを撤去する

- **ステータス**: Accepted
- **日付**: 2026-11-12
- **決定者**: applejxd
- **関係**: [ADR-0030](#置き換えた決定と記録)（自作基盤の凍結）と ADR-0034（凍結した試験を `verify:all` から外す）を置き換える。pi の標準の構成は [ADR-0031](0031-evaluate-existing-extensions-first.md)。

## コンテキスト

- 2026-11-10 から、pi は公式の既定に人気の拡張を足した構成（stock）で動かしていて、安定している。自作の構成（custom）に戻したことは無い。
- 凍結した自作の基盤と、pi 以外の CLI（Claude Code・Codex・Copilot CLI・Gemini CLI・OpenCode・oh-my-pi）の設定生成は、使わないのに残っていた。
  全件の試験 13,593 件（`pytest --collect-only`。2026-11-12）のうち、約 84%（11,471 件・約 8.2 万行。ファイル名での概算）がこれらの試験で、`verify:all` が 2 分 15 秒、`verify:full` が 12 分 29 秒かかった（ADR-0034 の実測。撤去した文書で、タグ `archive/custom-harness-2026-11-12` から読める）。docs も 341 ファイルあった。
- 凍結しても保守は止まらない。変更のたびに試験の登録・分類・省略の規則（`FROZEN_TESTS`・`CLOSED_MODULES`）を直す必要があった。

## 決定

次を、ソース・試験・docs ごと**撤去する**。git の履歴と下のタグから復元できる。

- **旧 custom プロファイル**: フルガード（判定器・確認画面・承認の保留）、自作の pi 拡張（`activity`・`ask`・`btw`・`delegate-nudge`・`notify`・`plan`・`speed`・`subagents`・`todo`）、作業台帳・`/goal`・並列実行、PR ビューアと統合の運用（`feature_gate`・`bundle`・`wt_*`・`prs`）、プロファイルを切り替える旗（`pi-profile`・`pi-own-extensions`）、モデルのカタログの道具（`scripts/models.py`・`scripts/model-eval`）。
- **自作の境界と隔離環境**: `pis`・`ocs`（Fence）・`oc-utils`・kcage（Incus の箱）・broker・Envoy。
- **pi 以外のハーネス**: Claude Code・Codex・Copilot CLI・Gemini CLI・OpenCode の設定生成・hook・導入・起動関数・`agent` の別名・herdr の統合、`common.toml.tmpl`（5 つの CLI の単一ソース）と、それを読む判定器（`home/dot_claude/hooks`）。

**残すもの**（pi の stock の構成と、pi が使う周辺）:

- pi の設定: `~/.pi/agent/`（`AGENTS.md`・`settings.json`・`mcp.json`・`mcp-adapter.json`・`compaction.json`・`pi-plan-mode.json`・`keybindings.json`・`prompts/`・`agents/`・`themes/`・`extensions/pi-permission-system`・`extensions/subagent` の設定）、`~/.cc-safety-net`。
- コマンド実行の囲い `pib`・`pib-shell`・`pi-sandbox-runner`（[ADR-0036](0036-pi-sandbox-shell-wrap-and-tool-policy.md)）、補助スクリプトの入口 `pk`、専用 WSL の GPU サンドボックス（`scripts/windows/wsl-sandbox`）。
- スキル（`~/.agents/skills`）、検索の MCP（`~/.config/agents/websearch`・`agentcore_websearch_mcp.py`）、MCP の宣言（`pi-mcp-servers.toml`）と生成器（`scripts/agents/generate.py`。pi の MCP だけを生成する）。
- 検証の入口（`scripts/verify.py`。変更に応じた選択実行と全件）。

## 結果

- 試験は 13,593 件から 1,607 件になり、全件が約 12 分から約 32 秒（6 並列。2026-11-12 実測）になった。`verify:all` と `verify:full` の区別と、凍結した試験の分類・省略の規則は不要になった。
- docs は 341 ファイルから約 90 ファイルになった。
- 設定の源が 1 つ減った（5 つの CLI の `common.toml.tmpl`）。pi の MCP の宣言は `pi-mcp-servers.toml`（2 つの `[[mcp]]`）だけになった。
- **失うもの**: pi 以外の CLI の保護（権限・hook）と、その設定の自動生成。フルガードと自作の境界の保護（stock の pi は、権限の確認の package と `pib` の囲いで、うっかりを防ぐ程度）。PR ビューア・作業台帳。

### 配備済みの残り（各機）

- `chezmoi apply` が消す（`.chezmoiremove`）: 旧 custom の `~/.config/pi`・自作の拡張・`models.json`、`~/.local/bin/{pis,ocs,ocs-boundary-check,oc-utils,kcage}`、`~/.local/share/ocs`、`~/.config/agents/{common.toml,command_policy.py}`。
- **消さない**: `~/.claude`・`~/.codex`・`~/.copilot`・`~/.gemini`・`~/.config/opencode` の設定と hook。資格情報・履歴と同じ場所にあるため。使わなければ利用者が手で消す。以後は更新されない。
- kcage を導入済みの機は、`kcage uninstall`（配備コピー・sudoers・許可表）を先に実行する。実行ファイルを消したあとでは使えない。

### 復元

- 撤去の直前の状態: 注釈つきタグ `archive/custom-harness-2026-11-12`（`3447682d`。ローカルだけ。`git push origin archive/custom-harness-2026-11-12` で残す）。
- 自作基盤が全部入った最後の状態: 注釈つきタグ `archive/agent-stack-2026-11-08`（`86de89dd`。これもローカルだけ）。
- 未完の枝（`feature/kcage-clone-*`・`feature/pisd`・`feature/dev-env-front`）は、ローカルに残っている。

## 設計の原則として残すもの

隔離は「完全」を目指さず、**被害の上限を決める**。信頼の線は次の 3 つの問いで引いた。

| 問い | 「はい」なら | 「いいえ」なら |
| --- | --- | --- |
| 戻せるか（reflog・snapshot・bundle・再生成） | 信頼してよい（確認で足りる） | 境界で守る |
| 箱の外へ出る、またはホストで自動実行されるか（push・認証・秘密・ホストの git が読む設定） | 境界で遮断する | 信頼してよい |
| 機械で検証できるか（試験で縛れるか） | 「保証する」と書ける | 保証せず、運用か受容に回す |

守りは **遮断 → 抑止（確認）→ 回復 → 受容** の順に割り当てる。信頼は「コード」ではなく**データの流れの向き**で決める（ホスト → 箱は信頼、箱 → ホストは検証してから使う）。

## 学び（実測・調査で確かめたこと）

- 保守の負担は、部品の数でなく**部品どうしの接続**（権限・認証・git・worktree・ポート）で増えた。層を足すたびに別の層との接続が増え、穴を塞ぐ作業が本来の開発を圧迫した。
- 制限つき Incus プロジェクトでは足りない。デバイスを作れると、`proxy` デバイスで管理ソケットを箱へ出して脱出できた。
- リポジトリを書き込み可で箱に重ねると、ホストの git が箱の書いた設定（`.git/hooks`・`config`・`commondir`・`mv .git`）を実行する経路ができる。ホストの `.git` を箱に見せなければ、この種類は構造的に消える。
- `git fetch <bundle>` は、git 2.43 では `fetch.fsckObjects=true` でも fsck しない（`.git`・`git~1` の tree と `.gitmodules` の symlink が通る）。取り込み後の `git fsck --strict` が要る。
- WSL2 は全ディストロが VM とループバックを共有し、Microsoft も隔離境界とみなさない。実機でしか出ない不具合が 12 件以上あった。
- 公開の package で足りるものは、自作より先に評価する（[ADR-0031](0031-evaluate-existing-extensions-first.md)）。
- 並列実装の運用の知見（試験の登録漏れ・並列 worker・全件検査の排他）は、[feature-orchestration スキル](../../.agents/skills/feature-orchestration/SKILL.md)に残している。

## 置き換えた決定と記録

撤去した docs は、タグ `archive/custom-harness-2026-11-12` で読める。

- ADR: 0001（外部ツールの設定領域との共存）・0002・0004〜0009・0012〜0019・0021〜0028・**0030（自作基盤の凍結）**・**0034（凍結した試験の省略）**。0017 は pi への一本化、0024 は PR ビューア、0026 は作業台帳、0028 は kcage の決定。
- 仕様・調査・案件（約 250 ファイル）: ガード・作業台帳・PR ビューア・サンドボックス（`pi-sandbox-runner` と WSL を除く）・OpenCode と各 CLI の生成・調査記録・案件。

## 後続（撤去では片づけていないもの）

- （済み 2026-11-12）検索の核（`websearch/core.py`）と `imozuru_net.py` にあった、`pis` の内側のプロキシ越しの取得（`PIS_FETCH_VIA_PROXY`）の死んだコードと、その試験・docs を消した。
- 検索の核（`websearch/core.py`）に、`pis` の検索ブローカー（`WEBSEARCH_BROKER_URL`・応答 `pis-broker: no key for …`）の死んだ経路が残っている。消すときは、`test_websearch.py`・`test_websearch_mcp.py`・`env_check.py` の許可リスト・[web-search](../spec/web-search.md) を同時に直す。
- （済み 2026-11-12）残った試験の重複の洗い出し。カバレッジで重複らしい試験を除くと、変異テストでの検出力が 5〜17% 落ちたので、件数を減らさない（[実測](../research/testing/test-reduction-2026-11.md)）。
- 配備済みの他ハーネスの設定（`~/.claude` など）は、利用者が手で消す。
