/* 起票する: 承認シート（入力 → 確認 → 結果）。押下の POST で、アプリが feature の枝と作業ツリーと依頼文（brief）を作る。契約は docs/spec/pr-viewer.md */
(function () {
  "use strict";
  var PRV = window.PRV;
  var h = PRV.h;
  /* 上限はサーバ（review-log.ts の BRIEF_LIMITS）と同じ。文字数はコードポイント */
  var LIM = { title: 100, goal: 1500, constraints: 1500, acceptance: 800, scopeItems: 20, scopeItem: 120, total: 4000 };
  var NAME_RE = /^[a-z0-9][a-z0-9._-]{0,63}$/;
  var RESERVED = /^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])$/;
  var BIDI = "\\u061c\\u200e\\u200f\\u202a-\\u202e\\u2066-\\u2069\\u2028\\u2029";
  var BAD_SINGLE = new RegExp("[\\u0000-\\u001f\\u007f-\\u009f" + BIDI + "]");
  var BAD_MULTI = new RegExp("[\\u0000-\\u0008\\u000b-\\u001f\\u007f-\\u009f" + BIDI + "]");
  var LONE = /[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/;
  /* 秘密らしい文字列（サーバの SECRET_PATTERNS と同じ種類。値は表示しない） */
  var SECRETS = [
    ["private_key", /-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----/],
    ["aws_key", /\b(?:AKIA|ASIA)[0-9A-Z]{16}\b/],
    ["github_token", /\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})/],
    ["slack_token", /\bxox[abprs]-[A-Za-z0-9-]{10,}/],
    ["bearer", /\bbearer\s+[A-Za-z0-9._~+/=-]{16,}/i],
    ["jwt", /\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}/],
    ["url_userinfo", /\b[a-z][a-z0-9+.-]*:\/\/[^/\s:@]+:[^/\s@]+@/i],
    ["password", /\b(?:password|passwd|pwd)\s*=\s*[^\s"']{4,}/i],
  ];
  var DRAFT = "prv.create.draft";
  var NOTE = "公開リポジトリに書けない内容（秘密・組織の具体）は書かない。書いた内容は LLM と worktree に届く。";
  var UNKNOWN = "結果を確認できません。一覧を再読み込みして、同じ名前の PR ができていないか確認してください。";
  var FIELDS = ["name", "title", "goal", "constraints", "scope", "acceptance"];

  function cp(s) {
    return Array.from(s).length;
  }

  function nameError(v) {
    if (v === "") return "名前を入力してください。";
    if (!NAME_RE.test(v)) return "名前は小文字・数字・. _ - だけ（先頭は英数字、64 字まで）です。";
    if (v.indexOf("..") >= 0 || /\.$|\.lock$|\.git$/.test(v)) return "名前の末尾に . .lock .git は使えません。また .. も使えません。";
    if (RESERVED.test(v.split(".")[0])) return "予約された名前（con・nul・com1 など）は使えません。";
    return "";
  }

  function textError(v, multi, max, label) {
    if ((multi ? BAD_MULTI : BAD_SINGLE).test(v) || LONE.test(v)) return label + "に使えない文字（制御文字・双方向制御文字など）があります。";
    if (cp(v) > max) return label + "は " + max + " 文字までです（現在 " + cp(v) + " 文字）。";
    return "";
  }

  function scopeLines(v) {
    return v
      .replace(/\r\n/g, "\n")
      .split("\n")
      .map(function (s) {
        return s.trim();
      })
      .filter(Boolean);
  }

  /* 入力欄の値 → 送る brief・欄ごとの誤り・秘密の種類。誤りが無ければ ok */
  function evaluate(S) {
    var err = {};
    var brief = {
      title: S.title.trim(),
      goal: S.goal.replace(/\r\n/g, "\n").trim(),
      constraints: S.constraints.replace(/\r\n/g, "\n").trim(),
      acceptance: S.acceptance.replace(/\r\n/g, "\n").trim(),
      scope: scopeLines(S.scope),
    };
    err.name = nameError(S.name);
    err.title = brief.title === "" ? (S.touched.title ? "題名は必須です。" : "-") : textError(brief.title, false, LIM.title, "題名");
    err.goal = brief.goal === "" ? (S.touched.goal ? "目的は必須です。" : "-") : textError(brief.goal, true, LIM.goal, "目的");
    err.constraints = textError(brief.constraints, true, LIM.constraints, "守る条件");
    err.acceptance = textError(brief.acceptance, true, LIM.acceptance, "完了条件");
    var sc = "";
    if (brief.scope.length > LIM.scopeItems) sc = "担当範囲は " + LIM.scopeItems + " 行までです（現在 " + brief.scope.length + " 行）。";
    brief.scope.forEach(function (s) {
      if (sc) return;
      sc = textError(s, false, LIM.scopeItem, "担当範囲の各行");
      if (!sc && (/^[\\/]/.test(s) || /^[A-Za-z]:/.test(s) || s.split(/[\\/]/).indexOf("..") >= 0)) sc = "担当範囲はリポジトリ内の相対パスで書いてください。";
    });
    err.scope = sc;
    var total = cp(brief.title) + cp(brief.goal) + cp(brief.constraints) + cp(brief.acceptance) + brief.scope.reduce(function (n, s) { return n + cp(s); }, 0);
    err.total = total > LIM.total ? "合計は " + LIM.total + " 文字までです（現在 " + total + " 文字）。" : "";
    var all = [brief.title, brief.goal, brief.constraints, brief.acceptance].concat(brief.scope).join("\n");
    var secrets = SECRETS.filter(function (p) {
      return p[1].test(all);
    }).map(function (p) {
      return p[0];
    });
    err.secret = secrets.length ? "秘密らしい文字列が含まれています（種類: " + secrets.join(", ") + "）。取り除いてください。" : "";
    var ok = FIELDS.concat(["total", "secret"]).every(function (k) {
      return !err[k];
    });
    return { brief: brief, err: err, total: total, ok: ok };
  }

  /* 依頼文の全文（確認画面の表示と「コピー」に使う。サーバが記録する内容と同じ） */
  function briefText(b) {
    var out = ["# " + b.title, "", "## 目的", b.goal];
    if (b.constraints) out.push("", "## 守る条件", b.constraints);
    if (b.scope.length) out.push("", "## 担当範囲", b.scope.map(function (s) { return "- " + s; }).join("\n"));
    if (b.acceptance) out.push("", "## 完了条件", b.acceptance);
    return out.join("\n");
  }

  function uuid() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    var b = new Uint8Array(16);
    crypto.getRandomValues(b);
    b[6] = (b[6] & 15) | 64;
    b[8] = (b[8] & 63) | 128;
    var x = Array.prototype.map.call(b, function (v) {
      return (v + 256).toString(16).slice(1);
    }).join("");
    return x.slice(0, 8) + "-" + x.slice(8, 12) + "-" + x.slice(12, 16) + "-" + x.slice(16, 20) + "-" + x.slice(20);
  }

  function loadDraft() {
    try {
      var d = JSON.parse(sessionStorage.getItem(DRAFT) || "null");
      return d && typeof d === "object" ? d : {};
    } catch (e) {
      return {};
    }
  }

  function saveDraft(S) {
    try {
      var d = { repoId: S.repoId, rid: S.rid, ridKey: S.ridKey };
      FIELDS.forEach(function (k) {
        d[k] = S[k];
      });
      sessionStorage.setItem(DRAFT, JSON.stringify(d));
    } catch (e) {}
  }

  function clearDraft() {
    try {
      sessionStorage.removeItem(DRAFT);
    } catch (e) {}
  }

  function code(t) {
    return h("code", { text: t });
  }

  /* 失敗の表示。to: 戻る先（"form" 入力 / "confirm" 確認 / "none"）。resend: 同じ依頼として再送してよい */
  function describe(e) {
    var c = (e && e.code) || "";
    var status = (e && e.status) || 0;
    var msg = (e && e.serverMessage) || "";
    var d = { text: "", msg: msg, to: "confirm", resend: false, reload: false, stale: false };
    if (!e || e.network || !c || status >= 500 || c === "create_failed" || c === "internal") {
      if (c === "create_partial") {
        d.text = "起票の途中で止まりました。枝・作業ツリー・依頼文の記録が一部だけ残っている可能性があります。画面からは続けられません。";
        d.to = "none";
        d.reload = true;
      } else if (c === "shutting_down") {
        d.text = "サーバが停止中です。しばらくしてから再試行してください。";
        d.resend = true;
      } else {
        d.text = UNKNOWN;
        d.resend = true;
        d.reload = true;
      }
      return d;
    }
    var T = {
      create_disabled: "この画面からは起票できません（サーバが起票を許可していません）。",
      forbidden_funnel: "この接続（公開経由）からは起票できません。",
      forbidden_origin: "この接続元からは起票できません。",
      bad_name: "名前が正しくありません。",
      bad_brief: "依頼文の形が正しくありません。",
      brief_too_large: "依頼文が上限（字数・件数・サイズ）を超えています。",
      secret_like: "秘密らしい文字列が含まれています。取り除いてから、もう一度送ってください。",
      name_used: "その名前は既に使われています（枝・作業ツリー・記録のどれか）。別の名前にしてください。",
      busy: "別の起票が実行中です。しばらくして再試行してください。",
      stale_view: "develop が更新されました。最新の基点を読み込んで、内容を確認し直してください。",
      too_large: "本文が大きすぎます。",
      not_found: "リポジトリが見つかりません。画面を再読み込みしてください。",
      unsupported_repo: "このリポジトリには起票できません。",
      bad_layout: "このリポジトリの作業ツリーの配置では起票できません。",
      external_code: "このリポジトリは外部コードの設定があるため起票できません。",
      worktree_registered: "同じ場所に作業ツリーが既に登録されています。別の名前にしてください。",
      limit: "起票の上限に達しています。",
    };
    d.text = T[c] || (/^bad_/.test(c) ? "入力に誤りがあります。" : "起票できませんでした。");
    if (c === "bad_name" || c === "name_used" || c === "worktree_registered" || c === "bad_brief" || c === "brief_too_large" || c === "secret_like") d.to = "form";
    if (c === "stale_view") d.stale = true;
    if (c === "busy" || c === "too_large") d.resend = true;
    if (/^bad_(request|kind|expect)/.test(c) || c === "not_found") d.reload = true;
    /* secret_like の message は種類だけ（本文は含まれない）。そのほかも、サーバの文言は textContent で足す */
    return d;
  }

  function openCreate(ctx, opener) {
    var repos = ctx.repos;
    var dr = loadDraft();
    var S = { closed: false, running: false, done: false, step: "form", touched: {}, notice: "", snap: null };
    var pick = repos.filter(function (r) { return r.repoId === dr.repoId; })[0] || repos[0];
    S.repoId = pick.repoId;
    FIELDS.forEach(function (k) {
      S[k] = typeof dr[k] === "string" ? dr[k] : "";
    });
    S.rid = typeof dr.rid === "string" ? dr.rid : "";
    S.ridKey = typeof dr.ridKey === "string" ? dr.ridKey : "";
    var sheet = h("div", { class: "sheet mergesheet createsheet", role: "dialog", "aria-modal": "true", "aria-label": "起票する", tabindex: "-1" });
    var backdrop = h("div", { class: "backdrop" }, sheet);
    var app = document.getElementById("app");

    function repo() {
      return repos.filter(function (r) { return r.repoId === S.repoId; })[0] || repos[0];
    }

    function requestClose() {
      if (S.running) return;
      if (S.done) return finish(null);
      PRV.closeSheet();
    }

    function finish(hash) {
      PRV.closeSheet();
      PRV.cache = {};
      if (hash) location.hash = hash;
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
      var b = h("button", { class: "btn createclose", type: "button", text: "閉じる" });
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

    /* --- 手順 1: 入力 --- */
    function form(focusName) {
      S.step = "form";
      var el = {};
      var kids = [h("h2", { text: "起票する" })];
      if (S.notice) kids.push(h("p", { class: "attn", role: "status", text: S.notice }));
      var rp;
      if (repos.length > 1) {
        el.repo = h("select", { "aria-label": "リポジトリ" });
        repos.forEach(function (r) {
          var o = h("option", { text: r.name });
          o.value = r.repoId;
          el.repo.appendChild(o);
        });
        el.repo.value = S.repoId;
        el.repo.addEventListener("change", function () {
          S.repoId = el.repo.value;
          paint();
        });
        rp = h("label", { class: "field" }, h("span", { class: "lbl", text: "リポジトリ" }), el.repo);
      } else {
        rp = h("p", { class: "muted small" }, "リポジトリ: ", code(repo().name));
      }
      kids.push(rp);
      var slots = {};
      function field(key, label, node, hint) {
        node.value = S[key];
        node.addEventListener("input", function () {
          S[key] = node.value;
          S.touched[key] = true;
          paint();
        });
        el[key] = node;
        slots[key] = { cnt: h("div", { class: "muted small" }), err: h("div", { class: "formerr", role: "alert" }) };
        kids.push(
          h(
            "div",
            { class: "field" },
            h("label", { class: "field" }, h("span", { class: "lbl", text: label }), node),
            hint ? h("span", { class: "muted small", text: hint }) : null,
            slots[key].cnt,
            slots[key].err
          )
        );
      }
      function area(key, rows) {
        var t = h("textarea", { class: "cbox" });
        t.setAttribute("rows", String(rows));
        return t;
      }
      var nm = h("input", { type: "text", class: "cbox createname" });
      nm.setAttribute("autocapitalize", "none");
      nm.setAttribute("autocorrect", "off");
      nm.setAttribute("autocomplete", "off");
      nm.setAttribute("spellcheck", "false");
      nm.setAttribute("inputmode", "text");
      nm.setAttribute("maxlength", "80");
      field("name", "名前（枝名・作業ツリー名）", nm, "小文字・数字・. _ - だけ。");
      var pv = h("div", { class: "createpreview muted small" });
      kids.push(pv);
      var ti = h("input", { type: "text", class: "cbox" });
      ti.setAttribute("autocomplete", "off");
      field("title", "題名", ti);
      field("goal", "目的", area("goal", 4));
      field("constraints", "守る条件（任意）", area("constraints", 3));
      field("scope", "担当範囲（任意。1 行に 1 つの glob）", area("scope", 3), "例: apps/pr-viewer/**");
      field("acceptance", "完了条件（任意）", area("acceptance", 3));
      var total = h("div", { class: "muted small createtotal" });
      var secret = h("div", { class: "formerr", role: "alert" });
      kids.push(total, secret, h("p", { class: "sheetnote createnote", text: NOTE }));
      var next = h("button", { class: "btn primary createnext", type: "button", text: "確認へ" });
      kids.push(h("div", { class: "cact" }, next, closeBtn()));
      mount(kids);
      var LABELS = { title: LIM.title, goal: LIM.goal, constraints: LIM.constraints, acceptance: LIM.acceptance };

      function paint() {
        var r = evaluate(S);
        FIELDS.forEach(function (k) {
          var e = r.err[k] === "-" ? "" : r.err[k];
          slots[k].err.textContent = e;
          el[k].setAttribute("aria-invalid", e ? "true" : "false");
        });
        Object.keys(LABELS).forEach(function (k) {
          slots[k].cnt.textContent = cp(S[k].trim()) + " / " + LABELS[k] + " 文字";
        });
        slots.name.cnt.textContent = cp(S.name) + " / 64 文字";
        slots.scope.cnt.textContent = r.brief.scope.length + " / " + LIM.scopeItems + " 行";
        total.textContent = "合計 " + r.total + " / " + LIM.total + " 文字" + (r.err.total ? "。" + r.err.total : "");
        total.className = r.err.total ? "formerr createtotal" : "muted small createtotal";
        secret.textContent = r.err.secret;
        var n = S.name;
        pv.replaceChildren(
          h("div", null, "枝: ", code("feature/" + (n || "<名前>"))),
          h("div", null, "作業ツリー: ", code(".tmp/worktrees/" + (n || "<名前>") + "/"))
        );
        next.disabled = !r.ok;
        saveDraft(S);
      }
      next.addEventListener("click", function () {
        if (!next.disabled) confirmStep();
      });
      paint();
      if (focusName && el[focusName]) el[focusName].focus();
    }

    /* --- 手順 2: 確認。ここで送る内容（snapshot）を固定する --- */
    function confirmStep() {
      var r = evaluate(S);
      if (!r.ok) return form();
      var rp = repo();
      var oid = String(rp.targetOid || "");
      var valid = /^[0-9a-f]{40}$/.test(oid);
      var snap = { repoId: rp.repoId, repoName: rp.name, name: S.name, oid: oid, brief: r.brief, text: briefText(r.brief) };
      var key = JSON.stringify([snap.repoId, snap.name, snap.oid, snap.brief]);
      if (!S.rid || S.ridKey !== key) {
        S.rid = uuid(); /* 内容が変わったら別の依頼。同じ内容の再送は、同じ requestId で冪等にする */
        S.ridKey = key;
      }
      snap.rid = S.rid;
      S.snap = snap;
      S.notice = "";
      S.step = "confirm";
      saveDraft(S);
      var cb = h("input", { type: "checkbox" });
      var go = h("button", { class: "btn primary createsubmit", type: "button", text: "起票する" });
      var status = h("p", { class: "attn", role: "status" });
      var errBox = h("div", { class: "formerr", role: "alert" });
      var back = h("button", { class: "btn createbackbtn", type: "button", text: "戻る" });
      go.disabled = true;
      if (!valid) {
        cb.disabled = true;
        errBox.textContent = "基点（develop）の版を取得できません。再読み込みしてください。";
      }
      back.addEventListener("click", function () {
        S.snap = null;
        form();
      });
      cb.addEventListener("change", function () {
        go.disabled = !cb.checked || S.running;
      });
      function lock(on) {
        Array.prototype.forEach.call(sheet.querySelectorAll("button, input, textarea, select"), function (e) {
          e.disabled = on;
        });
        if (on) sheet.focus();
      }
      function failed(e) {
        var d = describe(e);
        S.running = false;
        lock(false);
        status.textContent = "";
        cb.checked = false;
        go.disabled = true;
        var kids = [h("p", { text: d.text })];
        if (d.msg && d.msg !== d.text) kids.push(h("p", { class: "small", text: d.msg }));
        var acts = [];
        if (d.stale) {
          var sb = h("button", { class: "btn", type: "button", text: "最新の基点を読み込む" });
          sb.addEventListener("click", function () {
            reloadBase(sb);
          });
          acts.push(sb);
        }
        if (d.to === "form") {
          var fb = h("button", { class: "btn", type: "button", text: "入力に戻って直す" });
          fb.addEventListener("click", function () {
            form(d.to === "form" && e && e.code === "name_used" ? "name" : null);
          });
          acts.push(fb);
        }
        if (d.reload) {
          var rb = h("button", { class: "btn", type: "button", text: "再読み込み" });
          rb.addEventListener("click", function () {
            finish(null);
          });
          acts.push(rb);
        }
        if (d.to === "none") {
          cb.disabled = true;
          snapDead = true;
        }
        if (acts.length) kids.push(h("div", { class: "cact" }, acts));
        errBox.replaceChildren.apply(errBox, kids);
      }
      var snapDead = false;
      go.addEventListener("click", function () {
        if (S.running || snapDead || !cb.checked || S.snap !== snap) return;
        S.running = true;
        lock(true);
        status.textContent = "起票中…（画面を閉じても処理は続きます）";
        errBox.replaceChildren();
        var b = { title: snap.brief.title, goal: snap.brief.goal };
        if (snap.brief.constraints) b.constraints = snap.brief.constraints;
        if (snap.brief.scope.length) b.scope = snap.brief.scope;
        if (snap.brief.acceptance) b.acceptance = snap.brief.acceptance;
        /* 送るのは、確認した時点の snapshot だけ（画面の現在値は見ない） */
        PRV.api.createFeature(snap.repoId, { name: snap.name, requestId: snap.rid, target: snap.oid, brief: b }).then(
          function (res) {
            if (S.closed) return;
            S.running = false;
            if (!res || !res.feature || typeof res.feature !== "object") return failed({ network: true });
            result(snap, res.feature);
          },
          function (e) {
            if (S.closed) return;
            failed(e);
          }
        );
      });
      var line = snap.repoName + " に feature/" + snap.name + " を作ります。基点は develop@" + (valid ? PRV.short(oid) : "?") + " です。";
      var full = h("pre", { class: "mmsg createtext" });
      full.textContent = snap.text;
      mount([
        h("h2", { text: "起票の確認" }),
        h("p", { class: "mergeline", text: line }),
        h("ul", { class: "plain mergebr" }, h("li", null, h("span", { class: "k", text: "枝" }), " ", code("feature/" + snap.name)), h("li", null, h("span", { class: "k", text: "作業ツリー" }), " ", code(".tmp/worktrees/" + snap.name + "/"))),
        h("div", { class: "lbl", text: "依頼文（全文）" }),
        full,
        h("label", { class: "confirmrow" }, cb, h("span", { text: "公開できない内容（秘密・組織の具体）を含まないことを確認しました" })),
        status,
        errBox,
        h("div", { class: "cact" }, go),
        h("div", { class: "mergeback" }, back, closeBtn()),
      ]);
    }

    /* stale_view: develop の最新を取り直して、確認をやり直す */
    function reloadBase(btn) {
      btn.disabled = true;
      PRV.api.repos().then(
        function (res) {
          if (S.closed) return;
          var fresh = (res.repos || []).filter(function (r) { return r.repoId === S.repoId; })[0];
          if (fresh) {
            repos.forEach(function (r) {
              if (r.repoId === fresh.repoId) r.targetOid = fresh.targetOid;
            });
          }
          S.notice = "develop が更新されました（基点: develop@" + PRV.short(fresh && fresh.targetOid) + "）。内容を確認し直してください。";
          form();
        },
        function () {
          if (!S.closed) btn.disabled = false;
        }
      );
    }

    /* --- 結果 --- */
    function result(snap, f) {
      S.done = true;
      clearDraft();
      S.notice = "";
      PRV.cache = {};
      var prKey = /^p[0-9a-f]{16}$/.test(String(f.prKey || "")) ? f.prKey : "";
      var href = prKey ? "#/pr/" + snap.repoId + "/" + prKey : "#/";
      var rel = f.worktree && /^\.tmp\/worktrees\/[a-z0-9][a-z0-9._-]*$/.test(String(f.worktree.rel || "")) ? f.worktree.rel : ".tmp/worktrees/" + snap.name;
      var cmd = "cd " + snap.repoName + "/" + rel + " && pis --new";
      var kids = [h("h2", { text: f.replay === true ? "起票済みでした（同じ依頼の再送）" : "起票しました" })];
      kids.push(h("p", null, "枝 ", code(String(f.branch || "feature/" + snap.name)), " ・ 基点 ", code("develop@" + PRV.short(f.base && f.base.oid ? f.base.oid : snap.oid))));
      (Array.isArray(f.warnings) ? f.warnings : []).forEach(function (w) {
        kids.push(h("p", { class: "attn", role: "status", text: "⚠ " + String(w) }));
      });
      if (f.recorded === false) kids.push(h("p", { class: "attn", role: "alert", text: "枝と作業ツリーは作れましたが、依頼文の記録は保存できませんでした。" }));
      kids.push(h("div", { class: "lbl", text: "作業を始めるには" }), h("p", { class: "createcmd" }, code(cmd)));
      var openA = h("a", { class: "btn primary createopen", href: href, text: "PR を開く" });
      openA.addEventListener("click", function () {
        PRV.closeSheet();
      });
      var copy = h("button", { class: "btn createcopy", type: "button", text: "依頼文をコピー" });
      var cs = h("p", { class: "small", role: "status" });
      copy.addEventListener("click", function () {
        function manual() {
          var t = h("textarea", { class: "cbox", "aria-label": "依頼文" });
          t.setAttribute("readonly", "");
          t.setAttribute("rows", "6");
          t.value = snap.text;
          cs.textContent = "自動でコピーできませんでした。下の文を選んでコピーしてください。";
          cs.after(t);
          t.focus();
          t.select();
        }
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(snap.text).then(function () {
            cs.textContent = "コピーしました。";
          }, manual);
        } else manual();
      });
      var done = h("button", { class: "btn createfinish", type: "button", text: "一覧を更新して閉じる" });
      done.addEventListener("click", function () {
        finish(null);
      });
      kids.push(h("div", { class: "cact" }, openA, copy, done), cs);
      mount(kids);
    }

    PRV.openSheet(backdrop, onKey, opener, function () {
      S.closed = true;
      app.removeAttribute("inert");
    });
    app.setAttribute("inert", "");
    form();
  }

  /* 一覧の「＋ 起票」。出せないときは null（caps.create が真で、起票先が develop の repo があるときだけ） */
  PRV.createEntry = function (caps, repos) {
    var targets = (repos || []).filter(function (r) {
      return r && r.target === "develop";
    });
    if (!(caps && caps.create === true) || !targets.length) return null;
    var b = h("button", { class: "btn primary createopenbtn", type: "button", text: "＋ 起票" });
    b.addEventListener("click", function () {
      openCreate({ repos: targets.map(function (r) { return { repoId: r.repoId, name: r.name, target: r.target, targetOid: r.targetOid }; }) }, b);
    });
    return b;
  };

  /* PR 画面の「依頼文」カード（rev・digest 先頭 8 桁）。brief が無ければ null。本文は textContent だけ */
  PRV.briefCard = function (rv) {
    var b = rv && rv.brief;
    if (!b || typeof b !== "object") return null;
    var text = briefText({
      title: String(b.title || ""),
      goal: String(b.goal || ""),
      constraints: String(b.constraints || ""),
      scope: Array.isArray(b.scope) ? b.scope.map(String) : [],
      acceptance: String(b.acceptance || ""),
    });
    var pre = h("pre", { class: "mmsg briefbody" });
    pre.textContent = text;
    return h(
      "section",
      { class: "card briefcard" },
      h("details", null, h("summary", null, h("strong", { text: "依頼文" }), " ", h("span", { class: "muted small", text: "rev " + String(b.rev) + " ・ " + String(b.digest || "").slice(0, 8) })), pre)
    );
  };
})();
