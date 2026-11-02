/* 差分 #/pr/<repoId>/<prKey>/files?path=<パス>。行のクリックでコメント入力欄、行の下にスレッド */
(function () {
  "use strict";
  var PRV = window.PRV;
  var h = PRV.h;
  var mode = "unified";

  function lineNo(v) {
    return h("td", { class: "num", text: v === null || v === undefined ? "" : String(v) });
  }

  /* 行 → 側と行番号。削除行は旧側、それ以外は新側 */
  function lineKey(l) {
    return l.t === "-" ? { side: "old", line: l.o } : { side: "new", line: l.n };
  }

  /* ctx = { id, path, res, rv, canWrite, reload, shown } */
  function threadsAt(ctx, k) {
    if (!k || !k.line) return [];
    /* その行の側の blob と一致するスレッドだけを置く（別の版の同じ行番号には置かない） */
    var blob = k.side === "old" ? ctx.res.oldBlob : ctx.res.newBlob;
    return ctx.threads.filter(function (t) {
      var a = t.comments[0].anchor;
      return a.side === k.side && a.lineEnd === k.line && !!blob && a.blob === blob;
    });
  }

  function threadRow(ctx, ts, cols) {
    ts.forEach(function (t) {
      ctx.shown[t.id] = true;
    });
    return h("tr", { class: "thr" }, h("td", { colspan: cols }, ts.map(function (t) { return PRV.threadView(t, ctx); })));
  }

  /* 行の直後（その行のスレッドの後）に入力欄を開く */
  function openEditor(ctx, tr, cols, k) {
    if (!ctx.canWrite || !k.line) return;
    if (window.getSelection && String(window.getSelection()).length) return; // 文字の選択中は開かない
    var ref = tr;
    while (ref.nextSibling && ref.nextSibling.classList.contains("thr")) ref = ref.nextSibling;
    var next = ref.nextSibling;
    var id = "ed-" + k.side + "-" + k.line;
    if (next && next.getAttribute("data-ed") === id) {
      next.querySelector("textarea").focus();
      return;
    }
    var blob = k.side === "old" ? ctx.res.oldBlob : ctx.res.newBlob;
    var ed = h("tr", { class: "editor", "data-ed": id });
    if (!blob || !/^[0-9a-f]{40,64}$/.test(blob)) {
      ed.appendChild(h("td", { colspan: cols }, h("div", { class: "formerr", role: "alert", text: "この行には、版の情報が無いためコメントを書けません。" })));
      ref.after(ed);
      return;
    }
    var anchor = { path: ctx.path, side: k.side, blob: blob, line: k.line, lineEnd: k.line };
    var form = PRV.commentForm({
      label: (k.side === "old" ? "旧" : "新") + " " + k.line + " 行目へのコメント",
      placeholder: k.line + " 行目へのコメントを入力",
      onSave: function (body) {
        return PRV.api.comment(ctx.id, { anchor: anchor, body: body, expect: PRV.expectOf(ctx.pr) }).then(function () {
          return ctx.reload();
        });
      },
      onCancel: function () {
        ed.remove();
      },
    });
    ed.appendChild(h("td", { colspan: cols }, h("div", { class: "editbox" }, h("div", { class: "muted small", text: "コメントする行: " + (k.side === "old" ? "旧 " : "新 ") + k.line }), form)));
    ref.after(ed);
    form.focusInput();
  }

  function unifiedRows(hunk, ctx) {
    var out = [];
    hunk.lines.forEach(function (l) {
      var cls = (l.t === "+" ? "a" : l.t === "-" ? "d" : "c") + (ctx.canWrite ? " can" : "");
      var k = lineKey(l);
      var tr = h("tr", { class: cls }, lineNo(l.o), lineNo(l.n), h("td", { class: "code" }, h("span", { class: "mk", text: l.t === " " ? "" : l.t }), l.s));
      tr.addEventListener("click", function () {
        openEditor(ctx, tr, 3, k);
      });
      out.push(tr);
      var ts = threadsAt(ctx, k);
      if (ts.length) out.push(threadRow(ctx, ts, 3));
    });
    return out;
  }

  /* 左右並び: 連続する削除と追加を行ごとに対にする。左は旧側、右は新側（文脈行は新側） */
  function splitRows(hunk, ctx) {
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
    var out = [];
    rows.forEach(function (p) {
      var isCtx = p[0] && p[0] === p[1];
      var can = ctx.canWrite ? " can" : "";
      function cell(l, cls) {
        return h("td", { class: "code " + (l ? (isCtx ? "c" : cls) : "empty") + can, text: l ? l.s : "" });
      }
      var left = p[0];
      var right = p[1];
      var kl = left && !isCtx ? { side: "old", line: left.o } : null;
      var kr = right ? { side: "new", line: right.n } : null;
      var cells = [lineNo(left && left.o), cell(left, "d"), lineNo(right && right.n), cell(right, "a")];
      var tr = h("tr", null, cells);
      if (kl) {
        [cells[0], cells[1]].forEach(function (c) {
          c.addEventListener("click", function () {
            openEditor(ctx, tr, 4, kl);
          });
        });
      }
      if (kr) {
        [cells[2], cells[3]].forEach(function (c) {
          c.addEventListener("click", function () {
            openEditor(ctx, tr, 4, kr);
          });
        });
      }
      out.push(tr);
      var ts = threadsAt(ctx, kl).concat(threadsAt(ctx, kr));
      if (ts.length) out.push(threadRow(ctx, ts, 4));
    });
    return out;
  }

  function hunkTable(hunks, ctx) {
    var split = mode === "split" && !PRV.isNarrow();
    var table = h("table", { class: "diff " + (split ? "split" : "unified") });
    hunks.forEach(function (hk) {
      table.appendChild(h("tr", { class: "gap" }, h("td", { colspan: split ? 4 : 3, class: "hh", text: hk.header })));
      var rows = split ? splitRows(hk, ctx) : unifiedRows(hk, ctx);
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

  function diffBody(ctx) {
    var res = ctx.res;
    if (res.binary) return h("div", { class: "binary" }, h("span", { text: "⬚" }), h("span", { text: "バイナリファイルのため差分を表示しません。" }));
    if (!res.hunks || res.hunks.length === 0) return h("div", { class: "binary", text: "表示できる差分がありません。" });
    return hunkTable(res.hunks, ctx);
  }

  /* 表示中の行に対応しないスレッド（古い版など）は、表の上にまとめて出す */
  function orphanBox(ctx) {
    var rest = ctx.threads.filter(function (t) {
      return !ctx.shown[t.id];
    });
    if (!rest.length) return null;
    return h(
      "div",
      { class: "orphans" },
      h("p", { class: "attn small", text: "⚠ 表示中の行に対応しないコメント (" + rest.length + ")。行が変わった・消えた可能性があります。" }),
      rest.map(function (t) {
        return PRV.threadView(t, ctx);
      })
    );
  }

  function draw(id, data, path, res, st) {
    var pr = data.pr;
    var tok = PRV.token;
    var rv = st.review;
    var f = data.files.filter(function (x) { return x.path === path; })[0] || { path: path, status: "M", additions: 0, deletions: 0 };
    var body = h("div", { class: "fbody" });
    var ctx = {
      id: id,
      pr: pr,
      path: path,
      res: res,
      canWrite: PRV.canWrite(rv),
      threads: [],
      shown: {},
      reload: function () {
        return PRV.loadReview(id).then(function (x) {
          if (PRV.token !== tok) return;
          rv = x.review;
          st.error = x.error;
          ctx.canWrite = PRV.canWrite(rv);
          paint();
        });
      },
    };
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
      ctx.review = rv;
      ctx.error = st.error;
      ctx.shown = {};
      ctx.threads = rv
        ? (rv.threads || []).filter(function (t) {
            var a = t.comments[0] && t.comments[0].anchor;
            return a && a.path === path;
          })
        : [];
      var table = diffBody(ctx);
      body.replaceChildren.apply(body, [orphanBox(ctx), table].filter(Boolean));
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
    var why = PRV.readOnlyReason(rv, st.error);
    var hint = why
      ? h("div", { class: "attn pad small", role: "status", text: why })
      : h("div", { class: "muted pad small", text: "行をクリック（スマホはタップ）すると、その行にコメントできます。" });
    var main = h("div", { class: "file" }, fh, warn, hint, body);
    PRV.mount(h("div", { class: "page wide" }, PRV.prHead(data, "files", rv), h("div", { class: "diffgrid" }, fileList(data, path), main)));
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
      return Promise.all([PRV.api.diff(r.id, path), PRV.loadReview(r.id)]).then(function (res) {
        if (isCurrent()) draw(r.id, data, path, res[0], { review: res[1].review, error: res[1].error });
      });
    }).catch(function (e) {
      if (isCurrent()) PRV.showError(e);
    });
  };
})();
