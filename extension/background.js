// Oasis Recorder: records one flow in the owner's own Chrome tab.
//
// - content.js reports clicks, typing and submits, and shows the owner's step panel;
// - chrome.debugger (Network + Fetch domains) captures the messages the site sends its server;
// - a new step starts whenever the page changes; each step gets a screenshot;
// - everything is masked (clean.js) as it arrives; on Finish the recording is uploaded to
//   Oasis, which cleans it again, and the owner continues there.
//
// The service worker can be stopped by Chrome at any time, so the recording lives in
// chrome.storage.local and is reloaded on wake-up.

import { cleanAction, isNoise, maskText, maskUrl, parseBody } from "./clean.js";

const DEFAULT_APP = "http://localhost:5173";
const KEPT_TYPES = new Set(["Document", "XHR", "Fetch"]);

let rec = null; // the recording in progress (mirrored to storage)
let loading = null;
const pending = new Map(); // CDP requestId -> request being captured
let lastShot = 0;
const shotTimers = {};

// --- storage ---------------------------------------------------------------------------

async function settings() {
  const s = await chrome.storage.local.get(["appUrl", "token", "user"]);
  return { appUrl: (s.appUrl || DEFAULT_APP).replace(/\/+$/, ""), token: s.token || "", user: s.user || null };
}

function load() {
  // Once per worker start; every event waits for the same read of storage.
  loading ??= (async () => {
    const s = await chrome.storage.local.get("rec");
    rec = s.rec || null;
    if (rec?.status === "recording" && rec.capture !== false) {
      try {
        await attach(rec.tabId);
      } catch {
        /* the tab may be gone; Finish still saves what was captured */
      }
    }
  })();
  return loading;
}

const save = () => chrome.storage.local.set({ rec });

async function clearShots() {
  const all = await chrome.storage.local.get(null);
  await chrome.storage.local.remove(Object.keys(all).filter((k) => k.startsWith("shot:")));
}

// --- API -------------------------------------------------------------------------------

async function api(path, options = {}) {
  const { appUrl, token } = await settings();
  const res = await fetch(appUrl + path, {
    ...options,
    headers: { "content-type": "application/json", ...(token ? { authorization: `Bearer ${token}` } : {}), ...(options.headers || {}) },
  });
  const body = await res.json().catch(() => null);
  if (res.status === 401) {
    await chrome.storage.local.remove(["token", "user"]);
    const err = new Error("Your Oasis session ended. Log in again.");
    err.status = 401;
    throw err;
  }
  if (!res.ok) {
    const d = body?.detail;
    throw new Error(typeof d === "string" ? d : d ? JSON.stringify(d) : `Oasis answered ${res.status}`);
  }
  return body;
}

// --- steps -----------------------------------------------------------------------------

const known = () => new Set(rec?.known || []);
const current = () => rec.steps[rec.steps.length - 1];
const noHash = (u) => String(u || "").split("#")[0];

function siteKey(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

function pageLabel(url) {
  if (siteKey(url) && siteKey(url) === siteKey(rec.site)) {
    const u = new URL(url);
    return maskText(u.pathname + u.search, known());
  }
  return maskUrl(url, known());
}

function newStep(url, force = false) {
  rec.currentUrl = url;
  const cur = rec.steps.length ? current() : null;
  if (cur && !force && !cur.actions.length && !cur.requests.length && !cur.owner_note) {
    cur.url = maskUrl(url, known());
    cur.page = pageLabel(url);
    return;
  }
  rec.steps.push({ n: rec.steps.length + 1, page: pageLabel(url), url: maskUrl(url, known()), owner_note: "", screenshot: false, actions: [], requests: [] });
}

function panelState() {
  if (!rec) return null;
  const step = current();
  return {
    title: rec.title,
    step: step.n,
    note: step.owner_note,
    actions: step.actions.length,
    requests: rec.steps.reduce((n, s) => n + s.requests.length, 0),
    status: rec.status,
  };
}

// --- network capture (Chrome's debugging interface) ------------------------------------

async function attach(tabId) {
  try {
    await chrome.debugger.attach({ tabId }, "1.3");
  } catch (e) {
    const msg = String(e?.message || e);
    if (msg.includes("Another debugger")) {
      throw new Error("Chrome DevTools is open on that tab. Close it and try again.");
    }
    if (!msg.includes("Already attached")) throw e;
  }
  // Only watch: the recorder never holds, changes or blocks the page's requests, so the site
  // behaves exactly as it does without recording. Answers are read once each request finishes.
  await chrome.debugger.sendCommand({ tabId }, "Network.enable", { maxPostDataSize: 65536 });
}

async function detach() {
  if (!rec || rec.capture === false) return;
  try {
    await chrome.debugger.detach({ tabId: rec.tabId });
  } catch {
    /* already detached */
  }
}

const header = (headers, name) => {
  for (const [k, v] of Object.entries(headers || {})) if (k.toLowerCase() === name) return v;
  return "";
};

function addRequest(p, rawBody, error) {
  const k = known();
  const entry = {
    method: p.method,
    url: pageLabel(p.url),
    type: p.type,
    content_type: String(p.contentType || "").split(";")[0],
    body: parseBody(p.postData, p.contentType, k),
  };
  if (error) entry.error = error;
  else if (p.status != null) {
    entry.response = { status: p.status, content_type: p.mimeType || "", body: rawBody != null && /json|text/.test(p.mimeType || "") ? parseBody(rawBody, p.mimeType, k, true) : null };
  }
  const step = rec.steps.find((s) => s.n === p.step) || current();
  step.requests.push(entry);
  save();
}

chrome.debugger.onEvent.addListener(async (source, method, params) => {
  const target = { tabId: source.tabId };
  await load();
  if (!rec || rec.status !== "recording" || source.tabId !== rec.tabId) return;
  if (method === "Network.requestWillBeSent") {
    const r = params.request;
    if (!KEPT_TYPES.has(params.type) || (params.type === "Document" && r.method === "GET")) return;
    if (!/^https?:/.test(r.url) || isNoise(r.url)) return; // tracking, ads, icons, styles, fonts
    pending.set(params.requestId, {
      step: current().n,
      method: r.method,
      url: r.url,
      type: params.type.toLowerCase(),
      contentType: header(r.headers, "content-type"),
      postData: r.postData ?? null,
      hasPostData: Boolean(r.hasPostData),
    });
  } else if (method === "Network.responseReceived") {
    const p = pending.get(params.requestId);
    if (p) {
      p.status = params.response.status;
      p.mimeType = params.response.mimeType;
      if (isNoise(p.url, p.mimeType)) pending.delete(params.requestId); // a static file after all
    }
  } else if (method === "Network.loadingFinished") {
    const p = pending.get(params.requestId);
    if (!p) return;
    pending.delete(params.requestId);
    let body = null;
    if (p.type !== "document" && /json|text/.test(p.mimeType || "")) {
      try {
        const res = await chrome.debugger.sendCommand(target, "Network.getResponseBody", { requestId: params.requestId });
        body = res.base64Encoded ? atob(res.body) : res.body;
      } catch {
        /* the page moved on; the status is still kept */
      }
    }
    if (p.hasPostData && p.postData == null) {
      try {
        p.postData = (await chrome.debugger.sendCommand(target, "Network.getRequestPostData", { requestId: params.requestId })).postData;
      } catch {
        /* not available */
      }
    }
    addRequest(p, body);
  } else if (method === "Network.loadingFailed") {
    const p = pending.get(params.requestId);
    if (!p) return;
    pending.delete(params.requestId);
    addRequest(p, null, params.errorText || "failed");
  }
});

chrome.debugger.onDetach.addListener(async (source, reason) => {
  await load();
  // The owner pressed "Cancel" on Chrome's "started debugging this browser" bar: save what we have.
  if (rec?.status === "recording" && source.tabId === rec.tabId && reason === "canceled_by_user") finish();
});

// --- pages -------------------------------------------------------------------------------

async function onPage(details) {
  await load();
  if (!rec || rec.status !== "recording" || details.tabId !== rec.tabId || details.frameId !== 0) return;
  if (!/^https?:/.test(details.url)) return;
  if (noHash(details.url) !== noHash(rec.currentUrl) || current().actions.length) newStep(details.url);
  else rec.currentUrl = details.url;
  save();
}
chrome.webNavigation.onCommitted.addListener(onPage);
chrome.webNavigation.onHistoryStateUpdated.addListener(onPage);
chrome.webNavigation.onCompleted.addListener(async (d) => {
  await load();
  if (rec?.status === "recording" && d.tabId === rec.tabId && d.frameId === 0) scheduleShot("load", 800);
});
chrome.tabs.onRemoved.addListener(async (tabId) => {
  await load();
  if (rec?.status === "recording" && tabId === rec.tabId) finish(); // closing the tab is Finish
});

// --- screenshots -----------------------------------------------------------------------

function scheduleShot(slot, delay) {
  clearTimeout(shotTimers[slot]);
  const n = current().n;
  shotTimers[slot] = setTimeout(() => {
    if (rec?.status === "recording" && current().n === n) shot();
  }, delay);
}

// For a screenshot: hide the step panel and cover personal fields (by type and autocomplete, and
// the fields this recording found personal). Applied by Chrome as a user style sheet, so the
// page's own document is never touched.
const COVER = "{ color: transparent !important; -webkit-text-fill-color: transparent !important; text-shadow: none !important; background: #a8a29e !important; }";
const PERSONAL_FIELDS =
  "input[type=password], input[type=email], input[type=tel], input[autocomplete~=name], input[autocomplete^=given], " +
  "input[autocomplete^=family], input[autocomplete^=cc-], input[autocomplete^=tel], input[autocomplete^=email], input[autocomplete*=address]";

function shotCss() {
  const own = new Set();
  for (const s of rec.steps) for (const a of s.actions) if (a.personal && a.selector && !a.selector.includes(":has-text")) own.add(a.selector);
  const cover = [PERSONAL_FIELDS, ...own].map((sel) => `${sel} ${COVER}`);
  return ["#agentready-recorder { display: none !important; }", ...cover].join("\n");
}

async function shot() {
  if (!rec || rec.status !== "recording") return;
  const wait = 600 - (Date.now() - lastShot); // Chrome allows two captures a second
  if (wait > 0) await new Promise((r) => setTimeout(r, wait));
  lastShot = Date.now();
  const step = current();
  const tab = await chrome.tabs.get(rec.tabId).catch(() => null);
  if (!tab || !tab.active) return;
  let dataUrl = null;
  let css = "";
  let target = null;
  try {
    // Cover personal fields in every frame first.
    css = shotCss();
    // Every frame if possible; a frame Chrome won't style (about:blank, a sandboxed embed) falls
    // back to the page itself. If even that fails, no screenshot is taken.
    target = { tabId: rec.tabId, allFrames: true };
    await chrome.scripting.insertCSS({ target, css, origin: "USER" }).catch(() => {
      target = { tabId: rec.tabId, frameIds: [0] };
      return chrome.scripting.insertCSS({ target, css, origin: "USER" });
    });
    await new Promise((r) => setTimeout(r, 60));
    dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: "jpeg", quality: 60 });
  } catch {
    /* the window is minimised or not focused, or the page can't be styled (no screenshot then) */
  } finally {
    if (target) chrome.scripting.removeCSS({ target, css, origin: "USER" }).catch(() => {});
  }
  const after = await chrome.tabs.get(rec.tabId).catch(() => null);
  if (!dataUrl || current() !== step || !after || after.url !== tab.url) return; // the page moved on meanwhile
  await chrome.storage.local.set({ [`shot:${step.n}`]: dataUrl });
  step.screenshot = true;
  save();
}

// --- start / finish ----------------------------------------------------------------------

async function start({ workspaceId, workspaceName, flow, title, startUrl, useCurrentTab, capture = true }) {
  await load();
  if (rec?.status === "recording" || rec?.status === "saving") throw new Error("A recording is already running.");
  if (!/^https?:\/\//.test(startUrl || "")) throw new Error("The start page must be a web address.");
  await clearShots();
  let tab;
  if (useCurrentTab) [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  else tab = await chrome.tabs.create({ url: "about:blank", active: true });
  rec = {
    status: "recording",
    tabId: tab.id,
    workspaceId,
    workspaceName,
    flow,
    title,
    site: startUrl,
    startedAt: new Date().toISOString(),
    currentUrl: startUrl,
    known: [],
    steps: [],
    capture, // watch the page's network requests (Chrome's debugging interface); off: actions only
  };
  newStep(startUrl, true);
  await save();
  if (capture) {
    try {
      await attach(tab.id);
    } catch (e) {
      rec = null;
      await save();
      throw e;
    }
  }
  await chrome.tabs.update(tab.id, { url: startUrl, active: true });
}

function tidy(steps) {
  const kept = steps.filter((s, i) => s.actions.length || s.requests.length || s.owner_note || i === steps.length - 1);
  return kept.map((s, i) => ({ ...s, original: s.n, n: i + 1 }));
}

// The file is handed to chrome.downloads as a Blob URL made by a hidden offscreen page (any size).
// If that isn't available, a data: URL is used instead, which Chrome caps at 2 MB: above that the
// file is saved without its step screenshots.
const MAX_FILE_URL = 1_900_000;

async function blobUrl(text) {
  if (!(await chrome.offscreen.hasDocument())) {
    await chrome.offscreen.createDocument({ url: "offscreen.html", reasons: ["BLOBS"], justification: "Save the recording as a file in Downloads." });
  }
  const url = await chrome.runtime.sendMessage({ type: "offscreen-blob", text });
  if (!String(url).startsWith("blob:")) throw new Error("no blob URL");
  return url;
}

function fileUrl(doc) {
  const bytes = new TextEncoder().encode(JSON.stringify(doc, null, 1));
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return `data:application/json;base64,${btoa(bin)}`;
}

function fileName() {
  const d = new Date(rec.startedAt);
  const pad = (n) => String(n).padStart(2, "0");
  const stamp = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}`;
  return `oasis-recordings/${rec.flow.replace(/_/g, "-")}-${stamp}.oasis.json`;
}

// Finish saves the recording as a file in Downloads/oasis-recordings. Nothing is uploaded: the
// owner imports the file in their workspace (Your tools → Import recording), where Oasis cleans
// it again, runs a security scan and builds the tool.
async function finish() {
  await load();
  if (!rec || rec.status !== "recording") return;
  rec.status = "saving";
  await save();
  await detach();
  const steps = tidy(rec.steps);
  const shots = await chrome.storage.local.get(steps.map((s) => `shot:${s.original}`));
  const doc = (withShots) => ({
    format: "oasis.recording/1",
    flow: rec.flow,
    title: rec.title,
    site: rec.site,
    recorded_at: rec.startedAt,
    source: "extension",
    workspace_id: rec.workspaceId || "",
    workspace_name: rec.workspaceName || "",
    steps: steps.map((s) => ({
      n: s.n,
      page: s.page,
      url: s.url,
      owner_note: s.owner_note,
      actions: s.actions,
      requests: s.requests,
      screenshot_data: (withShots && shots[`shot:${s.original}`]) || null,
    })),
  });
  try {
    let url;
    let screenshots = true;
    try {
      url = await blobUrl(JSON.stringify(doc(true), null, 1));
    } catch {
      url = fileUrl(doc(true));
      screenshots = url.length <= MAX_FILE_URL;
      if (!screenshots) url = fileUrl(doc(false));
    }
    const filename = fileName();
    const downloadId = await chrome.downloads.download({ url, filename, conflictAction: "uniquify", saveAs: false });
    // The download has its own copy once it starts; then the hidden page (and its Blob) can go.
    if (url.startsWith("blob:")) setTimeout(() => chrome.offscreen.closeDocument().catch(() => {}), 30_000);
    rec.status = "saved";
    rec.result = { downloadId, filename, screenshots };
    await clearShots();
  } catch (e) {
    rec.status = "failed";
    rec.error = e.message || String(e);
  }
  await save();
  chrome.tabs.sendMessage(rec.tabId, { type: "saved", status: rec.status, filename: rec.result?.filename, error: rec.error }).catch(() => {});
}

async function discard() {
  await load();
  await detach();
  if (rec) chrome.tabs.sendMessage(rec.tabId, { type: "discarded" }).catch(() => {});
  rec = null;
  await save();
  await clearShots();
}

// --- messages ----------------------------------------------------------------------------

async function handle(msg, sender) {
  await load();
  const fromRecordingTab = rec?.status === "recording" && sender.tab?.id === rec.tabId;
  // The step panel lives in the recording tab (content.js).
  const fromPanel = fromRecordingTab;

  switch (msg.type) {
    // from content.js
    case "hello":
      return { recording: fromRecordingTab, panel: fromRecordingTab ? panelState() : null };
    case "state":
      return fromRecordingTab ? panelState() : null;
    case "action": {
      if (!fromRecordingTab) return null;
      const k = known();
      const action = cleanAction(msg.action, k);
      rec.known = [...k];
      if (sender.frameId) action.frame_url = maskUrl(sender.url || "", k);
      const actions = current().actions;
      const last = actions[actions.length - 1];
      if (action.type === "fill" && last?.type === "fill" && last.selector === action.selector) actions[actions.length - 1] = action;
      else actions.push(action);
      await save();
      if (["click", "press", "submit"].includes(action.type)) await shot();
      else scheduleShot("action", 600);
      return { ok: true };
    }
    // from the step panel
    case "note":
      if (fromPanel) {
        current().owner_note = maskText(String(msg.text || "").slice(0, 500), known());
        await save();
      }
      return panelState();
    case "next_step":
      if (!fromPanel) return null;
      current().owner_note = maskText(String(msg.text || "").slice(0, 500), known());
      await shot();
      newStep(rec.currentUrl, true);
      await save();
      scheduleShot("load", 300);
      return panelState();
    case "finish":
      if (fromPanel && msg.text) current().owner_note = maskText(String(msg.text).slice(0, 500), known());
      finish();
      return { ok: true };
    case "cancel":
      await discard();
      return { ok: true };
    case "token": {
      // Only the Oasis address set in the popup may connect the extension.
      const { appUrl } = await settings();
      if (!sender.url || new URL(sender.url).origin !== new URL(appUrl).origin) {
        return { ok: false, error: `This extension is set up for ${appUrl}.` };
      }
      await chrome.storage.local.set({ token: msg.token, user: msg.user });
      return { ok: true };
    }

    // from the popup
    case "popup-state": {
      const s = await settings();
      return {
        connected: Boolean(s.token),
        user: s.user,
        appUrl: s.appUrl,
        rec: rec && {
          status: rec.status,
          title: rec.title,
          workspaceName: rec.workspaceName,
          steps: rec.steps.length,
          actions: rec.steps.reduce((n, x) => n + x.actions.length, 0),
          requests: rec.steps.reduce((n, x) => n + x.requests.length, 0),
          workspaceId: rec.workspaceId,
          result: rec.result,
          error: rec.error,
          capture: rec.capture !== false,
          // the step in progress
          step: rec.steps.length ? current().n : 0,
          note: rec.steps.length ? current().owner_note : "",
          stepActions: rec.steps.length ? current().actions.length : 0,
        },
      };
    }
    case "context":
      return api("/api/extension/context");
    case "show-file":
      if (rec?.result?.downloadId) chrome.downloads.show(rec.result.downloadId);
      return { ok: true };
    case "start":
      await start(msg.options);
      return { ok: true };
    case "popup-finish":
      await finish();
      return { ok: true };
    case "retry-save":
      if (rec?.status === "failed") {
        rec.status = "recording";
        await finish();
      }
      return { ok: true };
    case "dismiss":
      if (rec && rec.status !== "recording" && rec.status !== "saving") {
        rec = null;
        await save();
        await clearShots();
      }
      return { ok: true };
    case "set-app-url":
      await chrome.storage.local.set({ appUrl: String(msg.appUrl || DEFAULT_APP).replace(/\/+$/, "") });
      await chrome.storage.local.remove(["token", "user"]);
      return { ok: true };
    case "logout":
      await chrome.storage.local.remove(["token", "user"]);
      return { ok: true };
    default:
      return null;
  }
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  handle(msg, sender).then(sendResponse, (e) => sendResponse({ error: e.message || String(e) }));
  return true; // answer asynchronously
});

// The recording tab's panel keeps a port open so Chrome doesn't stop this worker mid-recording.
chrome.runtime.onConnect.addListener((port) => {
  if (port.name === "keepalive") port.onMessage.addListener(() => {});
});
