# OpenCode の危険な rm と pip を ocs の中でも止める

- **ステータス**: Accepted
- **日付**: 2026-10-03
- **決定者**: applejxd

> **部分改定（2026-10-03）**: 「bypass エージェントは対象外」（選択肢 3 の欠点、`bypass` の素通り）を
> [ADR-0014](0014-bypass-as-ask-upgrade.md) で改めた。`bypass` にも誘導・前段停止を同じに効かせる。
> それ以外の決定は有効。以下の本文は決定当時のまま残している。
>
> **注記（2026-10-03）**: 「ネガティブな結果」の 1 項目目（通常版の pip の静的 deny に
> 誘導文を付けられない）は、同日に解消した。決定は変えない。plugin の `tool.execute.before`
> （permission より前に走る）で pip の規則を判定し、例外で説明付きに止める
> （[実測](../research/opencode/permission/early-guard.md)、
> [仕様](../spec/agent-command-policy.md#opencode-の-pip-誘導と-rm-の誘導)）。
> 静的 deny は変えていない。以下の本文は決定当時のまま残している。

## コンテキスト

[ADR-0012](0012-ocs-boundary-for-accidents.md) は `ocs` の中の既定を allow に反転し、
`rm` / `mv` / `cp` / `pip` などの permission を捨てている（境界の内側なので
列挙をやめる、という判断）。一方で次の事故は境界では止まらない。

- 起動ディレクトリは書き込めるので、`rm -rf .git` で履歴が消える。
  起動前の退避があっても、うっかりは起きないほうがよい
- `rm -rf ~` などは境界が実際に守るが、止まるのが OS の拒否（後始末が要る失敗）になる
- `pip install` は uv 管理の方針と衝突する。これは安全の話ではなく「uv を使う」
  運用の取り決めで、境界の中でも同じに効かせたい

Claude Code / Copilot CLI は hook（[bashrules](../spec/agent-command-policy.md)）で
同等の保護を持つ。OpenCode は guide plugin の `[[opencode.shell.guide]]`
（生のコマンド文字列への正規表現）で止められる。

## 決定事項

ADR-0012 の「境界の内側では rm 等を確認しない」を、次の範囲に限って**部分的に改める**。

1. **pip / pip3 / `python -m pip`** を OpenCode で止め、uv へ誘導する
   （poetry / pipenv は止めない。`uv pip ...` は止めない）
2. **止めたい具体例だけ**を止める `rm` / `find` の規則を、`ocs` の内側にも効かせる:
   `.git` 自体またはその配下の直接削除、`~` / `$HOME` / `/` の指定、
   `.` / `..` / `*` による作業ディレクトリ全体の再帰削除、
   `/` `~` `.git` を起点にした `find -delete` / `-exec rm`

これは **「うっかり防止であって完全な保護ではない」**。正規表現でコマンド文字列を
見るだけなので、変数・サブシェル・別名・スクリプト経由は止まらない。
通常の掃除（`.tmp/` や build 成果物の削除など）は止めない。

実装は guide 規則で行う。`ocs` が捨てるのは permission であり guide 規則ではないため、
ocs の内側にも同じ規則が効く（実機で確認済み。
[仕様](../spec/agent-command-policy.md#opencode-の-pip-誘導と-rm-の誘導)）。

## 検討した選択肢

### 選択肢 1: ADR-0012 のとおり、ocs の中では何も確認しない

- **利点**: 規則が増えない
- **欠点**: `.git` の削除と `pip` が境界の中で素通りする

### 選択肢 2: ocs の内側にも permission の deny を残す

- **利点**: plugin に依存しない
- **欠点**: `ocs` の permission の整理（ADR-0012）を戻すことになり、
  `rm -rf .tmp/x` のような通常の掃除まで列挙で扱う必要が出る

### 選択肢 3（採用）: guide 規則で具体例だけを止める

- **利点**: 止める範囲を具体例に限れる。メッセージで代替案を示せる。ocs の整理を戻さない
- **欠点**: plugin が読み込めないと効かない（その場合の挙動は
  [rules.json が使えないとき](../spec/agent-config-generation.md#rulesjson-が使えないとき)）。
  bypass エージェントは対象外

## 結果

### ネガティブな結果

- pip の既存の静的 deny（通常版）には、誘導文を付けられない。静的 deny の呼び出しは
  plugin の `evaluate` に届かず、実機では `Permission denied: shell` だけが返る
  （説明のために静的 deny を外すと、plugin 不調時の挙動が変わるので外さない）。
  誘導文が出るのは `python -m pip` と、静的 deny を持たない `ocs` の内側
- 正規表現の限界で、クォート内の `;` の後ろに書かれた文章などは誤検知しうる
  （`git commit -m` の本文は除外している）

## 関連 ADR

- [ADR-0012](0012-ocs-boundary-for-accidents.md): 本 ADR が部分的に改める
- [ADR-0006](0006-instructions-to-mechanisms.md): 指示でなく機構で止める
