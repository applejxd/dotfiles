/* pi に依頼: カード（履歴・進行・結果）と承認シート（2 段）。起動の権限は、シートの「依頼する」の POST だけ。
   API の文字列（コメント・パス・ログ・理由）は非信頼: textContent だけで描画する。契約は docs/spec/pr-viewer.md */
(function () {
  "use strict";
  var PRV = window.PRV;
  var h = PRV.h;
  var POLL_MS = 2000;
  var POLL_MAX_MS = 10000;
  var HIST = 5;
  var LOG_KEEP = 8000;
  var FILES_SHOWN = 50;
  var UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

  var STATES = {
    starting: ["開始中", "c-info"],
    running: ["実行中", "c-info"],
    finalizing: ["仕上げ中", "c-info"],
    succeeded: ["完了", "c-ok"],
    no_change: ["変更なし", "c-mute"],
    needs_review: ["要確認", "c-warn"],
    failed: ["失敗", "c-bad"],
    timed_out: ["時間切れ", "c-bad"],
    cancelled: ["キャンセル", "c-mute"],
    interrupted: ["中断", "c-mute"],
  };
  var ACTIVE = { starting: 1, running: 1, finalizing: 1 };
  var RESULT = {
    succeeded: "pi の変更をコミットしました。",
    no_change: "変更はありませんでした。",
    needs_review: "変更は作業ツリーに残っています。commit していません。内容を確認してください。",
    failed: "失敗しました。",
    timed_out: "時間切れで止めました。",
    cancelled: "キャンセルしました。",
    interrupted: "アプリの停止で中断しました。",
  };
  var SHORT = {
    succeeded: "コミットしました",
    no_change: "変更はありませんでした",
    needs_review: "commit していません",
    failed: "失敗しました",
    timed_out: "時間切れ",
    cancelled: "キャンセルしました",
    interrupted: "中断しました",
  };
  var REASONS = {
    exit_nonzero: "pi が異常終了しました",
    output_limit: "出力が上限を超えました",
    tampered: "作業ツリーの記録が書き換えられています",
    risk_path: "保護対象のパスに触れています",
    unsupported_file: "対応していない種類のファイルがあります",
    too_many_files: "変更ファイルが多すぎます",
    too_large: "変更が大きすぎます",
    binary: "バイナリファイルがあります",
    outside: "作業ツリーの外に書き込もうとしました",
    spawn_failed: "pi を起動できませんでした",
    shutdown: "アプリの停止で中断しました",
  };
  var WHY = {
    unsupported_platform: "この環境（Linux 以外）では使えません。",
    pis_missing: "pis が見つかりません。この環境では使えません。",
  };
  var KINDS = { comment: "コメントのみ", changes: "変更を依頼", approve: "承認" };
  /* 起動の失敗: 画面に出す文言（サーバの message は、これに添えて文字として出す） */
  var BUSY = "他の依頼が実行中です。終わってからやり直してください。";
  var NOREDO = { not_found: 1, merged: 1, jobs_disabled: 1, unsupported_platform: 1, pis_missing: 1, shutting_down: 1 };
  var FAILS = {
    busy: BUSY,
    job_running: BUSY,
    merge_running: "統合が実行中です。終わってからやり直してください。",
    stale_input: "渡すコメントが変わりました。内容を取り直してください。",
    stale_view: "表示中の版から PR が更新されています。",
    nothing_to_do: "渡すコメントがありません（すでに pi が受け取っています）。",
    no_worktree: "この枝の作業ツリーが見つかりません。",
    dirty: "作業ツリーに未コミットの変更があります。",
    head_mismatch: "作業ツリーの HEAD が PR と一致しません。",
    in_progress: "作業ツリーで別の git 操作が進行中です。",
    fence_request_present: "作業ツリーに .opencode があるため実行できません。",
    external_code: "作業ツリーの設定に外部コードの実行指定があります。",
    tampered: "作業ツリーの記録が書き換えられています。確認が必要です。",
    merged: "この PR は統合済みです。",
    quota: "今日の依頼の上限に達しました。",
    too_large: "渡すコメントが大きすぎます。",
    unsupported_platform: WHY.unsupported_platform,
    pis_missing: WHY.pis_missing,
    shutting_down: "アプリが停止中です。",
    jobs_disabled: "この画面からは依頼できません。",
    not_found: "PR が見つかりません。",
  };
  var UNKNOWN = "依頼が始まったか確認できません。履歴を確認するか、再読み込みしてください。";
  /* 制御文字（\n と \t 以外）と双方向制御文字。ログは念のためサーバ側でも除去済み */
  var BAD_CHARS = /[\u0000-\u0008\u000B-\u001F\u007F-\u009F\u061C\u200E\u200F\u202A-\u202E\u2066-\u2069]/g;

  function pick(map, key, dflt) {
    return Object.prototype.hasOwnProperty.call(map, key) ? map[key] : dflt;
  }

  function code(t) {
    return h("code", { text: t });
  }

  function fmtSec(n) {
    n = Math.max(0, Math.floor(Number(n) || 0));
    return n < 60 ? n + " 秒" : Math.floor(n / 60) + " 分 " + (n % 60) + " 秒";
  }

  function validJob(j) {
    return !!j && typeof j === "object" && typeof j.id === "string" && UUID.test(j.id) && typeof j.state === "string";
  }

  function reloadAll() {
    PRV.closeSheet();
    PRV.cache = {};
    PRV.render();
  }

  function where(c) {
    var a = c.anchor;
    if (!a || typeof a.path !== "string") return "PR 全体";
    var s = a.path + ":" + a.line;
    return typeof a.lineEnd === "number" && a.lineEnd > a.line ? s + "-" + a.lineEnd : s;
  }

  function countOf(inp) {
    return inp.batches.reduce(function (n, b) {
      return n + (Array.isArray(b.comments) ? b.comments.length : 0);
    }, 0);
  }

  /* 起動の失敗の表示。{ nodes, stale, reload, list, redo } */
  function describe(e) {
    var c = (e && e.code) || "";
    var status = (e && e.status) || 0;
    var msg = (e && e.serverMessage) || "";
    var d = { nodes: [], stale: false, reload: false, list: false, redo: false };
    function p(t) {
      d.nodes.push(h("p", { text: t }));
    }
    var known = Object.prototype.hasOwnProperty.call(FAILS, c) || /^forbidden_/.test(c) || /^bad_/.test(c);
    if (!e || e.network || !c || (!known && status >= 500) || c === "internal") {
      d.reload = true;
      p(UNKNOWN);
      if (msg) p(msg);
      return d;
    }
    if (/^forbidden_/.test(c)) p(FAILS.jobs_disabled);
    else if (/^bad_/.test(c)) p("入力に誤りがあります。");
    else p(pick(FAILS, c, "依頼できませんでした。"));
    if (msg) p(msg);
    d.stale = c === "stale_view" || c === "stale_input";
    d.list = c === "not_found";
    d.redo = !pick(NOREDO, c, 0) && !/^forbidden_/.test(c);
    return d;
  }

  /* ---------------------------------------------------------------- 承認シート --- */

  /* card = { started(job) }。開いている間の状態は、このシートだけが持つ */
  function openSheet(ctx, card, opener) {
    var S = { closed: false, running: false, seq: 0, input: null };
    var sheet = h("div", { class: "sheet jobsheet", role: "dialog", "aria-modal": "true", "aria-label": "pi に依頼", tabindex: "-1" });
    var backdrop = h("div", { class: "backdrop" }, sheet);
    var app = document.getElementById("app");

    function requestClose() {
      if (!S.running) PRV.closeSheet();
    }

    function focusables() {
      return Array.prototype.filter.call(sheet.querySelectorAll("button, input, a[href]"), function (el) {
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
      var b = h("button", { class: "btn jobclose", type: "button", text: "閉じる" });
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

    function actions(d) {
      var out = [];
      function btn(text, fn) {
        var b = h("button", { class: "btn", type: "button", text: text });
        b.addEventListener("click", fn);
        out.push(b);
      }
      if (d.reload) btn("再読み込み", reloadAll);
      if (d.stale) btn("最新の版を読み込む", reloadAll);
      if (d.redo) btn("内容を取り直す", load);
      if (d.list) out.push(h("a", { class: "btn", href: "#/", text: "一覧へ" }));
      return out.length ? h("div", { class: "cact" }, out) : null;
    }

    /* --- job-input（副作用なし）の取得 --- */
    function load() {
      var n = ++S.seq;
      S.input = null;
      mount([
        h("h2", { text: "pi に依頼" }),
        h("p", { class: "muted", role: "status", text: "渡す内容を確認中…" }),
        h("div", { class: "cact" }, closeBtn()),
      ]);
      PRV.api.jobInput(ctx.id).then(
        function (res) {
          if (S.closed || n !== S.seq) return;
          var inp = res && res.input;
          if (!inp || !Array.isArray(inp.batches) || !Array.isArray(inp.blockers) || typeof inp.inputDigest !== "string") {
            return fail({ network: true });
          }
          S.input = inp;
          step1(inp);
        },
        function (e) {
          if (!S.closed && n === S.seq) fail(e);
        }
      );
    }

    function fail(e) {
      var d = describe(e);
      d.redo = true;
      d.reload = false;
      mount([
        h("h2", { text: "pi に依頼" }),
        h("div", { class: "formerr", role: "alert" }, d.nodes),
        actions(d),
        h("div", { class: "cact" }, closeBtn()),
      ]);
    }

    function minutes(inp) {
      var n = inp.notice && inp.notice.timeoutMin;
      var lim = ctx.caps && ctx.caps.jobLimits && ctx.caps.jobLimits.timeoutMin;
      return typeof n === "number" ? n : typeof lim === "number" ? lim : null;
    }

    function noticeList(inp) {
      var m = minutes(inp);
      return h(
        "ul",
        { class: "plain jobnotice" },
        h("li", { text: "サンドボックス内で実行します。" }),
        h("li", { text: m === null ? "時間の上限で止めます。" : "上限 " + m + " 分で止めます。" }),
        h("li", { text: "書き込むのはこの作業ツリーだけです。" }),
        h("li", { text: "commit はアプリが行います（pi は commit しません）。" })
      );
    }

    /* --- 手順 1: 渡す内容の確認 --- */
    function step1(inp) {
      var n = countOf(inp);
      var blockers = inp.blockers.map(function (b) {
        return h("li", { text: String((b && (b.message || b.code)) || "") });
      });
      var odd = !inp.notice || inp.notice.writes !== "worktree" || inp.notice.commit !== "app";
      if (odd) blockers.push(h("li", { text: "想定と異なる実行条件のため、依頼できません。" }));
      var ok = blockers.length === 0 && n > 0;
      var kids = [h("h2", null, "pi に依頼 ", h("span", { class: "chip " + (ok ? "c-ok" : "c-bad"), text: ok ? "依頼できます" : "依頼できません" }))];
      if (blockers.length) {
        var box = h("div", null, h("p", { text: "依頼を進められません。" }), h("ul", { class: "plain" }, blockers));
        kids.push(h("div", { class: "alertbox bad", role: "alert" }, box));
      }
      if (n === 0) kids.push(h("p", { class: "attn", role: "status", text: "渡すコメントがありません。" }));
      kids.push(h("p", { class: "jobcount", text: "渡すコメント: " + n + " 件（" + inp.batches.length + " 回の送信）" }));
      inp.batches.forEach(function (b) {
        var cs = Array.isArray(b.comments) ? b.comments : [];
        kids.push(h("div", { class: "lbl" }, "送信: " + pick(KINDS, b.kind, String(b.kind)) + " ・ " + PRV.ago(b.at)));
        kids.push(
          h(
            "ul",
            { class: "plain jobcomments" },
            cs.map(function (c) {
              var who = h("span", { class: "muted", text: String(c.by) + " ・ " + PRV.ago(c.at) });
              return h(
                "li",
                { class: "jobcm" },
                h("div", { class: "small" }, code(where(c)), " ", who),
                h("div", { class: "cbody", text: String(c.body) })
              );
            })
          )
        );
      });
      kids.push(h("div", { class: "lbl", text: "実行の条件" }), noticeList(inp));
      var next = h("button", { class: "btn primary jobnext", type: "button", text: "確認へ" });
      next.disabled = !ok;
      next.addEventListener("click", function () {
        if (ok) step2(inp, n);
      });
      kids.push(h("div", { class: "cact" }, next, closeBtn()));
      mount(kids);
    }

    /* --- 手順 2: 最終確認。ここで送る内容（版・batch・digest）を固定する --- */
    function step2(inp, n) {
      var snap = {
        expect: { source: ctx.pr.sourceOid, target: ctx.pr.targetOid },
        batches: inp.batches.map(function (b) {
          return b.batchId;
        }),
        inputDigest: inp.inputDigest,
      };
      var cb = h("input", { type: "checkbox" });
      var go = h("button", { class: "btn primary jobgo", type: "button", text: "依頼する" });
      var status = h("p", { class: "attn", role: "status" });
      var err = h("div", { class: "formerr", role: "alert" });
      var back = h("button", { class: "btn", type: "button", text: "戻る" });
      go.disabled = true;
      back.addEventListener("click", function () {
        step1(inp);
      });
      cb.addEventListener("change", function () {
        go.disabled = !cb.checked || S.running;
      });
      function lock(on) {
        Array.prototype.forEach.call(sheet.querySelectorAll("button, input"), function (el) {
          el.disabled = on;
        });
        if (on) sheet.focus();
      }
      function failed(e) {
        var d = describe(e);
        if (d.stale) PRV.cache = {};
        lock(false);
        status.textContent = "";
        cb.checked = false;
        cb.disabled = true;
        go.disabled = true;
        err.replaceChildren.apply(err, d.nodes.concat([actions(d) || ""]));
      }
      go.addEventListener("click", function () {
        if (S.running || !cb.checked) return;
        S.running = true;
        lock(true);
        status.textContent = "依頼しています…（画面を閉じても処理は続きます）";
        err.replaceChildren();
        PRV.api.jobStart(ctx.id, snap).then(
          function (res) {
            if (S.closed) return;
            S.running = false;
            if (!res || !validJob(res.job)) return failed({ network: true });
            card.started(res.job);
            PRV.closeSheet();
          },
          function (e) {
            if (S.closed) return;
            S.running = false;
            failed(e);
          }
        );
      });
      mount([
        h("h2", { text: "最終確認" }),
        h("p", {
          class: "jobline",
          text: "コメント " + n + " 件（" + inp.batches.length + " 回の送信）を pi に渡し、" + ctx.pr.branch + " の作業ツリーの修正を依頼します。",
        }),
        noticeList(inp),
        h("label", { class: "confirmrow" }, cb, h("span", { text: "この内容で pi に依頼することを確認しました" })),
        status,
        err,
        h("div", { class: "cact" }, go),
        h("div", { class: "mergeback" }, back, closeBtn()),
      ]);
    }

    PRV.openSheet(backdrop, onKey, opener, function () {
      S.closed = true;
      app.removeAttribute("inert");
    });
    app.setAttribute("inert", "");
    load();
  }

  /* ---------------------------------------------------------- カード（進行・結果・履歴） --- */

  /* 概要の「pi に依頼」カード。出せないとき（統合済み・jobs が無効で理由も無い）は null */
  PRV.jobEntry = function (ctx) {
    var pr = ctx.pr;
    var caps = ctx.caps || {};
    if (!(pr && pr.state === "open") || !(caps.jobs || caps.jobsReason)) return null;
    var card = h("section", { class: "card jobcard" }, h("h2", { text: "pi に依頼" }));
    if (!caps.jobs) {
      card.appendChild(h("p", { class: "attn small jobreason", role: "status", text: pick(WHY, caps.jobsReason, "使えません。") }));
      return card;
    }
    var S = {
      id: ctx.id,
      tok: PRV.token,
      cur: null,
      jobs: [],
      hist: "loading",
      log: "",
      next: 0,
      trunc: false,
      timer: null,
      fails: 0,
      pollErr: "",
      cancelErr: "",
      cancelling: false,
    };
    var startBtn = h("button", { class: "btn primary jobstart", type: "button", text: "変更を依頼…" });
    var panel = h("div", { class: "jobpanel" });
    var hist = h("div", { class: "jobhistbox" });
    var logEl = h("pre", { class: "joblog", tabindex: "0", "aria-label": "pi の出力（末尾）" });
    var note = "まだ pi が受け取っていないレビューコメントを渡し、この PR の作業ツリーの修正を依頼します。押すと内容の確認画面が開きます（この時点では何も変わりません）。";
    card.appendChild(h("p", { class: "small muted", text: note }));
    card.appendChild(startBtn);
    card.appendChild(panel);
    card.appendChild(hist);

    function alive() {
      return card.isConnected && PRV.token === S.tok;
    }

    function active() {
      return !!(S.cur && pick(ACTIVE, S.cur.state, 0));
    }

    function adopt(job) {
      var at = -1;
      S.jobs.forEach(function (j, i) {
        if (j.id === job.id) at = i;
      });
      if (at >= 0) S.jobs[at] = job;
      else S.jobs.unshift(job);
      if (S.cur && S.cur.id === job.id) S.cur = job;
    }

    /* --- 履歴: 直近 5 件 --- */
    function paintHist() {
      var kids = [h("div", { class: "lbl", text: "履歴（直近 " + HIST + " 件）" })];
      if (S.hist === "loading") kids.push(h("p", { class: "muted small", role: "status", text: "読み込み中…" }));
      else if (S.hist === "fail") kids.push(h("p", { class: "attn small", role: "status", text: "履歴を取得できません。" }));
      else if (!S.jobs.length) kids.push(h("p", { class: "muted small", text: "まだ依頼はありません。" }));
      else {
        var rows = S.jobs.slice(0, HIST).map(function (j) {
          var st = pick(STATES, j.state, [String(j.state), "c-mute"]);
          return h(
            "li",
            null,
            h("span", { class: "chip " + st[1], text: st[0] }),
            " ",
            h("span", { class: "muted small", text: PRV.ago(j.createdAt) }),
            pick(SHORT, j.state, "") ? " ・ " + SHORT[j.state] : null,
            typeof j.resultOid === "string" && j.resultOid ? [" ・ ", code(PRV.short(j.resultOid))] : null
          );
        });
        kids.push(h("ul", { class: "plain jobhist" }, rows));
      }
      hist.replaceChildren.apply(hist, kids);
    }

    /* --- 進行・結果 --- */
    function paintPanel() {
      startBtn.disabled = active();
      var j = S.cur;
      if (!j) {
        panel.replaceChildren();
        return;
      }
      var keepTop = logEl.scrollTop;
      var atEnd = logEl.scrollTop + logEl.clientHeight >= logEl.scrollHeight - 4;
      var st = pick(STATES, j.state, [String(j.state), "c-mute"]);
      var on = !!pick(ACTIVE, j.state, 0);
      var head = [
        h("span", { class: "chip jobstate " + st[1], text: st[0] }),
        " ",
        h("span", { class: "muted small jobelapsed", text: (on ? "経過 " : "所要 ") + fmtSec(j.elapsedSec) }),
      ];
      var kids = [h("div", { class: "jobhead" }, head)];
      if (on) {
        var cancel = h("button", { class: "btn jobcancel", type: "button", text: "キャンセル" });
        cancel.disabled = j.state === "finalizing" || S.cancelling;
        cancel.addEventListener("click", doCancel);
        kids[0].appendChild(cancel);
        if (j.state === "finalizing") kids.push(h("p", { class: "muted small", text: "仕上げ中は止められません。" }));
      } else {
        var res = pick(RESULT, j.state, "");
        var oid = typeof j.resultOid === "string" && j.resultOid ? [" commit ", code(PRV.short(j.resultOid))] : null;
        kids.push(h("p", { class: "jobresult" }, res, oid));
        var rs = Array.isArray(j.reasons) ? j.reasons : [];
        if (rs.length) {
          kids.push(
            h(
              "ul",
              { class: "plain jobreasons" },
              rs.map(function (r) {
                return h("li", { class: "attn", text: String(pick(REASONS, r, r)) });
              })
            )
          );
        }
        var fs = Array.isArray(j.files) ? j.files : [];
        if (fs.length) {
          var li = fs.slice(0, FILES_SHOWN).map(function (f) {
            return h("li", null, PRV.statusBadge(String(f.status)), " ", code(String(f.path)));
          });
          if (fs.length > FILES_SHOWN) li.push(h("li", { class: "muted", text: "ほか " + (fs.length - FILES_SHOWN) + " 件" }));
          kids.push(h("div", { class: "lbl", text: "変更されたファイル（" + fs.length + " 件）" }), h("ul", { class: "plain jobfiles" }, li));
        }
      }
      if (S.pollErr) kids.push(h("p", { class: "attn small", role: "status", text: S.pollErr }));
      if (on || S.log) {
        logEl.textContent = S.log || "（出力はまだありません）";
        kids.push(logEl);
        if (S.trunc) kids.push(h("p", { class: "muted small", text: "出力が長いため、途中を省略しています。" }));
      }
      kids.push(h("div", { class: "formerr", role: "alert", text: S.cancelErr }));
      if (!on) {
        var rl = h("button", { class: "btn jobreload", type: "button", text: "最新を読み込む" });
        rl.addEventListener("click", function () {
          PRV.cache = {};
          PRV.render();
        });
        kids.push(h("div", { class: "cact" }, rl));
      }
      panel.replaceChildren(h("div", { class: "jobrun" }, kids));
      logEl.scrollTop = atEnd ? logEl.scrollHeight : keepTop;
    }

    function paint() {
      paintPanel();
      paintHist();
    }

    /* --- polling（2 秒間隔。画面を離れる・カードが消えると止める） --- */
    function schedule(ms) {
      if (S.timer) clearTimeout(S.timer);
      S.timer = setTimeout(tick, ms);
    }

    function tick() {
      S.timer = null;
      if (!alive() || !active()) return;
      if (document.visibilityState !== "visible") return schedule(POLL_MS);
      var cur = S.cur;
      PRV.api.job(S.id, cur.id, S.next).then(
        function (res) {
          if (!alive() || !S.cur || S.cur.id !== cur.id) return;
          var j = res && res.job;
          var lg = res && res.log;
          if (!validJob(j) || !lg || typeof lg.text !== "string" || typeof lg.next !== "number") return onPollError({ network: true });
          S.fails = 0;
          S.pollErr = "";
          var text = lg.text.replace(BAD_CHARS, "");
          S.log = ((lg.from === S.next ? S.log : "") + text).slice(-LOG_KEEP);
          S.next = lg.next;
          S.trunc = lg.truncated === true;
          adopt(j);
          paint();
          if (active()) schedule(POLL_MS);
        },
        function (e) {
          if (alive() && S.cur && S.cur.id === cur.id) onPollError(e);
        }
      );
    }

    function onPollError(e) {
      if (e && e.code === "not_found") {
        S.pollErr = "この依頼の状態を取得できません。再読み込みしてください。";
        paint();
        return;
      }
      S.fails += 1;
      S.pollErr = "状態を取得できません（自動で再試行します）。";
      paint();
      schedule(Math.min(POLL_MS * Math.pow(2, S.fails), POLL_MAX_MS));
    }

    function doCancel() {
      if (!S.cur || S.cancelling || S.cur.state === "finalizing") return;
      var cur = S.cur;
      S.cancelling = true;
      S.cancelErr = "";
      paint();
      PRV.api.jobCancel(S.id, cur.id).then(
        function (res) {
          S.cancelling = false;
          if (!alive() || !S.cur || S.cur.id !== cur.id) return;
          if (res && validJob(res.job)) adopt(res.job);
          paint();
          if (active()) schedule(0);
        },
        function (e) {
          S.cancelling = false;
          if (!alive()) return;
          S.cancelErr = "キャンセルできませんでした。" + ((e && e.serverMessage) || "");
          paint();
        }
      );
    }

    startBtn.addEventListener("click", function () {
      openSheet(
        ctx,
        {
          started: function (job) {
            S.cur = job;
            S.log = "";
            S.next = 0;
            S.trunc = false;
            S.pollErr = "";
            S.cancelErr = "";
            S.hist = "ok";
            adopt(job);
            paint();
            schedule(POLL_MS);
          },
        },
        startBtn
      );
    });

    paint();
    PRV.api.jobs(S.id).then(
      function (res) {
        if (!alive()) return;
        var list = res && Array.isArray(res.jobs) ? res.jobs.filter(validJob) : [];
        /* 新しい順。進行中に同じ job を取り直したとき、手元の新しい状態を上書きしない */
        list.sort(function (a, b) {
          return (Date.parse(b.createdAt) || 0) - (Date.parse(a.createdAt) || 0);
        });
        S.jobs = list;
        if (S.cur) adopt(S.cur); /* 一覧の応答より先に起動した依頼を落とさない */
        S.hist = "ok";
        if (!S.cur) {
          var run = list.filter(function (j) {
            return pick(ACTIVE, j.state, 0);
          })[0];
          if (run) {
            S.cur = run;
            schedule(0);
          }
        }
        paint();
      },
      function () {
        if (!alive()) return;
        S.hist = "fail";
        paint();
      }
    );
    return card;
  };
})();
