/* API クライアント（契約: GET の 4 エンドポイントだけ。同一オリジンのみ） */
(function () {
  "use strict";
  var PRV = (window.PRV = window.PRV || {});

  function fail(message) {
    var e = new Error(message);
    e.userMessage = message;
    return e;
  }

  function get(path) {
    return fetch(path, { method: "GET", headers: { Accept: "application/json" }, cache: "no-store" }).then(
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
            throw fail(m || "サーバがエラーを返しました（" + res.status + "）。");
          }
          if (body === null || typeof body !== "object") throw fail("サーバの応答を読み取れませんでした。");
          return body;
        });
      },
      function () {
        throw fail("サーバに接続できません。起動しているか確認してください。");
      }
    );
  }

  function idPath(id) {
    var m = /^(r[0-9a-f]{8})\/(p[0-9a-f]{16})$/.exec(id);
    if (!m) throw fail("PR の指定が正しくありません。");
    return "/api/prs/" + m[1] + "/" + m[2];
  }

  PRV.api = {
    repos: function () {
      return get("/api/repos");
    },
    prs: function () {
      return get("/api/prs");
    },
    pr: function (id) {
      try {
        return get(idPath(id));
      } catch (e) {
        return Promise.reject(e);
      }
    },
    diff: function (id, path) {
      try {
        return get(idPath(id) + "/diff?path=" + encodeURIComponent(path));
      } catch (e) {
        return Promise.reject(e);
      }
    },
  };
})();
