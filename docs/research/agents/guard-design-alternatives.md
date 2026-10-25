# 外部送信・公開・破壊的操作を防ぐ設計の代替案（網羅調査）

- **観測日**: 2026-10-25。`explore` 3 件（ネットワーク層、資格情報・サーバ側、環境・承認方式）と `review` 1 件（リポジトリ内の独立評価）。子は検索結果の抜粋が中心で、**本文を読んでいないものが多い**（各節に明記）。実機の試験は無し
- **目的**: 現状（OS サンドボックス → 認証ブローカー → コマンド判定器）より良い設計があるかを確かめる。結果が現状維持でもよい（[CHG-0038](../../change/0038-guard-reclassification.md)）

## 結論

- **3 層の骨格は現状維持が妥当**。置き換える別設計は見つからなかった。研究が推す優先順位は「能力の除去（認証情報を持たせない・egress 遮断）> 隔離 > 人の承認 > 分類器 > コマンド判定」で、今の層の並びと一致（推測を含むまとめ。出典は二次情報）
- **小さな改善が 2 件**: ① 個人機の `gh` が広い権限の OAuth トークンで、「操作の防御は PAT スコープ」が個人機では成立していない（review の指摘）。② ブローカーへの REST の deny ルートは、判定器の**撤去ではなく追加**として有効
- 「判定器の公開系の列挙をブローカーへ寄せて撤去する」は**早計**（GraphQL と、ブローカーを通らない `git` の HTTPS・配布系が残る）。この点は、会話での私の暫定案を、review が否定した

## 系統別

### A. ネットワーク層・プロキシ層

- 既製品: Claude Code の sandbox（外部プロキシが `allowedDomains` を照合し、未知のホストは初回に人へ確認）、OpenShell（既定 deny。L7 でメソッド・パス。一時 CA で TLS を終端）、nono（L7 を可視化）、Codex（管理プロキシ。二次情報）、Docker Sandboxes（microVM。ホスト側プロキシ。認証情報は実行時に VM の外から注入）。Gemini と Fence は未調査
- 認証をプロキシ側に置く実例: mitmproxy の `agent-proxy`、Infisical の `agent-vault`、Onyx（操作ごとに ALWAYS/ASK/DENY。高リスクの操作は、認証を付ける前に人が承認）
- **限界**（確認済みの報告）: GraphQL は URL が同じで、`createIssue` は不透明な `repositoryId` しか持たず、プロキシがリポジトリを特定できない（flotilla の調査）。Anthropic の GitHub プロキシは GraphQL を全拒否し、`gh issue`/`gh pr` が壊れる。先頭にコメントや BOM を付けた mutation の回避例もある。ピン留め証明書・独自 CA のクライアントは MITM で壊れる。git over ssh は L7 で見えない。Claude Code の sandbox は、macOS で許可リスト外へ CONNECT が通る不具合の報告がある（#77045）
- **UX**: 承認画面にホストしか出ず意味が見えない（推測）。OpenShell の Policy Advisor は、L7 の提案を人が承認し、却下理由を agent に返す

### B. 資格情報・サーバ側の権限

- 出典: <https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens>（公式の権限表。**確認済み**）

| 操作 | 必要な権限 |
| --- | --- |
| 公開化・名称変更・設定変更・削除・移譲 | `Administration:write` |
| ファイル変更・ref の作成/更新/削除・release の作成・PR のマージ・`repository_dispatch` | `Contents:write` |
| issue の作成 | `Issues:write` |
| PR の作成 | `Pull requests:write` |
| `workflow_dispatch` | `Actions:write` |
| `.github/workflows` の変更 | `Workflows:write`（`Contents:write` に加えて） |

- `Metadata:read`+`Issues:write`+`Pull requests:write`+`Contents:read` なら、投稿はでき、公開化・削除・push・release・マージはできない（権限表からの読み取り。**実機では未試験**）。PR の作成には head ブランチの push が要る（推測）
- GitHub App のインストールトークンは約 1 時間で失効し、1 リポジトリに絞れる（検索結果の要約）。運用負荷は、App の作成、秘密鍵の保管、JWT からのトークン発行
- トークンに依らない防御: 組織の設定でリポジトリの公開化・作成を制限（**個人アカウントでは使えない**。推測）、ruleset（削除・force push の禁止、必須レビュー）
- publish 権限: npm の Trusted Publishing（CI の短命資格情報）、crates.io の Trusted Publishing、PyPI の Trusted Publishers。Docker Hub は確認できなかった。**いずれも本文は未読**

### C. 環境・OS・承認方式

- **提案-承認分離**（agent は push・PR 作成ができず、別プロセスの特権 publisher が実行）: 個人・小規模の issue での提案のみ（agent-flywheel、FirstContact-ControlPlane）。広く使われた実例ではない
- **ネットワーク遮断+許可リストの VM**: Docker Sandboxes など。隔離が解くのはホスト侵害で、**権限の問題（保護ブランチへの push、公開）は解けない**（permit.io）
- **LLM 分類器**: Anthropic の auto mode は、実際の「出過ぎた行動」52 件に対する偽陰性率 17%、実トラフィック 1 万件での偽陽性率 0.4%（公表値）。第三者の評価（arXiv 2604.04978）では、曖昧な DevOps プロンプト 128 件で偽陰性率 81.0%（著者は本番へ当てはめないよう注記。要約記事経由）。分類器は確率的で、決定論的な遮断ではない
- **サーバ側のゲート**: ブランチ保護・必須 PR・CI は、agent が回避できない。ローカルの pre-push hook は `--no-verify` で回避される（推測）。GitHub 以外の送信や破壊的操作は止められない
- **研究**: lethal trifecta（私的データ・信頼できない入力・外部送信を同一の文脈に置かない）、Meta の Rule of Two（3 要素のうち同時に 2 つまで。3 つ要るなら人の承認）

## リポジトリ内の独立評価（review）

- **MAJOR**: 個人機は `gh auth token` を採用し（`common.toml.tmpl` の `github_token_command`）、その OAuth トークンは広く後から絞れない（`opencode-sandbox.md`、CHG-0037）。Envoy は全メソッド・全パスを通す（`envoy-github.yaml`）。**資格情報の隔離はできても、その資格情報で許される破壊的操作の防止にはなっていない**。最小の改善: 個人機も対象を絞った fine-grained PAT へ（代償: 発行・更新の運用）
- **MAJOR**: 「REST の deny ルートで `check_gh_api_publish` を撤去できる」は早計。判定器は GraphQL の公開・ref 更新も検出している（`judge/ghapi.ts`）。Envoy のパス・メソッドでは `/graphql` 内を区別できず、本文を読む案は自作コード削減に逆行する。Envoy が守るのは**そのソケットを通る認証済み API**で、`git` の HTTPS は通らない。ブローカーの REST の deny は**追加**し、既存の判定器と併用して試験する
- **MINOR**: 「外部への送信を防ぐ」の保証範囲を分けて書くべき。`curl`/`wget` の POST と MCP は bypass 可能な ask、Python 経由は語の判定を外れる
- **問題なし**: 投稿の内容確認をコマンド層に残す判断（Envoy は本文を承認 UI に出せない）

## 未確認・次の候補

- 実機で、絞った PAT（`Administration` 無し）が日常の `gh issue`/`gh pr` を通し、公開化・push を 403 にするか。個人機の移行手順
- ブローカーへの REST の deny の、Envoy 実機での挙動。GraphQL をどう扱うか（全拒否は閲覧も壊す）
- Gemini・Fence・Squid・Envoy の `ext_authz` の実装例、各社 docs の本文、Firecracker・gVisor・devcontainer の個別の運用例

## 参照

- <https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens>、<https://docs.github.com/en/rest/authentication/permissions-required-for-github-apps>
- <https://code.claude.com/docs/en/sandboxing>、<https://github.com/anthropics/claude-code/issues/77045>、<https://github.com/flotilla-org/flotilla/issues/3125>、<https://onyx.app/insights/secure-agent-access-control>
- <https://www.docker.com/blog/why-microvms-the-architecture-behind-docker-sandboxes/>、<https://www.permit.io/blog/coding-agent-sandboxes-credentials>
- <https://www.anthropic.com/engineering/claude-code-auto-mode>、<https://arxiv.org/html/2604.04978v2>
- <https://simonwillison.net/tags/lethal-trifecta/>、<https://ai.meta.com/blog/practical-ai-agent-security/>
