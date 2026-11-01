// Runs in every page and frame, but stays asleep unless this tab is being recorded.
// - In the recording tab: reports clicks, typing, choices and submits to the background worker,
//   and shows the owner's step panel (top frame only, in its own shadow root). Nothing else in
//   the page is added or changed.
// - On Oasis's /extension/connect page: passes the signed-in session to the extension.
(() => {
  if (window.__agentReadyRecorder) return;
  window.__agentReadyRecorder = true;

  const HOST_ID = "agentready-recorder";
  const isTop = window.top === window;
  const inPanel = (el) => !!(el && el.closest && el.closest("#" + HOST_ID));

  const send = (type, data = {}) =>
    new Promise((resolve) => {
      try {
        chrome.runtime.sendMessage({ type, ...data }, (reply) => {
          void chrome.runtime.lastError; // the worker may be waking up
          resolve(reply ?? null);
        });
      } catch {
        resolve(null); // the extension was reloaded; this page is stale
      }
    });

  // --- Oasis's connect page ----------------------------------------------------------
  if (isTop && location.pathname.startsWith("/extension/connect")) {
    window.addEventListener("message", async (e) => {
      if (e.source !== window || e.data?.source !== "agentready-app") return;
      if (e.data.type === "ping") {
        window.postMessage({ source: "agentready-extension", type: "present" }, location.origin);
      } else if (e.data.type === "token") {
        const reply = await send("token", { token: e.data.token, user: e.data.user });
        window.postMessage({ source: "agentready-extension", type: reply?.ok ? "connected" : "rejected", reason: reply?.error || "" }, location.origin);
      }
    });
  }

  // --- recording -------------------------------------------------------------------------
  const clean = (s) => (s || "").replace(/\s+/g, " ").trim();
  const quote = (s) => s.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
  const generatedId = (id) => /\d{4,}|[a-f0-9]{10,}|^:r|^(ember|react|radix|headlessui|mui)/i.test(id);
  const unique = (sel) => {
    try {
      return document.querySelectorAll(sel).length === 1;
    } catch {
      return false;
    }
  };

  function labelOf(el) {
    if (el.labels && el.labels.length) return clean(el.labels[0].innerText);
    const by = el.getAttribute("aria-labelledby");
    if (by) {
      const l = document.getElementById(by.split(" ")[0]);
      if (l) return clean(l.innerText);
    }
    return clean(el.getAttribute("aria-label") || el.getAttribute("placeholder") || el.getAttribute("title") || "");
  }

  // Prefer selectors a replay can rely on: id, test ids, name, then visible text.
  function selectorFor(el) {
    const tag = el.tagName.toLowerCase();
    if (el.id && !generatedId(el.id) && unique("#" + CSS.escape(el.id))) return "#" + CSS.escape(el.id);
    for (const attr of ["data-testid", "data-test", "data-qa", "name", "aria-label"]) {
      const v = el.getAttribute(attr);
      if (v) {
        const sel = `${tag}[${attr}="${quote(v)}"]`;
        if (unique(sel)) return sel;
      }
    }
    const text = clean(el.innerText || el.value || "");
    if ((tag === "button" || tag === "a" || el.getAttribute("role")) && text && text.length <= 60) return `${tag}:has-text("${quote(text)}")`;
    const parts = [];
    let cur = el;
    while (cur && cur.nodeType === 1 && cur !== document.body && parts.length < 6) {
      if (cur.id && !generatedId(cur.id)) {
        parts.unshift("#" + CSS.escape(cur.id));
        break;
      }
      let part = cur.tagName.toLowerCase();
      const parent = cur.parentElement;
      if (parent) {
        const same = [...parent.children].filter((c) => c.tagName === cur.tagName);
        if (same.length > 1) part += `:nth-of-type(${same.indexOf(cur) + 1})`;
      }
      parts.unshift(part);
      cur = parent;
    }
    return parts.join(" > ");
  }

  function describe(el) {
    const tag = el.tagName.toLowerCase();
    return {
      selector: selectorFor(el),
      tag,
      input_type: (el.type || "").toLowerCase(),
      name: el.getAttribute("name") || "",
      id: el.id || "",
      label: labelOf(el),
      autocomplete: el.getAttribute("autocomplete") || "",
      text: ["form", "select", "textarea", "input"].includes(tag) ? "" : clean(el.innerText || "").slice(0, 80),
    };
  }

  const report = (type, el, extra = {}) => send("action", { action: { type, ...describe(el), ...extra } });

  const CLICKABLE =
    "button, a, [role=button], [role=link], [role=option], [role=tab], [role=menuitem], [role=gridcell], " +
    "input[type=submit], input[type=button], input[type=image], label, summary, td, [onclick]";
  const TYPING = "input:not([type=submit]):not([type=button]):not([type=image]):not([type=checkbox]):not([type=radio]), textarea, select, option";

  let listening = false;
  function listen() {
    if (listening) return;
    listening = true;
    document.addEventListener(
      "click",
      (e) => {
        const t = e.target;
        if (!t || !t.closest || inPanel(t)) return;
        const el = t.closest(CLICKABLE) || t;
        if (el.matches(TYPING) || el.matches("input[type=checkbox], input[type=radio]")) return; // recorded on change
        report("click", el);
      },
      true,
    );
    document.addEventListener(
      "change",
      (e) => {
        const el = e.target;
        if (!el || !el.tagName || inPanel(el)) return;
        if (el.tagName === "SELECT") {
          const opt = el.selectedOptions && el.selectedOptions[0];
          report("select", el, { value: el.value, option_text: clean(opt ? opt.text : "") });
        } else if (el.type === "checkbox" || el.type === "radio") {
          report(el.checked ? "check" : "uncheck", el, { value: el.value });
        } else if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") {
          report("fill", el, { value: el.type === "password" ? "[MASKED]" : el.value, personal: el.type === "password" });
        }
      },
      true,
    );
    document.addEventListener(
      "keydown",
      (e) => {
        const el = e.target;
        if (e.key !== "Enter" || !el || el.tagName !== "INPUT" || inPanel(el)) return;
        report("fill", el, { value: el.type === "password" ? "[MASKED]" : el.value, personal: el.type === "password" });
        report("press", el, { key: "Enter" });
      },
      true,
    );
    document.addEventListener(
      "submit",
      (e) => {
        if (!inPanel(e.target)) report("submit", e.target);
      },
      true,
    );
  }

  // --- the owner's panel (top frame only) --------------------------------------------------
  const STYLE = `
    :host { all: initial; }
    .panel { font: 13px/1.45 ui-sans-serif, -apple-system, "Segoe UI", sans-serif; color: #37352f; width: 300px; background: #fff;
      border: 1px solid rgba(55,53,47,.16); border-radius: 10px; box-shadow: 0 12px 32px rgba(15,15,15,.16); overflow: hidden; }
    .head { display: flex; align-items: center; gap: 8px; padding: 10px 12px; border-bottom: 1px solid rgba(55,53,47,.09); font-weight: 600; }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: #eb5757; animation: pulse 1.4s infinite; }
    @keyframes pulse { 50% { opacity: .3; } }
    .title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .min { background: none; border: 0; color: #787774; cursor: pointer; font-size: 16px; padding: 0 2px; }
    .body { padding: 10px 12px 12px; }
    .step { font-weight: 600; }
    .meta { color: #787774; font-size: 12px; margin: 2px 0 8px; }
    textarea { box-sizing: border-box; width: 100%; min-height: 58px; resize: vertical; font: inherit; color: inherit; padding: 6px 8px;
      border: 1px solid rgba(55,53,47,.16); border-radius: 6px; background: #fbfbfa; }
    textarea:focus { outline: 2px solid rgba(13,138,120,.35); border-color: #0d8a78; background: #fff; }
    .row { display: flex; gap: 6px; margin-top: 8px; }
    button.b { flex: 1; font: inherit; font-weight: 500; padding: 6px 8px; border-radius: 6px; cursor: pointer; border: 1px solid rgba(55,53,47,.16);
      background: #fff; color: #37352f; }
    button.b:hover { background: rgba(55,53,47,.06); }
    button.primary { background: #0d8a78; border-color: #0d8a78; color: #fff; }
    button.primary:hover { background: #0a6f61; }
    button.link { flex: 0 0 auto; white-space: nowrap; border: 0; background: none; color: #787774; padding-left: 0; }
    .hint { color: #787774; font-size: 12px; margin-top: 8px; }
    .hidden { display: none; }`;

  let panel = null;
  let state = null;

  function mountPanel() {
    if (!isTop || document.getElementById(HOST_ID) || !document.documentElement) return;
    const host = document.createElement("div");
    host.id = HOST_ID;
    host.style.cssText = "position:fixed;right:16px;bottom:16px;z-index:2147483647;";
    const root = host.attachShadow({ mode: "open" });
    root.innerHTML = `<style>${STYLE}</style>
      <div class="panel">
        <div class="head"><span class="dot"></span><span class="title">Recording</span><button class="min" title="Minimise">–</button></div>
        <div class="body">
          <div class="live">
            <div class="step">Step 1</div>
            <div class="meta"></div>
            <textarea placeholder="In one sentence: what does the customer do on this step?"></textarea>
            <div class="row"><button class="b next">Next step</button><button class="b primary finish">Finish</button></div>
            <div class="row"><button class="b link cancel">Discard recording</button></div>
            <div class="hint">Do the task like a customer would. A new step starts by itself when the page changes.</div>
          </div>
          <div class="done hidden"></div>
        </div>
      </div>`;
    document.documentElement.appendChild(host);
    const $ = (sel) => root.querySelector(sel);
    const note = $("textarea");
    let timer = null;
    note.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(() => send("note", { text: note.value }), 400);
    });
    $(".min").addEventListener("click", () => $(".body").classList.toggle("hidden"));
    $(".next").addEventListener("click", async () => {
      clearTimeout(timer);
      render(await send("next_step", { text: note.value }));
    });
    $(".finish").addEventListener("click", () => {
      clearTimeout(timer);
      $(".finish").textContent = "Saving…";
      $(".finish").disabled = true;
      send("finish", { text: note.value });
    });
    $(".cancel").addEventListener("click", () => {
      if (confirm("Discard this recording? Nothing will be saved.")) send("cancel");
    });
    panel = { $, note, root, host };
    if (state) render(state);
  }

  function render(s) {
    if (!s) return;
    state = s;
    if (!panel) return;
    const { $, note, root } = panel;
    $(".title").textContent = "Recording: " + s.title;
    $(".step").textContent = "Step " + s.step;
    $(".meta").textContent = `${s.actions} action${s.actions === 1 ? "" : "s"} on this step · ${s.requests} request${s.requests === 1 ? "" : "s"} captured`;
    if (root.activeElement !== note && note.value !== (s.note || "")) note.value = s.note || ""; // don't overwrite typing
  }

  function showDone(msg) {
    if (!panel) return;
    const { $ } = panel;
    $(".live").classList.add("hidden");
    $(".dot").style.background = msg.status === "saved" ? "#0f7b6c" : "#eb5757";
    $(".dot").style.animation = "none";
    $(".title").textContent = msg.status === "saved" ? "Recording saved" : "Couldn't save the file";
    const done = $(".done");
    done.classList.remove("hidden");
    if (msg.status === "saved") {
      const name = String(msg.filename || "").split("/").pop();
      done.textContent = `Saved to Downloads as ${name}. Passwords and personal details were masked. In Oasis, open your workspace → Your tools → Import recording.`;
    } else {
      done.textContent = `${msg.error || "Could not save the file."} Open the extension to try again.`;
    }
  }

  let active = false;
  let tick = null;
  function activate(initial) {
    if (active) return;
    active = true;
    listen();
    if (!isTop) return;
    state = initial;
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mountPanel);
    else mountPanel();
    // Keep the panel fresh, put it back if the page replaces the document, and keep the
    // extension's worker awake while recording.
    const port = chrome.runtime.connect({ name: "keepalive" });
    tick = setInterval(async () => {
      try {
        port.postMessage("ping");
      } catch {
        /* reconnects on the next page */
      }
      mountPanel();
      const s = await send("state");
      if (s) render(s);
    }, 1500);
  }

  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === "saved" && isTop) {
      clearInterval(tick);
      showDone(msg);
    } else if (msg.type === "discarded" && isTop) {
      clearInterval(tick);
      panel?.host.remove();
      panel = null;
    }
  });

  send("hello").then((reply) => {
    if (reply?.recording) activate(reply.panel);
  });
})();
