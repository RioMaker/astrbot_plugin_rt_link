const bridge = window.AstrBotPluginView || window.AstrBotPluginPage;
const $ = (id) => document.getElementById(id);
const names = { kinoko: "菌菌", sakura: "Sakura" };
const state = {
  tab: "users",
  users: { page: 1, pages: 1, filters: {}, version: 0, loaded: false },
  botVersion: 0,
  accountVersion: 0,
  owner: null,
  pending: null,
};
const pageSize = 20;
const dialog = $("account-dialog");
const dateFormat = new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
function date(value) { const d = new Date(value); return value && !Number.isNaN(d.getTime()) ? dateFormat.format(d) : "尚未同步"; }
function el(tag, cls, text) { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; }
function notice(message, error = false, id = dialog.open ? "dialog-notice" : "notice") {
  const node = $(id);
  node.textContent = message;
  node.classList.toggle("error", error);
  node.hidden = !message;
}
function button(text, cls, action) { const n = el("button", cls, text); n.type = "button"; n.onclick = () => run(action, n); return n; }
async function run(action, node) {
  if (node) node.disabled = true;
  try { await action(); } catch (error) { notice(error.message || "操作失败，请重试。", true); }
  finally { if (node) node.disabled = false; }
}
const api = (endpoint, params) => bridge.apiGet(`admin/${endpoint}`, params);
function ratingText(account, unbound = "当前来源未绑定") {
  if (account.rating !== null) return Number(account.rating).toFixed(2);
  if (account.rating_state === "unbound") return unbound;
  if (account.rating_state === "no_ratable_scores") return "暂无可评级成绩";
  return "待同步评级";
}
function chip(text, source = "") { return el("span", `chip ${source}`, text); }

function tableMessage(message) {
  const row = el("tr"), cell = el("td", "empty", message);
  cell.colSpan = 5;
  row.append(cell);
  $("users-body").replaceChildren(row);
}

function renderUsers(data) {
  for (const key of ["total", "bound", "unbound"]) $(`stat-${key}`).textContent = data.stats[key];
  const body = $("users-body"); body.replaceChildren();
  for (const row of data.items) {
    const tr = el("tr"), user = el("td"), sources = el("td"), sync = el("td"), rating = el("td"), action = el("td");
    user.append(el("span", "name", row.name));
    for (const source of row.bound_sources) sources.append(chip(names[source], source));
    if (!row.bound_sources.length) sources.append(chip("已解绑", "quiet"));
    sync.append(el("span", "", date(row.last_sync_at)));
    rating.append(el("span", row.rating === null ? "muted" : "rating", ratingText(row)), el("small", "", names[row.current_source]));
    if (row.rating_at) rating.append(el("small", "", `评级于 ${date(row.rating_at)}`));
    action.append(button("管理", "secondary", () => openAccount(row.owner_id)));
    tr.append(user, sources, sync, rating, action); body.append(tr);
  }
  if (!data.items.length) tableMessage(data.stats.total ? "没有符合条件的用户记录" : "暂无绑定记录");
  $("page-info").textContent = `共 ${data.total} 位用户 · 第 ${state.users.page} / ${state.users.pages} 页`;
}

function setListLoading(loading) {
  $("users-body").setAttribute("aria-busy", String(loading));
  $("previous").disabled = loading || state.users.page <= 1;
  $("next").disabled = loading || state.users.page >= state.users.pages;
}

async function loadUsers(page = state.users.page, filters = state.users.filters) {
  const list = state.users, version = ++list.version;
  setListLoading(true);
  notice("", false, "users-notice");
  if (!list.loaded) tableMessage("正在读取用户记录…");
  try {
    const data = await api("users", { page, page_size: pageSize, ...filters });
    if (version !== list.version) return;
    list.page = data.page;
    list.pages = Math.max(1, Math.ceil(data.total / data.page_size));
    list.filters = filters;
    renderUsers(data);
    list.loaded = true;
  } catch (error) {
    if (version !== list.version) return;
    if (!list.loaded) tableMessage("暂时无法显示用户记录");
    notice(error.message || "读取用户记录失败，请重试。", true, "users-notice");
  } finally {
    if (version === list.version) setListLoading(false);
  }
}

async function openAccount(owner) {
  const version = ++state.accountVersion;
  notice("", false, "notice");
  try {
    const account = await api("account", { owner_id: owner });
    if (version !== state.accountVersion || state.tab !== "users" || dialog.open) return;
    state.owner = owner;
    $("dialog-title").textContent = `用户 ${account.name}`;
    renderAccount($("dialog-content"), account);
    dialog.showModal();
  } catch (error) {
    if (version === state.accountVersion && state.tab === "users") throw error;
  }
}

async function loadBot() {
  if (state.pending?.is_bot) return;
  const container = $("bot-account"), version = ++state.botVersion;
  if (!container.querySelector(".account-summary")) {
    container.replaceChildren(el("p", "empty", "正在读取可可子账号…"));
  }
  try {
    const account = await api("account");
    if (version === state.botVersion) renderAccount(container, account);
  } catch (error) {
    if (version !== state.botVersion || state.tab !== "bot") return;
    if (!container.querySelector(".account-summary")) {
      container.replaceChildren(el("p", "empty", "暂时无法显示可可子账号"));
    }
    throw error;
  }
}

function field(text, input) { const label = el("label", "", text); label.append(input); return label; }
function input(name, type, placeholder, value = "") {
  const n = el("input"); n.name = name; n.type = type; n.placeholder = placeholder; n.value = value; n.required = true; return n;
}
function renderAccount(container, account) {
  container.replaceChildren();
  const summary = el("div", "account-summary"), info = el("div");
  info.append(el("span", "", `${names[account.current_source]} · 当前来源`));
  if (account.rating_at) info.append(el("small", "", `Rating 更新于 ${date(account.rating_at)}`));
  summary.append(el("strong", "", ratingText(account)), info); container.append(summary);
  const grid = el("div", "source-grid");
  for (const source of account.sources) {
    const card = el("article", "source-card"), header = el("div", "source-header"), badges = el("div");
    header.append(el("h3", "", names[source.source]));
    badges.append(chip(source.bound ? "已绑定" : source.ever_bound ? "已解绑" : "未绑定", source.bound ? source.source : "quiet"));
    if (account.current_source === source.source) badges.append(chip("当前来源"));
    header.append(badges); card.append(header);
    const dl = el("dl");
    const values = [["玩家 ID", source.player_id || "—"], ["服务器", source.server || "—"], ["最新同步", date(source.last_sync_at)], ["来源 Rating", ratingText(source, "未绑定")]];
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
    form.append(field(source.source === "kinoko" ? "菌菌 API Key" : "Sakura Token", token));
    if (source.source === "kinoko") {
      const row = el("div", "form-row"), player = input("player_id", "text", "玩家 ID", source.player_id);
      player.maxLength = 64; player.pattern = "[A-Za-z0-9_\\-]{1,64}";
      const server = el("select"); server.name = "server";
      for (const [value, text] of [["cn", "国服 cn"], ["jp", "日服 jp"], ["custom", "custom"]]) { const option = el("option", "", text); option.value = value; server.append(option); }
      server.value = ["cn", "jp", "custom"].includes(source.server) ? source.server : "cn";
      row.append(field("玩家 ID", player), field("服务器", server)); form.append(row);
    }
    form.append(el("small", "", "验证成功后自动设为当前来源。"));
    const submit = el("button", "", "验证并保存"); submit.type = "submit"; form.append(submit);
    form.onsubmit = (event) => {
      event.preventDefault();
      if (state.pending) return;
      const credentials = Object.fromEntries(new FormData(form));
      token.value = "";
      run(() => mutate(account, source, "bind", credentials), submit);
    };
    details.append(form); card.append(details); grid.append(card);
  }
  container.append(grid);
}

async function mutate(account, source, action, credentials = {}) {
  if (state.pending) return;
  state.pending = account;
  if (account.is_bot) state.botVersion++;
  const nodes = [...document.querySelectorAll(".account-content button, .account-content input, .account-content select")];
  nodes.forEach((n) => { n.disabled = true; });
  const messageRegion = () => !account.is_bot && dialog.open && state.owner === account.owner_id ? "dialog-notice" : "notice";
  const status = { sync: "正在同步成绩…", bind: "正在验证绑定凭据…", select: "正在切换来源…", unbind: "正在解绑…" };
  notice(status[action], false, messageRegion());
  try {
    const result = await bridge.apiPost("admin/action", { owner_id: account.owner_id, source: source.source, action, ...credentials });
    if (account.is_bot) renderAccount($("bot-account"), result.account);
    else if (messageRegion() === "dialog-notice") renderAccount($("dialog-content"), result.account);
    notice(result.message, false, messageRegion());
    if (!account.is_bot) void loadUsers();
  } catch (error) {
    let message = error.message || "操作失败，请重试。";
    const token = credentials.token?.trim();
    if (token && message.includes(token)) message = "验证绑定凭据失败，请检查后重试。";
    notice(message, true, messageRegion());
  } finally {
    state.pending = null;
    nodes.forEach((n) => { n.disabled = false; });
  }
}

async function tab(name) {
  state.tab = name;
  if (name !== "users") state.accountVersion++;
  for (const key of ["users", "bot"]) {
    $(`${key}-panel`).hidden = key !== name;
    if (key === name) $(`tab-${key}`).setAttribute("aria-current", "page"); else $(`tab-${key}`).removeAttribute("aria-current");
  }
  await (name === "users" ? loadUsers() : loadBot());
}
$("tab-users").onclick = () => run(() => tab("users"));
$("tab-bot").onclick = () => run(() => tab("bot"));
$("refresh").onclick = () => run(() => tab(state.tab), $("refresh"));
$("filters").onsubmit = (event) => {
  event.preventDefault();
  const filters = { q: $("search").value.trim(), source: $("source").value, status: $("status").value };
  void loadUsers(1, filters);
};
$("previous").onclick = () => loadUsers(state.users.page - 1);
$("next").onclick = () => loadUsers(state.users.page + 1);
$("close-dialog").onclick = () => dialog.close();
dialog.addEventListener("close", () => {
  state.owner = null;
  $("dialog-content").replaceChildren();
  notice("", false, "dialog-notice");
});
for (const [value, label] of Object.entries(names)) {
  $("source").append(new Option(label, value));
}
if (!bridge) notice("请从 AstrBot WebUI 的 RTLink 插件详情打开此管理页。", true);
else await run(async () => {
  const context = await bridge.ready();
  const theme = (value) => { document.documentElement.dataset.theme = value.isDark ? "dark" : "light"; };
  theme(context);
  if (bridge.onContext) bridge.onContext(theme);
  await loadUsers();
});
