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

  /* 詳細のヘッダー: 主状態チップ 1 つ + 注意が要るものだけの 1 行。rv は review の応答（無ければ null） */
  PRV.prHead = function (data, tab, rv) {
    var pr = data.pr;
    var attn = [];
    if (data.filesTruncated) attn.push("ファイル一覧は先頭の一部だけです");
    if (data.commits && pr.commits > data.commits.length) attn.push("コミット一覧は新しい順の先頭 " + data.commits.length + " 件だけです");
    if (rv && PRV.canWrite(rv) && rv.unsent > 0) attn.push("未送信のコメントが " + rv.unsent + " 件あります（概要の「レビューを送る」から送れます）");
    return h(
      "div",
      { class: "prhead" },
      h("div", { class: "crumb" }, h("a", { href: "#/", text: "← PR 一覧" }), " ", h("span", { class: "muted", text: "/ " + pr.repoName })),
      h("h1", null, pr.branch, " ", h("span", { class: "hchips" }, PRV.mainChip(pr, rv), " ", PRV.staleReviewChip(rv))),
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

  function generalOf(rv) {
    return rv ? (rv.threads || []).filter(function (t) { return !(t.comments[0] && t.comments[0].anchor); }) : [];
  }

  /* スレッドの箱だけを作り直す（入力欄はこの箱の外にあるので、作り直しの影響を受けない） */
  function fillThreads(ctx) {
    var threads = generalOf(ctx.review);
    var d = ctx.dom;
    d.count.textContent = "PR 全体のコメント (" + threads.length + ")";
    var kids = threads.map(function (t) { return PRV.threadView(t, ctx); });
    if (!threads.length) kids.push(h("p", { class: "muted", text: "コメントはありません。" }));
    d.threads.replaceChildren.apply(d.threads, kids);
    d.keys.threads = JSON.stringify(threads);
  }

  /* PR 全体のコメント（anchor が null のスレッド）と入力欄 */
  function generalCard(ctx) {
    var rv = ctx.review;
    ctx.dom.count = h("h2");
    ctx.dom.threads = h("div", { class: "threads" });
    var card = h("section", { class: "card" }, ctx.dom.count, ctx.dom.threads);
    fillThreads(ctx);
    if (ctx.canWrite) {
      card.appendChild(
        PRV.commentForm({
          label: "PR 全体へのコメント",
          placeholder: "PR 全体へのコメントを入力",
          saveText: "コメントを保存",
          onSave: function (body) {
            return PRV.api.comment(ctx.id, { body: body, expect: PRV.expectOf(ctx.pr) }).then(function () {
              return ctx.reload();
            });
          },
        })
      );
    } else {
      var why = PRV.readOnlyReason(rv, ctx.error);
      if (why) card.appendChild(h("p", { class: "attn small", text: why }));
    }
    return card;
  }

  /* 入力途中の内容がある（書きかけの欄・開いた返信欄・送信シート）間は、スレッドの本文を差し替えない */
  function blocked(ctx) {
    if (PRV.sheetOpen && PRV.sheetOpen()) return true;
    return Array.prototype.some.call(document.querySelectorAll("#app textarea"), function (ta) {
      return ta.value !== "" || ctx.dom.threads.contains(ta);
    });
  }

  /* 自動更新で取り直した rv を画面へ反映する。返り値は「本文の反映を見送った」（バナーを出す）。force は利用者がバナーを押したとき */
  function liveApply(ctx, rv, force, redraw) {
    var d = ctx.dom;
    if (PRV.canWrite(rv) !== ctx.canWrite) {
      /* 書き込めるかが変わると、入力欄の有無が変わる: 入力が無いときだけ全体を描き直す */
      if (force || !blocked(ctx)) {
        redraw(rv);
        return false;
      }
      return true;
    }
    ctx.review = rv;
    var deferred = false;
    /* 状態の表示（入力欄を含まない部分）は、常に部分更新する */
    var count = d.bar && d.bar.querySelector(".revcount");
    if (count) count.textContent = "未送信 " + (rv.unsent || 0) + " 件";
    if (d.bar && PRV.paintQueue) PRV.paintQueue(d.bar, rv);
    var chips = d.bar && d.bar.querySelector(".revchips");
    if (chips) chips.replaceChildren.apply(chips, [PRV.mainChip(ctx.pr, rv) || "", PRV.staleReviewChip(rv) || ""]);
    var hc = document.querySelector(".prhead .hchips");
    if (hc) hc.replaceChildren.apply(hc, [PRV.mainChip(ctx.pr, rv) || "", " ", PRV.staleReviewChip(rv) || ""]);
    var sk = JSON.stringify((rv && rv.summary) || null);
    if (sk !== d.keys.summary) {
      d.keys.summary = sk;
      d.summary.replaceChildren.apply(d.summary, [PRV.summaryCard(rv.summary) || ""]);
    }
    var bk = JSON.stringify([rv.batches || [], rv.worktrees || []]);
    if (bk !== d.keys.batches) {
      if (!force && d.batches.contains(document.activeElement)) deferred = true;
      else {
        d.keys.batches = bk;
        d.batches.replaceChildren.apply(d.batches, [PRV.batchList(rv, ctx) || ""]);
      }
    }
    /* スレッドの本文: 入力が無いときだけ自動で、あるときは利用者の操作で */
    if (JSON.stringify(generalOf(rv)) !== d.keys.threads) {
      if (!force && blocked(ctx)) deferred = true;
      else fillThreads(ctx);
    }
    return deferred;
  }

  function draw(id, data, st) {
    var tok = st.tok || PRV.token;
    var ctx = {
      dom: { keys: {} },
      id: id,
      pr: data.pr,
      review: st.review,
      error: st.error,
      canWrite: PRV.canWrite(st.review),
      reload: function (notice) {
        return PRV.loadReview(id).then(function (x) {
          if (PRV.token !== tok) return;
          draw(id, data, { review: x.review, error: x.error, notice: typeof notice === "string" ? notice : "", tok: tok, caps: st.caps });
        });
      },
      caps: st.caps,
    };
    draw2(data, ctx, st.notice);
    PRV.liveBind(st.review, function (rv, force) {
      return liveApply(ctx, rv, force, function (x) {
        draw(id, data, { review: x, error: null, notice: "", tok: tok, caps: st.caps });
      });
    });
  }

  /* 統合先が分岐後に進んだことと、両側で変更されたファイル（衝突の可能性の目安。判定ではない）。パスは textContent だけで出す */
  function behindCard(pr) {
    if (pr.state !== "open" || !(pr.behind > 0)) return null;
    var ov = pr.overlap || { count: 0, paths: [], truncated: false };
    var kids = [h("h2", { text: pr.target + " が " + pr.behind + " コミット進みました" })];
    if (ov.count > 0) {
      var many = ov.paths.length === 0;
      var label = many ? "衝突の可能性: 多数（" + ov.count + " 件以上）" : "衝突の可能性: " + ov.count + " 件";
      var items = ov.paths.map(function (p) { return h("li", null, h("span", { class: "fp", text: p })); });
      if (!many && ov.truncated) items.push(h("li", { class: "muted small", text: "ほか " + (ov.count - ov.paths.length) + " 件" }));
      kids.push(
        h(
          "details",
          { class: "overlap" },
          h("summary", { text: label }),
          items.length ? h("ul", { class: "plain files" }, items) : null,
          h("p", { class: "muted small", text: "両側が変更したファイルの目安です。実際の可否は「統合する」の確認画面で出ます。" })
        )
      );
    } else {
      kids.push(h("p", { class: "muted small", text: "両側で変更されたファイルはありません。" }));
    }
    return h("section", { class: "card behindcard" }, kids);
  }

  function draw2(data, ctx, notice) {
    var pr = data.pr;
    var rv = ctx.review;
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
    /* 自動更新で差し替える部分は、箱に入れておく（入力欄の箱とは別） */
    var d = ctx.dom;
    d.summary = h("div", { class: "live-summary" }, PRV.summaryCard(rv && rv.summary));
    d.keys.summary = JSON.stringify((rv && rv.summary) || null);
    d.batches = h("div", { class: "live-batches" }, PRV.batchList(rv, ctx));
    d.keys.batches = JSON.stringify([(rv && rv.batches) || [], (rv && rv.worktrees) || []]);
    var main = [PRV.briefCard ? PRV.briefCard(rv) : null, behindCard(pr), d.summary, generalCard(ctx), files, commits, d.batches];
    d.bar = PRV.reviewBar(ctx, notice);
    var me = PRV.mergeEntry ? PRV.mergeEntry(ctx) : null;
    var je = PRV.jobEntry ? PRV.jobEntry(ctx) : null;
    PRV.mount(
      h(
        "div",
        { class: me ? "page withbar hasmerge" : "page withbar" },
        PRV.prHead(data, "overview", rv),
        PRV.liveBar(),
        h("div", { class: "cols" }, h("div", { class: "col-main" }, main), h("div", { class: "col-side" }, me ? me.card : null, je, side)),
        d.bar,
        me ? me.bar : null
      )
    );
  }

  PRV.viewOverview = function (r, isCurrent) {
    PRV.loading();
    Promise.all([PRV.getPr(r.id), PRV.loadReview(r.id), PRV.api.capabilities()]).then(
      function (res) {
        if (!isCurrent()) return;
        PRV.liveStart(r.id);
        draw(r.id, res[0], { review: res[1].review, error: res[1].error, notice: "", caps: res[2] });
      },
      function (e) {
        if (isCurrent()) PRV.showError(e);
      }
    );
  };
})();
