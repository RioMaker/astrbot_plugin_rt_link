const bridge = window.AstrBotPluginView || window.AstrBotPluginPage;
const $ = (id) => document.getElementById(id);
const names = { kinoko: "菌菌", sakura: "SakuraBot" };
const state = { tab: "users", page: 1, total: 0, size: 20, epoch: 0, owner: null, busy: false };
const dateFormat = new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
function date(value) { const d = new Date(value); return value && !Number.isNaN(d.getTime()) ? dateFormat.format(d) : "尚未同步"; }
function el(tag, cls, text) { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; }
function notice(message, error = false) {
  for (const id of ["notice", "dialog-notice"]) { $(id).textContent = message; $(id).className = error ? "error" : ""; $(id).hidden = !message; }
}
function button(text, cls, action) { const n = el("button", cls, text); n.type = "button"; n.onclick = () => run(action, n); return n; }
async function run(action, node) {
  if (node) node.disabled = true;
  try { await action(); } catch (error) { notice(error.message || "操作失败，请重试。", true); }
  finally { if (node) node.disabled = false; }
}
const api = (endpoint, params) => bridge.apiGet(`admin/${endpoint}`, params);
function ratingText(account) { return account.rating === null ? (account.rating_state === "unbound" ? "当前来源未绑定" : "待同步评级") : Number(account.rating).toFixed(2); }
function chip(text, source = "") { return el("span", `chip ${source}`, text); }

async function loadUsers() {
  const epoch = ++state.epoch;
  const data = await api("users", { page: state.page, page_size: state.size, q: $("search").value.trim(), source: $("source").value, status: $("status").value });
  if (epoch !== state.epoch) return;
  state.page = data.page; state.total = data.total;
  for (const key of ["total", "bound", "unbound"]) $(`stat-${key}`).textContent = data.stats[key];
  const body = $("users-body"); body.replaceChildren();
  for (const row of data.items) {
    const tr = el("tr"), user = el("td"), sources = el("td"), sync = el("td"), rating = el("td"), action = el("td");
    user.append(el("span", "name", row.name));
    if (!row.bound_sources.length) user.append(el("small", "", "已解绑 · 历史保留"));
    for (const source of row.bound_sources) sources.append(chip(names[source], source));
    if (!row.bound_sources.length) sources.append(chip("暂无绑定", "quiet"));
    sync.append(el("span", "", date(row.last_sync_at)));
    rating.append(el("span", row.rating === null ? "muted" : "rating", ratingText(row)), el("small", "", `当前：${names[row.current_source]}`));
    if (row.rating_at) rating.append(el("small", "", `评级于 ${date(row.rating_at)}`));
    action.append(button("管理", "secondary", () => openAccount(row.owner_id)));
    tr.append(user, sources, sync, rating, action); body.append(tr);
  }
  if (!data.items.length) { const tr = el("tr"), td = el("td", "empty", "没有符合条件的用户记录"); td.colSpan = 5; tr.append(td); body.append(tr); }
  const pages = Math.max(1, Math.ceil(data.total / data.page_size));
  $("page-info").textContent = `共 ${data.total} 位用户 · 第 ${data.page} / ${pages} 页`;
  $("previous").disabled = data.page <= 1; $("next").disabled = data.page >= pages;
}

async function openAccount(owner) {
  const account = await api("account", { owner_id: owner });
  state.owner = owner;
  $("dialog-title").textContent = `用户 ${account.name}`;
  $("dialog-notice").hidden = true;
  renderAccount($("dialog-content"), account);
  $("account-dialog").showModal();
}
async function loadBot() { renderAccount($("bot-account"), await api("account")); }

function field(text, input) { const label = el("label", "", text); label.append(input); return label; }
function input(name, type, placeholder, value = "") {
  const n = el("input"); n.name = name; n.type = type; n.placeholder = placeholder; n.value = value; n.required = true; return n;
}
function renderAccount(container, account) {
  container.replaceChildren();
  const summary = el("div", "account-summary"), info = el("div");
  info.append(el("span", "", `${names[account.current_source]} · 当前来源`), el("small", "", account.rating_at ? `Rating 更新于 ${date(account.rating_at)}` : "绑定并同步后显示 Rating"));
  summary.append(el("strong", "", ratingText(account)), info); container.append(summary);
  const grid = el("div", "source-grid");
  for (const source of account.sources) {
    const card = el("article", "source-card"), header = el("div", "source-header"), badges = el("div");
    header.append(el("h3", "", names[source.source]));
    badges.append(chip(source.bound ? "已绑定" : source.ever_bound ? "已解绑" : "未绑定", source.bound ? source.source : "quiet"));
    if (account.current_source === source.source) badges.append(chip("当前来源"));
    header.append(badges); card.append(header);
    const dl = el("dl");
    const values = [["玩家 ID", source.player_id || "—"], ["服务器", source.server || "—"], ["最后同步", date(source.last_sync_at)], ["来源 Rating", ratingText(source)]];
    for (const [title, value] of values) dl.append(el("dt", "", title), el("dd", "", value));
    card.append(dl);
    const actions = el("div", "actions");
    if (source.bound) {
      actions.append(button("同步成绩", "", () => mutate(account, source, "sync")));
      if (account.current_source !== source.source) actions.append(button("设为当前来源", "secondary", () => mutate(account, source, "select")));
      actions.append(button("解绑", "danger", async () => {
        if (window.confirm(`确认解绑 ${account.name} 的 ${names[source.source]}？历史成绩会保留。`)) await mutate(account, source, "unbind");
      }));
    }
    card.append(actions);
    const details = el("details"), form = el("form", "bind-form");
    details.append(el("summary", "", source.bound ? "更换绑定凭据" : "绑定此来源"));
    if (!source.bound && account.is_bot) details.open = true;
    const token = input("token", "password", source.source === "kinoko" ? "tk_ 开头的 API Key" : "48 位字母或数字");
    token.autocomplete = "new-password"; token.maxLength = source.source === "sakura" ? 48 : 512;
    if (source.source === "sakura") token.pattern = "[A-Za-z0-9]{48}";
    form.append(field(source.source === "kinoko" ? "菌菌 API Key" : "SakuraBot Token", token));
    if (source.source === "kinoko") {
      const row = el("div", "form-row"), player = input("player_id", "text", "玩家 ID", source.player_id);
      player.maxLength = 64; player.pattern = "[A-Za-z0-9_-]{1,64}";
      const server = el("select"); server.name = "server";
      for (const [value, text] of [["cn", "国服 cn"], ["jp", "日服 jp"], ["custom", "custom"]]) { const option = el("option", "", text); option.value = value; server.append(option); }
      server.value = ["cn", "jp", "custom"].includes(source.server) ? source.server : "cn";
      row.append(field("玩家 ID", player), field("服务器", server)); form.append(row);
    }
    form.append(el("small", "", "保存时验证凭据，并设为当前来源。已保存的 Token 不回显。"));
    const submit = el("button", "", "验证并保存"); submit.type = "submit"; form.append(submit);
    form.onsubmit = (event) => { event.preventDefault(); if (state.busy) return; const credentials = Object.fromEntries(new FormData(form)); token.value = ""; run(() => mutate(account, source, "bind", credentials), submit); };
    details.append(form); card.append(details); grid.append(card);
  }
  container.append(grid);
}

async function mutate(account, source, action, credentials = {}) {
  if (state.busy) return;
  state.busy = true;
  const nodes = [...document.querySelectorAll(".account-content button, .account-content input, .account-content select")];
  nodes.forEach((n) => { n.disabled = true; });
  notice(action === "sync" ? "正在同步成绩，请稍候…" : action === "bind" ? "正在验证绑定凭据，请稍候…" : "正在保存…");
  try {
    const result = await bridge.apiPost("admin/action", { owner_id: account.owner_id, source: source.source, action, ...credentials });
    if (account.is_bot) renderAccount($("bot-account"), result.account);
    else if (state.owner === account.owner_id) renderAccount($("dialog-content"), result.account);
    notice(result.message);
    if (!account.is_bot) await loadUsers();
  } finally { state.busy = false; nodes.forEach((n) => { n.disabled = false; }); }
}

async function tab(name) {
  state.tab = name;
  for (const key of ["users", "bot"]) {
    $(`${key}-panel`).hidden = key !== name;
    if (key === name) $(`tab-${key}`).setAttribute("aria-current", "page"); else $(`tab-${key}`).removeAttribute("aria-current");
  }
  await (name === "users" ? loadUsers() : loadBot());
}
$("tab-users").onclick = () => run(() => tab("users"));
$("tab-bot").onclick = () => run(() => tab("bot"));
$("refresh").onclick = () => run(() => tab(state.tab), $("refresh"));
$("filters").onsubmit = (event) => { event.preventDefault(); state.page = 1; run(loadUsers); };
$("previous").onclick = () => { if (state.page > 1) { state.page--; run(loadUsers); } };
$("next").onclick = () => { if (state.page * state.size < state.total) { state.page++; run(loadUsers); } };
$("close-dialog").onclick = () => $("account-dialog").close();
if (!bridge) notice("请从 AstrBot WebUI 的 RTLink 插件详情打开此管理页。", true);
else await run(async () => {
  const context = await bridge.ready();
  const theme = (value) => { document.documentElement.dataset.theme = value.isDark ? "dark" : "light"; };
  theme(context);
  if (bridge.onContext) bridge.onContext(theme);
  await loadUsers();
});
