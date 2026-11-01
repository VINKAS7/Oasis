// The extension's popup: choose what to record, start, finish. Finish saves a file to import in Oasis;
// logging in is optional and only fills in your workspaces and their suggested flows.

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

const show = (...nodes) => view.replaceChildren(...nodes.filter((n) => n != null && n !== false));
const errorBox = (msg) => (msg ? h("div", { class: "error" }, msg) : null);

function snake(s) {
  return String(s).toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
}

const callout = () =>
  h("div", { class: "callout" }, "Do the task like a customer would, all the way to the confirmation. It really happens on your site (a booking, order or message); undo it in your own system afterwards.");

// "Capture network requests" (on by default): the requests behind each step, which give the best
// tools. Switch it off for a site that misbehaves while recording; then only actions are recorded.
const captureBox = () => h("input", { type: "checkbox", checked: true });
const captureLabel = (box) =>
  h("label", { class: "check" }, box, h("span", {}, "Capture network requests ", h("span", { class: "muted" }, "(switch off if the site shows errors while recording)")));

async function start(options, button, error) {
  button.disabled = true;
  const r = await ask("start", { options });
  if (r?.error) {
    button.disabled = false;
    return error.replaceChildren(errorBox(r.error));
  }
  window.close();
}

// Without an Oasis login: name the flow and record the current site.
async function simpleView(state, note) {
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  const title = h("input", { type: "text", placeholder: "For example: Book an appointment" });
  const startUrl = h("input", { type: "url", value: /^https?:/.test(tab?.url || "") ? tab.url : "" });
  const currentTab = h("input", { type: "checkbox" });
  const capture = captureBox();
  const error = h("div");
  const startBtn = h("button", {
    class: "primary",
    onclick: () => {
      const t = title.value.trim();
      if (!t) return error.replaceChildren(errorBox("Say what the customer does, for example “Book an appointment” or “Request a quote”."));
      start({ flow: snake(t), title: t, startUrl: startUrl.value.trim(), useCurrentTab: currentTab.checked, capture: capture.checked }, startBtn, error);
    },
  }, "Start recording");
  show(
    note ? errorBox(note) : null,
    h("label", {}, "What will you record?", title),
    h("label", {}, "Start page", startUrl),
    h("label", { class: "check" }, currentTab, "Record in the current tab"),
    captureLabel(capture),
    callout(),
    h("p", { class: "muted" }, "Finish saves the recording as a file in Downloads. Import it in Oasis under Your tools."),
    error,
    h(
      "div",
      { class: "row" },
      h("button", { class: "link", onclick: () => chrome.tabs.create({ url: `${state.appUrl}/extension/connect` }) }, "Log in for your workspaces"),
      startBtn,
    ),
  );
}

async function idleView(state) {
  show(h("p", { class: "muted" }, "Loading your workspaces…"));
  const ctx = await ask("context");
  // Not reachable or logged out: record without workspaces; the file is imported in Oasis anyway.
  if (ctx?.error || !ctx.workspaces.length) return simpleView(state, ctx?.error && !ctx.error.includes("session") ? ctx.error : "");

  const workspace = h("select", {}, ctx.workspaces.map((w) => h("option", { value: w.id }, w.name)));
  const flow = h("select");
  const other = h("input", { type: "text", placeholder: "For example: Book an appointment", hidden: true });
  const startUrl = h("input", { type: "url" });
  const currentTab = h("input", { type: "checkbox" });
  const capture = captureBox();
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
    onclick: () => {
      const w = ctx.workspaces.find((x) => x.id === workspace.value);
      const chosen = w.flows.find((f) => f.flow === flow.value);
      const title = chosen ? chosen.title : other.value.trim();
      if (!title) return error.replaceChildren(errorBox("Say what the customer does, for example “Book an appointment” or “Request a quote”."));
      start({ workspaceId: w.id, workspaceName: w.name, flow: chosen ? chosen.flow : snake(title), title, startUrl: startUrl.value.trim(), useCurrentTab: currentTab.checked, capture: capture.checked }, startBtn, error);
    },
  }, "Start recording");

  show(
    h("label", {}, "Workspace", workspace),
    h("label", {}, "What will you record?", flow, other),
    h("label", {}, "Start page", startUrl),
    h("label", { class: "check" }, currentTab, "Record in the current tab"),
    captureLabel(capture),
    callout(),
    h("p", { class: "muted" }, "Finish saves the recording as a file in Downloads. Import it in the workspace under Your tools."),
    error,
    h("div", { class: "row" }, h("button", { class: "secondary", onclick: () => window.close() }, "Cancel"), startBtn),
  );
}

function recordingView(rec) {
  const saving = rec.status === "saving";
  show(
    h("div", { class: "rec" }, h("span", { class: "dot" }), saving ? "Saving…" : `Recording: ${rec.title}`),
    rec.workspaceName ? h("p", { class: "muted" }, rec.workspaceName) : null,
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

function resultView(rec, state) {
  if (rec.status === "saved") {
    const where = rec.workspaceId ? `${state.appUrl}/workspaces/${rec.workspaceId}` : `${state.appUrl}/workspaces`;
    return show(
      h("h1", {}, "Recording saved"),
      h("p", { class: "muted" }, "“", rec.title, "” is in your Downloads as ", h("b", {}, rec.result.filename.split("/").pop()), ". Passwords and personal details were masked."),
      rec.result.screenshots ? null : h("p", { class: "muted" }, "The step screenshots were left out to keep the file small."),
      h("div", { class: "callout" }, "In Oasis, open ", rec.workspaceName ? h("b", {}, rec.workspaceName) : "your workspace", ", then Your tools → Import recording. Oasis checks the file and builds the tool for you to approve."),
      h(
        "div",
        { class: "row" },
        h("button", { class: "secondary", onclick: () => ask("show-file") }, "Show file"),
        h("button", { class: "secondary", onclick: async () => { await ask("dismiss"); render(); } }, "Record another"),
        h("button", { class: "primary", onclick: async () => { chrome.tabs.create({ url: where }); await ask("dismiss"); } }, "Open Oasis"),
      ),
    );
  }
  show(
    h("h1", {}, "Couldn't save the file"),
    errorBox(rec.error),
    h(
      "div",
      { class: "row" },
      h("button", { class: "secondary", onclick: async () => { await ask("dismiss"); render(); } }, "Throw away"),
      h("button", { class: "primary", onclick: async () => { await ask("retry-save"); render(); } }, "Try again"),
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
  if (rec && (rec.status === "saved" || rec.status === "failed")) return resultView(rec, state);
  if (!state.connected) return simpleView(state);
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
