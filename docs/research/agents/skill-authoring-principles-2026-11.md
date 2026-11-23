# スキルを書き換えるときの原則（調査。2026-11）

観測日 2026-11-23。自作スキルの本文が再膨張するので、公開されている原則を調べた。適用の例は `feature-orchestration` の書き換え。

| 原則 | 出典 | このリポジトリでの適用 |
| --- | --- | --- |
| **簡潔さ**: エージェントが既に知っていることは書かない。段落ごとに「このトークンの費用に見合うか」を問う | Anthropic「Skill authoring best practices」<https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices> | `git commit` の書き方・`git diff --stat` の説明など、汎用の知識を削る |
| **自由度を作業に合わせる**: 壊れやすい操作は正確なコマンド、判断は方針だけ | 同上 | `finish` のフラグ・worktree の作成は逐語で残し、レビューの観点などは 1 行にする |
| **段階的な読み込み**: 本文は目次と手順、詳細は 1 段の資料。本文 500 行以内 | 同上 | 事実の表を `references/pi-facts.md` へ移す |
| **時間に依存する記述を避ける**: 古い挙動は、印をつけた別の節へ | 同上、arXiv「Authoring Agent Skills: A Software-Engineering Approach」<https://arxiv.org/html/2607.25032v1> | 「2026-11-14 に起きた」のような日付つきの経緯を、本文から `docs/research/` へ移す |
| **単一責任・高い凝集・低い結合・トークンの節約** | 同上（arXiv） | 1 つの規則は 1 か所に書き、ほかは 1 行のリンクにする |
| **手順・事実・理由・入門を分ける**。手順の文書に事実や理由を混ぜると、読みにくく、正本になりにくい | Diátaxis <https://diataxis.fr/> | `SKILL.md` は手順、`references/` は事実、`docs/research/` は理由・経緯 |

出典はいずれも取得 2026-11-23。
