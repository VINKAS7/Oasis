// AgentReady Recorder: records one flow in the owner's own Chrome tab.
//
// - content.js reports clicks, typing and submits, and shows the owner's step panel;
// - chrome.debugger (Network + Fetch domains) captures the messages the site sends its server;
// - a new step starts whenever the page changes; each step gets a screenshot;
// - everything is masked (clean.js) as it arrives; on Finish the recording is uploaded to
//   AgentReady, which cleans it again, and the owner continues there.
//
// The service worker can be stopped by Chrome at any time, so the recording lives in
// chrome.storage.local and is reloaded on wake-up.

import { cleanAction, isTracker, maskText, maskUrl, parseBody } from "./clean.js";

const DEFAULT_APP = "http://localhost:5173";
const KEPT_TYPES = new Set(["Document", "XHR", "Fetch"]);

let rec = null; // the recording in progress (mirrored to storage)
let loading = null;
const pending = new Map(); // CDP requestId -> request being captured
const writeBodies = new Map(); // CDP requestId -> response body of a write request (caught by Fetch)
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
    if (rec?.status === "recording") {
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
    const err = new Error("Your AgentReady session ended. Log in again.");
    err.status = 401;
    throw err;
  }
  if (!res.ok) {
    const d = body?.detail;
    throw new Error(typeof d === "string" ? d : d ? JSON.stringify(d) : `AgentReady answered ${res.status}`);
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
  await chrome.debugger.sendCommand({ tabId }, "Network.enable", { maxPostDataSize: 65536 });
  // Write requests (the booking POST) pause at the response, so their answer is read before
  // the page navigates away and the browser forgets it.
  await chrome.debugger.sendCommand({ tabId }, "Fetch.enable", {
    patterns: [
      { resourceType: "XHR", requestStage: "Response" },
      { resourceType: "Fetch", requestStage: "Response" },
    ],
  });
}

async function detach() {
  if (!rec) return;
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
    entry.response = { status: p.status, content_type: p.mimeType || "", body: rawBody != null && /json|text/.test(p.mimeType || "") ? parseBody(rawBody, p.mimeType, k) : null };
  }
  const step = rec.steps.find((s) => s.n === p.step) || current();
  step.requests.push(entry);
  save();
}

chrome.debugger.onEvent.addListener(async (source, method, params) => {
  await load();
  if (!rec || rec.status !== "recording" || source.tabId !== rec.tabId) return;
  const target = { tabId: source.tabId };

  if (method === "Fetch.requestPaused") {
    try {
      const r = params.request;
      if (r.method !== "GET" && !isTracker(r.url) && params.networkId) {
        const res = await chrome.debugger.sendCommand(target, "Fetch.getResponseBody", { requestId: params.requestId });
        writeBodies.set(params.networkId, res.base64Encoded ? atob(res.body) : res.body);
      }
    } catch {
      /* no body (e.g. a redirect) */
    } finally {
      chrome.debugger.sendCommand(target, "Fetch.continueRequest", { requestId: params.requestId }).catch(() => {});
    }
    return;
  }
  if (method === "Network.requestWillBeSent") {
    const r = params.request;
    if (!KEPT_TYPES.has(params.type) || (params.type === "Document" && r.method === "GET")) return;
    if (!/^https?:/.test(r.url) || isTracker(r.url)) return;
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
    }
  } else if (method === "Network.loadingFinished") {
    const p = pending.get(params.requestId);
    if (!p) return;
    pending.delete(params.requestId);
    let body = writeBodies.get(params.requestId) ?? null;
    writeBodies.delete(params.requestId);
    if (body == null && p.type !== "document" && /json|text/.test(p.mimeType || "")) {
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

async function shot() {
  if (!rec || rec.status !== "recording") return;
  const wait = 600 - (Date.now() - lastShot); // Chrome allows two captures a second
  if (wait > 0) await new Promise((r) => setTimeout(r, wait));
  lastShot = Date.now();
  const step = current();
  const tab = await chrome.tabs.get(rec.tabId).catch(() => null);
  if (!tab || !tab.active) return;
  let dataUrl = null;
  try {
    // Hide the panel and cover personal fields in every frame first.
    await chrome.tabs.sendMessage(rec.tabId, { type: "prepare-shot" }).catch(() => {});
    await new Promise((r) => setTimeout(r, 60));
    dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: "jpeg", quality: 60 });
  } catch {
    /* the window is minimised or not focused */
  } finally {
    chrome.tabs.sendMessage(rec.tabId, { type: "after-shot" }).catch(() => {});
  }
  const after = await chrome.tabs.get(rec.tabId).catch(() => null);
  if (!dataUrl || current() !== step || !after || after.url !== tab.url) return; // the page moved on meanwhile
  await chrome.storage.local.set({ [`shot:${step.n}`]: dataUrl });
  step.screenshot = true;
  save();
}

// --- start / finish ----------------------------------------------------------------------

async function start({ workspaceId, workspaceName, flow, title, startUrl, useCurrentTab }) {
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
  };
  newStep(startUrl, true);
  await save();
  try {
    await attach(tab.id);
  } catch (e) {
    rec = null;
    await save();
    throw e;
  }
  await chrome.tabs.update(tab.id, { url: startUrl, active: true });
}

function tidy(steps) {
  const kept = steps.filter((s, i) => s.actions.length || s.requests.length || s.owner_note || i === steps.length - 1);
  return kept.map((s, i) => ({ ...s, original: s.n, n: i + 1 }));
}

async function finish() {
  await load();
  if (!rec || rec.status !== "recording") return;
  rec.status = "saving";
  await save();
  await detach();
  const { appUrl } = await settings();
  const steps = tidy(rec.steps);
  const shots = await chrome.storage.local.get(steps.map((s) => `shot:${s.original}`));
  const doc = {
    flow: rec.flow,
    title: rec.title,
    site: rec.site,
    recorded_at: rec.startedAt,
    source: "extension",
    steps: steps.map((s) => ({
      n: s.n,
      page: s.page,
      url: s.url,
      owner_note: s.owner_note,
      actions: s.actions,
      requests: s.requests,
      screenshot_data: shots[`shot:${s.original}`] || null,
    })),
  };
  try {
    const saved = await api(`/api/workspaces/${rec.workspaceId}/recordings/upload`, { method: "POST", body: JSON.stringify(doc) });
    rec.status = "saved";
    rec.result = { recordingId: saved.id, url: `${appUrl}/workspaces/${rec.workspaceId}/recordings/${saved.id}` };
    await clearShots();
  } catch (e) {
    rec.status = "failed";
    rec.error = e.message;
  }
  await save();
  chrome.tabs.sendMessage(rec.tabId, { type: "saved", status: rec.status, url: rec.result?.url, error: rec.error }).catch(() => {});
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
      return { personal: Boolean(action.personal) };
    }
    case "note":
      if (fromRecordingTab) {
        current().owner_note = maskText(String(msg.text || "").slice(0, 500), known());
        await save();
      }
      return panelState();
    case "next_step":
      if (!fromRecordingTab) return null;
      current().owner_note = maskText(String(msg.text || "").slice(0, 500), known());
      await shot();
      newStep(rec.currentUrl, true);
      await save();
      scheduleShot("load", 300);
      return panelState();
    case "finish":
      if (fromRecordingTab && msg.text) current().owner_note = maskText(String(msg.text).slice(0, 500), known());
      finish();
      return { ok: true };
    case "cancel":
      await discard();
      return { ok: true };
    case "token": {
      // Only the AgentReady address set in the popup may connect the extension.
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
          result: rec.result,
          error: rec.error,
        },
      };
    }
    case "context":
      return api("/api/extension/context");
    case "start":
      await start(msg.options);
      return { ok: true };
    case "popup-finish":
      await finish();
      return { ok: true };
    case "retry-upload":
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
