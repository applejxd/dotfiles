# 秘密ファイルの禁止を `experimental.policies` へ移せるか

全体の `permissions` に置いた秘密ファイルの read / edit の deny とその例外を、OpenCode の
`experimental.policies` へ移したときの効き方の実測。[CHG-0018](../../../change/closed/0018-opencode-policy-role-split.md)
の段 1。

## 記録 E1 — 2026-10-08

> **後続の観測**: E1 の「`build` は全件一致」は read の `.env.sample` / `.env.template` を含んでいない。
> 例外を policy に移すだけでは、この 2 つの read が ask に戻る（[E2](#記録-e2--2026-10-08)）。

- **対象バージョン**: OpenCode v2.0.22
- **環境**: WSL2 (Ubuntu)、基準コミット beae156、モデル `github-copilot/claude-opus-5`

### 問い

秘密ファイルの deny と例外（`.env.example` など）を policy にすれば、エージェント別の
`permissions` の allow や保存した承認に負けずに効き、例外は権限を与えないか。

### 事前の予想

公式の docs どおりなら、policy の deny はエージェントの規則と保存した承認の後に効き、
policy の `allow` は先の deny を解除するだけになる。

### 方法・条件

- 公式の docs（<https://opencode.ai/v2/docs/policies>、<https://opencode.ai/v2/docs/plugins>）と、
  バイナリの中の `Permission` サービスと組み込みの plugin `opencode.config.policy` の判定処理を読んだ
- 実際の設定を `.tmp/opencode/chg0018/` へ写し、次の版を作った（`plugins` は写した側の絶対パス）
  - `cfg-ctl`: 今の設定の写し（対照）
  - `cfg`: 全体の秘密ファイルの read / edit の deny 155 件と例外を policy へ移し、`plan` の
    `restate_global_deny` の edit の写し直しを外した版。並びは「対の deny → その例外 → 他の
    独立した deny」。`~` は生成時に絶対パスへ展開した
  - `cfg-noex`: `cfg` から `explore` の 4 つの deny も外した版
  - `cfg-noplug`: `cfg` から plugin を外した版
  - `cfg-bad`: 正しくない statement を混ぜた版
- v2.0.22 には policy を API から取り出す手段が無い。判定は 2 通りで確かめた
  - 評価器: 読んだ判定処理を `eval_policy.py` に写し、別ポートのサーバ
    （[組み込みエージェントの制限の上書き](builtin-agent-override.md) の記録 E2 の方法）から
    取った各エージェントの規則に当てた。評価器は写しで、正本ではない
  - 実機: `opencode run --standalone`（`--auto` なし。確認は自動で拒否される）を P1〜P5 で回した。
    モデルは全手順でツールを実際に呼んだ
- 保存した承認（P5）は、試験用 DB の写しの `permission` 表に `read *` / `edit *` /
  `shell touch *` を足して試した。実際の DB には書いていない

### 結果

| 確認 | 結果 | 根拠 |
| --- | --- | --- |
| `build` は `.env.example` を今までどおり扱える | はい | P1: `.env.example` の write・read と `sub/.env.template` の write が成功。評価器で 32 件を対照と比べ、`build` の allow / ask / deny は全件一致（作業ツリーの外の `.env.example` も今と同じ ask） |
| `explore` は `.env.example` を編集できない（4 つの deny を外した版） | はい | P2: `.env.example` も `a.txt` も `Permission denied: edit`（組み込みの `* * deny`）。`.env.example` の read は成功、`.ssh/.env.example` の read は `Blocked by configuration policy` |
| `plan` は計画ディレクトリの中の `.env` / `a.key` / `secrets/x.md` を編集できない（写し直しを外した版） | はい | P3: 3 件とも拒否、`ok.md` は成功 |
| `.ssh/.env.example` は例外で開かない | はい | P1・P4 で read・write とも `Blocked by configuration policy` |
| plugin を外しても禁止が残る | はい | P4（guide と checkpoint を外し、`-opencode.config.policy` も指定）: `.env` と `a.key` は Blocked、`.env.example` は成功。`opencode.config.policy` は外れなかった |
| 保存した承認が policy の deny を外さない | はい | P5: 保存が効いていること（普段 ask の `touch` が確認なしで実行された）を確かめたうえで、`.env` の read・write と `.ssh/.env.example` の read は Blocked |
| 通常の起動（`ocs` でない）で効く | はい | P1〜P5 はすべて通常の起動 |

policy の仕様（docs とバイナリを読んだ結果）:

- 書く場所は `opencode.json` の `experimental.policies`。statement は `action`
  （`permission` / `provider.use`）・`resource`・`effect`（`allow` / `deny`）の 3 キー。
  permission の `resource` は `<action>:<値>`
- 照合は `permissions` と同じく全体一致で、`*` は `/` も跨ぎ、最後に一致したものが勝つ
- 評価の順序
  1. エージェントとセッションの規則に deny があれば、その場で deny。plugin の hook は呼ばれない
  2. それ以外は、規則と保存した承認から ask / allow を決め、`permission.evaluate` の hook に渡す
  3. `opencode.config.policy` がこの hook の中で、resource ごとに最後に一致した statement が
     deny なら結果を deny にする。plugin の並びで guide / checkpoint より後に来る
- docs の記述: 「It applies after agent rules and saved approvals」、「A `permission` statement
  with `allow` never grants access」（<https://opencode.ai/v2/docs/policies>）
- `~` は展開されない（コードを読んだだけで、`~` 付きの statement は試していない）

`restate_global_deny` との差:

- 写し直しは deny だけを写して例外を写さないので、今の `plan` は計画ディレクトリの中の
  `.env.example` も拒否する（評価器）。policy 版は例外が効き、P3 で `.env.example` が作られた。
  秘密そのもの（`.env` / `*.key` / `secrets/`）の拒否は保たれた
- 規則の件数: `plan` は 170 件から 107 件（edit の写し直し 63 件が消えた）、全体は 356 件から
  159 件。全体の減った分のうち 42 件は「例外と確認の重なり」を ask に戻す規則で、例外の
  allow が `permissions` から消えると要らなくなる

正しくない statement:

- `effect: "ask"` や `action: "permissions"` の statement は、`opencode.log` に
  `configuration normalization diagnostic … kind=invalid action="skipped malformed recognized value"`
  の警告を出して捨てられた。ほかの statement は生きていた。警告は起動のたびに 2 回出た
- 余分なキーが付いた statement は警告なしで採られた

`explore` の 4 つの deny を外した版（P2）では、全体の `shell * ask` で shell が ask、`git log *` が
allow、`mise.toml` の edit が ask になり、ツールの一覧にも shell / edit / write / subagent が出た。

### 考察

- policy は通常の起動で効き、エージェントの allow・ask・保存した承認・plugin の有無のどれにも
  負けない。例外は解除だけで権限を与えない。候補 B は成り立つ
- `plan` の edit の写し直しは policy で置き換えられる。`explore` の 4 つの deny は、全体の
  allow / ask をエージェント別へ移さない限り外せない
- 正しくない statement は捨てられ、余分なキーは黙って通るので、生成器で形を検査する必要がある
- 組み込みの `plan` は、edit の拒否をすべて「計画ディレクトリの外は編集できない」という文面に
  書き換える。計画ディレクトリの中の拒否でもこの文面になる（コードで確認。今の静的な deny でも同じ）

### 次の問い

- `~` 付きの statement が実際に一致しないこと
- 対話の画面（TUI）と、Orca の上書き用の設定（`OPENCODE_CONFIG`）が重なったときの合成
- `ocs` の設定（`~/.config/opencode-sandbox/opencode.json`）にも秘密の policy を出すか
- 実機の試験は各 1 回で、再現性は確かめていない

## 記録 E2 — 2026-10-08

- **対象バージョン**: OpenCode v2.0.22
- **環境**: WSL2 (Ubuntu)、基準コミット 75c5f6e、モデル `github-copilot/claude-opus-5`

### 問い

全体の `permissions` の allow / ask をエージェント別の規則の束（プロファイル）へ移し、全体を
deny だけにしたとき、各エージェントの判定は今と同じになるか。どのプロファイルも当てない
エージェントはどうなるか。

### 事前の予想

`build` などは今と同じになり、組み込みの制限を持つ `explore` / `title` / `summary` は組み込み
どおりに戻る。プロファイルの無い子は基底の全部許可になる。

### 方法・条件

- 実際の `~/.config/opencode/opencode.json` と E1 の対照（`cfg-ctl`）が `plugins` 以外で同じことを
  確かめ、別ポートのサーバの `/api/agent` から全エージェントの実効規則を取った
- 全体の規則 356 件を群に分け、試作（`.tmp/opencode/chg0018/stage2/cfg-b2/`）を作った
  - 全体の `permissions` は `subagent` の `bypass-worker` / `bypass-fleet-worker` の deny 2 件だけ
    （`bypass` が自分の規則で解除するので policy に移せない）
  - shell の deny 101 件と、秘密ファイルの read / edit の deny と例外を policy へ
  - 実装役のプロファイル（`shell * ask`、shell の allow と ask、開けた場所の外部アクセスの allow、
    edit の ask、read の例外の allow）を `build` / `general` / `compaction` / 作業役 / `bypass` 系に、
    読み取り役のプロファイル（外部アクセスの allow、read の例外の allow）を `explore` / `plan` /
    `review` / `commit` に当てた。`title` / `summary` には何も当てない
  - `explore` の 4 つの deny と `plan` の `restate_global_deny` を外した。例外と ask の重なりを
    ask に戻す 42 件も外した。`bypass` / `bypass-worker` は V2 の `agents` へ移した
  - 対照と試作の両方に、プロファイルを当てない試験用の子 `dummy-child` を足した
- E1 の評価器で、969 件の操作を全エージェントについて対照と比べた。実機は
  `opencode run --standalone` を 1 回回した

### 結果

- 全エージェントは 13（`build` / `plan` / `general` / `explore` / `title` / `summary` / `compaction` と、
  自作の `bypass` / `bypass-worker` / `fleet-worker` / `bypass-fleet-worker` / `commit` / `review`）。
  plugin や skill が足すエージェントは無かった
- 今の設定では、組み込みの `* * deny` を持つ `title` / `summary` に、全体の allow / ask が流れ込んで
  いた（shell が ask / allow、`.env.example` の edit が allow など）。組み込みの追加方針は公式の docs の
  Defaults 節（<https://opencode.ai/v2/docs/permissions>）と一致し、`compaction` は基底のままだった
- 試作と対照の比較

  | 対象 | 結果 |
  | --- | --- |
  | `build` / `general` / `compaction` / `bypass` / `bypass-worker` / 作業役 2 つ / `commit` / `review` | 差 0 |
  | `explore`（4 つの deny を外した） | 差 0。実機のツールの一覧は glob / grep / read / subagent / webfetch / websearch。subagent は評価上 deny だが一覧には残った |
  | `title` / `summary` | 各 283 件が allow / ask から deny へ |
  | `plan` | 計画ディレクトリの中の `.env.example` の edit が deny から allow へ（1 件） |
  | `dummy-child` | 187 件が ask から allow へ、30 件が allow から ask へ。実機で shell の `touch` が確認なしに実行され、write も成功した。`git push --dry-run` は `Blocked by configuration policy` |

- 最初の試作では、全エージェントで `.env.sample` / `.env.template` の read が allow から ask に
  変わった（各 8 件）。基底の `read *.env.* ask` が残り、policy の allow は権限を与えないため。
  プロファイルに read の例外の allow を足すと解消した
- 試作の policy 258 件で、`opencode.log` に正規化の警告は出なかった

### 考察

- 全体の allow / ask をプロファイルへ移せば、`build` などの判定を保ったまま、組み込みの制限
  （`explore` / `title` / `summary`）が素のまま効く
- read の例外は、policy の allow とプロファイルの read の allow の両方に要る
- プロファイルを当てない子は基底の全部許可になる。守れるのは policy の deny だけ
- shell の deny を policy に移すと guide の `evaluate` の後に効く（`guide-plugin/index.js` の確認の
  説明の生成が先に走る。コードを読んだだけ）

### 次の問い

- 実際の生成器で同じ出力を作れるか。Claude Code / Copilot CLI の生成結果が変わらないか
- `compaction` / `title` / `summary` が実際にツールを呼ぶか
- V1 の `agent` と V2 の `agents` を同じ ID で併用したときの合成
- 実機は 1 回だけで、再現性は確かめていない
