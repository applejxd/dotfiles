/* 統合する: 承認シート（2 段）。押下の POST で、アプリが develop への統合を実行する。契約は docs/spec/pr-viewer.md */
(function () {
  "use strict";
  var PRV = window.PRV;
  var h = PRV.h;
  var MAX = 4000;
  var CLEANUPS = [
    ["none", "残す"],
    ["branch", "枝を削除"],
    ["branch_and_worktree", "枝と作業ツリーを削除"],
  ];
  /* 制御文字（\n と \t 以外）と双方向制御文字 */
  var BAD_CHARS = /[\u0000-\u0008\u000B-\u001F\u007F-\u009F\u061C\u200E\u200F\u202A-\u202E\u2066-\u2069]/;
  var UNKNOWN = "結果を確認できません。再読み込みして PR の状態を確認してください。";
  var TREE = { already_merged: 1, dirty: 1, ignored: 1, head_mismatch: 1, external_code: 1, no_identity: 1 };
  var RETRY = { busy: 1, too_large: 1, dirty: 1, ignored: 1, head_mismatch: 1, external_code: 1, no_identity: 1 };
  var RECOVER = [
    "他の git・エディターの自動保存・ビルドが動いていないことを確かめる",
    "リポジトリで node apps/pr-viewer/merge-cli.ts recover <リポジトリのパス> を実行する",
    "画面を再読み込みする（診断が返ったら git status で手当てして、もう一度 recover）",
  ];

  function code(t) {
    return h("code", { text: t });
  }

  function messageError(v) {
    var n = Array.from(v).length;
    if (n === 0) return "メッセージを入力してください。";
    if (n > MAX) return "メッセージは " + MAX + " 文字までです（現在 " + n + " 文字）。";
    if (BAD_CHARS.test(v)) return "制御文字・双方向制御文字は使えません。";
    if (v.split("\n")[0].trim() === "") return "1 行目が空白だけです。";
    return "";
  }

  function reloadAll() {
    PRV.closeSheet();
    PRV.cache = {};
    PRV.render();
  }

  /* 失敗の表示。通信断・merge_failed・internal は、成功とも失敗とも決め付けない（forPlan は副作用が無いので別の文言） */
  function describe(e, forPlan) {
    var c = (e && e.code) || "";
    var status = (e && e.status) || 0;
    var msg = (e && e.serverMessage) || "";
    var d = { nodes: [], retry: false, reload: false, stale: false, list: false };
    function p(t) {
      d.nodes.push(h("p", { text: t }));
    }
    if (c === "unverified") {
      /* 反映を読めなかった。統合されたか不明で、状態ファイルが残っているので recover が必要（500 のまま専用の案内） */
      d.reload = true;
      p("統合の結果を確認できませんでした。統合されたかどうかは不明で、復旧（recover）が必要です。次の手順で確かめてください。");
      d.nodes.push(
        h(
          "ol",
          null,
          RECOVER.map(function (t) {
            return h("li", { text: t });
          })
        )
      );
      return d;
    }
    if (!e || e.network || !c || status >= 500 || c === "merge_failed" || c === "internal") {
      d.reload = true;
      p(forPlan ? "統合の内容を取得できませんでした。" : UNKNOWN);
      if (msg) p(msg);
      d.retry = !!forPlan;
      return d;
    }
    if (c === "recover_needed") {
      d.reload = true;
      p("統合の途中で止まっています。次の手順で復旧してください（実パスは表示しません）。");
      d.nodes.push(
        h(
          "ol",
          null,
          RECOVER.map(function (t) {
            return h("li", { text: t });
          })
        )
      );
      return d;
    }
    if (c === "conflict") {
      p(msg || "統合先と衝突しています。");
      var cf = Array.isArray(e.conflicts) ? e.conflicts.slice(0, 100) : [];
      if (cf.length) {
        d.nodes.push(
          h(
            "ul",
            { class: "plain" },
            cf.map(function (t) {
              return h("li", null, code(String(t)));
            })
          )
        );
      }
      p("衝突の解消は pi で行ってください。");
      return d;
    }
    if (c === "merge_disabled" || /^forbidden_/.test(c)) p("この画面からは統合できません。");
    else if (/^bad_/.test(c)) p("入力に誤りがあります。");
    else if (c === "not_found" || c === "no_source" || c === "no_target") {
      p("PR が見つかりません。");
      d.list = true;
    } else if (/^policy_/.test(c)) p("統合できない PR です。");
    else if (c === "stale_view" || c === "not_ff") {
      p("表示中の版から PR が更新されています。");
      d.stale = true;
    } else if (c === "busy") p("しばらくして再試行してください。");
    else if (c === "too_large") p("本文が大きすぎます。");
    else if (!TREE[c] && !/^legacy_/.test(c)) p("統合できませんでした。");
    if (msg) p(msg);
    if (TREE[c]) p("統合先の作業ツリーを確認してください。");
    d.retry = !!RETRY[c] || /^bad_/.test(c);
    return d;
  }

  function actions(d) {
    var out = [];
    if (d.reload) {
      var r = h("button", { class: "btn", type: "button", text: "再読み込み" });
      r.addEventListener("click", reloadAll);
      out.push(r);
    }
    if (d.stale) {
      var s = h("button", { class: "btn", type: "button", text: "最新の版を読み込む" });
      s.addEventListener("click", reloadAll);
      out.push(s);
    }
    if (d.list) out.push(h("a", { class: "btn", href: "#/", text: "一覧へ" }));
    return out.length ? h("div", { class: "cact" }, out) : null;
  }

  function oidLine(label, side) {
    return h(
      "li",
      null,
      h("span", { class: "k", text: label }),
      " ",
      code(side.branch),
      " ",
      code(PRV.short(side.oid)),
      h("details", { class: "oidfull" }, h("summary", { text: "全文" }), code(side.oid))
    );
  }

  /* ctx = { id, pr, ... }。開いている間の状態は、このシートだけが持つ（別の PR・閉じた後のシートへ応答が混ざらない） */
  function openMerge(ctx, opener) {
    var S = {
      id: ctx.id,
      closed: false,
      running: false,
      done: null,
      dead: false,
      seq: 0,
      res: null,
      message: "",
      cleanup: "none",
      edited: false,
      touched: false,
      snap: null,
    };
    var sheet = h("div", { class: "sheet mergesheet", role: "dialog", "aria-modal": "true", "aria-label": "統合する", tabindex: "-1" });
    var backdrop = h("div", { class: "backdrop" }, sheet);
    var app = document.getElementById("app");

    function requestClose() {
      if (S.running) return;
      if (S.done) return finish();
      PRV.closeSheet();
    }

    function finish() {
      var gone = S.done && S.done.deleted;
      PRV.closeSheet();
      PRV.cache = {};
      if (gone) location.hash = "#/";
      else PRV.render();
    }

    function focusables() {
      return Array.prototype.filter.call(sheet.querySelectorAll("button, input, textarea, select, summary, a[href]"), function (el) {
        return !el.disabled && el.getClientRects().length > 0;
      });
    }

    var onKey = function (ev) {
      if (ev.key === "Escape") {
        ev.preventDefault();
        requestClose();
        return;
      }
      if (ev.key !== "Tab") return;
      var f = focusables();
      var at = document.activeElement;
      if (!f.length) {
        ev.preventDefault();
        sheet.focus();
      } else if (!sheet.contains(at) || at === sheet) {
        ev.preventDefault();
        f[ev.shiftKey ? f.length - 1 : 0].focus();
      } else if (ev.shiftKey && at === f[0]) {
        ev.preventDefault();
        f[f.length - 1].focus();
      } else if (!ev.shiftKey && at === f[f.length - 1]) {
        ev.preventDefault();
        f[0].focus();
      }
    };
    backdrop.addEventListener("click", function (ev) {
      if (ev.target === backdrop) requestClose();
    });

    function closeBtn() {
      var b = h("button", { class: "btn mergeclose", type: "button", text: "閉じる" });
      b.addEventListener("click", requestClose);
      return b;
    }

    function mount(kids) {
      sheet.replaceChildren.apply(sheet, kids);
      var hd = sheet.querySelector("h2");
      if (hd) {
        hd.setAttribute("tabindex", "-1");
        hd.focus();
      }
    }

    /* --- 計画（merge-plan）の取得 --- */
    function loadPlan() {
      var n = ++S.seq;
      S.res = null;
      S.snap = null;
      S.dead = false;
      mount([h("h2", { text: "統合する" }), h("p", { class: "muted", role: "status", text: "統合の内容を確認中…" }), h("div", { class: "cact" }, closeBtn())]);
      PRV.api.mergePlan(S.id).then(
        function (res) {
          if (S.closed || n !== S.seq) return; /* 閉じた後・取り直した後の古い応答は捨てる */
          S.res = res;
          var d = res.defaults || {};
          if (!S.edited) S.message = typeof d.message === "string" ? d.message : "";
          if (!S.touched) S.cleanup = d.cleanup === "branch" || d.cleanup === "branch_and_worktree" ? d.cleanup : "none";
          step1();
        },
        function (e) {
          if (S.closed || n !== S.seq) return;
          var d = describe(e, true);
          var retry = h("button", { class: "btn", type: "button", text: "計画を取り直す" });
          retry.addEventListener("click", loadPlan);
          mount([
            h("h2", { text: "統合する" }),
            h("div", { class: "formerr", role: "alert" }, d.nodes),
            actions(d),
            h("div", { class: "cact" }, d.retry || d.reload ? retry : null, closeBtn()),
          ]);
        }
      );
    }

    /* --- 手順 1: 内容の確認 --- */
    function step1() {
      var res = S.res;
      var plan = res.plan;
      var blockers = Array.isArray(res.blockers) ? res.blockers : [];
      var ok = res.mergeable === true && !!plan && blockers.length === 0;
      var kids = [h("h2", null, "統合する ", h("span", { class: "chip " + (ok ? "c-ok" : "c-bad"), text: ok ? "統合できます" : "統合できません" }))];
      if (res.refusal) {
        var cf = Array.isArray(res.refusal.conflicts) ? res.refusal.conflicts : [];
        kids.push(h("div", { class: "alertbox bad", role: "alert" }, h("div", null, h("p", { text: String(res.refusal.message || "統合できません。") }))));
        if (cf.length) {
          kids.push(
            h(
              "ul",
              { class: "plain" },
              cf.map(function (t) {
                return h("li", null, code(String(t)));
              })
            )
          );
          kids.push(h("p", { text: "衝突の解消は pi で行ってください。" }));
        }
      }
      if (blockers.length) {
        var bl = blockers.map(function (b) {
          return h("li", { text: String(b.message || b.code) });
        });
        kids.push(h("div", { class: "alertbox bad", role: "alert" }, h("div", null, h("p", { text: "統合を進められません。" }), h("ul", { class: "plain" }, bl))));
      }
      var ta, counter, err;
      var btns = {};
      if (plan) {
        kids.push(h("ul", { class: "plain mergebr" }, oidLine("統合元", plan.source), oidLine("統合先", plan.target)));
        var fc = typeof plan.fileCount === "number" ? plan.fileCount : (plan.files || []).length;
        kids.push(h("p", { class: "mergestat" }, "コミット " + plan.commits + " 件 ・ ファイル " + fc + " 件 ・ ", PRV.size(plan.additions, plan.deletions)));
        if (plan.touchesApp) kids.push(h("p", { class: "attn", role: "status", text: "⚠ アプリ自身を変更します。統合後に再起動してください。" }));
        var risks = Array.isArray(plan.risks) ? plan.risks : [];
        if (plan.riskConfig === "unavailable") {
          kids.push(h("p", { class: "attn", role: "status", text: "⚠ リスク設定を読み込めません（リスクの有無を判定できません）。" }));
        } else if (risks.length) {
          kids.push(h("div", { class: "lbl", text: "リスクのあるパス" }));
          var rl = risks.map(function (r) {
            return h("li", null, code(String(r.path)), " ", h("span", { class: "muted small", text: String(r.reason) }));
          });
          kids.push(h("ul", { class: "plain" }, rl));
          if (plan.risksTruncated) kids.push(h("p", { class: "muted small", text: "ほかにもあります（先頭の一部だけ表示）。" }));
        } else {
          kids.push(h("p", { class: "muted small", text: "リスクのあるパスはありません。" }));
        }
        (res.warnings || []).forEach(function (w) {
          kids.push(h("p", { class: "attn", role: "status", text: "⚠ " + String(w.message || w.code) }));
        });
        var files = Array.isArray(plan.files) ? plan.files : [];
        var rest = fc - files.length;
        var fl = files.map(function (f) {
          return h("li", null, PRV.statusBadge(f.status), " ", code(String(f.path)));
        });
        if (rest > 0) fl.push(h("li", { class: "muted", text: "ほか " + rest + " 件" }));
        kids.push(h("details", { class: "mfiles" }, h("summary", { text: "変更ファイル（" + fc + " 件）" }), h("ul", { class: "plain" }, fl)));
        var d = res.defaults || {};
        var src = d.messageSource === "summary" ? "レビュー記録の下書き" : "自動生成";
        kids.push(h("div", { class: "lbl", text: "統合コミットのメッセージ（" + src + "）" }));
        if (d.summaryStale) kids.push(h("p", { class: "attn", role: "status", text: "⚠ 古い版の下書きです。内容を確認してください。" }));
        ta = h("textarea", { class: "cbox", "aria-label": "統合コミットのメッセージ" });
        ta.setAttribute("rows", "6");
        ta.value = S.message;
        counter = h("div", { class: "muted small" });
        err = h("div", { class: "formerr", role: "alert" });
        kids.push(ta, counter, err);
        var seg = h("div", { class: "seg", role: "group", "aria-label": "統合後の後始末" });
        CLEANUPS.forEach(function (c) {
          var b = h("button", { class: "btn", type: "button", "aria-pressed": "false", text: c[1] });
          b.addEventListener("click", function () {
            S.cleanup = c[0];
            S.touched = true;
            paint();
          });
          btns[c[0]] = b;
          seg.appendChild(b);
        });
        kids.push(h("div", { class: "lbl", text: "統合後の後始末" }), seg);
        kids.push(h("p", { class: "muted small", text: "作業ツリーの削除は、未コミットがあれば残します。" }));
      }
      var next = h("button", { class: "btn primary mergenext", type: "button", text: "確認へ" });
      var replan = h("button", { class: "btn", type: "button", text: "計画を取り直す" });
      replan.addEventListener("click", loadPlan);
      kids.push(h("div", { class: "cact" }, next, replan, closeBtn()));
      mount(kids);

      function paint() {
        var bad = plan ? messageError(S.message) : "";
        if (plan) {
          counter.textContent = Array.from(S.message).length + " / " + MAX + " 文字";
          err.textContent = bad;
          Object.keys(btns).forEach(function (k) {
            btns[k].setAttribute("aria-pressed", k === S.cleanup ? "true" : "false");
          });
        }
        next.disabled = !ok || !!bad;
      }
      if (ta) {
        ta.addEventListener("input", function () {
          S.message = ta.value;
          S.edited = true;
          paint();
        });
      }
      next.addEventListener("click", function () {
        if (!next.disabled) step2(plan);
      });
      paint();
    }

    /* --- 手順 2: 最終確認。ここで承認 snapshot（PR・OID・メッセージ・cleanup）を固定する --- */
    function step2(plan) {
      var snap = {
        id: S.id,
        source: plan.source.oid,
        target: plan.target.oid,
        sb: plan.source.branch,
        tb: plan.target.branch,
        message: S.message,
        cleanup: S.cleanup,
      };
      S.snap = snap;
      var lines = snap.message.split("\n");
      var shown = lines.slice(0, 3).join("\n") + (lines.length > 3 ? "\n…" : "");
      var after =
        snap.cleanup === "none"
          ? "統合後、枝と作業ツリーは残します。"
          : snap.cleanup === "branch"
            ? "統合後、枝 " + snap.sb + " を削除します（作業ツリーは残します）。"
            : "統合後、枝 " + snap.sb + " を削除し、作業ツリーも削除します（追跡ファイルの変更・未追跡のファイルがあれば残します。無視ファイルは退避してから消します）。";
      var cb = h("input", { type: "checkbox" });
      var go = h("button", { class: "btn primary mergego", type: "button", text: "統合する" });
      var status = h("p", { class: "attn", role: "status" });
      var err = h("div", { class: "formerr", role: "alert" });
      var back = h("button", { class: "btn mergebackbtn", type: "button", text: "戻る" });
      go.disabled = true;
      if (S.dead) {
        cb.disabled = true;
        err.textContent = "前回の結果により、この確認は使えません。「戻る」から計画を取り直してください。";
      }
      back.addEventListener("click", function () {
        S.snap = null;
        step1();
      });
      cb.addEventListener("change", function () {
        go.disabled = !cb.checked || S.dead || S.running;
      });
      function lock(on) {
        Array.prototype.forEach.call(sheet.querySelectorAll("button, input, textarea, select"), function (el) {
          el.disabled = on;
        });
        if (on) sheet.focus();
      }
      function failed(e) {
        var d = describe(e, false);
        if (e && (e.code === "stale_view" || e.code === "not_ff")) PRV.cache = {};
        S.dead = !d.retry;
        lock(false);
        status.textContent = "";
        cb.checked = false;
        cb.disabled = S.dead;
        go.disabled = true;
        err.replaceChildren.apply(err, d.nodes.concat([actions(d) || ""]));
      }
      go.addEventListener("click", function () {
        if (S.running || S.dead || !cb.checked || S.snap !== snap) return;
        S.running = true;
        lock(true);
        status.textContent = "統合中…（画面を閉じても処理は続きます）";
        err.replaceChildren();
        /* 送るのは、確認した時点の snapshot だけ（画面の現在値は見ない） */
        var body = { expect: { source: snap.source, target: snap.target }, message: snap.message, cleanup: snap.cleanup };
        PRV.api.merge(snap.id, body).then(
          function (res) {
            if (S.closed) return;
            S.running = false;
            if (!res || !res.merge || typeof res.merge !== "object") return failed({ network: true });
            result(res.merge);
          },
          function (e) {
            if (S.closed) return;
            S.running = false;
            failed(e);
          }
        );
      });
      var line = snap.sb + "（" + PRV.short(snap.source) + "）を " + snap.tb + "（" + PRV.short(snap.target) + "）へ merge commit で統合します。";
      mount([
        h("h2", { text: "最終確認" }),
        h("p", { class: "mergeline", text: line }),
        h("div", { class: "lbl", text: "メッセージ（先頭 3 行）" }),
        h("pre", { class: "mmsg", text: shown }),
        h("p", { text: after }),
        h("label", { class: "confirmrow" }, cb, h("span", { text: "この内容で " + snap.tb + " を更新することを確認しました" })),
        status,
        err,
        h("div", { class: "cact" }, go),
        h("div", { class: "mergeback" }, back, closeBtn()),
      ]);
    }

    /* --- 成功 --- */
    function result(m) {
      var cl = m.cleanup && Array.isArray(m.cleanup.done) ? m.cleanup.done : [];
      var deleted = cl.indexOf("branch") >= 0;
      S.done = { deleted: deleted };
      var moved = PRV.short(m.targetOld) + " → " + PRV.short(m.targetNew);
      var kids = [h("h2", { text: "統合しました" }), h("p", { class: "mergeresult" }, "統合コミット ", code(PRV.short(m.commit)), " ・ ", h("span", { class: "muted", text: moved }))];
      var asked = m.cleanup && m.cleanup.requested;
      if (asked && asked !== "none") {
        kids.push(h("p", { text: "後始末: " + (cl.length ? cl.join("・") + " を実行しました" : "実行されたものはありません") + "。" }));
      }
      (Array.isArray(m.warnings) ? m.warnings : []).forEach(function (w) {
        kids.push(h("p", { class: "attn", role: "status", text: "⚠ " + String(w) }));
      });
      if (m.recorded === false) {
        kids.push(h("p", { class: "attn", role: "alert", text: "統合は成功しました。画面用の記録は保存できませんでした。" }));
      }
      var fin = h("button", { class: "btn primary mergefinish", type: "button", text: deleted ? "一覧へ" : "最新の状態を読み込む" });
      fin.addEventListener("click", finish);
      kids.push(h("div", { class: "cact" }, fin));
      mount(kids);
    }

    PRV.openSheet(backdrop, onKey, opener, function () {
      S.closed = true;
      app.removeAttribute("inert");
    });
    app.setAttribute("inert", "");
    loadPlan();
  }

  /* 概要の「統合」カードとスマホ用の固定バー。出せないときは null */
  PRV.mergeEntry = function (ctx) {
    var pr = ctx.pr;
    if (!(ctx.caps && ctx.caps.merge && pr && pr.state === "open" && pr.target === "develop")) return null;
    function button() {
      var b = h("button", { class: "btn primary", type: "button", text: "統合する…" });
      b.addEventListener("click", function () {
        openMerge(ctx, b);
      });
      return b;
    }
    var note = "develop へ merge commit で統合します。押すと内容の確認画面が開きます（この時点では何も変わりません）。";
    var card = h("section", { class: "card mergecard" }, h("h2", { text: "統合" }), h("p", { class: "small muted", text: note }), button());
    var bar = h("div", { class: "mergebar", role: "region", "aria-label": "統合する" }, button());
    return { card: card, bar: bar };
  };
})();
