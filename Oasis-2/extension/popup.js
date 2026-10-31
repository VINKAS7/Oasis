// The extension's popup: log in through AgentReady, choose what to record, start, finish.

const view = document.getElementById("view");
const who = document.getElementById("who");
const ask = (type, data = {}) => chrome.runtime.sendMessage({ type, ...data });

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, "");
    else if (v !== false && v != null) el.setAttribute(k, v);
  }
  el.append(...children.flat().filter((c) => c != null && c !== false));
  return el;
}

const show = (...nodes) => view.replaceChildren(...nodes);
const errorBox = (msg) => (msg ? h("div", { class: "error" }, msg) : null);

function snake(s) {
  return String(s).toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
}

function loginView(state, error) {
  show(
    h("h1", {}, "Connect your AgentReady account"),
    h("p", { class: "muted" }, "Log in on the AgentReady website once. The extension then records flows on your own website and saves them to your workspace."),
    errorBox(error),
    h("div", { class: "row" }, h("button", { class: "primary", onclick: () => chrome.tabs.create({ url: `${state.appUrl}/extension/connect` }) }, "Log in")),
  );
}

async function idleView(state) {
  show(h("p", { class: "muted" }, "Loading your workspaces…"));
  const ctx = await ask("context");
  if (ctx?.error) return ctx.error.includes("session") ? loginView(state, ctx.error) : show(errorBox(ctx.error));
  if (!ctx.workspaces.length) {
    return show(
      h("h1", {}, "No workspace yet"),
      h("p", { class: "muted" }, "Create a workspace for your business on the AgentReady website first."),
      h("div", { class: "row" }, h("button", { class: "primary", onclick: () => chrome.tabs.create({ url: `${state.appUrl}/workspaces/new` }) }, "Open AgentReady")),
    );
  }

  const workspace = h("select", {}, ctx.workspaces.map((w) => h("option", { value: w.id }, w.name)));
  const flow = h("select");
  const other = h("input", { type: "text", placeholder: "For example: Book an appointment", hidden: true });
  const startUrl = h("input", { type: "url" });
  const currentTab = h("input", { type: "checkbox" });
  const error = h("div");

  function fillFlows() {
    const w = ctx.workspaces.find((x) => x.id === workspace.value);
    startUrl.value = w.website_url || "";
    flow.replaceChildren(
      ...w.flows.map((f) => h("option", { value: f.flow }, `${f.title}${f.recorded ? ` (recorded ${f.recorded}×)` : f.suggested ? " (to-do)" : ""}`)),
      h("option", { value: "__other" }, "Something else…"),
    );
    if (!w.flows.length) flow.value = "__other";
    other.hidden = flow.value !== "__other";
  }
  workspace.addEventListener("change", fillFlows);
  flow.addEventListener("change", () => (other.hidden = flow.value !== "__other"));
  fillFlows();

  const startBtn = h("button", {
    class: "primary",
    onclick: async () => {
      const w = ctx.workspaces.find((x) => x.id === workspace.value);
      const chosen = w.flows.find((f) => f.flow === flow.value);
      const title = chosen ? chosen.title : other.value.trim();
      if (!title) return error.replaceChildren(errorBox("Say what the customer does, for example “Book an appointment” or “Request a quote”."));
      startBtn.disabled = true;
      const r = await ask("start", {
        options: { workspaceId: w.id, workspaceName: w.name, flow: chosen ? chosen.flow : snake(title), title, startUrl: startUrl.value.trim(), useCurrentTab: currentTab.checked },
      });
      if (r?.error) {
        startBtn.disabled = false;
        return error.replaceChildren(errorBox(r.error));
      }
      window.close();
    },
  }, "Start recording");

  show(
    h("label", {}, "Workspace", workspace),
    h("label", {}, "What will you record?", flow, other),
    h("label", {}, "Start page", startUrl),
    h("label", { class: "check" }, currentTab, "Record in the current tab"),
    h("div", { class: "callout" }, "Do the task like a customer would, all the way to the confirmation. It really happens on your site (a booking, order or message); undo it in your own system afterwards."),
    error,
    h("div", { class: "row" }, h("button", { class: "secondary", onclick: () => window.close() }, "Cancel"), startBtn),
  );
}

function recordingView(rec) {
  const saving = rec.status === "saving";
  show(
    h("div", { class: "rec" }, h("span", { class: "dot" }), saving ? "Saving…" : `Recording: ${rec.title}`),
    h("p", { class: "muted" }, rec.workspaceName),
    h("div", { class: "stats" }, h("span", {}, h("b", {}, String(rec.steps)), " steps"), h("span", {}, h("b", {}, String(rec.actions)), " actions"), h("span", {}, h("b", {}, String(rec.requests)), " requests")),
    h("p", { class: "muted" }, "Write one sentence per step in the panel on the page."),
    h(
      "div",
      { class: "row" },
      h("button", { class: "secondary", disabled: saving, onclick: async () => { if (confirm("Discard this recording?")) { await ask("cancel"); render(); } } }, "Discard"),
      h("button", { class: "primary", disabled: saving, onclick: async () => { await ask("popup-finish"); render(); } }, "Finish"),
    ),
  );
}

function resultView(rec) {
  if (rec.status === "saved") {
    return show(
      h("h1", {}, "Recording saved"),
      h("p", { class: "muted" }, `“${rec.title}” is in ${rec.workspaceName}. Passwords and personal details were masked.`),
      h(
        "div",
        { class: "row" },
        h("button", { class: "secondary", onclick: async () => { await ask("dismiss"); render(); } }, "Record another"),
        h("button", { class: "primary", onclick: async () => { chrome.tabs.create({ url: rec.result.url }); await ask("dismiss"); } }, "Continue in AgentReady"),
      ),
    );
  }
  show(
    h("h1", {}, "Upload failed"),
    errorBox(rec.error),
    h(
      "div",
      { class: "row" },
      h("button", { class: "secondary", onclick: async () => { await ask("dismiss"); render(); } }, "Throw away"),
      h("button", { class: "primary", onclick: async () => { await ask("retry-upload"); render(); } }, "Try again"),
    ),
  );
}

let refresh = null;
async function render() {
  clearTimeout(refresh);
  const state = await ask("popup-state");
  document.getElementById("app-url").value = state.appUrl;
  who.textContent = state.user ? state.user.email : "";
  document.getElementById("logout").hidden = !state.connected;
  const rec = state.rec;
  if (rec && (rec.status === "recording" || rec.status === "saving")) {
    refresh = setTimeout(render, 1500); // live counts while the popup is open
    return recordingView(rec);
  }
  if (rec && (rec.status === "saved" || rec.status === "failed")) return resultView(rec);
  if (!state.connected) return loginView(state);
  return idleView(state);
}

document.getElementById("settings-toggle").addEventListener("click", () => {
  const s = document.getElementById("settings");
  s.hidden = !s.hidden;
});
document.getElementById("save-settings").addEventListener("click", async () => {
  await ask("set-app-url", { appUrl: document.getElementById("app-url").value.trim() });
  document.getElementById("settings").hidden = true;
  render();
});
document.getElementById("logout").addEventListener("click", async () => {
  await ask("logout");
  render();
});

render();
