# コマンド判定の設計の経緯メモ（廃止した判定・以前の穴・採用理由）

`docs/spec/guard/agent-command-policy.md` の各節から移した記録。移設時点で再測定していない。元の文をそのまま書く。

## 記録 E1 — 日付不明（移設時点の記述）

- **対象バージョン**: 該当なし（設計の経緯）
- **環境**: このリポジトリ（chezmoi）。観測日は元の文に無い

### 問い

コマンド判定の各規則は、なぜ今の形になったか（廃止した判定、直した穴、他の案を採らなかった理由）。

### 事前の予想

元の文には書かれていない。

### 方法・条件

spec の記述から、経緯・比較の部分だけを移した。

### 結果

#### git -C の部分一致の判定を廃止した理由

（元: 照合規則）以前あった部分一致の判定は `git -C sub show HEAD -- config/app.yml` のような読み取りまで deny する誤検知しか生まなかったため廃止した。

#### OpenCode の unless の以前の穴

（元: OpenCode の pip 誘導と rm の誘導）以前の `unless` はコマンドのどこかに `git … -m` があれば全体を見送り、`git commit -m x && rm -rf ~` が素通りしていた。

#### scratch 免除の誘導をメッセージにした理由

（元: 使い捨てディレクトリ (`./.tmp`) の削除）常時読み込まれる個人用カスタム指示に書くと毎ターンコンテキストを消費するため、**止めた時点のメッセージで誘導する**方を採った。

#### OpenCode 前段停止の過去の穴

（元: OpenCode の deny の説明（前段停止））

- エージェントの規則が静的 deny を覆す項目（`except_agents`）: 以前は `commit` がコミットまで行い、`git restore --staged -- *` の allow が該当した。
- `guide` 節の検証: `pattern` 欠落が `new RegExp(undefined)` で全一致になり、全 shell を止める穴があった。

### 考察

現行の仕様は [agent-command-policy.md](../../spec/guard/agent-command-policy.md)。

### 次の問い

なし。

### 参照

- [agent-command-policy.md](../../spec/guard/agent-command-policy.md)
