/* 稼働版の表示（画面の隅）。GET /api/version。取れなければ何も出さない（古いサーバ） */
(function () {
  "use strict";
  var PRV = window.PRV;
  if (!PRV || !PRV.api || typeof PRV.api.version !== "function") return;
  PRV.api
    .version()
    .then(function (v) {
      var el = document.createElement("div");
      el.className = "verchip muted small";
      el.textContent = v.pinned === true && typeof v.oid === "string" ? "稼働版 " + v.oid.slice(0, 8) : "稼働版 固定なし";
      if (v.pinned === true && typeof v.pinnedAt === "string") el.title = "固定した時刻: " + v.pinnedAt;
      document.body.appendChild(el);
    })
    .catch(function () {});
})();
