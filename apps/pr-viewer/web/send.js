/* レビューを送る: 固定バーと送信シート（スマホは下から出るシート） */
(function () {
  "use strict";
  var PRV = window.PRV;
  var h = PRV.h;
  var KINDS = [
    ["comment", "コメントのみ"],
    ["changes", "変更を依頼"],
    ["approve", "承認"],
  ];
  var DELIVERY = "送ったレビューは、次に pi へ入力したときに届く（pi が自動で読みに来るわけではない）。";
  var current = null;

  PRV.closeSheet = function () {
    if (current) {
      var c = current;
      current = null;
      c.backdrop.remove();
      document.removeEventListener("keydown", c.onKey);
      if (c.onClose) c.onClose();
      if (c.opener && c.opener.isConnected) c.opener.focus();
    }
  };

  /* 別のシート（統合する）が、同じ「開いている」扱いと閉じ方を使うための入口。onClose は閉じた直後に呼ぶ */
  PRV.openSheet = function (backdrop, onKey, opener, onClose) {
    PRV.closeSheet();
    document.addEventListener("keydown", onKey);
    document.body.appendChild(backdrop);
    current = { backdrop: backdrop, onKey: onKey, opener: opener, onClose: onClose };
  };

  PRV.sheetOpen = function () {
    return !!current;
  };

  function destName(w) {
    return String(w.name || "") + (w.isMain ? "（親）" : "");
  }

  /* ctx = { id, review, reload(notice) } */
  function openSheet(ctx, opener, presetKind) {
    PRV.closeSheet();
    var rv = ctx.review;
    var kind = presetKind || "comment";
    var unsent = rv.unsent || 0;
    var sheet = h("div", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-label": "レビューを送る" });
    var backdrop = h("div", { class: "backdrop" }, sheet);
    var err = h("div", { class: "formerr", role: "alert" });
    var hint = h("p", { class: "attn small", role: "status" });
    var send = h("button", { class: "btn primary", type: "button", text: "送る" });

    var seg = h("div", { class: "seg", role: "group", "aria-label": "レビューの種別" });
    var btns = {};
    KINDS.forEach(function (k) {
      var b = h("button", { class: "btn", type: "button", "aria-pressed": "false", text: k[1] });
      b.addEventListener("click", function () {
        kind = k[0];
        paint();
      });
      btns[k[0]] = b;
      seg.appendChild(b);
    });

    var sel = h("select", { "aria-label": "宛先の作業ツリー", id: "dest-sel" });
    (rv.worktrees || []).forEach(function (w) {
      var o = h("option", { text: destName(w) });
      o.value = w.worktreeId;
      sel.appendChild(o);
    });
    if (rv.defaultDest && rv.defaultDest.worktreeId) sel.value = rv.defaultDest.worktreeId;

    function paint() {
      Object.keys(btns).forEach(function (k) {
        btns[k].setAttribute("aria-pressed", k === kind ? "true" : "false");
      });
      var empty = kind === "comment" && unsent === 0;
      send.disabled = empty;
      hint.textContent = empty ? "未送信のコメントが無いため、「コメントのみ」は送れません。" : kind === "approve" ? "「承認」はレビューの承認です。統合はしません。" : "";
    }

    send.addEventListener("click", function () {
      err.textContent = "";
      send.disabled = true;
      var dest = sel.value ? { worktreeId: sel.value } : undefined;
      PRV.api.submit(ctx.id, { kind: kind, dest: dest, expect: PRV.expectOf(ctx.pr) }).then(
        function (res) {
          var n = res && Array.isArray(res.items) ? res.items.length : 0;
          PRV.closeSheet();
          ctx.reload("レビューを送りました（コメント " + n + " 件）。次に pi へ入力したときに届きます。");
        },
        function (e) {
          err.textContent = e && e.userMessage ? e.userMessage : "送信に失敗しました。";
          var again = PRV.staleAction(e);
          if (again) err.appendChild(again);
          paint();
        }
      );
    });
    var close = h("button", { class: "btn", type: "button", text: "閉じる" });
    close.addEventListener("click", PRV.closeSheet);
    backdrop.addEventListener("click", function (ev) {
      if (ev.target === backdrop) PRV.closeSheet();
    });

    sheet.appendChild(h("h2", { text: "レビューを送る" }));
    sheet.appendChild(h("p", { class: "sheetnote", text: DELIVERY }));
    sheet.appendChild(h("div", { class: "field" }, h("div", { class: "lbl", text: "種別" }), seg));
    sheet.appendChild(h("div", { class: "field" }, h("label", { class: "lbl", text: "宛先（作業ツリー）" }), sel));
    sheet.appendChild(h("p", { class: "unsentline", text: "未送信のコメント: " + unsent + " 件" }));
    sheet.appendChild(hint);
    sheet.appendChild(err);
    sheet.appendChild(h("div", { class: "cact" }, send, close));
    var onKey = function (ev) {
      if (ev.key === "Escape") PRV.closeSheet();
    };
    PRV.openSheet(backdrop, onKey, opener);
    paint();
    btns.comment.focus();
  }

  /* 概要の固定バー。書けないときは理由だけ出す */
  PRV.reviewBar = function (ctx, notice) {
    var rv = ctx.review;
    var bar = h("div", { class: "revbar", role: "region", "aria-label": "レビューを送る" });
    var why = PRV.readOnlyReason(rv, ctx.error);
    if (why) {
      bar.appendChild(h("span", { class: "muted", text: why }));
      return bar;
    }
    var main = h("div", { class: "revmain" });
    main.appendChild(h("strong", { class: "revcount", text: "未送信 " + (rv.unsent || 0) + " 件" }));
    main.appendChild(h("span", { class: "revchips" }, PRV.mainChip(ctx.pr, rv), PRV.staleReviewChip(rv)));
    var open = h("button", { class: "btn primary", type: "button", text: "レビューを送る…" });
    open.addEventListener("click", function () {
      openSheet(ctx, open);
    });
    var approve = h("button", { class: "btn", type: "button", text: "承認して送る…" });
    approve.addEventListener("click", function () {
      openSheet(ctx, approve, "approve");
    });
    bar.appendChild(main);
    bar.appendChild(h("span", { class: "revnote small", text: DELIVERY }));
    bar.appendChild(h("div", { class: "revbtns" }, open, approve));
    if (notice) bar.appendChild(h("div", { class: "revnotice", role: "status", text: notice }));
    return bar;
  };

  /* 送信履歴（受信されたかどうか）。ctx = { id, pr, canWrite, reload }。「再送」で同じ項目をもう一度送る */
  PRV.batchList = function (rv, ctx) {
    var bs = rv && Array.isArray(rv.batches) ? rv.batches : [];
    if (!bs.length) return null;
    var names = {};
    (rv.worktrees || []).forEach(function (w) {
      names[w.worktreeId] = destName(w);
    });
    var label = { comment: "コメントのみ", changes: "変更を依頼", approve: "承認" };
    var err = h("div", { class: "formerr", role: "alert" });
    function resendButton(b) {
      var btn = h("button", { class: "btn sm", type: "button", text: "再送" });
      btn.addEventListener("click", function () {
        err.textContent = "";
        btn.disabled = true;
        PRV.api.submit(ctx.id, { kind: b.kind, dest: b.dest, resendOf: b.batchId, expect: PRV.expectOf(ctx.pr) }).then(
          function () {
            ctx.reload("レビューを再送しました。次に pi へ入力したときに届きます。");
          },
          function (e) {
            btn.disabled = false;
            err.textContent = e && e.userMessage ? e.userMessage : "再送に失敗しました。";
            var again = PRV.staleAction(e);
            if (again) err.appendChild(again);
          }
        );
      });
      return btn;
    }
    return h(
      "section",
      { class: "card" },
      h("h2", { text: "送信したレビュー (" + bs.length + ")" }),
      h(
        "ul",
        { class: "plain" },
        bs.map(function (b) {
          var n = Array.isArray(b.items) ? b.items.length : 0;
          var to = (b.dest && names[b.dest.worktreeId]) || "宛先不明";
          return h(
            "li",
            null,
            h("strong", { text: label[b.kind] || String(b.kind) }),
            " ・ " + n + " 件 ・ " + to + " ・ ",
            b.received ? h("span", { class: "c-ok", text: "● pi が受け取り済み" }) : h("span", { class: "attn", text: "○ 未受信（次に pi へ入力したときに届く）" }),
            ctx && ctx.canWrite ? " " : null,
            ctx && ctx.canWrite ? resendButton(b) : null
          );
        })
      ),
      err
    );
  };
})();
