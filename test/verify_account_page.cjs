/* Isolated browser smoke test. Synthetic data only; no upstream API or AstrBot session. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const http = require("node:http");
const { chromium } = require(process.argv[2] || "playwright");
const root = path.resolve(__dirname, "../pages/manage");
const output = path.resolve(__dirname, "tmp/account-admin-ui");

async function main() {
  fs.mkdirSync(output, { recursive: true });
  const server = http.createServer((req, res) => {
    const file = { "/": "index.html", "/app.js": "app.js", "/style.css": "style.css" }[req.url];
    if (!file) { res.writeHead(204); res.end(); return; }
    res.setHeader("Content-Type", file.endsWith(".js") ? "text/javascript" : file.endsWith(".css") ? "text/css" : "text/html; charset=utf-8");
    res.end(fs.readFileSync(path.join(root, file)));
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.addInitScript(() => {
      const BOT = "__rtlink_ai__";
      const source = (key, bound, rating) => ({ source: key, label: key, bound, ever_bound: bound, player_id: bound ? "001234" : "", server: bound ? "cn" : "", last_sync_at: bound && rating !== null ? "2026-10-30T02:32:00Z" : null, rating_at: bound && rating !== null ? "2026-10-30T02:32:00Z" : null, rating: bound ? rating : null, rating_state: !bound ? "unbound" : rating === null ? "needs_sync" : "available", score_count: bound ? 250 : null });
      const derive = (row) => {
        const active = row.sources.find((s) => s.source === row.current_source);
        return { ...row, bound_sources: row.sources.filter((s) => s.bound).map((s) => s.source), last_sync_at: row.sources.find((s) => s.last_sync_at)?.last_sync_at || null, rating: active.rating, rating_at: active.rating_at, rating_state: active.rating_state };
      };
      const rows = Array.from({ length: 26 }, (_, i) => derive({ owner_id: String(33000001 + i), name: String(33000001 + i), is_bot: false, current_source: i % 2 ? "sakura" : "kinoko", sources: [source("kinoko", i % 3 !== 0, 9.31), source("sakura", i % 3 !== 2, i === 1 ? 0 : 8.72)] }));
      rows[25].name = '<img src="x" onerror="window.injected=true">';
      let bot = derive({ owner_id: BOT, name: "可可子", is_bot: true, current_source: "kinoko", sources: [source("kinoko", false, null), source("sakura", false, null)] });
      window.audit = []; window.failNext = false;
      const clone = (data) => JSON.parse(JSON.stringify(data));
      window.AstrBotPluginPage = {
        ready: async () => ({ isDark: false }),
        onContext: (handler) => { window.setTestTheme = handler; },
        apiGet: async (endpoint, query = {}) => {
          if (endpoint === "admin/account") return clone(query.owner_id ? rows.find((r) => r.owner_id === query.owner_id) : bot);
          let filtered = rows.filter((row) => (!query.q || [row.owner_id, row.name, "001234"].some((v) => v.includes(query.q))) && (!query.source || row.bound_sources.includes(query.source)) && (query.status !== "bound" || row.bound_sources.length) && (query.status !== "unbound" || !row.bound_sources.length));
          const size = Number(query.page_size || 20), p = Math.min(Number(query.page || 1), Math.max(1, Math.ceil(filtered.length / size)));
          return clone({ items: filtered.slice((p - 1) * size, p * size), total: filtered.length, page: p, page_size: size, stats: { total: 26, bound: 26, unbound: 0 } });
        },
        apiPost: async (endpoint, data) => {
          window.audit.push({ endpoint, ...data });
          if (window.failNext) { window.failNext = false; throw new Error("绑定验证失败，请检查凭据。"); }
          const row = data.owner_id === BOT ? bot : rows.find((r) => r.owner_id === data.owner_id);
          const item = row.sources.find((s) => s.source === data.source);
          if (data.action === "bind") { Object.assign(item, source(item.source, true, null), { player_id: data.player_id || "001234" }); row.current_source = item.source; }
          if (data.action === "select") row.current_source = item.source;
          if (data.action === "sync") Object.assign(item, source(item.source, true, 9.38));
          if (data.action === "unbind") Object.assign(item, { bound: false, rating: null, rating_at: null, rating_state: "unbound" });
          const updated = derive(row);
          if (data.owner_id === BOT) bot = updated; else rows[rows.findIndex((r) => r.owner_id === row.owner_id)] = updated;
          return clone({ message: "操作完成", account: updated });
        },
      };
    });
    const url = `http://127.0.0.1:${server.address().port}/`;
    await page.goto(url);
    await page.waitForFunction(() => document.getElementById("stat-total").textContent === "26");
    assert.equal(await page.locator("tbody tr").count(), 20);
    assert((await page.locator("tbody .rating").allTextContents()).includes("0.00"));
    assert.match(await page.locator("tbody").innerText(), /2026\/10\/30 10:32/);
    await page.screenshot({ path: path.join(output, "users.png"), fullPage: true });
    await page.getByRole("button", { name: "下一页", exact: true }).click();
    await page.waitForFunction(() => document.querySelectorAll("tbody tr").length === 6);
    assert.equal(await page.locator("tbody img").count(), 0);
    assert.equal(await page.evaluate(() => window.injected), undefined);
    await page.locator("#search").fill("33000001");
    await page.getByRole("button", { name: "搜索", exact: true }).click();
    await page.waitForFunction(() => document.querySelectorAll("tbody tr").length === 1);
    await page.getByRole("button", { name: "管理", exact: true }).click();
    assert.equal(await page.locator("dialog[open] .source-card").count(), 2);
    await page.getByRole("button", { name: "关闭", exact: true }).click();

    await page.getByRole("button", { name: "可可子账号", exact: true }).click();
    const kinoko = page.locator("#bot-account .source-card").filter({ has: page.getByRole("heading", { name: "菌菌", exact: true }) });
    const sakura = page.locator("#bot-account .source-card").filter({ has: page.getByRole("heading", { name: "SakuraBot", exact: true }) });
    await kinoko.getByLabel("菌菌 API Key", { exact: true }).fill("tk_synthetic_browser");
    await kinoko.getByLabel("玩家 ID", { exact: true }).fill("001234");
    await kinoko.getByRole("button", { name: "验证并保存" }).click();
    await kinoko.getByRole("button", { name: "同步成绩" }).waitFor();
    assert.equal(await kinoko.locator("input[type=password]").inputValue(), "");
    assert(!((await page.locator("body").innerText()).includes("tk_synthetic_browser")));
    await kinoko.getByRole("button", { name: "同步成绩" }).click();
    await page.waitForFunction(() => document.querySelector("#bot-account .account-summary strong").textContent === "9.38");
    await sakura.getByLabel("SakuraBot Token", { exact: true }).fill("b".repeat(48));
    await sakura.getByRole("button", { name: "验证并保存" }).click();
    await sakura.getByRole("button", { name: "同步成绩" }).waitFor();
    await sakura.getByRole("button", { name: "同步成绩" }).click();
    await page.waitForFunction(() => document.querySelector("#bot-account .account-summary strong").textContent === "9.38");
    await page.screenshot({ path: path.join(output, "bot.png"), fullPage: true });
    await kinoko.getByRole("button", { name: "设为当前来源" }).click();
    await page.waitForFunction(() => document.querySelector("#bot-account .account-summary").textContent.includes("菌菌 · 当前来源"));
    await sakura.locator("summary").click();
    await sakura.getByLabel("SakuraBot Token", { exact: true }).fill("c".repeat(48));
    await page.evaluate(() => { window.failNext = true; });
    await sakura.getByRole("button", { name: "验证并保存" }).click();
    await page.locator("#notice.error").waitFor();
    assert.equal(await sakura.locator("input[type=password]").inputValue(), "");
    assert.equal(await sakura.getByRole("button", { name: "验证并保存" }).isEnabled(), true);
    page.once("dialog", (dialog) => dialog.accept());
    await kinoko.getByRole("button", { name: "解绑", exact: true }).click();
    await page.waitForFunction(() => document.querySelector("#bot-account .account-summary strong").textContent === "当前来源未绑定");
    assert.equal(await sakura.getByRole("button", { name: "同步成绩" }).count(), 1);
    assert((await page.evaluate(() => window.audit)).every((entry) => entry.owner_id === "__rtlink_ai__"));
    await page.evaluate(() => window.setTestTheme({ isDark: true }));
    await page.setViewportSize({ width: 390, height: 844 });
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
    await page.screenshot({ path: path.join(output, "bot-mobile-dark.png"), fullPage: true });
    assert.deepEqual(errors, []);
    console.log("PASS: pagination, search, dialog, bot bind/sync/switch/unbind, credential clearing, failed save, XSS, mobile and dark theme.");
    console.log(`Screenshots: ${output}`);
  } finally { await browser.close(); await new Promise((resolve) => server.close(resolve)); }
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
