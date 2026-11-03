/* 安全な小さい markdown 描画器。入力は非信頼: createElement と textContent だけで DOM を作る（生の HTML は文字として出す）。
   対応と上限は docs/spec/pr-viewer.md#markdown-の描画 */
(function () {
  "use strict";
  var PRV = (window.PRV = window.PRV || {});
  var MAX_CHARS = 20000; /* これを超えた分は書式なしの文字で出す */
  var MAX_LINES = 300; /* 行数の上限。超えた分は書式なし */
  var MAX_LINE = 2000; /* 1 行の長さの上限。超えた行は書式なしの段落 */
  var MAX_DEPTH = 2; /* 引用・箇条書きの入れ子 */
  var MAX_INLINE = 3; /* 太字・斜体・リンクの入れ子 */

  var FENCE = /^\s*```/;
  var HEAD = /^(#{1,3})\s+(.*?)\s*$/;
  var HR = /^\s*([-*_])(\s*\1){2,}\s*$/;
  var ITEM = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/;
  var DELIM = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/;
  var INLINE = /`([^`\n]+)`|!\[([^\]\n]*)\]\(([^)\s]*)\)|\[([^\]\n]+)\]\(([^)\s]+)\)|\*\*([^\n]+?)\*\*|\*([^*\s][^*\n]*?)\*/g;

  function el(tag, cls) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    return e;
  }

  function txt(parent, s) {
    if (s) parent.appendChild(document.createTextNode(s));
  }

  /* リンク先: http(s) と同一ページ内の # だけ */
  function safeUrl(u) {
    return /^https?:\/\/[^\s<>"]+$/i.test(u) || /^#[^\s]*$/.test(u);
  }

  function inline(s, parent, depth, noLink) {
    if (depth > MAX_INLINE || s.length > MAX_LINE) {
      txt(parent, s);
      return;
    }
    var re = new RegExp(INLINE.source, "g");
    var pos = 0;
    var m;
    while ((m = re.exec(s))) {
      txt(parent, s.slice(pos, m.index));
      pos = m.index + m[0].length;
      if (m[1] !== undefined) {
        var c = el("code");
        c.textContent = m[1];
        parent.appendChild(c);
      } else if (m[3] !== undefined) {
        txt(parent, "[画像: " + m[2] + "]");
      } else if (m[5] !== undefined) {
        if (noLink || !safeUrl(m[5])) {
          txt(parent, m[0]);
        } else {
          var a = el("a");
          a.setAttribute("href", m[5]);
          a.setAttribute("rel", "noopener noreferrer");
          a.setAttribute("target", "_blank");
          inline(m[4], a, depth + 1, true);
          parent.appendChild(a);
        }
      } else if (m[6] !== undefined) {
        var b = el("strong");
        inline(m[6], b, depth + 1, noLink);
        parent.appendChild(b);
      } else {
        var i = el("em");
        inline(m[7], i, depth + 1, noLink);
        parent.appendChild(i);
      }
    }
    txt(parent, s.slice(pos));
  }

  /* 改行は <br>。1 行ずつ inline にかける */
  function inlineLines(lines, parent) {
    lines.forEach(function (l, k) {
      if (k) parent.appendChild(el("br"));
      inline(l, parent, 0, false);
    });
  }

  function cells(line) {
    var t = line.trim().replace(/^\|/, "").replace(/\|$/, "");
    return t.split("|").map(function (x) {
      return x.trim();
    });
  }

  function isTableAt(lines, k) {
    return lines[k].indexOf("|") >= 0 && k + 1 < lines.length && lines[k + 1].indexOf("-") >= 0 && DELIM.test(lines[k + 1]);
  }

  function startsBlock(lines, k, depth) {
    var l = lines[k];
    return FENCE.test(l) || HEAD.test(l) || HR.test(l) || ITEM.test(l) || (depth < MAX_DEPTH && /^\s*>/.test(l)) || isTableAt(lines, k);
  }

  function list(lines, k, parent, depth) {
    var root = null;
    var cur = null; /* 直近の第 1 段の li */
    var sub = null;
    while (k < lines.length) {
      var l = lines[k];
      var m = ITEM.exec(l);
      if (!m && l.trim() === "") {
        var n = k;
        while (n < lines.length && lines[n].trim() === "") n++;
        if (n < lines.length && ITEM.test(lines[n]) && !HR.test(lines[n])) {
          k = n;
          continue;
        }
        break;
      }
      if (m && !HR.test(l)) {
        var ordered = /\d/.test(m[2].charAt(0));
        if (root && !(m[1].length >= 2 && cur) && root.tagName !== (ordered ? "OL" : "UL")) break; /* 種類が変わったら別のリスト */
        var li = el("li");
        inline(m[3], li, 0, false);
        if (m[1].length >= 2 && cur && depth + 1 < MAX_DEPTH + 1) {
          if (!sub) {
            sub = el(ordered ? "ol" : "ul");
            cur.appendChild(sub);
          }
          sub.appendChild(li);
        } else {
          if (!root) {
            root = el(ordered ? "ol" : "ul");
            parent.appendChild(root);
          }
          root.appendChild(li);
          cur = li;
          sub = null;
        }
        k++;
      } else if (cur && /^\s/.test(l) && !startsBlock(lines, k, depth)) {
        var target = sub && sub.lastChild ? sub.lastChild : cur;
        target.appendChild(el("br"));
        inline(l.trim(), target, 0, false);
        k++;
      } else {
        break;
      }
    }
    return k;
  }

  function table(lines, k, parent) {
    var head = cells(lines[k]);
    var wrap = el("div", "mdtable");
    var t = el("table");
    var tr = el("tr");
    head.forEach(function (c) {
      var th = el("th");
      inline(c, th, 0, false);
      tr.appendChild(th);
    });
    var thead = el("thead");
    thead.appendChild(tr);
    t.appendChild(thead);
    var tb = el("tbody");
    k += 2;
    while (k < lines.length && lines[k].trim() !== "" && lines[k].indexOf("|") >= 0) {
      var row = el("tr");
      var cs = cells(lines[k]);
      for (var c = 0; c < head.length; c++) {
        var td = el("td");
        inline(cs[c] || "", td, 0, false);
        row.appendChild(td);
      }
      tb.appendChild(row);
      k++;
    }
    t.appendChild(tb);
    wrap.appendChild(t);
    parent.appendChild(wrap);
    return k;
  }

  function blocks(lines, parent, depth) {
    var k = 0;
    while (k < lines.length) {
      var l = lines[k];
      var m;
      if (l.trim() === "") {
        k++;
      } else if (FENCE.test(l)) {
        var pre = el("pre", "mdcode");
        var code = el("code");
        var buf = [];
        k++;
        while (k < lines.length && !/^\s*```\s*$/.test(lines[k])) buf.push(lines[k++]);
        k++; /* 閉じの fence。無ければ末尾まで */
        code.textContent = buf.join("\n");
        pre.appendChild(code);
        parent.appendChild(pre);
      } else if ((m = HEAD.exec(l)) && l.length <= MAX_LINE) {
        var hd = el("h" + (m[1].length + 3), "mdh");
        inline(m[2], hd, 0, false);
        parent.appendChild(hd);
        k++;
      } else if (HR.test(l)) {
        parent.appendChild(el("hr"));
        k++;
      } else if (depth < MAX_DEPTH && /^\s*>/.test(l)) {
        var inner = [];
        while (k < lines.length && /^\s*>/.test(lines[k])) inner.push(lines[k++].replace(/^\s*>\s?/, ""));
        var q = el("blockquote");
        blocks(inner, q, depth + 1);
        parent.appendChild(q);
      } else if (ITEM.test(l)) {
        k = list(lines, k, parent, depth);
      } else if (isTableAt(lines, k)) {
        k = table(lines, k, parent);
      } else {
        var para = [l.replace(/\s+$/, "")];
        k++;
        while (k < lines.length && lines[k].trim() !== "" && !startsBlock(lines, k, depth)) para.push(lines[k++].replace(/\s+$/, ""));
        var p = el("p");
        inlineLines(para, p);
        parent.appendChild(p);
      }
    }
  }

  /* 本文 → <div class="cbody md">。文字列でない・空なら空の div */
  PRV.md = function (text) {
    var root = el("div", "cbody md");
    var s = typeof text === "string" ? text : "";
    var rest = "";
    if (s.length > MAX_CHARS) {
      rest = s.slice(MAX_CHARS);
      s = s.slice(0, MAX_CHARS);
    }
    var cut = -1;
    var from = 0;
    for (var n = 0; n < MAX_LINES; n++) {
      cut = s.indexOf("\n", from);
      if (cut < 0) break;
      from = cut + 1;
    }
    if (cut >= 0) {
      rest = s.slice(cut + 1) + rest;
      s = s.slice(0, cut);
    }
    blocks(s.replace(/\r\n?/g, "\n").split("\n"), root, 0);
    if (rest !== "") {
      root.appendChild(el("p", "muted small")).textContent = "（長いため、ここから先は書式なしで表示します）";
      var pre = el("pre", "mdrest");
      pre.textContent = rest;
      root.appendChild(pre);
    }
    return root;
  };
})();
