// Shared by Oasis's MCP App views: the JSON-RPC bridge with the assistant (MCP Apps, protocol
// 2026-01-26) and ChatGPT's older window.openai bridge, theme and fonts from the host, the host's
// language, resizing, and small helpers. Inlined into each view by apps.py (the sandbox can't
// load scripts from elsewhere).
const Oasis = (() => {
  "use strict";
  const PROTOCOL = "2026-01-26";
  let nextId = 1, connected = false, ctx = {};
  const pending = new Map(), listeners = {};
  const post = (msg) => window.parent.postMessage({ jsonrpc: "2.0", ...msg }, "*");
  const request = (method, params) => new Promise((resolve, reject) => {
    const id = nextId++;
    pending.set(id, { resolve, reject });
    post({ id, method, params });
  });
  const notify = (method, params) => post({ method, params });
  const emit = (kind, value) => (listeners[kind] || []).forEach((f) => { try { f(value); } catch (e) { console.error(e); } });
  const on = (kind, f) => { (listeners[kind] = listeners[kind] || []).push(f); };

  window.addEventListener("message", (event) => {
    if (event.source !== window.parent) return;
    const m = event.data;
    if (!m || m.jsonrpc !== "2.0") return;
    if (m.id !== undefined && !m.method) {
      const p = pending.get(m.id);
      if (!p) return;
      pending.delete(m.id);
      m.error ? p.reject(new Error(m.error.message || "The assistant refused the request.")) : p.resolve(m.result);
      return;
    }
    if (m.method === "ui/notifications/tool-input") emit("input", (m.params && m.params.arguments) || {});
    else if (m.method === "ui/notifications/tool-result") emit("result", (m.params && (m.params.structuredContent || m.params)) || {});
    else if (m.method === "ui/notifications/host-context-changed") applyContext(m.params);
    if (m.id !== undefined) post({ id: m.id, result: {} });  // ui/resource-teardown, ping...
  });

  // ---- language: the assistant's locale (en, fr, it, de), English otherwise ----
  const LANGS = ["en", "fr", "it", "de"];
  const pick = (l) => { const c = String(l || "").slice(0, 2).toLowerCase(); return LANGS.includes(c) ? c : "en"; };
  let lang = pick(navigator.language);
  document.documentElement.lang = lang;

  function applyContext(c) {
    if (!c) return;
    ctx = { ...ctx, ...c };
    if (c.theme) document.documentElement.classList.toggle("dark", c.theme === "dark");
    const vars = c.styles && c.styles.variables;
    if (vars) for (const [k, v] of Object.entries(vars)) if (k.startsWith("--font") && v) document.documentElement.style.setProperty(k, v);
    if (c.locale && pick(c.locale) !== lang) { lang = pick(c.locale); document.documentElement.lang = lang; }
    emit("context", ctx);
  }
  if (window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches) document.documentElement.classList.add("dark");

  /** strings: {en: {...}, fr: {...}}; English text is the fallback; {name} placeholders from vars. */
  const t = (strings, key, vars) => {
    const s = (strings[lang] && strings[lang][key]) || (strings.en && strings.en[key]) || key;
    return vars ? s.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m)) : s;
  };
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // Tell the assistant how tall the view is, so the frame fits it: the MCP Apps message, and
  // ChatGPT's own call (its frames may not size from the message alone).
  let lastHeight = 0;
  new ResizeObserver(() => {
    const height = Math.ceil(document.documentElement.getBoundingClientRect().height);
    if (height !== lastHeight) {
      lastHeight = height;
      notify("ui/notifications/size-changed", { height });
      try { if (window.openai && window.openai.notifyIntrinsicHeight) window.openai.notifyIntrinsicHeight(height); } catch { /* not ChatGPT */ }
    }
  }).observe(document.body);

  const oa = () => (!connected && window.openai) || null;  // ChatGPT's older bridge, when MCP Apps didn't answer

  async function callTool(name, args) {
    if (oa() && window.openai.callTool) {
      const r = await window.openai.callTool(name, args);
      return (r && (r.structuredContent || r)) || {};
    }
    const r = await request("tools/call", { name, arguments: args });
    const data = (r && r.structuredContent) || {};
    if ((r && r.isError) || data.ok === false) throw new Error(data.message || "That didn't work. Try again.");
    return data;
  }
  function openLink(url) {
    if (oa() && window.openai.openExternal) return window.openai.openExternal({ href: url });
    request("ui/open-link", { url }).catch(() => window.open(url, "_blank", "noopener,noreferrer"));
  }
  /** Sends text as the user's next message in the conversation. */
  async function say(text) {
    if (oa() && window.openai.sendFollowUpMessage) return window.openai.sendFollowUpMessage({ prompt: text });
    return request("ui/message", { role: "user", content: [{ type: "text", text }] });
  }
  /** Tells the model something without a visible message (what the user did in the view). */
  function tellModel(text) {
    request("ui/update-model-context", { content: [{ type: "text", text }] }).catch(() => undefined);
  }
  const canFullscreen = () => (ctx.availableDisplayModes || []).includes("fullscreen") || !!(oa() && window.openai.requestDisplayMode);
  const displayMode = () => ctx.displayMode || (window.openai && window.openai.displayMode) || "inline";
  async function setDisplayMode(mode) {
    try {
      if (oa() && window.openai.requestDisplayMode) { await window.openai.requestDisplayMode({ mode }); ctx.displayMode = mode; }
      else { const r = await request("ui/request-display-mode", { mode }); ctx.displayMode = (r && r.mode) || mode; }
    } catch { /* the host said no */ }
    emit("context", ctx);
    return ctx.displayMode;
  }
  /** View state the host keeps with this message (ChatGPT), so an answered question stays answered. */
  const saved = () => (window.openai && window.openai.widgetState) || null;
  const save = (state) => { try { if (window.openai && window.openai.setWidgetState) window.openai.setWidgetState(state); } catch { /* ignore */ } };

  function start(name, version) {
    request("ui/initialize", { appInfo: { name, version }, appCapabilities: {}, protocolVersion: PROTOCOL })
      .then((r) => { connected = true; applyContext(r && r.hostContext); notify("ui/notifications/initialized", {}); })
      .catch(() => undefined);
    const fromOpenAI = () => {
      if (connected || !window.openai) return;
      applyContext({ theme: window.openai.theme, locale: window.openai.locale, displayMode: window.openai.displayMode });
      if (window.openai.toolInput) emit("input", window.openai.toolInput);
      if (window.openai.toolOutput) emit("result", window.openai.toolOutput);
    };
    window.addEventListener("openai:set_globals", fromOpenAI);
    setTimeout(fromOpenAI, 300);
  }

  const icon = (path) => `<svg class="ico" viewBox="0 0 24 24" aria-hidden="true">${path}</svg>`;
  const ICONS = {
    check: '<path d="M20 6 9 17l-5-5"/>',
    x: '<path d="M18 6 6 18M6 6l12 12"/>',
    star: '<path d="m12 2 3.1 6.3 6.9 1-5 4.9 1.2 6.8L12 17.8 5.8 21l1.2-6.8-5-4.9 6.9-1z"/>',
    phone: '<path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.7 2z"/>',
    globe: '<circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15.3 15.3 0 0 1 0 20 15.3 15.3 0 0 1 0-20"/>',
    route: '<circle cx="6" cy="19" r="3"/><path d="M9 19h8.5a3.5 3.5 0 0 0 0-7h-11a3.5 3.5 0 0 1 0-7H15"/><circle cx="18" cy="5" r="3"/>',
    clock: '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    pin: '<path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z"/><circle cx="12" cy="10" r="3"/>',
    bag: '<path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/><path d="M3 6h18M16 10a4 4 0 0 1-8 0"/>',
    expand: '<path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/>',
    shrink: '<path d="M4 14h6v6M20 10h-6V4M14 10l7-7M3 21l7-7"/>',
    send: '<path d="m22 2-7 20-4-9-9-4z"/><path d="M22 2 11 13"/>',
  };

  return { on, start, t, esc, callTool, openLink, say, tellModel, canFullscreen, displayMode, setDisplayMode, saved, save, icon, ICONS,
           get lang() { return lang; }, get context() { return ctx; } };
})();
