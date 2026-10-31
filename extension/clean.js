// What a recording may keep, applied in the browser before anything is uploaded. The
// Oasis server cleans every upload again with the same rules (backend/app/recorder/clean.py).

export const MASK = "[MASKED]";
const BODY_LIMIT = 20000;

const PERSONAL =
  /(^|_)(name|firstname|lastname|fullname|surname|vorname|nachname|guest|email|e_mail|mail|phone|telephone|tel|mobile|handy|address|street|strasse|city|zip|postcode|postal|plz|birthday|birthdate|dob|card|cc|ccnum|cvc|cvv|iban|password|passwd|pwd|pin)($|_)/;
const SECRET = /(password|passwd|pwd|token|csrf|xsrf|secret|session|sessid|auth|api_?key|signature|nonce|cookie)/i;
const PERSONAL_AUTOCOMPLETE =
  /^(name|given-name|family-name|additional-name|nickname|email|tel.*|street-address|address-.*|postal-code|country|cc-.*|bday.*|username|current-password|new-password|one-time-code)$/;
const EMAIL = /[\w.+-]+@[\w-]+\.[\w.-]+/g;
const PHONE = /(?<![\w-])(?:\+|00)\d[\d\s\-/().]{6,}\d|\b0\d{2}[\s\-/]?\d{3}[\s\-/]?\d{2}[\s\-/]?\d{2}\b/g;
const JWT = /\beyJ[\w-]+\.[\w-]+\.[\w-]+/g;

export const TRACKERS = [
  "google-analytics.com", "googletagmanager.com", "doubleclick.net", "googleadservices.com", "google.com/recaptcha",
  "facebook.net", "facebook.com/tr", "connect.facebook", "hotjar.com", "hotjar.io", "segment.io", "segment.com",
  "mixpanel.com", "amplitude.com", "sentry.io", "clarity.ms", "bing.com/bat", "tiktok.com", "linkedin.com/px",
  "plausible.io", "matomo", "cookiebot.com", "onetrust.com", "intercom.io", "fullstory.com", "newrelic.com", "nr-data.net",
];

export function snake(s) {
  return String(s || "")
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

export const keyIsSensitive = (key) => PERSONAL.test(snake(key)) || SECRET.test(key);

export function fieldIsPersonal(f) {
  if (["password", "email", "tel"].includes(String(f.input_type || "").toLowerCase())) return true;
  if (PERSONAL_AUTOCOMPLETE.test(String(f.autocomplete || "").toLowerCase())) return true;
  return ["name", "id", "label"].some((k) => PERSONAL.test(snake(f[k] || "")));
}

export const isTracker = (url) => TRACKERS.some((t) => String(url).toLowerCase().includes(t));

export function maskText(text, known) {
  let out = String(text ?? "");
  for (const v of [...known].sort((a, b) => b.length - a.length)) {
    if (v.length >= 3) out = out.split(v).join(MASK);
  }
  return out.replace(EMAIL, MASK).replace(JWT, MASK).replace(PHONE, MASK);
}

export function maskData(value, known) {
  if (Array.isArray(value)) return value.map((v) => maskData(v, known));
  if (value && typeof value === "object") {
    const out = {};
    for (const [k, v] of Object.entries(value)) out[k] = keyIsSensitive(k) && (v === null || typeof v !== "object") ? MASK : maskData(v, known);
    return out;
  }
  return typeof value === "string" ? maskText(value, known) : value;
}

export function maskUrl(url, known) {
  try {
    const u = new URL(url);
    for (const [k, v] of [...u.searchParams.entries()]) u.searchParams.set(k, keyIsSensitive(k) ? MASK : maskText(v, known));
    u.hash = "";
    return maskText(u.toString().replace(/%5BMASKED%5D/g, MASK), known);
  } catch {
    return maskText(url, known);
  }
}

export function parseBody(raw, contentType, known) {
  if (raw == null || raw === "") return null;
  const ct = String(contentType || "").toLowerCase();
  if (ct.includes("json") || /^\s*[{[]/.test(raw)) {
    try {
      return maskData(JSON.parse(raw), known);
    } catch {
      /* not JSON after all */
    }
  }
  if (ct.includes("x-www-form-urlencoded")) return maskData(Object.fromEntries(new URLSearchParams(raw)), known);
  if (ct.includes("multipart/form-data")) return "[multipart body omitted]";
  if (ct.includes("html")) return "[html page]";
  return maskText(raw.length <= BODY_LIMIT ? raw : raw.slice(0, BODY_LIMIT) + " [cut]", known);
}

/** Mask an action's value; personal values are remembered so they are masked everywhere. */
export function cleanAction(action, known) {
  const out = {};
  for (const [k, v] of Object.entries(action)) if (v !== undefined && v !== null && v !== "") out[k] = v;
  const personal = Boolean(action.personal) || fieldIsPersonal(action);
  if ("value" in action) {
    const value = String(action.value ?? "");
    if (personal) {
      if (value && value !== MASK) known.add(value);
      out.value = MASK;
      out.personal = true;
    } else {
      out.value = maskText(value, known);
    }
  }
  if (out.text) out.text = maskText(out.text, known);
  return out;
}
