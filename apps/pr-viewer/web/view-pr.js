/* 概要 #/pr/<repoId>/<prKey> と、詳細の共通ヘッダー */
(function () {
  "use strict";
  var PRV = window.PRV;
  var h = PRV.h;

  var STATUS = { A: "追加", M: "変更", D: "削除", R: "改名" };

  PRV.filesHref = function (pr, path) {
    var base = PRV.prHref(pr) + "/files";
    return path ? base + "?path=" + encodeURIComponent(path) : base;
  };

  PRV.statusBadge = function (st) {
    var cls = st === "A" ? "c-ok" : st === "D" ? "c-bad" : st === "R" ? "c-info" : "c-mute";
    return h("span", { class: "chip " + cls, title: STATUS[st] || "", text: st });
  };

  /* 詳細のヘッダー: 主状態チップ 1 つ + 注意が要るものだけの 1 行 */
  PRV.prHead = function (data, tab) {
    var pr = data.pr;
    var attn = [];
    if (data.filesTruncated) attn.push("ファイル一覧は先頭の一部だけです");
    if (data.commits && pr.commits > data.commits.length) attn.push("コミット一覧は新しい順の先頭 " + data.commits.length + " 件だけです");
    return h(
      "div",
      { class: "prhead" },
      h("div", { class: "crumb" }, h("a", { href: "#/", text: "← PR 一覧" }), " ", h("span", { class: "muted", text: "/ " + pr.repoName })),
      h("h1", null, pr.branch, " ", PRV.stateChip(pr)),
      h("div", { class: "branches" }, pr.branch, " → ", pr.target),
      attn.length ? h("div", { class: "attn", role: "status", text: "⚠ " + attn.join(" ・ ") }) : null,
      h(
        "nav",
        { class: "tabs", "aria-label": "表示の切り替え" },
        h("a", { href: PRV.prHref(pr), class: tab === "overview" ? "on" : null, "aria-current": tab === "overview" ? "page" : null, text: "概要" }),
        h("a", { href: PRV.filesHref(pr), class: tab === "files" ? "on" : null, "aria-current": tab === "files" ? "page" : null, text: "差分 (" + pr.files + ")" })
      )
    );
  };

  function fileRow(pr, f) {
    var name = f.status === "R" && f.oldPath ? f.oldPath + " → " + f.path : f.path;
    return h(
      "li",
      null,
      h(
        "a",
        { class: "frow", href: PRV.filesHref(pr, f.path) },
        PRV.statusBadge(f.status),
        h("span", { class: "fp", text: name }),
        f.binary ? h("span", { class: "muted small", text: "バイナリ" }) : PRV.size(f.additions, f.deletions)
      )
    );
  }

  function commitRow(c) {
    return h(
      "li",
      { class: "crow" },
      h("div", { class: "csub", text: c.subject }),
      h("div", { class: "muted small" }, h("code", { text: PRV.short(c.oid) }), " ・ ", c.author, " ・ ", PRV.ago(c.at))
    );
  }

  function stat(k, v) {
    return h("li", null, h("span", { class: "k", text: k }), h("span", null, v));
  }

  function draw(data) {
    var pr = data.pr;
    var last = pr.lastCommit || {};
    var side = h(
      "section",
      { class: "card" },
      h("h2", { text: "統計" }),
      h(
        "ul",
        { class: "plain st3" },
        stat("コミット", String(pr.commits)),
        stat("ファイル", String(pr.files)),
        stat("変更行", PRV.size(pr.additions, pr.deletions)),
        stat("最後のコミット", PRV.ago(last.at)),
        stat("作者", last.author || ""),
        stat("統合先", h("code", { text: PRV.short(pr.targetOid) })),
        stat("分岐元", h("code", { text: PRV.short(pr.baseOid) })),
        stat("先頭", h("code", { text: PRV.short(pr.sourceOid) }))
      )
    );
    var commits = h(
      "section",
      { class: "card" },
      h("h2", { text: "コミット (" + pr.commits + ")" }),
      data.commits.length ? h("ul", { class: "plain" }, data.commits.map(commitRow)) : h("p", { class: "muted", text: "コミットはありません。" })
    );
    var files = h(
      "section",
      { class: "card" },
      h("h2", { text: "変更ファイル (" + pr.files + ")" }),
      data.files.length ? h("ul", { class: "plain files" }, data.files.map(function (f) { return fileRow(pr, f); })) : h("p", { class: "muted", text: "変更ファイルはありません。" })
    );
    PRV.mount(h("div", { class: "page" }, PRV.prHead(data, "overview"), h("div", { class: "cols" }, h("div", { class: "col-main" }, files, commits), h("div", { class: "col-side" }, side))));
  }

  PRV.viewOverview = function (r, isCurrent) {
    PRV.loading();
    PRV.getPr(r.id).then(
      function (data) {
        if (isCurrent()) draw(data);
      },
      function (e) {
        if (isCurrent()) PRV.showError(e);
      }
    );
  };
})();
