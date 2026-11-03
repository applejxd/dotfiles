/* 画面の自動更新: PR の詳細（概要）を表示している間だけ、レビューの状態を約 3 秒ごとに取り直す。
   入力途中の内容を守るため、反映の仕方（部分更新・保留）は呼び出し側の apply が決める */
(function () {
  "use strict";
  var PRV = window.PRV;
  var h = PRV.h;
  var POLL_MS = 3000;
  var MAX_MS = 30000;
  var run = null;

  function visible() {
    return document.visibilityState === "visible";
  }

  function show() {
    if (!run) return;
    if (run.err) run.err.hidden = !run.failed;
    if (run.btn) run.btn.hidden = !run.pending;
  }

  function clearTimer(r) {
    if (r.timer) clearTimeout(r.timer);
    r.timer = null;
  }

  function abort(r) {
    if (r.ctl) r.ctl.abort();
    r.ctl = null;
  }

  function schedule() {
    var me = run;
    if (!me) return;
    clearTimer(me);
    if (!visible()) return;
    me.timer = setTimeout(function () {
      me.timer = null;
      if (run === me) tick();
    }, me.delay);
  }

  /* 取り直した状態が、表示済みと違うときだけ反映する */
  function onData(rv) {
    var key = JSON.stringify(rv);
    if (key === run.key) return;
    run.key = key;
    run.latest = rv;
    if (run.apply) run.pending = !!run.apply(rv, false);
    show();
  }

  function tick() {
    var me = run;
    if (!me || me.ctl || !visible()) return;
    var ctl = new AbortController();
    me.ctl = ctl;
    PRV.api.review(me.id, ctl.signal).then(
      function (rv) {
        if (run !== me || me.ctl !== ctl) return;
        me.ctl = null;
        me.failed = false;
        me.delay = POLL_MS;
        onData(rv);
        show();
        schedule();
      },
      function () {
        if (run !== me || me.ctl !== ctl) return;
        me.ctl = null;
        me.failed = true;
        me.delay = Math.min(me.delay * 2, MAX_MS);
        show();
        schedule();
      }
    );
  }

  function onVisibility() {
    if (!run) return;
    clearTimer(run);
    if (visible()) {
      tick();
    } else {
      abort(run);
    }
  }

  PRV.liveStop = function () {
    if (!run) return;
    clearTimer(run);
    abort(run);
    document.removeEventListener("visibilitychange", onVisibility);
    run = null;
  };

  /* 開始。次の取り直しは約 3 秒後（描画のたびに作り直さないよう、描画とは別に 1 回だけ呼ぶ） */
  PRV.liveStart = function (id) {
    PRV.liveStop();
    run = { id: id, delay: POLL_MS, timer: null, ctl: null, key: null, latest: null, apply: null, failed: false, pending: false, err: null, btn: null };
    document.addEventListener("visibilitychange", onVisibility);
    schedule();
  };

  /* 画面を（全体）描画したあとに呼ぶ: 表示済みの状態と、反映の関数を登録する。保留中の更新は、描き直しで消える */
  PRV.liveBind = function (rv, apply) {
    if (!run) return;
    run.key = JSON.stringify(rv);
    run.latest = rv;
    run.apply = apply;
    run.pending = false;
    show();
  };

  /* 画面の上の小さな表示: 取り直しの失敗と、保留した更新のバナー。無効なときは空の箱 */
  PRV.liveBar = function () {
    var bar = h("div", { class: "livebar" });
    if (!run) return bar;
    var err = h("span", { class: "attn small", role: "status", text: "更新できません（自動で再試行します）" });
    var btn = h("button", { class: "btn sm", type: "button", text: "新しい更新があります（押すと反映します）" });
    btn.addEventListener("click", function () {
      if (!run || !run.apply || !run.latest) return;
      run.pending = !!run.apply(run.latest, true);
      show();
    });
    run.err = err;
    run.btn = btn;
    bar.appendChild(err);
    bar.appendChild(btn);
    show();
    return bar;
  };
})();
