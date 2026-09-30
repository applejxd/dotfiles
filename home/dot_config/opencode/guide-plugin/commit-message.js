// git commit の確認に出す件名と本文を、コマンドから決定的に抜き出す (モデルは呼ばない)。
// index.js (説明の生成を省く判定) と tui.ts (表示) の両方が使う。
// see docs/spec/agent-config-generation.md#git-commit-の件名と本文

// 引用符の外に現れたら、実行時の展開や別コマンドがあり得るので抜き出さない。
const UNQUOTED_STOP = new Set([..."\n\r;&|<>()$`*?[{}!"])
// メッセージを -m 以外から取るオプション。抜き出すと実際と食い違う。
const OTHER_SOURCE_LONG = /^--(file|reuse-message|reedit-message|template|fixup|squash)(=|$)/
const OTHER_SOURCE_SHORT = new Set([..."FCct"])

// sh の単語分割のうち、単純なコマンド 1 つに要る分だけ。解けないものは null。
function words(command) {
  const out = []
  let cur = null
  let i = 0
  const n = command.length
  while (i < n) {
    const c = command[i]
    if (c === " " || c === "\t") {
      if (cur !== null) out.push(cur)
      cur = null
      i++
      continue
    }
    if (c === "'") {
      const end = command.indexOf("'", i + 1)
      if (end < 0) return null
      cur = (cur ?? "") + command.slice(i + 1, end)
      i = end + 1
      continue
    }
    if (c === '"') {
      cur = cur ?? ""
      i++
      for (;;) {
        if (i >= n) return null
        const d = command[i]
        if (d === '"') break
        if (d === "$" || d === "`") return null
        if (d === "\\" && i + 1 < n && '"\\$`\n'.includes(command[i + 1])) {
          if (command[i + 1] !== "\n") cur += command[i + 1]
          i += 2
          continue
        }
        cur += d
        i++
      }
      i++
      continue
    }
    if (c === "\\") {
      if (i + 1 >= n) return null
      if (command[i + 1] !== "\n") cur = (cur ?? "") + command[i + 1]
      i += 2
      continue
    }
    if (UNQUOTED_STOP.has(c)) return null
    if (cur === null && (c === "#" || c === "~")) return null
    cur = (cur ?? "") + c
    i++
  }
  if (cur !== null) out.push(cur)
  return out
}

// -m / --message の値と、それ以外の引数。単純な `git commit …` 1 つでなければ null。
export function parseCommit(command) {
  if (typeof command !== "string") return null
  const w = words(command)
  if (!w || w[0] !== "git" || w[1] !== "commit") return null
  const messages = []
  const extra = []
  for (let i = 2; i < w.length; i++) {
    const a = w[i]
    if (a === "--") {
      extra.push(...w.slice(i))
      break
    }
    if (a === "-m" || a === "--message") {
      if (i + 1 >= w.length) return null
      messages.push(w[++i])
      continue
    }
    if (a.startsWith("--message=")) {
      messages.push(a.slice("--message=".length))
      continue
    }
    if (OTHER_SOURCE_LONG.test(a)) return null
    if (/^-[^-]/.test(a)) {
      const m = a.indexOf("m")
      const flags = m < 0 ? a.slice(1) : a.slice(1, m)
      if ([...flags].some((f) => OTHER_SOURCE_SHORT.has(f))) return null
      if (m < 0) {
        extra.push(a)
        continue
      }
      if (flags) extra.push(`-${flags}`)
      if (m + 1 < a.length) messages.push(a.slice(m + 1))
      else if (i + 1 < w.length) messages.push(w[++i])
      else return null
      continue
    }
    extra.push(a)
  }
  if (!messages.length) return null
  // git は -m を段落として空行でつなぐ。
  const lines = messages.join("\n\n").split("\n").map((l) => l.trimEnd())
  return {
    subject: lines[0],
    body: lines.slice(1).filter((l) => l.trim()),
    extra,
  }
}

function wide(cp) {
  return (
    (cp >= 0x1100 && cp <= 0x115f) ||
    (cp >= 0x2e80 && cp <= 0xa4cf) ||
    (cp >= 0xac00 && cp <= 0xd7a3) ||
    (cp >= 0xf900 && cp <= 0xfaff) ||
    (cp >= 0xfe30 && cp <= 0xfe4f) ||
    (cp >= 0xff00 && cp <= 0xff60) ||
    (cp >= 0xffe0 && cp <= 0xffe6) ||
    (cp >= 0x1f300 && cp <= 0x1faff) ||
    (cp >= 0x20000 && cp <= 0x3fffd)
  )
}

// 端末の桁数 (全角は 2 桁) で切る。
export function clip(text, width) {
  let used = 0
  let out = ""
  for (const ch of text) {
    const w = wide(ch.codePointAt(0)) ? 2 : 1
    if (used + w > width) {
      // "…" の 1 桁を残す
      while (used + 1 > width && out) {
        const last = [...out].pop()
        out = out.slice(0, -last.length)
        used -= wide(last.codePointAt(0)) ? 2 : 1
      }
      return `${out}…`
    }
    out += ch
    used += w
  }
  return text
}

// 表示用の行。件名は切らずに先頭へ置き、本文は各行を line_width 桁・max_lines 行までにする。
export function commitPreview(command, opts) {
  const parsed = parseCommit(command)
  if (!parsed) return null
  const width = Math.max(4, Number(opts?.line_width) || 72)
  const max = Math.max(0, Number.isFinite(opts?.max_lines) ? opts.max_lines : 8)
  const body = parsed.body.slice(0, max).map((l) => clip(l, width))
  if (parsed.body.length > max) body.push(`…ほか ${parsed.body.length - max} 行`)
  return {
    subject: parsed.subject,
    body,
    extra: parsed.extra.length ? clip(`引数: ${parsed.extra.join(" ")}`, width) : null,
  }
}
