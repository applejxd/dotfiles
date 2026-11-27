# Copilot Gemini の画像ガード（未配備の試作）

Copilot の Gemini に画像が蓄積して送信できなくなる問題を、Pi の送信直前に緩和する。
通常起動では読み込まれない。chezmoi の配布対象と既定モデルは変更しない。

## 対象と動作

- `github-copilot` の `openai-completions` 経由で、Gemini 4 Neon・Carbon・Argon・Hydrogen と 3.8 Flash のみが対象。Sol、Claude、Google 直接 API、未確認の将来のモデル ID には触れない。
- 上限は 1 リクエストで画像 10 枚。送信 JSON の予算は **4 MiB** とする。後者は [VS Code の実装にある 5 MB](https://github.com/microsoft/vscode/blob/ae7dce46/extensions/copilot/src/extension/prompts/node/panel/toolCalling.tsx) を下回るための試作値で、サーバの保証値ではない。
- Pi のユーザー入力とツール結果を区別できる段階で、送信用コピーの古い画像だけを最古から置き換える。現在のユーザー入力と、それ以降のツール結果の画像は保護し、元の履歴は変えない。
- 古い画像を省く目安は、10 枚または画像データ 3.5 MiB。テキストやツール定義に余地を残すため、JSON が 4 MiB になる前に古い画像を省く場合がある。
- 送信直前は加工せず、送信モデル、JSON と data URL の形式、全画像の内容と順序、10 枚・4 MiB を検査する。計画がない対象リクエスト、現在ターンでの超過、画像の追加・欠落、その他の予算超過は中止する。自動再試行、画像圧縮、モデル切り替えは行わない。

## 10 枚対策を Neon 以外にも入れる根拠

2026-11-27 確認。[VS Code の Copilot 実装](https://github.com/microsoft/vscode/pull/310437) は Gemini ファミリ全体に 10 枚のガードをかける。
[Copilot 経由での公開報告](https://github.com/orgs/community/discussions/211800) には、Argon と 3.8 Flash が対象として挙げられ、Argon では 11 枚で HTTP 400 が記録されている。
Carbon・Neon・Hydrogen 個別の公開サーバ実測は未確認。試作では VS Code と同じ考えで保守的に扱うが、サーバが全モデル一律に拒否すると断定しない。

## 試験

```bash
node --test prototypes/pi-copilot-image-guard/guard.test.mjs
PI_IMAGE_GUARD_TEST_PI=pi uv run --with pytest --no-project pytest test/test_pi_copilot_image_guard.py -q
```

2 行目は指定した Pi を一時の設定・合成 PNG・ループバックの模擬サーバで起動する。ユーザー添付と `read` が返す画像の両方を検査する。実 Copilot アカウントや現在のセッションを使わない。
試作を別の Pi 起動で読み込む場合の入口は `pi -e ./prototypes/pi-copilot-image-guard/index.js`。常用への組み込みは別に判断する。

## 採用しなかった代替と撤去条件

- Pi 1.6.0 / [1.6.1 の `inputLimits`](https://github.com/earendil-works/pi/blob/v1.6.1/packages/coding-agent/docs/models.md#describe-model-input-and-caching) は、画像枚数の記述だけで送信を制限しない。画像縮小は枚数を減らさず、新規セッションへの切り出しは履歴を保った継続にはならない。
- [既製 `pi-image-budget` 0.2.0](https://github.com/Aaalice233/pi-image-budget/tree/742e9f0afd1e303117fa28c41c9ef50b9b7e3d66) は、合成試験で現在ターンの11枚を10枚に減らして送る挙動だった。設定だけでモデル別に無効化できず、保護画像だけでサイズを超える場合も送信を止めない。そのままでは採用しない。
- 維持対象は Pi の公開フック2つと、Copilot が使う OpenAI Completions の画像形式。Pi の更新で、特に画像を含むツール出力の変換と、中止時に要求がサーバへ到達しないことを再検査する。後から他の拡張が送信 JSON を変更する組み合わせは未検証。
- Pi 本体・既製品が同等に対応したら、このディレクトリ・専用試験・検証規則を削除する。配備しない限り利用環境での撤去操作は不要。
