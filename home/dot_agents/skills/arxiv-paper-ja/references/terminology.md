# 誤訳しやすい専門用語

この表は出発点であり、対象分野と文脈を優先する。論文固有の用語集を別途作る。

## 訳語を採用する基準

**定訳が確認できない語は、無理に訳さない。** 次の順で選ぶ。

1. その分野の教科書・学会論文・主要な日本語解説で繰り返し使われている訳語があれば、それを使う。
2. 訳語が複数あって定まっていなければ、初出で「日本語（English）」と併記し、以降はどちらかに統一する。
3. **定訳が無い、または直訳が意味を損なう場合は原語のまま書く。**
   カタカナ化した造語や逐語訳をこの場で新しく作らない。
4. 略語（RANSAC、ICP、ELBO、CFG など）は展開せず原語で書き、初出のみ日本語の説明を添える。

この表の「推奨訳」も、対象論文の分野で通用していなければ採用しない。
下の「原語のまま書く語」に挙げた語は、日本語に置き換えず英語表記を残す。
訳さないと判断した語は、その理由とともに論文固有の用語集に記録する。

訳語の選び方全般は `translation-guidelines.md` を参照する。

## 分野共通

| English | 推奨訳 | 避けたい機械訳・注意 |
| --- | --- | --- |
| point cloud registration | 点群位置合わせ | 「点群登録」では幾何的整合の意味が伝わりにくい |
| image registration | 画像位置合わせ | 文脈により「画像レジストレーション」も可 |
| score function | スコア関数 | 「得点関数」ではない |
| evidence | 周辺尤度 | ベイズ統計で単なる「証拠」としない。`evidence lower bound` は下表 |
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
| ablation study | アブレーション（研究・実験） | 「要素除去実験」は定着していない。原語のままでもよい |
| state of the art | 最先端、最高水準 | 不自然な「技術の状態」を避ける |
| end-to-end | エンドツーエンド | 無理な直訳を避ける |
| fine-tuning | ファインチューニング | 必要なら初出で「追加学習」を併記 |
| prompt | プロンプト | 一般語の「促す」と区別 |
| token | トークン | 文脈により字句・単位を補足 |
| rollout | ロールアウト | 「軌跡生成」は定着していない。配備の rollout と強化学習で訳を分ける |
| reward | 報酬 | 一般語の「褒美」を避ける |
| policy | 方策 | 強化学習では「政策」としない |
| trajectory | 軌跡 | 最適化・力学・強化学習で共通 |
| pose | 姿勢 | 位置を含む場合は「位置姿勢」 |
| optical flow | オプティカルフロー | 「光学流」より定着語を優先 |
| rendering | レンダリング | 文書組版では「描画」との違いに注意 |
| typesetting | 組版 | 単なる「入力」ではない |

## 点群処理・3D 幾何

| English | 推奨訳 | 避けたい機械訳・注意 |
| --- | --- | --- |
| point cloud | 点群 | 「ポイントクラウド」より定着語を優先 |
| correspondence | 対応点、対応関係 | 「通信」「文通」としない |
| inlier / outlier | インライア / 外れ値 | outlier は「外れ値」が定訳。「内れ値」という語は無い |
| voxel | ボクセル | |
| occupancy grid map | 占有格子地図 | 「占有グリッドマップ」も可 |
| downsampling | ダウンサンプリング、間引き | |
| nearest neighbor | 最近傍 | `k-nearest neighbor` は「k 近傍」 |
| normal | 法線 | 「正常」「通常」としない |
| curvature | 曲率 | |
| mesh | メッシュ | |
| surface reconstruction | 表面再構成 | |
| signed distance function | 符号付き距離関数 | 略語の SDF / TSDF は展開しない |
| rigid transformation | 剛体変換 | |
| rotation / translation | 回転 / 並進 | **translation を「翻訳」としない** |
| quaternion | クォータニオン、四元数 | どちらも定着。文書内で統一する |
| Lie group / Lie algebra | リー群 / リー代数 | `SE(3)` `SO(3)` は原語表記 |
| descriptor | 記述子 | `feature descriptor` は「特徴記述子」 |
| keypoint | キーポイント、特徴点 | |
| point-to-point / point-to-plane | 点対点 / 点対平面 | ICP の誤差指標 |
| segmentation | セグメンテーション、領域分割 | |

## SLAM・ロボティクス

| English | 推奨訳 | 避けたい機械訳・注意 |
| --- | --- | --- |
| localization | 自己位置推定 | 「局所化」「現地化」としない |
| mapping | 地図作成、地図生成 | 数学の「写像」と区別する |
| odometry | オドメトリ | `visual odometry` は「ビジュアルオドメトリ」 |
| loop closure | ループクロージャ | 「ループ閉じ込み」も使われる。「ループ閉鎖」としない |
| bundle adjustment | バンドル調整 | 「束調整」としない |
| pose graph optimization | ポーズグラフ最適化 | |
| factor graph | 因子グラフ | |
| keyframe | キーフレーム | |
| landmark | ランドマーク | 「目印」では専門語にならない |
| data association | データ対応付け | 「データ連合」としない |
| drift | ドリフト、累積誤差 | |
| relocalization | 再位置推定 | 「再局在化」としない。原語併記でもよい |
| scan matching | スキャンマッチング | |
| particle filter | パーティクルフィルタ | 「粒子フィルタ」も可 |
| Kalman filter | カルマンフィルタ | `extended` は「拡張カルマンフィルタ」 |
| calibration | キャリブレーション、校正 | |
| intrinsic / extrinsic parameters | 内部 / 外部パラメータ | 「本質的 / 外因的」としない |
| disparity | 視差 | 「不一致」としない |
| depth | 深度 | `depth map` は「深度マップ」 |
| front-end / back-end | フロントエンド / バックエンド | |

## VAE・拡散モデル

| English | 推奨訳 | 避けたい機械訳・注意 |
| --- | --- | --- |
| variational autoencoder | 変分オートエンコーダ | 略語 VAE は展開しない |
| evidence lower bound | 変分下界、証拠下限 | 略語 ELBO を併記する。「証拠の下限」と分けない |
| variational inference | 変分推論 | |
| reparameterization trick | 再パラメータ化トリック | 「再媒介変数化」としない |
| KL divergence | KL ダイバージェンス | 「KL 発散」としない |
| posterior collapse | 事後崩壊 | |
| encoder / decoder | エンコーダ / デコーダ | 「符号化器 / 復号器」は文脈次第 |
| forward / reverse process | 順過程 / 逆過程 | 「拡散過程 / 逆拡散過程」も可 |
| noise schedule | ノイズスケジュール | 「雑音予定表」としない |
| score-based model | スコアベースモデル | |
| Langevin dynamics | ランジュバン動力学 | |
| stochastic differential equation | 確率微分方程式 | 略語 SDE を併記 |
| probability flow ODE | 確率フロー ODE | |
| sampler / sampling steps | サンプラー / サンプリングステップ | |
| timestep | タイムステップ、時刻 | |
| latent diffusion | 潜在拡散 | |
| cross-attention | クロスアテンション | 「交差注意」としない |
| inpainting | インペインティング | 文脈により「画像修復」 |
| super-resolution | 超解像 | |
| distillation | 蒸留 | `model distillation` は「モデル蒸留」 |
| mode collapse | モード崩壊 | GAN・VAE で使う。`posterior collapse` と区別 |
| variance preserving / exploding | 分散保存 / 分散発散 | 略語 VP / VE は展開しない |
| annealing | 焼きなまし | |

## 原語のまま書く語

定訳が無い、または略語が原語で通用している。日本語へ置き換えない。
初出でのみ短い説明を添える。

| 語 | 初出時の説明例 |
| --- | --- |
| SLAM | 自己位置推定と地図作成の同時実行 |
| RANSAC | 外れ値に頑健なモデル推定手法 |
| ICP | 点群の位置合わせ手法（反復最近点法） |
| SE(3) / SO(3) | 剛体変換群 / 回転群 |
| SDF / TSDF | 符号付き距離関数 / 打ち切り版 |
| IMU | 慣性計測装置 |
| LiDAR | レーザ測距センサ |
| NeRF / 3DGS | 三次元シーン表現の手法名 |
| VAE / ELBO | 変分オートエンコーダ / 変分下界 |
| DDPM / DDIM | 拡散モデルのサンプリング手法名 |
| classifier-free guidance (CFG) | 条件付き生成の強度を調整する手法 |
| U-Net | 符号化・復号を対称に持つネットワーク構造 |
| disentanglement | 潜在表現の各次元が独立な要因に対応する性質。定訳は無い |
| coarse-to-fine | 粗い解像度から細かい解像度へ段階的に解く方式。定訳は無い |
| ablation | 構成要素を外して寄与を測る実験 |
| amortized inference | 推論器を学習して個別最適化を省く方式。訳語は定着していない |
