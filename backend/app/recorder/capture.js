// Injected into every page and frame of the recording browser. Reports what the owner does
// (clicks, typing, choices, submits) to the recorder through window.__arRecord, and shows the
// owner's step panel in the top window. Password values never leave the page.
(() => {
  if (window.__agentReadyRecorder) return;
  window.__agentReadyRecorder = true;

  const HOST_ID = "agentready-recorder";
  const send = (kind, data) => {
    try {
      return window.__arRecord(kind, data || {});
    } catch (e) {
      return Promise.resolve(null);
    }
  };
  const clean = (s) => (s || "").replace(/\s+/g, " ").trim();
  const inPanel = (el) => !!(el && el.closest && el.closest("#" + HOST_ID));
  const quote = (s) => s.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
  const generatedId = (id) => /\d{4,}|[a-f0-9]{10,}|^:r|^(ember|react|radix|headlessui|mui)/i.test(id);
  const unique = (sel) => {
    try {
      return document.querySelectorAll(sel).length === 1;
    } catch (e) {
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

  // Prefer selectors a later replay can rely on: id, test ids, name, then visible text.
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
    if ((tag === "button" || tag === "a" || el.getAttribute("role")) && text && text.length <= 60) {
      return `${tag}:has-text("${quote(text)}")`;
    }
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
    return {
      selector: selectorFor(el),
      tag: el.tagName.toLowerCase(),
      input_type: (el.type || "").toLowerCase(),
      name: el.getAttribute("name") || "",
      id: el.id || "",
      label: labelOf(el),
      autocomplete: el.getAttribute("autocomplete") || "",
      text: ["form", "select", "textarea", "input"].includes(el.tagName.toLowerCase()) ? "" : clean(el.innerText || "").slice(0, 80),
    };
  }

  const CLICKABLE =
    "button, a, [role=button], [role=link], [role=option], [role=tab], [role=menuitem], [role=gridcell], " +
    "input[type=submit], input[type=button], input[type=image], label, summary, td, [onclick]";
  const TYPING = "input:not([type=submit]):not([type=button]):not([type=image]):not([type=checkbox]):not([type=radio]), textarea, select, option";

  document.addEventListener(
    "click",
    (e) => {
      const t = e.target;
      if (!t || !t.closest || inPanel(t)) return;
      const el = t.closest(CLICKABLE) || t;
      if (el.matches(TYPING) || el.matches("input[type=checkbox], input[type=radio]")) return; // recorded on change
      send("click", describe(el));
    },
    true,
  );

  document.addEventListener(
    "change",
    (e) => {
      const el = e.target;
      if (!el || !el.tagName || inPanel(el)) return;
      const d = describe(el);
      if (el.tagName === "SELECT") {
        const opt = el.selectedOptions && el.selectedOptions[0];
        send("select", { ...d, value: el.value, option_text: clean(opt ? opt.text : "") });
      } else if (el.type === "checkbox" || el.type === "radio") {
        send(el.checked ? "check" : "uncheck", { ...d, value: el.value });
      } else if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") {
        send("fill", { ...d, value: el.type === "password" ? "[MASKED]" : el.value, personal: el.type === "password" });
      }
    },
    true,
  );

  document.addEventListener(
    "keydown",
    (e) => {
      const el = e.target;
      if (e.key !== "Enter" || !el || el.tagName !== "INPUT" || inPanel(el)) return;
      // Enter can submit before "change" fires, so record the value first.
      const d = describe(el);
      send("fill", { ...d, value: el.type === "password" ? "[MASKED]" : el.value, personal: el.type === "password" });
      send("press", { ...d, key: "Enter" });
    },
    true,
  );

  document.addEventListener(
    "submit",
    (e) => {
      if (inPanel(e.target)) return;
      send("submit", describe(e.target));
    },
    true,
  );

  // --- the owner's panel (top window only) ----------------------------------------------
  if (window.top !== window) return;

  const STYLE = `
    :host { all: initial; }
    .panel { font: 13px/1.4 system-ui, -apple-system, "Segoe UI", sans-serif; color: #1c1917; width: 300px;
      background: #fff; border: 1px solid #d6d3d1; border-radius: 12px; box-shadow: 0 10px 30px rgba(0,0,0,.18); overflow: hidden; }
    .head { display: flex; align-items: center; gap: 8px; padding: 10px 12px; background: #115e59; color: #fff; font-weight: 600; }
    .dot { width: 9px; height: 9px; border-radius: 50%; background: #f87171; animation: pulse 1.4s infinite; }
    @keyframes pulse { 50% { opacity: .35; } }
    .title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .min { background: none; border: 0; color: #fff; cursor: pointer; font-size: 16px; padding: 0 2px; }
    .body { padding: 10px 12px 12px; }
    .step { font-weight: 600; margin-bottom: 4px; }
    .meta { color: #78716c; font-size: 12px; margin-bottom: 8px; }
    textarea { box-sizing: border-box; width: 100%; min-height: 58px; resize: vertical; font: inherit; padding: 6px 8px;
      border: 1px solid #d6d3d1; border-radius: 8px; }
    textarea:focus { outline: 2px solid #0d948855; border-color: #0d9488; }
    .row { display: flex; gap: 6px; margin-top: 8px; }
    button.b { flex: 1; font: inherit; font-weight: 600; padding: 7px 8px; border-radius: 8px; cursor: pointer; border: 1px solid #d6d3d1; background: #fff; }
    button.primary { background: #0f766e; border-color: #0f766e; color: #fff; }
    button.link { flex: 0; border: 0; background: none; color: #78716c; font-weight: 500; }
    .hint { color: #78716c; font-size: 12px; margin-top: 8px; }
    .hidden { display: none; }
  `;

  let state = null;
  let mounted = null;

  function mount() {
    if (document.getElementById(HOST_ID) || !document.documentElement) return;
    const host = document.createElement("div");
    host.id = HOST_ID;
    host.style.cssText = "position:fixed;right:16px;bottom:16px;z-index:2147483647;";
    const root = host.attachShadow({ mode: "open" });
    root.innerHTML = `<style>${STYLE}</style>
      <div class="panel">
        <div class="head"><span class="dot"></span><span class="title">Recording</span><button class="min" title="Minimise">–</button></div>
        <div class="body">
          <div class="step">Step 1</div>
          <div class="meta"></div>
          <textarea placeholder="In one sentence: what does the customer do on this step?"></textarea>
          <div class="row">
            <button class="b next">Next step</button>
            <button class="b primary finish">Finish</button>
          </div>
          <div class="row"><button class="b link cancel">Discard recording</button></div>
          <div class="hint">Do the task like a customer would. A new step starts by itself when the page changes.</div>
        </div>
      </div>`;
    document.documentElement.appendChild(host);
    const $ = (s) => root.querySelector(s);
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
      if (confirm("Discard this recording? Nothing will be saved.")) send("cancel", {});
    });
    mounted = { $, note, root };
    if (state) render(state);
  }

  function render(s) {
    if (!s) return;
    state = s;
    if (!mounted) return;
    const { $, note, root } = mounted;
    $(".title").textContent = "Recording: " + s.title;
    $(".step").textContent = "Step " + s.step;
    $(".meta").textContent = `${s.actions} action${s.actions === 1 ? "" : "s"} on this step · ${s.requests} request${s.requests === 1 ? "" : "s"} captured`;
    // Don't overwrite what the owner is typing.
    if (root.activeElement !== note && note.value !== (s.note || "")) note.value = s.note || "";
  }

  send("state").then(render);
  // Keep the panel's counts fresh and put it back if the page replaces the document.
  setInterval(() => {
    mount();
    send("state").then(render);
  }, 1500);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
  else mount();
})();
