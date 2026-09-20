# One message and information density

## Purpose

「一枚一メッセージ」は一枚一要素ではない。複数の箱、段階、比較対象があっても、
それらが一つの結論、判断、全体地図を支えるなら一メッセージである。
逆に文字数が少なくても、独立した結論を二つ要求するページは分割する。

## Plan contract

新規デッキでは `meta.message_policy.enabled = true` とし、各ページへ次を持たせる。

- `claim`: 観客が一文で持ち帰る主張
- `message_mode`: `focused` または `overview`
- `detail_policy`: `explain` / `recognize` / `reference`
- `information_units`: その場で処理させる意味単位
- `reading_goal`: overviewで認識する構造と、後回しにする詳細

## Default cutoffs

| mode | 上限 | 意図 |
| --- | ---: | --- |
| focused | 5 units | 一つの因果、比較、手順、判断を説明する |
| overview | 7 units | 地図、アーキテクチャ、目次、まとめを認識させる |

情報単位は図形数ではない。たとえば六つの本番境界を一枚の責任地図として示すなら
overviewの6 unitsである。各境界の設定値、失敗例、担当作業まで同時に説明するなら、
それらは追加unitとなり、分割対象になる。

## Projection and text limits

情報単位の上限だけでなく、`quality_gate.py` の実測フォント、文字収容、画像サイズ、
文字量も併用する。既定の文字量は520文字超でwarning、850文字超でerrorだが、
上限未満でも独立主張が複数なら不合格である。

引用したoverview図は、会場で細部をすべて読ませない。認識対象を3〜7領域へ絞り、
詳細ラベルは画像リンク、配布資料、付録へ送る。

## Review question

独立レビューでは各ページについて次を答える。

1. タイトルとclaimを一文で言い換えられるか。
2. すべての要素がその一文を支えているか。
3. 観客がその場で処理するunit数は申告値と一致するか。
4. overviewは「何を見るか」が明確で、細部を読むよう要求していないか。
5. 一つ削っても主張が変わらない要素は、ノイズとして除去できないか。
