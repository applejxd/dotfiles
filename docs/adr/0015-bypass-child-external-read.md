# OpenCode の bypass から起動した読むだけの子の、作業ツリーの外の読み取りの確認を省く

- **ステータス**: Accepted
- **日付**: 2026-10-08
- **決定者**: applejxd

## コンテキスト

[ADR-0014](0014-bypass-as-ask-upgrade.md) で、`bypass` は「確認（ask）を guide plugin が
`allow` にするだけ」のエージェントになった。対象は `bypass = true` を付けたエージェント
（`bypass` / `bypass-worker` / `bypass-fleet-worker`）で、判定は評価しているエージェントの
名前だけを見る。そのため、`bypass` から起動した読むだけの子（`explore` / `review` /
`commit`）の確認は自動で通らない（ADR-0014 のネガティブな結果）。

[CHG-0017](../change/0017-builtin-agent-restrictions.md) で `explore` に shell と edit の deny を
足した後も、子に残る主な確認は、開けていない作業ツリーの外を読むときの
`external_directory` だった。利用者の方針は「`bypass` と `bypass` の上の `/fleet` では、
利用者に聞かずできるだけ自動で判断させる」である。

`permission.evaluate` の入力に親のセッションの ID は無いが、`sessionID` から
`ctx.session.get` で `parentID` と、そのセッションの今のエージェントを引けることを実測した
（CHG-0017 の段 7）。

`external_directory` は読み取りだけの確認ではない。shell を作業ツリーの外の `workdir` で
動かすときにも出る。`commit` は `git status` / `git diff` を allow しているので、shell 由来まで
省くと外部のリポジトリで git が確認なしに動き、リポジトリの設定によっては外部のコマンドも
起動しうる。

## 検討した選択肢

### 選択肢 1: 現状維持

- **利点**: 変更なし
- **欠点**: `bypass` から起動した子が作業ツリーの外を読むたびに確認が出て、利用者の方針に合わない

### 選択肢 2: `bypass` 専用の読むだけの子（`bypass-explore` など）を新設する

- **利点**: plugin の判定は今のまま（名前だけ）で済む
- **欠点**: 自作のエージェントは基底の「全部許可」から始まるので、組み込みの `explore` が
  持つ制限（MCP や Code Mode を使えない）を別に設計して保守する必要があり、定義が二重になる。
  `build` から起動させない仕組みも要る。`commit` の git の副作用の問題は解決しない

### 選択肢 3（採用）: 親が `bypass` のとき、決めた子の作業ツリーの外の読み取りの確認を plugin が省く

- **利点**: 組み込みの子の権限とプロンプトをそのまま使える。`build` から起動した子には効かない。
  条件から外れれば確認に戻る
- **欠点**: plugin がセッションの API に依存する。親の今のエージェントで判定するので、
  親を切り替えると既に起動していた子にも効き方が変わる

## 決定事項

選択肢 3 を採用する。guide plugin の `permission.evaluate` で、ADR-0014 の `ask` → `allow` の
直後に、次の条件を**全部**満たすときだけ `ask` を `allow` にする。

1. 効果が `ask`
2. 評価しているエージェントが、`common.toml` の `[opencode.bypass_children] agents` に明示した
   子（現行は `explore` / `review` / `commit`）に完全一致で含まれる。この一覧は `bypass` の
   起動の許可リストから導出しない（「起動してよい」と「確認を省いてよい」は別の権限）。
   生成器は、起動の許可リストの部分集合であること・`bypass_agents` と重ならないこと・
   ワイルドカードを含まないことを検査する
3. action が `external_directory`
4. その確認が `read` / `grep` / `glob` ツールから出たもの（shell や edit から出たものは対象外）
5. 直接の親（1 段だけ）の今のエージェントが `bypass_agents` に入っている

親を辿れないとき、一覧が読めないときは `ask` のまま（権限を足す機能なので、分からなければ
足さない）。静的 deny は plugin に届かないので、この決定でも外れない。

仕様の詳細は [bypass から呼べる子エージェント](../spec/agent-config-generation.md#bypass-から呼べる子エージェント)。

## 決定の確認方法

- [x] 生成した `rules.json` に `bypass_child_agents` が出る（通常版と `ocs`、私用と会社用）
- [x] node で plugin を読むテストで、条件の各組み合わせ・API の失敗・設定の異常を固定した
- [x] 試験用の設定の実機で、`bypass` → `explore` の作業ツリーの外の read が確認なしで通り、
  `build` → `explore` では確認のままだった
- [x] 本物の設定に apply した後の実機（CHG-0017 の段 8）。3 つの子の read / grep / glob が
  確認なしで通り、`commit` の shell 由来と `build` から起動した子は確認のままだった

## 結果

### ポジティブな結果

- `bypass` から起動した読むだけの子が、作業ツリーの外を読むたびに止まらなくなる
- 定義を二重に持たない

### ネガティブな結果

- 自動で確認を省くのは作業ツリーの外の読み取りだけで、`production.env` のような読み取りの
  確認や、shell 由来の確認は残る
- `bypass` の意味が「自分の確認を省く」から「自分と、自分が起動した決めた子の外の読み取りの
  確認を省く」に広がる

### 中立的な結果

- 判定は親の今のエージェントで行う。親を `bypass` から `build` に切り替えると確認に戻り、
  逆に切り替えると `build` が起動していた子にも効く

## 関連 ADR

- [ADR-0014](0014-bypass-as-ask-upgrade.md): `bypass` を ask → allow に再定義した。
  ネガティブな結果の「子の ask は対象外」を本 ADR で部分的に改める
