/* API クライアント(契約: GET 5 本 + POST 2 本。同一オリジンのみ) */
(function () {
  "use strict";
  var PRV = (window.PRV = window.PRV || {});

  function fail(message, code, extra) {
    var e = new Error(message);
    e.userMessage = message;
    if (code) e.code = code;
    if (extra) Object.keys(extra).forEach(function (k) { e[k] = extra[k]; });
    return e;
  }

  function request(path, init) {
    return fetch(path, init).then(
      function (res) {
        return res.text().then(function (text) {
          var body = null;
          try {
            body = JSON.parse(text);
          } catch (e) {
            body = null;
          }
          if (!res.ok) {
            var m = body && body.error && typeof body.error.message === "string" ? body.error.message : "";
            var code = body && body.error && typeof body.error.code === "string" ? body.error.code : "";
            var cf = body && body.error && Array.isArray(body.error.conflicts) ? body.error.conflicts.map(String) : undefined;
            var dt = body && body.error && body.error.details && typeof body.error.details === "object" ? body.error.details : undefined;
            /* 表示中の版から PR が更新された: 詳細のキャッシュを捨てる（次の描画で取り直す） */
            if (code === "stale_view" || code === "not_ff") PRV.cache = {};
            throw fail(m || "サーバがエラーを返しました（" + res.status + "）。", code, { status: res.status, serverMessage: m, conflicts: cf, details: dt });
          }
          if (body === null || typeof body !== "object") throw fail("サーバの応答を読み取れませんでした。", "", { status: res.status });
          return body;
        });
      },
      function () {
        throw fail("サーバに接続できません。起動しているか確認してください。", "", { network: true });
      }
    );
  }

  function get(path, signal) {
    return request(path, { method: "GET", headers: { Accept: "application/json" }, cache: "no-store", signal: signal });
  }

  /* 書き込み: 独自ヘッダー X-PRV と JSON の Content-Type が必須（契約 C10・C14） */
  function post(path, payload) {
    return request(path, {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json", "X-PRV": "1" },
      cache: "no-store",
      body: JSON.stringify(payload),
    });
  }

  function idPath(id) {
    var m = /^(r[0-9a-f]{8})\/(p[0-9a-f]{16})$/.exec(id);
    if (!m) throw fail("PR の指定が正しくありません。");
    return "/api/prs/" + m[1] + "/" + m[2];
  }

  /* idPath が投げる失敗を Promise の失敗にそろえる */
  function guard(f) {
    try {
      return f();
    } catch (e) {
      return Promise.reject(e);
    }
  }

  PRV.api = {
    /* 稼働版（固定した版の OID。ver.js が画面の隅に出す） */
    version: function () {
      return get("/api/version");
    },
    repos: function () {
      return get("/api/repos");
    },
    prs: function () {
      return get("/api/prs");
    },
    pr: function (id) {
      return guard(function () {
        return get(idPath(id));
      });
    },
    diff: function (id, path) {
      return guard(function () {
        return get(idPath(id) + "/diff?path=" + encodeURIComponent(path));
      });
    },
    review: function (id, signal) {
      return guard(function () {
        return get(idPath(id) + "/review", signal);
      });
    },
    /* 統合（CHG-0062 段 A2）。capabilities は 404（古いサーバ）・通信断のとき merge:false 扱い */
    capabilities: function () {
      return get("/api/capabilities").then(
        function (b) {
          return {
            merge: b.merge === true,
            targets: Array.isArray(b.targets) ? b.targets : [],
          };
        },
        function () {
          return { merge: false, targets: [] };
        }
      );
    },
    mergePlan: function (id) {
      return guard(function () {
        return post(idPath(id) + "/merge-plan", {});
      });
    },
    merge: function (id, m) {
      return guard(function () {
        return post(idPath(id) + "/merge", { expect: m.expect, message: m.message, cleanup: m.cleanup });
      });
    },
  };
})();
