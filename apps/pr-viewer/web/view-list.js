/* 一覧 #/ */
(function () {
  "use strict";
  var PRV = window.PRV;
  var h = PRV.h;
  var FILTERS = [
    ["all", "すべて"],
    ["open", "オープン"],
    ["merged", "統合済み"],
    ["empty", "起票のみ"],
  ];

  function row(pr, rv) {
    var bt = rv && rv.brief && typeof rv.brief.title === "string" ? rv.brief.title : "";
    return h(
      "li",
      { class: "prrow" },
      h(
        "a",
        { class: "rowlink", href: PRV.prHref(pr) },
        h("div", { class: "rt" }, h("span", { class: "ttl", text: pr.branch }), PRV.mainChip(pr, rv), PRV.staleReviewChip(rv)),
        bt ? h("div", { class: "rtitle", text: bt }) : null,
        h(
          "div",
          { class: "rm" },
          h("span", { class: "br" }, pr.repoName, " → ", pr.target),
          h(
            "span",
            { class: "rm2" },
            h("span", { class: "sep", text: "・" }),
            PRV.ago(pr.lastCommit && pr.lastCommit.at),
            h("span", { class: "sep", text: "・" }),
            PRV.size(pr.additions, pr.deletions),
            h("span", { class: "sep", text: "・" }),
            pr.files + " ファイル",
            h("span", { class: "sep", text: "・" }),
            pr.commits + " コミット"
          )
        ),
        pr.state === "open" && pr.behind > 0
          ? h("div", { class: "rw small" }, h("span", { class: "behind", text: pr.target + " が " + pr.behind + " 進んだ" }))
          : null
      )
    );
  }

  /* リポジトリごとの「origin より N 件先」（fetch はしないので、最後に取得した状態との比較） */
  function unpushedNote(repos, multi) {
    var lines = repos
      .filter(function (r) { return r.unpushed > 0; })
      .map(function (r) {
        return (multi ? r.name + ": " : "") + r.target + " は origin（最後に取得した状態）より " + r.unpushed + " 件先";
      });
    return lines.length ? h("div", { class: "attn unpushed", role: "status" }, lines.map(function (t) { return h("div", { text: t }); })) : null;
  }

  PRV.viewList = function (isCurrent) {
    PRV.loading();
    Promise.all([PRV.api.repos(), PRV.api.prs(), PRV.api.capabilities()]).then(
      function (res) {
        if (!isCurrent()) return;
        draw(res[0].repos || [], res[1].prs || [], res[2]);
      },
      function (e) {
        if (isCurrent()) PRV.showError(e);
      }
    );
  };

  function draw(repos, prs, caps) {
    var filter = "all";
    var repo = "";
    var query = "";
    var box = h("div");
    var seg = h("div", { class: "seg", role: "group", "aria-label": "状態で絞り込み" });
    var btns = {};
    FILTERS.forEach(function (f) {
      var n = f[0] === "all" ? prs.length : prs.filter(function (p) { return p.state === f[0]; }).length;
      var b = h("button", { class: "btn", type: "button", "aria-pressed": "false" }, f[1], " ", h("span", { class: "cnt", text: n }));
      b.addEventListener("click", function () {
        filter = f[0];
        update();
      });
      btns[f[0]] = b;
      seg.appendChild(b);
    });
    var search = h("input", { type: "search", class: "search", "aria-label": "ブランチ名で検索", title: "ブランチ名で検索" });
    search.setAttribute("placeholder", "ブランチ名で検索");
    search.addEventListener("input", function () {
      query = search.value.trim().toLowerCase();
      update();
    });
    var sel = null;
    if (repos.length > 1) {
      sel = h("select", { "aria-label": "リポジトリ" }, h("option", { text: "すべてのリポジトリ" }));
      repos.forEach(function (r) {
        var o = h("option", { text: r.name });
        o.value = r.repoId;
        sel.appendChild(o);
      });
      sel.addEventListener("change", function () {
        repo = sel.value;
        update();
      });
    }

    function update() {
      Object.keys(btns).forEach(function (k) {
        btns[k].setAttribute("aria-pressed", k === filter ? "true" : "false");
      });
      var shown = prs.filter(function (p) {
        return (
          (filter === "all" || p.state === filter) &&
          (!repo || p.repoId === repo) &&
          (!query || String(p.branch).toLowerCase().indexOf(query) >= 0)
        );
      });
      if (shown.length === 0) {
        box.replaceChildren(
          h(
            "div",
            { class: "empty" },
            h("div", { class: "big", text: "∅" }),
            h("p", { text: prs.length === 0 ? "PR（feature/・bugfix/ のブランチ）がありません。" : "条件に合う PR がありません。" })
          )
        );
        return;
      }
      box.replaceChildren(h("ul", { class: "prlist" }, shown.map(function (p) { return row(p, reviews[p.id]); })));
    }

    /* レビュー状態のチップは、先に一覧を出してから PR ごとに取り足す（失敗してもチップが無いだけ） */
    var reviews = {};
    prs.forEach(function (p) {
      if (p.state !== "open" && p.state !== "empty") return;
      PRV.api.review(p.id).then(function (rv) {
        reviews[p.id] = rv;
        if (box.isConnected) update();
      }, function () {});
    });

    var mk = PRV.createEntry ? PRV.createEntry(caps, repos) : null;
    PRV.mount(
      h(
        "div",
        { class: "page" },
        h("div", { class: "listhead" }, h("h1", { text: "PR 一覧" }), h("span", { class: "muted", text: prs.length + " 件" }), mk ? h("span", { class: "listact" }, mk) : null),
        unpushedNote(repos, repos.length > 1),
        h("div", { class: "toolbar" }, seg, sel, search),
        box
      )
    );
    update();
  }
})();
