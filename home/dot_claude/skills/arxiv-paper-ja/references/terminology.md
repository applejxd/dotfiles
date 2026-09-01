# 誤訳しやすい専門用語

この表は出発点であり、対象分野と文脈を優先する。論文固有の用語集を別途作る。

| English | 推奨訳 | 避けたい機械訳・注意 |
|---|---|---|
| point cloud registration | 点群位置合わせ | 「点群登録」では幾何的整合の意味が伝わりにくい |
| image registration | 画像位置合わせ | 文脈により「画像レジストレーション」も可 |
| score function | スコア関数 | 「得点関数」ではない |
| evidence | エビデンス、周辺尤度 | ベイズ統計で単なる「証拠」ではない |
| guidance | ガイダンス | 生成モデルで「指導」としない |
| tractable | 計算可能、扱いやすい | 「追跡可能」としない |
| corruption | 劣化、ノイズ付加 | 画像・信号で「汚職」「破損」としない |
| denoising | ノイズ除去 | 「消音」ではない |
| mode | モード | 確率分布で「様式」としない |
| manifold | 多様体 | `data manifold` は「データ多様体」 |
| embedding | 埋め込み | DB の「埋込み」と混同しない |
| representation | 表現 | 文脈により「表現ベクトル」 |
| feature | 特徴、特徴量 | UI の「機能」と区別 |
| alignment | 整合、位置合わせ | 幾何、系列、価値観で訳を変える |
| matching | マッチング、整合 | `score matching` は「スコアマッチング」 |
| objective | 目的関数 | 最適化文脈で単なる「目的」としない |
| estimate | 推定値、推定する | `estimator` は「推定量」 |
| expectation | 期待値 | 日常語の「期待」と区別 |
| variance | 分散 | `variance preserving` は「分散保存」 |
| covariance | 共分散 | `diagonal covariance` は「対角共分散」 |
| prior | 事前分布 | 形容詞の「以前の」と区別 |
| posterior | 事後分布 | 位置を表す「後方」としない |
| likelihood | 尤度 | probability と区別 |
| marginalize | 周辺化する | 「疎外する」としない |
| inference | 推論 | 実行時推論と統計的推論を文脈で区別 |
| latent | 潜在 | `latent space` は「潜在空間」 |
| ground truth | 正解、正解データ | 文脈により「真値」 |
| baseline | ベースライン、比較基準 | 「基線」としない |
| ablation study | アブレーション研究、要素除去実験 | 分野慣行を優先 |
| state of the art | 最先端、最高水準 | 不自然な「技術の状態」を避ける |
| end-to-end | エンドツーエンド | 無理な直訳を避ける |
| fine-tuning | ファインチューニング | 必要なら初出で「追加学習」を併記 |
| prompt | プロンプト | 一般語の「促す」と区別 |
| token | トークン | 文脈により字句・単位を補足 |
| rollout | ロールアウト、軌跡生成 | 配備の rollout と強化学習で訳を分ける |
| reward | 報酬 | 一般語の「褒美」を避ける |
| policy | 方策 | 強化学習では「政策」としない |
| trajectory | 軌跡 | 最適化・力学・強化学習で共通 |
| pose | 姿勢 | 位置を含む場合は「位置姿勢」 |
| optical flow | オプティカルフロー | 「光学流」より定着語を優先 |
| rendering | レンダリング | 文書組版では「描画」との違いに注意 |
| typesetting | 組版 | 単なる「入力」ではない |
