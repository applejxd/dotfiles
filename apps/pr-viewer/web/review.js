/* レビューの部品: スレッド・入力欄・サマリー。API の文字列は非信頼（textContent だけで描画する） */
(function () {
  "use strict";
  var PRV = window.PRV;
  var h = PRV.h;

  /* 状態は記号 + 文字（色だけに頼らない） */
  var STATUS = {
    unsent: ["○", "未送信", "c-warn"],
    sent: ["➤", "送信済み", "c-info"],
    read: ["◐", "pi が読んだ", "c-merged"],
    replied: ["●", "pi が返信済み", "c-ok"],
  };

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

  PRV.canWrite = function (rv) {
    return !!rv && !rv.readonly && !rv.bad && !rv.merged;
  };

  /* 書けない理由（書けるときは空） */
  PRV.readOnlyReason = function (rv, error) {
    if (!rv) return error ? "レビュー情報を取得できないため、コメントは読み取り専用です（" + error + "）" : "";
    if (rv.readonly) return "この PR のレビューは新しい形式のため、読み取り専用です。";
    if (rv.bad) return "この PR のレビュー記録に問題があるため、書き込めません。";
    if (rv.merged) return "統合済みの PR には書き込めません。";
    return "";
  };

  PRV.statusChip = function (status) {
    var s = STATUS[status] || ["?", "状態不明", "c-mute"];
    return h("span", { class: "chip " + s[2], text: s[0] + " " + s[1] });
  };

  /* PR の主状態チップ。統合済みは最優先（統合後に変更依頼は残らない）。段 2 は 統合済み・変更依頼・承認だけ */
  PRV.mainChip = function (pr, rv) {
    if (pr.state === "merged") return PRV.stateChip(pr);
    if (rv && rv.review === "changes") return h("span", { class: "chip c-bad", text: "✎ 変更依頼" });
    if (rv && rv.review === "approve") return h("span", { class: "chip c-ok", text: "✓ 承認" });
    return null;
  };

  PRV.staleReviewChip = function (rv) {
    if (!rv || !rv.reviewStale || rv.review === "none") return null;
    return h("span", { class: "chip c-warn", title: "レビューの後に、ブランチが変わりました", text: "⚠ 古いレビュー" });
  };

  function byLabel(by) {
    if (by === "app") return "あなた";
    if (by === "pi") return "pi";
    return String(by || "");
  }

  /* 表示中の版から PR が更新されたとき（409 stale_view）の「取り直し」ボタン。それ以外は null */
  PRV.staleAction = function (e) {
    if (!e || e.code !== "stale_view") return null;
    var btn = PRV.h("button", { class: "btn sm", type: "button", text: "最新の版を読み込む" });
    btn.addEventListener("click", function () {
      PRV.cache = {};
      PRV.render();
    });
    return btn;
  };

  /* 入力欄。onSave(本文) は Promise を返す。失敗は日本語で出し、ボタンを戻す */
  PRV.commentForm = function (opts) {
    var ta = h("textarea", { class: "cbox", "aria-label": opts.label });
    ta.setAttribute("rows", "3");
    ta.setAttribute("maxlength", "8000");
    ta.setAttribute("placeholder", opts.placeholder || "コメントを入力");
    var err = h("div", { class: "formerr", role: "alert" });
    var save = h("button", { class: "btn sm primary", type: "button", text: opts.saveText || "保存" });
    var kids = [save];
    var cancel = null;
    if (opts.onCancel) {
      cancel = h("button", { class: "btn sm", type: "button", text: "キャンセル" });
      cancel.addEventListener("click", opts.onCancel);
      kids.push(cancel);
    }
    function busy(b) {
      save.disabled = b;
      ta.disabled = b;
      if (cancel) cancel.disabled = b;
    }
    save.addEventListener("click", function () {
      err.textContent = "";
      if (ta.value.trim() === "") {
        err.textContent = "コメントを入力してください。";
        return;
      }
      busy(true);
      opts.onSave(ta.value).catch(function (e) {
        busy(false);
        err.textContent = e && e.userMessage ? e.userMessage : "保存に失敗しました。";
        var again = PRV.staleAction(e);
        if (again) err.appendChild(again);
      });
    });
    var form = h("div", { class: "cform" }, ta, err, h("div", { class: "cact" }, kids));
    form.focusInput = function () {
      ta.focus();
    };
    return form;
  };

  function commentView(c) {
    return h(
      "div",
      { class: "comment" },
      h("div", { class: "cmeta" }, h("strong", { text: byLabel(c.by) }), " ", h("span", { class: "muted small", text: PRV.ago(c.at) })),
      PRV.md(c.body)
    );
  }

  /* ctx = { id, canWrite, reload } */
  PRV.threadView = function (t, ctx) {
    var box = h("div", { class: "thread" + (t.stale ? " stale" : "") });
    var head = h("div", { class: "thead" }, PRV.statusChip(t.status));
    if (t.stale) head.appendChild(h("span", { class: "chip c-warn", text: "⚠ 古い版" }));
    box.appendChild(head);
    if (t.stale) {
      box.appendChild(h("p", { class: "attn small", text: "このコメントは、現在より前の版のコードに付いています。行の内容が変わっている可能性があります。" }));
    }
    (t.comments || []).forEach(function (c) {
      box.appendChild(commentView(c));
    });
    if (ctx.canWrite) {
      var slot = h("div", { class: "reply" });
      var open = h("button", { class: "btn sm", type: "button", text: "返信" });
      open.addEventListener("click", function () {
        var form = PRV.commentForm({
          label: "返信",
          placeholder: "返信を入力",
          saveText: "返信を保存",
          onSave: function (body) {
            return PRV.api.comment(ctx.id, { thread: t.id, body: body, expect: PRV.expectOf(ctx.pr) }).then(function () {
              return ctx.reload();
            });
          },
          onCancel: function () {
            slot.replaceChildren(open);
          },
        });
        slot.replaceChildren(form);
        form.focusInput();
      });
      slot.appendChild(open);
      box.appendChild(slot);
    }
    return box;
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
