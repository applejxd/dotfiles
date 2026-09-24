# filesystem ガードの機構を「両 CLI が強制できるか」で分ける

- **ステータス**: Accepted
- **日付**: 2026-09-14
- **決定者**: applejxd

## コンテキスト

ファイルアクセスの防御は 3 層ある ([エージェント権限仕様](../spec/agent-permissions.md))。

| 層 | 仕組み | 効く CLI |
| --- | --- | --- |
| 0. sandbox | OS レベル (bwrap / Seatbelt) のパス制御 | 両方 |
| 1. permission リスト | `~/.claude/settings.json` の `permissions` | **Claude のみ** |
| 2. hook | `check_bash.py` 等が返す deny / ask | 両方 |

`common.toml` のキー名を「共有 = 無印 / CLI 固有 = CLI 名の接頭辞」へ揃える
作業 ([ADR-0006](0006-instructions-to-mechanisms.md) の続き) の中で、
**層 1 にしか載っていない防御**が残っていることが分かった。

`[file] claude_read_deny_globs` は `**/*.pem` や `**/secrets/**` のような glob で、
Claude では `Read()` の deny permission になる。ところが Copilot には対応物が無い。

- `permissions-config.json` はファイル規則を表現できない (bash の allow と
  locations だけ)
- sandbox の `deniedPaths` は **絶対パス限定・ワイルドカード非対応**
- しかも Copilot は cwd を自動で read/write 許可する

結果として **リポジトリの中に置かれた秘密ファイル (`certs/server.key` など) は
Claude では読めず Copilot では読める**、という非対称が生まれていた。

同時に、逆向きの非対称もある。`claude_read_allow` / `copilot_read_allow` は
「Copilot の `allowDevToolAccess` に相当する機構が Claude に無い」ことを
手で埋めるためのもので、これは**実効ポリシーを揃えるための補償**であって
方針の違いではない。

この 2 つは見た目が似ている (どちらも CLI 名の接頭辞が付く) が、性質が違う。
区別する基準が無いと、次に設定を足すときにまた片方だけの防御が生まれる。

## 検討した選択肢

### 選択肢 1: 現状維持 (層 1 の Claude 専用防御を許容する)

- **利点**: 変更が要らない。Claude は厳しいままでいられる
- **欠点**: 「Copilot は家用で緩め」という運用方針を超えて、
  リポジトリ内の秘密が読めるかどうかが CLI によって変わる。
  しかも設定ファイルを見ても、どの防御が片側だけなのか分からない

### 選択肢 2: Copilot の sandbox `deniedPaths` に絶対パスで列挙する

- **利点**: OS レベルで強制でき、迂回耐性が最も高い
- **欠点**: ワイルドカードが使えないので `**/*.pem` を表現できない。
  リポジトリごとに実在するファイルを列挙することになり、
  ファイルが増えるたびに設定が古くなる。マシン間でも共有できない

### 選択肢 3: 層を「誰が強制できるか」で分け、片側だけの防御を無くす

機構の選択を次の規則に従わせる。

1. **両方の sandbox で表現できるものは sandbox に置く** (共有キー `deny`)
2. **sandbox で表現できないものは hook に置く** (両 CLI で動く)
3. **CLI 固有キーは「許可」の補償にだけ使う。「禁止」を置かない**

3 が肝で、「禁止が片側にしか無い」状態を定義上作れなくする。
許可の非対称は実効ポリシーを揃えるためのものなので安全側に働くが、
禁止の非対称はそのまま穴になる。

- **利点**: 設定を見れば防御がどちらに効くか判断でき、テストで固定できる。
  新しい規則を足すときの置き場所が一意に決まる
- **欠点**: hook 層が増える。プロセス起動のコストと誤検知の管理が要る

## 決定事項

**選択肢 3 を採用する。**

### 機構の境界

| 表現したいもの | 置き場所 | 効く CLI |
| --- | --- | --- |
| 絶対パス・ワイルドカード無しの遮断 | `[sandbox] deny` | 両方 (OS レベル) |
| glob / cwd 相対 / 意味論を含む遮断 | hook | 両方 |
| 片方の自動付与を再現する**許可** | `claude_*` / `copilot_*` | 片方 (補償) |

**CLI 固有キーに禁止を置かない。** これは
`test_generate_sandbox.py` と `test_check_file_read.py` で固定する。

### `[file] claude_read_deny_globs` の扱い

`check_file_read.py` を追加し、Copilot のファイル読み取りツール (`view`) に
対して **Claude の permission と同じリスト**を適用する。
判定ロジックは `command_policy.matches_any_glob()` に置き、
`Read()` permission と同じ glob 記法 (`**/` と `*`) を解釈する。

### hook を Claude に付けない理由

`claude_event` を書かず、**Copilot 専用**にする。

Claude は同じリストから `Read()` deny permission を生成済みで、CLI 本体が
評価する。hook を足しても防御は増えず、**全ファイル読み取りに Python の
プロセス起動が乗る**だけになる。ファイル読み取りはエージェントの操作の中で
最も頻度が高いので、この差は無視できない
([ADR-0004](0004-hook-check-semantic-axis.md) の実測では hook 1 回あたり
110ms、その大半が Python の起動時間だった)。

「機構が CLI ごとに違う」ことは許容する。禁止したいのは
**防御の有無が CLI ごとに違う**ことであって、実現手段の違いではない。
両者が同じリストから導出されることをテストで固定しておけば、
ルールが 2 箇所に分かれて片方だけ古くなる事故は防げる。

## 完了条件

- [x] `command_policy` に `load_read_deny_globs()` と `matches_any_glob()` を追加
- [x] `check_file_read.py` を追加し、Copilot の `view` / `Read` に適用する
- [x] 設定を読めないときは fail-closed で deny する
- [x] hook を実プロセスで起動する回帰テストを 30 件追加
- [x] `[file]` のキーへ `claude_` 接頭辞を付け、未知キーを `validate_sandbox_keys()`
      が検出するようにする
- [x] 生成物が改名前と完全一致することを確認する

## 結果

### ポジティブな結果

- リポジトリ内の秘密ファイルが、Claude と Copilot の**両方**で読めなくなった
  (実測: `certs/server.key` `secrets/db.yaml` `.env`
  `config/service-account-prod.json` がいずれも deny)
- 新しい規則の置き場所が一意に決まるようになった。
  「sandbox で書けるか」を最初に判断し、書けなければ hook へ回す
- 「CLI 固有キーに禁止を置かない」がテストで固定され、
  片側だけの防御が再発しなくなった

### ネガティブな結果

- hook が 1 つ増え、Copilot のファイル読み取りにプロセス起動のコストが乗る。
  Claude 側は permission のままなので影響を受けない
- glob の照合エンジンが 2 つ (Claude 本体と `matches_any_glob()`) になった。
  同じリストを読むのでルールは 1 箇所だが、記法の解釈がずれる可能性は残る。
  `**/` と `*` の扱いはテストで固定した
- `[file]` の glob は元々 Claude 向けに調整されたもので、
  誤検知の許容線もそこで決まっている。Copilot にも同じ線が適用される

### 中立的な結果

- 残る非対称は `claude_network_*` だけになった。
  Copilot にドメイン単位の制御が無く (`allowOutbound` の on/off だけ)、
  hook でも代替できない (shell 経由の通信は `check_bash.py` が見るが、
  CLI 内蔵の web fetch は対象外)

## 後日の更新（2026-09-23）

**`[file]` への `claude_` 接頭辞は [CHG-0005](../change/0005-agents-config-naming.md)
で外した。** 本 ADR の**原則（共有 = 無印 / CLI 固有 = CLI 名の接頭辞）は変えて
いない**。原則はそのままに、事実の側が変わった。

| 当時 | 現在 |
| --- | --- |
| `[file]` の glob は Claude の `Read()` / `Edit()` permission になるだけ | Claude に加えて **OpenCode の通常版・境界版**の read / edit 規則にもなる（[CHG-0004](../change/closed/0004-opencode-sandbox.md)） |
| Copilot へは `check_file_read.py` で別途適用 | 同じ（変わらず） |

3 つの CLI へ届くものに `claude_` が付いたままだと、**規則 3（CLI 固有キーに
禁止を置かない）に違反して見える**。実際には両側に効いているので、接頭辞を
外して実態に合わせた。

```text
claude_read_deny_globs   → read_deny_globs
claude_write_deny_globs  → write_deny_globs
claude_read_ask_globs    → read_ask_globs
claude_write_ask_globs   → write_ask_globs
claude_network_allow     → shell_network_allow   ([sandbox]。Claude と OpenCode)
```

`claude_read_allow` は Claude 固有の補償なので**接頭辞を残した**。

> **未解決**: `[sandbox] claude_write_deny` は「CLI 固有キーに置かれた禁止」で、
> 規則 3 に照らすと違反のまま残っている。CHG-0005 で扱う。

## 関連 ADR

- [ADR-0006](0006-instructions-to-mechanisms.md): 指示ではなく機構で強制する
  という方針。本 ADR はその機構をどう選ぶかの基準を定めたもの
- [ADR-0004](0004-hook-check-semantic-axis.md): hook の判定軸と実行コストの実測
- [ADR-0002](0002-loopback-http-approval-scope.md): Copilot の `ask` が
  自動承認される制約。本 ADR の hook も `deny` だけを使う
