# エージェント基盤（自作のガード・境界・隔離環境）を全面凍結し、pi を公式の既定＋人気の拡張へ戻す

- **ステータス**: Accepted（2026-11-08。可逆。再開の条件は下に書く）
- **日付**: 2026-11-08
- **決定者**: applejxd
- **関係**: [ADR-0017](0017-pi-only-and-ts-judge.md)・[0018](0018-pis-sandbox-default-relax-only-when-proven.md)・[0022](0022-containment-first-minimal-approvals.md)・[0024](0024-human-press-merges-in-app.md)・[0026](0026-work-ledger-integrated-architecture.md)・[0027](0027-isolation-unit-is-environment.md)・[0028](0028-per-repo-agent-container.md) で作ってきた自作の基盤を**凍結する**（置き換えるのではなく、動かさず残す）。記録と再開の手引きは [CHG-0065](../change/0065-agent-stack-freeze.md)。番号 0029 は、凍結した枝（`feature/kcage-clone-docs`）の「kcage の clone モード」の ADR が持っているので、使わない。

## コンテキスト

約 2 か月で、AI コーディングエージェントのまわりに次の自作の基盤を積み上げた。

- **フルガード**（pi のハーネス・TypeScript の判定器・確認画面・承認の保留）
- **境界**（`pis`／`ocs`／Fence の OS サンドボックス）と、使い捨てコンテナ `pisd`
- **作業台帳・`/goal`・並列実行・通知**、PR ビューアと統合の運用
- **隔離環境**（kcage: WSL2 の Incus の箱、broker、`.git` の保護、clone モード、複数 repo）

どれも「守る」という目的には筋が通っていたが、次の問題が出た。

- **部品が多く、保守の負担が実装の価値を上回った。** 層を足すたびに別の層との接続（権限・認証・git・worktree・ポート）が増える。
- **守りの穴が次々に見つかった**（kcage だけで、制限つきプロジェクトの脱出、`commondir` の迂回、`mv .git` の迂回、bundle の fetch が fsck しないこと、など。詳細は [CHG-0065](../change/0065-agent-stack-freeze.md) の「学び」）。穴を塞ぐ作業が、本来の開発を圧迫した。
- **公式の pi と、コミュニティの package が成熟した。** 権限の確認・子エージェント・MCP・todo・利用者への質問・Web 検索などは、人気の package で足りる（[pi の package カタログ](https://pi.dev/packages)）。pi の公式文書にも、隔離の標準的な構成（Docker・Docker Sandboxes・OpenShell・ツールだけの隔離）が載っている。

## 決定

1. **自作のエージェント基盤を全面凍結する。** ソース・docs・試験は消さず、これ以上は開発しない。未完の作業（kcage の clone モードなど）は枝に残す。
2. **pi は、公式の既定の構成に戻し、人気の拡張（package）をそのまま入れる**（stock プロファイル。初期の一覧は `home/.chezmoitemplates/pi-stock-packages`）。切り替えは**可逆な旗**（`~/.config/chezmoi/pi-profile` か環境変数 `CHEZMOI_PI_PROFILE`）で行い、リポジトリの既定は custom のままにする（自作の配備に戻せる）。
3. **他の CLI（Claude Code・Codex・OpenCode・Copilot・Gemini）の設定生成と、実行ファイル（`pis`・`pk`・`kcage` など）は触らない。**
4. **記録を残す。** 経緯・凍結の一覧・未完の枝・学び・再開の手引きを [CHG-0065](../change/0065-agent-stack-freeze.md) に、調査の原本を `docs/research/archive/2026-11-agent-stack/` に、凍結した枝の bundle を `.tmp/keep/archive/` に置く。

## 設計の原則として残すもの（再開するときの出発点）

隔離は「完全」を目指さず、**被害の上限を決める**ものとする。信頼の線は、次の 3 つの問いで引く。

| 問い | 「はい」なら | 「いいえ」なら |
| --- | --- | --- |
| **1. 戻せるか**（reflog・snapshot・bundle・再生成） | 信頼してよい（フルガードの確認で足りる） | 境界で守る |
| **2. 箱の外へ出る、またはホストで自動実行されるか**（push・認証・秘密・ホストの git が読む設定） | 境界で遮断する | 信頼してよい |
| **3. 機械で検証できるか**（試験・selftest で縛れるか） | 「保証する」と書ける | 保証せず、運用（レビュー）か受容に回す |

守りは 4 段階で割り当てる: **遮断**（境界。試験で縛る）→ **抑止**（確認画面）→ **回復**（reflog・snapshot・bundle）→ **受容**（検証できないもの。最新化と運用）。信頼は「コード」ではなく**データの流れの向き**で決める（ホスト → 箱は信頼、箱 → ホストは検証してから使う）。「pi が箱の中にあるか」より「箱の外に対して何を行使できるか」が本質で、ホストで自動実行される設定・認証・push が、遮断すべき通り道である。

## 結果

- **失うもの**: フルガードの機械的な拒否・承認の画面・境界（Fence）による隔離。stock の pi は、権限の確認の package（`pi-permission-system`・`cc-safety-net`）が入っても、**うっかり防止の程度**にとどまる。コンテナ開発（GPU・compose が要る repo）の隔離環境は、当面無い。
- **得るもの**: 保守する自作部品が（凍結により）無くなる。pi の更新・package の更新に追従するだけでよくなる。
- **運用の注意**: 信頼できないコード・依存を動かす作業や、秘密を含む環境では、自分の判断で隔離する（pi の公式文書 `docs/containerization.md` の方法: Docker Sandboxes など）か、その作業をしない。
- 統合済みの kcage（develop に入っている）は、動かさず残す。この機械に導入済みの Incus・許可表・sudoers の片付けは、利用者が行う任意の手順（CHG-0065）。

## 採らなかった案

- **kcage の clone モードを完成させる**: 設計（D1〜D20）と第 1 波の実装は済んでいたが、残りが大きく（複数 repo の列挙・seed・sync・CLI・実機の確認）、守る対象に対して重すぎると判断した。
- **ツール隔離**（pi はホストに残し、ツールの実行だけを隔離環境へ流す）: pi の公式の型で、調査では実現可能だった（`operations` の差し替え。grep は自作が要る）。ただし、ハーネスのローカル前提（git・worktree・台帳・子エージェント・`bg_run`・`post_edit`）が深く、ホストの pi が注入を受けうる弱点が残る。スパイクは着手前に中止した。
- **ネイティブ Ubuntu 機（SSH のみ）を実行先にする**: GPU 開発が WSL 側にあるため、第一候補にしなかった。
- **coi・isx を採用する**: どちらも、制御面の分離・GPU・WSL2 の要件を満たさない（[評価](../research/agents/oss-sandbox-evaluations-2026-11.md)）。

## 見直しの条件

- stock の運用で、実際の事故または事故の寸前が起きたとき。
- 公式の pi が、権限の制御・隔離の機能を標準で持つようになったとき。
- コンテナ開発（GPU・compose）の隔離が、また要るようになったとき。再開の入口は [CHG-0065 の再開の手引き](../change/0065-agent-stack-freeze.md#再開の手引き)。

## 関連

[CHG-0065](../change/0065-agent-stack-freeze.md)（記録と再開の手引き）・[ADR-0028](0028-per-repo-agent-container.md)・[kcage の概要（凍結した枝）](../research/archive/2026-11-agent-stack/README.md)・[同種の OSS の評価](../research/agents/oss-sandbox-evaluations-2026-11.md)・[ツール隔離の実現性](../research/agents/tool-isolation-feasibility-2026-11.md)
