// コミット計画の apply の前段の確かめ (モデルは呼ばない)。
// 同じターン (最後の利用者の発言より後) に、`commit_plan.py show <ID>` の出力と同じ全文を
// ```text ブロックで返答に書いていなければ止める。会話の中で全文を読めることを仕組みで担保する。
// see docs/change/0014-deterministic-commit-runner.md

const APPLY = /commit_plan\.py['"]?\s+apply\s+['"]?([A-Za-z0-9-]+)/
const BLOCK = /```[^\n]*\n([\s\S]*?)```/g

export function applyPlanID(command) {
  if (typeof command !== "string") return null
  return APPLY.exec(command)?.[1] ?? null
}

// 行末の空白と前後の空行を落とし、改行を揃える
export function normalize(text) {
  return String(text)
    .replace(/\r\n?/g, "\n")
    .split("\n")
    .map((line) => line.trimEnd())
    .join("\n")
    .replace(/^\n+|\n+$/g, "")
}

function turnParts(messages) {
  const list = Array.isArray(messages) ? messages : []
  let lastUser = -1
  list.forEach((m, i) => {
    if (m?.type === "user") lastUser = i
  })
  return list
    .slice(lastUser + 1)
    .filter((m) => m?.type === "assistant")
    .flatMap((m) => (Array.isArray(m.content) ? m.content : []))
}

function showOutput(parts, planID) {
  const show = new RegExp(`commit_plan\\.py['"]?\\s+show\\s+['"]?${planID}(?![A-Za-z0-9-])`)
  let out = null
  for (const p of parts) {
    if (p?.type !== "tool" || p.name !== "shell") continue
    const state = p.state ?? {}
    if (state.status !== "completed" || !show.test(state.input?.command ?? "")) continue
    out = (state.content ?? [])
      .filter((c) => c?.type === "text")
      .map((c) => c.text)
      .join("")
  }
  return out
}

// 止めるなら理由 (モデルへの指示)、通すなら null
export function checkApply(command, messages) {
  const planID = applyPlanID(command)
  if (!planID) return null
  const parts = turnParts(messages)
  const shown = showOutput(parts, planID)
  const steps =
    `コミット前の確かめ (commit スキルの手順): \`commit_plan.py show ${planID}\` の出力を、` +
    "一字一句変えずに ```text のコードブロック 1 つで返答の文章に書いてから、同じ apply を再実行してください。" +
    "利用者が会話の中で全文を読めるようにするための確かめで、利用者による拒否ではありません。"
  if (shown === null) return `計画 ${planID} の show がこのターンにありません。${steps}`
  const want = normalize(shown)
  if (!want) return `計画 ${planID} の show の出力が空です。snapshot からやり直してください。`
  const written = parts
    .filter((p) => p?.type === "text")
    .flatMap((p) => [...String(p.text ?? "").matchAll(BLOCK)].map((m) => normalize(m[1])))
  if (written.includes(want)) return null
  return `計画 ${planID} の全文が返答に見つかりません (書き写しが違うか、コードブロックの外です)。${steps}`
}
