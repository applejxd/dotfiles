/* 差分 #/pr/<repoId>/<prKey>/files?path=<パス>（閲覧のみ） */
(function () {
  "use strict";
  var PRV = window.PRV;
  var h = PRV.h;
  var mode = "unified";

  function lineNo(v) {
    return h("td", { class: "num", text: v === null || v === undefined ? "" : String(v) });
  }

  function unifiedRows(hunk) {
    var out = [];
    hunk.lines.forEach(function (l) {
      var cls = l.t === "+" ? "a" : l.t === "-" ? "d" : "c";
      out.push(h("tr", { class: cls }, lineNo(l.o), lineNo(l.n), h("td", { class: "code" }, h("span", { class: "mk", text: l.t === " " ? "" : l.t }), l.s)));
    });
    return out;
  }

  /* 左右並び: 連続する削除と追加を行ごとに対にする。左は旧側、右は新側（文脈行は新側） */
  function splitRows(hunk) {
    var rows = [];
    var dels = [];
    var adds = [];
    function flush() {
      var n = Math.max(dels.length, adds.length);
      for (var i = 0; i < n; i++) rows.push([dels[i] || null, adds[i] || null]);
      dels = [];
      adds = [];
    }
    hunk.lines.forEach(function (l) {
      if (l.t === "-") dels.push(l);
      else if (l.t === "+") adds.push(l);
      else {
        flush();
        rows.push([l, l]);
      }
    });
    flush();
    return rows.map(function (p) {
      var isCtx = p[0] && p[0] === p[1];
      function cell(l, cls) {
        return h("td", { class: "code " + (l ? (isCtx ? "c" : cls) : "empty"), text: l ? l.s : "" });
      }
      var left = p[0];
      var right = p[1];
      return h("tr", null, [lineNo(left && left.o), cell(left, "d"), lineNo(right && right.n), cell(right, "a")]);
    });
  }

  function hunkTable(hunks) {
    var split = mode === "split" && !PRV.isNarrow();
    var table = h("table", { class: "diff " + (split ? "split" : "unified") });
    hunks.forEach(function (hk) {
      table.appendChild(h("tr", { class: "gap" }, h("td", { colspan: split ? 4 : 3, class: "hh", text: hk.header })));
      var rows = split ? splitRows(hk) : unifiedRows(hk);
      rows.forEach(function (r) {
        table.appendChild(r);
      });
    });
    return h("div", { class: "frame" }, table);
  }

  function fileList(data, cur) {
    var pr = data.pr;
    var items = data.files.map(function (f) {
      var cut = f.path.lastIndexOf("/") + 1;
      return h(
        "li",
        null,
        h(
          "a",
          { href: PRV.filesHref(pr, f.path), class: f.path === cur ? "cur" : null, "aria-current": f.path === cur ? "true" : null },
          PRV.statusBadge(f.status),
          h("span", { class: "tn" }, h("span", { class: "dir", text: f.path.slice(0, cut) }), f.path.slice(cut))
        )
      );
    });
    var d = h("details", { class: "filetree" }, h("summary", { text: "ファイル (" + data.files.length + ")" }), h("ul", { class: "tree" }, items));
    d.open = !PRV.isNarrow();
    return d;
  }

  function diffBody(res) {
    if (res.binary) return h("div", { class: "binary" }, h("span", { text: "⬚" }), h("span", { text: "バイナリファイルのため差分を表示しません。" }));
    if (!res.hunks || res.hunks.length === 0) return h("div", { class: "binary", text: "表示できる差分がありません。" });
    return hunkTable(res.hunks);
  }

  function draw(data, path, res) {
    var f = data.files.filter(function (x) { return x.path === path; })[0] || { path: path, status: "M", additions: 0, deletions: 0 };
    var body = h("div", { class: "fbody" });
    var seg = h("div", { class: "seg", role: "group", "aria-label": "表示形式" });
    var bs = {};
    [["unified", "1 列"], ["split", "左右並び"]].forEach(function (m) {
      var b = h("button", { class: "btn sm" + (m[0] === "split" ? " hide-sp" : ""), type: "button", "aria-pressed": "false", text: m[1] });
      b.addEventListener("click", function () {
        mode = m[0];
        paint();
      });
      bs[m[0]] = b;
      seg.appendChild(b);
    });
    function paint() {
      Object.keys(bs).forEach(function (k) {
        bs[k].setAttribute("aria-pressed", k === mode ? "true" : "false");
      });
      body.replaceChildren(diffBody(res));
    }
    var fh = h(
      "div",
      { class: "fh" },
      PRV.statusBadge(f.status),
      h("span", { class: "path", text: f.status === "R" && f.oldPath ? f.oldPath + " → " + f.path : f.path }),
      PRV.size(f.additions, f.deletions),
      seg
    );
    var warn = res.truncated ? h("div", { class: "attn pad", role: "status", text: "⚠ 差分が大きいため、途中までを表示しています。" }) : null;
    var main = h("div", { class: "file" }, fh, warn, body);
    PRV.mount(h("div", { class: "page wide" }, PRV.prHead(data, "files"), h("div", { class: "diffgrid" }, fileList(data, path), main)));
    paint();
  }

  PRV.viewDiff = function (r, isCurrent) {
    PRV.loading();
    PRV.getPr(r.id).then(function (data) {
      if (!isCurrent()) return null;
      var path = r.path;
      if (!path && data.files.length) path = data.files[0].path;
      if (!path) {
        PRV.mount(h("div", { class: "page wide" }, PRV.prHead(data, "files"), h("p", { class: "muted", text: "変更ファイルはありません。" })));
        return null;
      }
      return PRV.api.diff(r.id, path).then(function (res) {
        if (isCurrent()) draw(data, path, res);
      });
    }).catch(function (e) {
      if (isCurrent()) PRV.showError(e);
    });
  };
})();
