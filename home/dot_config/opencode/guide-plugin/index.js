import { readFileSync } from "node:fs"

// 判定表は common.toml から生成する (rules.json)。ここには置かない。
// ディレクトリ名を plugin / plugins にしてはいけない。その 2 つは
// 設定ディレクトリ直下で自動探索され、明示指定と二重にロードされる。
// see docs/research/opencode-plugin-loading.md
const rules = JSON.parse(
  readFileSync(new URL("./rules.json", import.meta.url), "utf8"),
)

const compiled = (rules.guide ?? []).map((r) => ({
  re: new RegExp(r.pattern),
  message: r.message,
}))

export default {
  id: "guide",
  async setup(ctx) {
    const raw = new Map()

    await ctx.tool.hook("execute.before", (e) => {
      if (e.tool === "shell") raw.set(e.id, e.input?.command ?? "")
    })

    await ctx.permission.hook("evaluate", (e) => {
      if (e.action !== "shell") return
      // 規約 1: すでに allow のものには触らない。bypass はここで素通りする。
      if (e.effect === "allow") return

      // scanner は変数代入を落とすので、生のコマンドを使う。
      const cmd = raw.get(e.source?.id) ?? e.resources.join(" ; ")
      for (const rule of compiled) {
        if (!rule.re.test(cmd)) continue
        e.effect = "deny"
        e.message = rule.message
        return
      }
    })
  },
}
