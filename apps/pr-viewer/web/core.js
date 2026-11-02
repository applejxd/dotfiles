/* 部品・ルータ。API の文字列は非信頼: すべて textContent と createElement だけで描画する */
(function () {
  "use strict";
  var PRV = (window.PRV = window.PRV || {});
  var SAFE_ATTR = /^(class|id|title|type|role|href|colspan|tabindex|open|lang|aria-[a-z]+|data-[a-z]+)$/;

  /* 要素の作成。属性は許可リストだけ。href は同一ページの hash に限る */
  PRV.h = function (tag, attrs) {
    var el = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        var v = attrs[k];
        if (v === null || v === undefined || v === false) return;
        if (k === "text") {
          el.textContent = String(v);
          return;
        }
        if (!SAFE_ATTR.test(k)) throw new Error("許可されていない属性: " + k);
        if (k === "href" && !/^#\//.test(String(v))) throw new Error("許可されていない href");
        el.setAttribute(k, v === true ? "" : String(v));
      });
    }
    for (var i = 2; i < arguments.length; i++) PRV.append(el, arguments[i]);
    return el;
  };

  PRV.append = function (el, c) {
    if (c === null || c === undefined || c === false) return;
    if (Array.isArray(c)) {
      c.forEach(function (x) {
        PRV.append(el, x);
      });
    } else if (typeof c === "string" || typeof c === "number") {
      el.appendChild(document.createTextNode(String(c)));
    } else {
      el.appendChild(c);
    }
  };

  PRV.mount = function (node) {
    document.getElementById("app").replaceChildren(node);
  };

  PRV.ago = function (iso) {
    var t = Date.parse(iso);
    if (isNaN(t)) return "";
    var s = Math.max(0, Math.round((Date.now() - t) / 1000));
    if (s < 60) return "たった今";
    if (s < 3600) return Math.floor(s / 60) + " 分前";
    if (s < 86400) return Math.floor(s / 3600) + " 時間前";
    if (s < 86400 * 30) return Math.floor(s / 86400) + " 日前";
    return new Date(t).toLocaleDateString("ja-JP");
  };

  PRV.short = function (oid) {
    return String(oid || "").slice(0, 7);
  };

  PRV.size = function (a, d) {
    return PRV.h("span", { class: "size" }, PRV.h("span", { class: "sa", text: "+" + a }), " ", PRV.h("span", { class: "sd", text: "−" + d }));
  };

  /* 主状態のチップ。既定値（open）は何も出さない */
  PRV.stateChip = function (pr) {
    if (pr.state === "merged") return PRV.h("span", { class: "chip c-merged", text: "✓ 統合済み" });
    return null;
  };

  PRV.prHref = function (pr) {
    if (!/^r[0-9a-f]{8}$/.test(pr.repoId) || !/^p[0-9a-f]{16}$/.test(pr.prKey)) return "#/";
    return "#/pr/" + pr.repoId + "/" + pr.prKey;
  };

  /* 失敗の表示。再読み込みボタンは再描画だけ */
  PRV.showError = function (err) {
    var msg = err && err.userMessage ? err.userMessage : "画面の表示に失敗しました。";
    var btn = PRV.h("button", { class: "btn sm", type: "button", text: "再読み込み" });
    btn.addEventListener("click", function () {
      PRV.render();
    });
    PRV.mount(
      PRV.h(
        "div",
        { class: "page" },
        PRV.h("div", { class: "alertbox bad", role: "alert" }, PRV.h("span", { class: "ic", text: "✕" }), PRV.h("div", null, PRV.h("p", { text: msg }), btn))
      )
    );
  };

  PRV.loading = function () {
    PRV.mount(PRV.h("div", { class: "page" }, PRV.h("p", { class: "muted", role: "status", text: "読み込み中…" })));
  };

  PRV.isNarrow = function () {
    return window.matchMedia("(max-width: 719px)").matches;
  };

  /* 詳細は同じ PR の間だけ使い回す（一覧に戻ると捨てる） */
  PRV.cache = {};
  PRV.getPr = function (id) {
    if (!PRV.cache[id]) {
      PRV.cache[id] = PRV.api.pr(id).catch(function (e) {
        delete PRV.cache[id];
        throw e;
      });
    }
    return PRV.cache[id];
  };

  PRV.route = function () {
    var raw = (location.hash || "").replace(/^#/, "") || "/";
    var qi = raw.indexOf("?");
    var path = qi < 0 ? raw : raw.slice(0, qi);
    var params = new URLSearchParams(qi < 0 ? "" : raw.slice(qi + 1));
    var parts = path.split("/").filter(Boolean);
    if (parts.length === 0) return { view: "list" };
    if (parts[0] === "pr" && /^r[0-9a-f]{8}$/.test(parts[1] || "") && /^p[0-9a-f]{16}$/.test(parts[2] || "")) {
      var id = parts[1] + "/" + parts[2];
      if (parts.length === 3) return { view: "overview", id: id };
      if (parts.length === 4 && parts[3] === "files") return { view: "files", id: id, path: params.get("path") };
    }
    return { view: "notfound" };
  };

  PRV.token = 0;
  PRV.render = function () {
    var r = PRV.route();
    var tok = ++PRV.token;
    var isCurrent = function () {
      return tok === PRV.token;
    };
    window.scrollTo(0, 0);
    if (r.view === "list") {
      PRV.cache = {};
      return PRV.viewList(isCurrent);
    }
    if (r.view === "overview") return PRV.viewOverview(r, isCurrent);
    if (r.view === "files") return PRV.viewDiff(r, isCurrent);
    PRV.showError({ userMessage: "ページが見つかりません。" });
  };

  PRV.start = function () {
    window.addEventListener("hashchange", PRV.render);
    PRV.render();
  };
})();
