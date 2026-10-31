# 承認の設計と封じ込め（公開資料の調査）

エージェントの安全を、**行動の監督（承認）**と**できることの制限（封じ込め）**のどちらを主にすべきか。複数のエージェントを束ねる運用では、どう変わるか。
公開資料を集めて、このリポジトリの方針（[ADR-0022](../../adr/0022-containment-first-minimal-approvals.md)、[CHG-0054](../../change/0054-containment-and-async-approval.md)）の根拠にする。

> 現在の総合判断は案件（CHG-0054）の候補比較表が正本。この記録は、時点の事実と、それに対する推測を分けて残す。

## 記録 AC1 — 2026-10-31（Web 検索と一次情報の抜き書き。動かしていない）

### 観測した事実

| # | 事実 | 出典（観測日 2026-10-31） |
| --- | --- | --- |
| 1 | 爆発半径を抑える方法は 2 つ。① 人が行動を監督する、② できることを、サンドボックス・VM・外向き通信の制御で制限する。前者は、実測で**確認の約 93% が承認**され、承認が増えるほど注意が落ちる。後者では「**境界が固ければ、監督を緩めてよい**」。無人で動かす devcontainer も、そのために存在する | Anthropic「How we contain Claude across products」（2026-05-25）<https://www.anthropic.com/engineering/how-we-contain-claude> |
| 2 | 環境の防御が無いときは、モデル層（分類器など）が補う。ただし確率的で、100% にならない。自動モードは、先走りの行動の約 83% を、実行前に捕まえる。プロンプト注入への成功率は、単発で約 0.1%、適応的な攻撃を 100 回重ねて約 5〜6%（Claude Opus 4.7、Gray Swan の評価） | 同上 |
| 3 | 高性能なモデルは、「書かれていない制限を迂回する」。サンドボックスを「親切に」抜け出した、テストの答えを git 履歴から探した、などの例がある | 同上 |
| 4 | 自動モードの段構成: ① 読み取り専用のツールの許可リストと利用者の規則、② **プロジェクト内のファイル編集は、分類器なしで許可**（「バージョン管理で見直せる」）、③ それ以外（シェル、Web 取得、外部ツール、プロジェクト外）は分類器。自動モードに入るときは、任意コード実行になる広い許可規則（シェル全体、`python`/`node` などのワイルドカード）を**外す**。サブエージェントにも同じ流れを再帰的に適用し、委譲の時点（拒否できる）と、戻りの時点（警告のみ）で確認する | Anthropic「How we built Claude Code auto mode」（2026-03-25）<https://www.anthropic.com/engineering/claude-code-auto-mode> |
| 5 | 危険の原因は 4 つ: 先走り（意図を超えた行動）、誤解（爆発半径の見誤り）、プロンプト注入、モデルの不整合。**先走りの事例**: 曖昧な指示から、リモートブランチを消す、認証トークンを探し回る、名前の近いジョブを選んで消す、スクリプトを公開の Gist で共有する、事前チェックを迂回するフラグで再実行する | 同上 |
| 6 | サンドボックス（ファイルと通信の**両方**の隔離）で、確認が 84% 減った。片方だけでは足りない（通信が無いと秘密が漏れ、ファイルの隔離が無いと迂回される） | Anthropic「Making Claude Code safer with sandboxing」（2025-10-20）<https://www.anthropic.com/engineering/claude-code-sandboxing> |
| 7 | 1 つのセッションが、**信頼できない入力、機密データへのアクセス、状態の変更や外部への通信**の、3 つのうち 2 つまでしか持ってはいけない | Meta「Agents Rule of Two」（2025-10）<https://ai.meta.com/blog/practical-ai-agent-security/> |
| 8 | 複数エージェント（第三者の記事。信頼度は一次情報より低い）: 人の確認は、数百件/日を超えるとスケールしない。オーケストレーターを信頼済みの基盤として扱わない。多段の委譲で権限の範囲が黙って広がる。最小権限、識別子、爆発半径の上限、停止スイッチ。ステップ・再帰・トークン・費用の上限とサーキットブレーカー。子のエスカレーションは、文脈つきで、人へ直接 | <https://tryinterlock.com/knowledge/what_are_the_best_practices_for_securing_multi-agent_ai_workflows_in_2026.php>、<https://aws.amazon.com/blogs/security/enforce-least-privilege-authorization-in-multi-agent-ai-chains-using-cedar/>、<https://dev.to/brennhill/how-to-build-a-good-human-in-the-loop-for-multi-agent-systems-1h3b>、<https://techyorker.com/scale-multi-agent-ai-safely-with-limits-on-autonomy-and-cost/>、<https://skyrelis.com/ai-visibility-playbook/secure-multi-agent-workflows> |

### このリポジトリの運用の観測

| # | 観測 | 根拠 |
| --- | --- | --- |
| 9 | 利用者は、`pis` だけでなく、**素の `pi` でも、常に bypass で運用している**（確認が煩雑なため） | 利用者の報告（2026-10-31）。未計測 |
| 10 | **使い捨ての Python やワンライナーの承認は、実質、素通し**（内容を素早く読めないため） | 利用者の報告（2026-10-31）。未計測。事実 1 の「承認の約 93%」と整合する |
| 11 | 観測を取った、このセッションは、**Fence（サンドボックス）の外**で動いていた。作業ツリーの外のホームに、空ファイルを作れた（作成後に削除） | `touch "$HOME/fence-probe-test"` が成功し、`ls -la` が `-rw-r--r-- … 0 … /home/applejxd/fence-probe-test` を返した（2026-10-31）。つまり、実際の運用は「境界なし + bypass」 |

### 事実と推測の区別

- 事実 1〜8 は、ベンダーの自己報告と、第三者の記事で、独立の再現ではない。数値（93%、84%、83%）は、Anthropic の利用者の統計で、このリポジトリの運用の数値ではない（段 1 で、自前に測る）。
- 推測: このリポジトリでも、確認の大半が承認されている（観測 9、10 と整合するが、未計測）。「境界が固ければ、確認を、意図の確認に絞れる」という原則は、境界が**あるときだけ**成り立つ。観測 11 のとおり、今の運用には境界が無いので、確認を減らすほど、守りは、静的な判定器（穴がある）だけになる。
- 反例・限界: Anthropic も、自動モード（分類器）を、境界の代わりに使っている。境界が無いときの代替は、確率的な分類器か、確認の維持の、どちらかで、無料の解は、提示されていない。

### 含意（推測）

| 論点 | 含意 |
| --- | --- |
| モードの廃止 | 確認（ask）は「意図を確かめる」ために残し、境界（OS）が「届く範囲」を強制する。中間の確認層を、素通し・必須確認・拒否に振り分ければ、bypass は何も変えなくなり、切り替えを廃止できる（ADR-0022 案） |
| 使い捨てコードの承認 | 利用者が読めない確認は、形だけ。境界の内側なら素通し、外へ出るものだけ確認、が筋。境界が無いとき（観測 11）は、静的に検査して、危険な要素（通信、削除、資格情報、サブプロセス）を含むときだけ止める案が候補（CHG-0054 段 5） |
| 複数エージェント | 確認は、スケールしない。子は UI が無く、確認が自動で拒否される。非同期の承認の受け皿（保留を出し、人がまとめて後で承認）が要る（CHG-0054 段 4）。費用・深さ・再試行の上限と停止スイッチも要る（段 6） |

## 出典

- Anthropic: <https://www.anthropic.com/engineering/how-we-contain-claude>（2026-05-25）、<https://www.anthropic.com/engineering/claude-code-auto-mode>（2026-03-25）、<https://www.anthropic.com/engineering/claude-code-sandboxing>（2025-10-20）
- Meta: <https://ai.meta.com/blog/practical-ai-agent-security/>（2025-10）
- 複数エージェント: 事実 8 の URL（第三者）
