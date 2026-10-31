"""Catalogs: the menu, products, services or rooms a website lists, as data.

A site's own HTML never reaches the customer chat (it would run its markup inside our app and
could carry hidden text for the AI). Instead the crawler finds *repeated item blocks*, the cards,
rows or list entries that each hold a name and an image or a price, plus schema.org JSON-LD
when the site has it. A tool of kind item_list reads them again when called and returns plain
items (name, description, price, image, link) that the chat draws as its own cards.

The same page script finds catalogs at crawl time (DETECT_JS) and reads items at call time
(ITEMS_JS), so both agree on what an item is."""

import hashlib
import json
import re
from typing import Any
from urllib.parse import urljoin

MAX_ITEMS = 200

# Shared by both scripts: what an item is, and how its fields are read. Works on any markup:
# the name is the most heading-like text, the price is whatever matches a currency pattern,
# the image is an <img> or a CSS background, the description is the longest remaining text (or,
# when every line is short like skill tags, all of them). Items without a price or picture count
# too when they have a title of their own: a portfolio's projects, a school's courses.
_PRELUDE = r"""
  const clean = (s) => (s || "").replace(/\s+/g, " ").trim();
  // A price never starts right after a letter or digit: "Poster A2$1,299.00" is $1,299.00, not 2$.
  const PRICE = /(?:CHF|EUR|USD|GBP|INR|Fr\.|Rs\.?|€|\$|£|₹)\s?\d{1,6}(?:[.,']\d{3})*(?:[.,]\d{1,2})?(?:\.-)?|(?<![\w.,])\d{1,6}(?:[.,']\d{3})*(?:[.,]\d{1,2})?\s?(?:CHF|EUR|USD|GBP|INR|Fr\.?|€|\$|£|₹|\.-)/i;
  const UNSTABLE = /\d{3,}|active|selected|current|hover|open|show|hidden|first|last|odd|even|^js-|^is-|^has-/i;
  const classes = (el) => [...el.classList].filter((c) => !UNSTABLE.test(c) && /^[A-Za-z_-][\w-]*$/.test(c)).sort().slice(0, 3);
  const sig = (el) => el.tagName.toLowerCase() + classes(el).map((c) => "." + c).join("");
  const visible = (el) => { const r = el.getBoundingClientRect(); return r.width > 20 && r.height > 10; };
  const lines = (el) => (el.innerText || "").split(/[\n\t]+/).map(clean).filter(Boolean);
  const imageOf = (el) => {
    for (const img of el.querySelectorAll("img")) {
      const src = img.currentSrc || img.src || img.getAttribute("data-src") || img.getAttribute("data-lazy-src") || "";
      if (src && !src.startsWith("data:") && (img.naturalWidth || 100) >= 40) return src;
    }
    for (const e of [el, ...el.querySelectorAll("*")].slice(0, 40)) {
      const bg = getComputedStyle(e).backgroundImage;
      const m = bg && bg.match(/url\(["']?([^"')]+)["']?\)/);
      if (m && !m[1].startsWith("data:")) return new URL(m[1], location.href).href;
    }
    return "";
  };
  // Titles: headings, or text styled bold (sites built with utility classes rarely use <strong>).
  const TITLED = "h2, h3, h4, h5, h6, summary, dt, strong, b, [class*=title i], [class*=name i], [class*=font-semibold], [class*=font-bold]";
  const REGION = /^(SECTION|MAIN|HEADER|FOOTER|NAV|ASIDE|FORM)$/;  // page regions, never items
  const linkShare = (el, t) => [...el.querySelectorAll("a")].reduce((n, a) => n + clean(a.innerText).length, 0) / Math.max(1, t.length);
  // An item has a price, a picture, or (projects, skills, services listed as text) a title of its
  // own and some text that isn't just links: navigation, footers and tag chips stay out.
  const looksLikeItem = (el) => {
    const t = clean(el.innerText);
    if (t.length < 3 || t.length > 3000) return false;
    if (PRICE.test(t) || (el.querySelector("img") && imageOf(el))) return true;
    if (t.length >= 30 && el.querySelector(TITLED) && linkShare(el, t) < 0.7) return true;
    return !!imageOf(el);
  };
  // Collapsed parts (a project's "▶ details") are part of the item; open them in this headless copy.
  const openAll = () => document.querySelectorAll("details:not([open])").forEach((d) => { d.open = true; });
  const sectionOf = (el) => {
    // The heading just before the item's group: "Pizza", "Desserts", "Laptops". Only a heading or a
    // small header block counts, never a heading inside a neighbouring card or section.
    let level = 0;
    for (let n = el.parentElement; n && n !== document.body && level < 4; n = n.parentElement, level++) {
      for (let s = n.previousElementSibling; s; s = s.previousElementSibling) {
        if (/^H[1-4]$/.test(s.tagName)) return clean(s.innerText).slice(0, 80);
        const h = s.querySelector && s.querySelector("h1, h2, h3, h4");
        if (h && clean(s.innerText).length <= 160 && !s.querySelector("img")) return clean(h.innerText).slice(0, 80);
        if (clean(s.innerText).length > 160) break;  // real content in between: the heading isn't ours
      }
    }
    return "";
  };
  const priceOf = (el) => {
    // Best: the smallest element holding just a price (<span class="amount">$1,299.00</span>).
    for (const leaf of el.querySelectorAll("*")) {
      if (leaf.children.length) continue;
      const t = clean(leaf.innerText), m = t.match(PRICE);
      if (m && t.length - m[0].length <= 4) return m[0];
    }
    const line = lines(el).find((l) => PRICE.test(l));
    return line ? line.match(PRICE)[0] : "";
  };
  const fieldsOf = (el) => {
    const all = lines(el);
    const price = priceOf(el);
    const priceLine = all.find((l) => price && l.includes(price)) || "";
    const named = el.querySelector("h1, h2, h3, h4, h5, h6, [class*=title i], [class*=name i], dt, strong, b, td, th, summary");
    let name = clean(named && named.innerText);
    if (!name || PRICE.test(name) && name.replace(PRICE, "").trim().length < 2) name = all.find((l) => !PRICE.test(l) || l.replace(PRICE, "").trim().length > 2) || "";
    name = clean(name.replace(PRICE, "")).replace(/^[^\p{L}\p{N}]+/u, "").slice(0, 120);  // "▶ NAVA" → "NAVA"
    const rest = all.filter((l) => !l.endsWith(name) && clean(l.replace(PRICE, "")) !== name && l !== priceLine && l.length > 2);
    // One real sentence: the longest line. Only short ones (skill chips, tags): all of them.
    const longest = [...rest].sort((a, b) => b.length - a.length)[0] || "";
    const description = longest.length >= 60 || rest.length < 3 ? longest : rest.join(" · ");
    const link = el.matches("a[href]") ? el : el.querySelector("a[href]");
    return { name, description: description.slice(0, 300), price, image: imageOf(el), url: link ? link.href : "", section: sectionOf(el) };
  };
  const pathOf = (el) => {
    // Ancestors by tag and class, no positions: one selector covers every section of a menu.
    const parts = [];
    for (let n = el; n && n !== document.body && parts.length < 4; n = n.parentElement) {
      if (n.id && /^[A-Za-z][\w-]*$/.test(n.id) && n !== el) { parts.unshift("#" + n.id); break; }
      parts.unshift(sig(n));
    }
    return parts.join(" > ");
  };
  const detect = () => {
    openAll();
    const groups = new Map();
    for (const parent of document.querySelectorAll("body *")) {
      const kids = [...parent.children].filter(visible);
      if (kids.length < 2) continue;
      const counts = {};
      for (const k of kids) counts[sig(k)] = (counts[sig(k)] || 0) + 1;
      for (const k of kids) {
        if (counts[sig(k)] < 2 || REGION.test(k.tagName) || !looksLikeItem(k)) continue;
        const key = pathOf(k);
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(k);
      }
    }
    const found = [];
    for (const [selector, els] of groups) {
      const items = [...new Set(els)];
      if (items.length < 3) continue;
      const fields = items.map(fieldsOf).filter((f) => f.name);
      if (fields.length < 3) continue;
      const withPrice = fields.filter((f) => f.price).length / fields.length;
      const withImage = fields.filter((f) => f.image).length / fields.length;
      found.push({ selector, items, count: fields.length, with_price: withPrice, with_image: withImage,
                   score: fields.length * (1 + withPrice + withImage), samples: fields.slice(0, 3) });
    }
    // Drop groups nested inside a better one (the cards' inner rows of a card grid).
    found.sort((a, b) => b.score - a.score);
    const kept = [];
    for (const g of found) {
      if (kept.some((k) => k.items.some((it) => g.items.some((x) => it !== x && it.contains(x))))) continue;
      kept.push(g);
      if (kept.length >= 6) break;
    }
    return kept.map(({ items, ...g }) => g);
  };
"""

DETECT_JS = "() => {" + _PRELUDE + "  return detect();\n}"

# args: {selector, names}. When the saved selector finds nothing (the site was redesigned), the
# group whose items share the most names with the last known items is used instead.
ITEMS_JS = "(args) => {" + _PRELUDE + r"""
  openAll();
  let els = [];
  try { els = args.selector ? [...document.querySelectorAll(args.selector)] : []; } catch (e) { els = []; }
  let items = els.filter((e) => visible(e) && looksLikeItem(e)).map(fieldsOf).filter((f) => f.name);
  if (!items.length && (args.names || []).length) {
    const known = new Set(args.names.map((n) => n.toLowerCase()));
    const best = detect().map((g) => [g, [...document.querySelectorAll(g.selector)].filter(looksLikeItem).map(fieldsOf)])
      .map(([g, f]) => [f, f.filter((x) => known.has(x.name.toLowerCase())).length])
      .sort((a, b) => b[1] - a[1])[0];
    if (best && best[1] > 0) items = best[0];
  }
  return items.slice(0, """ + str(MAX_ITEMS) + """);
}"""

JSONLD_JS = """() => [...document.querySelectorAll('script[type="application/ld+json"]')].map((s) => s.textContent.trim()).filter(Boolean).slice(0, 20)"""

_CURRENCY = {"€": "EUR", "$": "USD", "£": "GBP", "₹": "INR", "fr.": "CHF", "fr": "CHF", "rs.": "INR", "rs": "INR", ".-": "CHF"}
_PRICE_RE = re.compile(r"(CHF|EUR|USD|GBP|INR|Fr\.|Rs\.?|€|\$|£|₹)?\s?(\d{1,6}(?:[.,']\d{3})*(?:[.,]\d{1,2})?)\s?(CHF|EUR|USD|GBP|INR|Fr\.?|€|\$|£|₹|\.-)?", re.I)


def parse_price(text: str) -> tuple[float | None, str]:
    """'CHF 19', '€12,50', '$1,299.00', '24.-' → (amount, ISO currency); (None, '') if there is no price."""
    m = _PRICE_RE.search(text or "")
    if not m or not (m.group(1) or m.group(3)):
        return None, ""
    number = m.group(2).replace("'", "")
    if re.search(r"[.,]\d{3}(?:[.,]|$)", number):  # thousands separators: 1,299.00 / 1.299,00
        number = re.sub(r"[.,](?=\d{3}(?:[.,]|$))", "", number)
    number = number.replace(",", ".")
    try:
        amount = round(float(number), 2)
    except ValueError:
        return None, ""
    symbol = (m.group(1) or m.group(3) or "").strip()
    return amount, _CURRENCY.get(symbol.lower(), symbol.upper())


def item_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48] or "item"
    return f"{slug}-{hashlib.sha1(name.strip().lower().encode()).hexdigest()[:6]}"


def normalize(raw: list[dict[str, Any]], base_url: str) -> list[dict[str, Any]]:
    """Items as the tool returns them: stable ids, parsed prices, absolute http(s) links only."""
    out, seen = [], set()
    for r in raw:
        name = (r.get("name") or "").strip()[:120]
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        price_text = (r.get("price") or "").strip()
        amount, currency = parse_price(price_text)
        if r.get("amount") is not None:
            amount, currency = r["amount"], r.get("currency") or currency
        out.append({
            "id": item_id(name),
            "name": name,
            "description": (r.get("description") or "").strip()[:300],
            "section": (r.get("section") or "").strip()[:80],
            "price": price_text or (f"{currency} {amount:g}".strip() if amount is not None else ""),
            "amount": amount,
            "currency": currency,
            "image_url": _http_url(r.get("image") or "", base_url),
            "url": _http_url(r.get("url") or "", base_url),
        })
    return out[:MAX_ITEMS]


def _http_url(value: Any, base_url: str) -> str:
    if isinstance(value, list):
        value = value[0] if value else ""
    if isinstance(value, dict):
        value = value.get("url") or value.get("contentUrl") or ""
    url = urljoin(base_url, str(value).strip()) if value else ""
    return url if url.startswith(("http://", "https://")) else ""


# --- schema.org JSON-LD --------------------------------------------------------------------

_ITEM_TYPES = {"menuitem", "product", "offer", "service", "course", "hotelroom", "room", "event", "book", "creativework"}


def _types(node: dict[str, Any]) -> set[str]:
    t = node.get("@type", [])
    return {str(x).lower() for x in (t if isinstance(t, list) else [t])}


def _offer_price(node: dict[str, Any]) -> tuple[float | None, str]:
    offers = node.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    price = offers.get("price", offers.get("lowPrice")) if isinstance(offers, dict) else None
    try:
        return (round(float(str(price).replace(",", ".")), 2) if price not in (None, "") else None), (offers.get("priceCurrency") or "").upper()
    except ValueError:
        return None, ""


def jsonld_items(blocks: list[str]) -> list[dict[str, Any]]:
    """Menu items, products, services... found anywhere in the page's JSON-LD."""
    found: list[dict[str, Any]] = []

    def walk(node: Any, section: str = "") -> None:
        if isinstance(node, list):
            for n in node:
                walk(n, section)
            return
        if not isinstance(node, dict):
            return
        types = _types(node)
        if "menusection" in types:
            section = node.get("name") or section
        if types & _ITEM_TYPES and node.get("name") and not types & {"menu", "menusection", "itemlist"}:
            amount, currency = _offer_price(node)
            found.append({"name": str(node["name"]), "description": str(node.get("description") or ""), "section": section,
                          "amount": amount, "currency": currency, "price": f"{currency} {amount:g}".strip() if amount is not None else "",
                          "image": node.get("image") or "", "url": node.get("url") or ""})
        for key in ("@graph", "hasMenu", "hasMenuSection", "hasMenuItem", "itemListElement", "item", "mainEntity", "hasOfferCatalog", "makesOffer", "itemOffered"):
            if key in node:
                walk(node[key], section)

    for block in blocks:
        try:
            walk(json.loads(block))
        except ValueError:
            continue
    return found


def candidates(page: dict[str, Any]) -> list[dict[str, Any]]:
    """What the crawl found on one page: JSON-LD first (cleanest), then the repeated blocks."""
    out = []
    ld = jsonld_items(page.get("json_ld") or [])
    if len(ld) >= 2:
        out.append({"source": "jsonld", "count": len(ld), "with_price": sum(i["amount"] is not None for i in ld) / len(ld),
                    "with_image": sum(bool(i["image"]) for i in ld) / len(ld), "samples": ld[:3]})
    for g in page.get("catalogs") or []:
        out.append({"source": "dom", **g})
    return out[:6]
