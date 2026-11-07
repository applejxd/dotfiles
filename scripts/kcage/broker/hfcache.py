"""hf のキャッシュの計画。秘密なし（D3: hf のトークンは箱に入れない）。host_ops も無い。

- 箱には HF_HOME（箱ごとの書き込み可の領域）とテレメトリ無効の env だけを渡す。公開モデルは、箱から
  一般通信（プロキシ）経由で認証なしで取得する。
- ゲート付きモデル・回数制限に当たるときの運用: ホストで `hf download` し、その場所を許可表の
  data_roots に置き、kcage.toml の data で要求する（読み取り専用のデータの根。ここでは触らない）。
- 自分の非公開モデルを箱で扱う例外（専用の読み取りトークン）は、C1 の例外手続きで別途検討する。
"""

from __future__ import annotations

from kcage import model

HF_HOME = "/var/cache/kcage/hf"


def plan(cfg: model.BoxConfig, policy: model.RepoPolicy) -> model.BrokerPlan:
    return model.BrokerPlan(
        kind="hf-cache",
        env={"HF_HOME": HF_HOME, "HF_HUB_DISABLE_TELEMETRY": "1"},
        routes=(
            model.Route(
                "hf",
                "箱 → 一般通信（プロキシ）経由 → Hugging Face（トークンなし）",
                ("nat", "proxy-only"),
            ),
        ),
    )
