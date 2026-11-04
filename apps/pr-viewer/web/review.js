/* レビュー情報の取得とサマリー表示。API の文字列は非信頼（textContent だけで描画する） */
(function () {
  "use strict";
  var PRV = window.PRV;
  var h = PRV.h;

  /* 失敗しても画面は読み取り専用で出す。error は日本語の短文 */
  PRV.loadReview = function (id) {
    return PRV.api.review(id).then(
      function (rv) {
        return { review: rv, error: null };
      },
      function (e) {
        return { review: null, error: e && e.userMessage ? e.userMessage : "レビュー情報を取得できません。" };
      }
    );
  };

  /* PR の主状態チップ。統合済みだけ出す */
  PRV.mainChip = function (pr) {
    return PRV.stateChip(pr);
  };

  function lines(v) {
    return typeof v === "string" && v !== "" ? v : "";
  }

  /* pi が書いたサマリー（表示だけ）。無ければ null */
  PRV.summaryCard = function (s) {
    if (!s || typeof s !== "object") return null;
    var card = h("section", { class: "card summary", "aria-label": "pi のまとめ" });
    card.appendChild(h("h2", null, "pi のまとめ ", h("span", { class: "muted small", text: PRV.ago(s.at) })));
    card.appendChild(h("h3", { text: "やったこと" }));
    card.appendChild(PRV.md(lines(s.done) || "（記載なし）"));
    if (Array.isArray(s.files) && s.files.length) {
      card.appendChild(h("h3", { text: "変更ファイル" }));
      card.appendChild(h("ul", { class: "plain mono" }, s.files.map(function (f) { return h("li", { text: String(f) }); })));
    }
    if (Array.isArray(s.findings) && s.findings.length) {
      card.appendChild(h("h3", { text: "指摘ごとの対応" }));
      card.appendChild(
        h(
          "ul",
          { class: "plain" },
          s.findings.map(function (f) {
            return h("li", null, h("code", { text: PRV.short(f && f.ref) }), " ", PRV.md(lines(f && f.reply)));
          })
        )
      );
    }
    if (lines(s.notes)) {
      card.appendChild(h("h3", { text: "確認してほしい点" }));
      card.appendChild(PRV.md(s.notes));
    }
    return card;
  };
})();
