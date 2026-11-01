import { useEffect, useRef, useState, type FormEvent } from "react";
import { Check, CircleX, ImageOff, Loader2, Minus, Plus, ShoppingBag } from "lucide-react";
import { cartKey, money, orderStatus, sendOrder, splitCartKey, type OrderDetails } from "../../lib/chat";
import type { CatalogItem, ChatCatalog, ChatOrder } from "../../types";
import { Button, cx } from "../ui";

const SHOWN = 9;

/** A shop photo's address, loaded from Oasis itself (the public address may be a development
 * tunnel that shows browsers a warning page instead of the image). */
function local(url: string): string {
  const at = url.indexOf("/api/public/shops/");
  return at > 0 ? url.slice(at) : url;
}

const axesOf = (i: CatalogItem) => Object.keys(i.options ?? {});
const stockOf = (i: CatalogItem, variant: string): number | null => {
  const a = i.available;
  if (!a) return null;
  if (variant in a) return a[variant];
  return !variant && "" in a ? a[""] : null;
};
const label = (variant: string) => variant.split("/").join(", ");

/** The variant shown on a card: the visitor's picks, then what they asked for ("black tee": colour
 *  Black), then the first combination in stock. */
function variantOf(i: CatalogItem, picks: Record<string, string> | undefined): string {
  const axes = axesOf(i);
  if (!axes.length) return "";
  const want = { ...(i.preselect ?? {}), ...(picks ?? {}) };
  if (axes.every((a) => want[a])) return axes.map((a) => want[a]).join("/");
  const combos = axes.reduce<string[]>((acc, a) => acc.flatMap((k) => i.options![a].map((v) => (k ? `${k}/${v}` : v))), [""]);
  const inStock = (c: string) => (stockOf(i, c) ?? 1) > 0;
  const fits = (c: string) => c.split("/").every((v, n) => !want[axes[n]] || want[axes[n]] === v);
  return combos.find((c) => fits(c) && inStock(c)) ?? combos.find(fits) ?? combos.find(inStock) ?? combos[0];
}

/** The business's own pictures, loaded straight from its site (or Oasis, for shops). No referrer is
 * sent, and a broken or missing picture becomes a quiet placeholder. Several photos: dots. */
function Picture({ item }: { item: CatalogItem }) {
  const photos = item.images?.length ? item.images : item.image_url ? [item.image_url] : [];
  const [at, setAt] = useState(0);
  const [failed, setFailed] = useState<Record<number, boolean>>({});
  if (!photos.length || failed[at]) {
    return (
      <div className="flex aspect-[4/3] items-center justify-center bg-stone-100 text-stone-300">
        <ImageOff className="size-6" />
      </div>
    );
  }
  return (
    <div className="relative">
      <img
        src={local(photos[at])}
        alt=""
        loading="lazy"
        referrerPolicy="no-referrer"
        onError={() => setFailed((f) => ({ ...f, [at]: true }))}
        className="aspect-[4/3] w-full object-cover"
      />
      {photos.length > 1 && (
        <div className="absolute inset-x-0 bottom-1.5 flex justify-center gap-1.5">
          {photos.map((_, n) => (
            <button
              key={n}
              onClick={() => setAt(n)}
              aria-label={`Photo ${n + 1}`}
              className={cx("size-1.5 rounded-full shadow-[0_0_0_1px_rgba(0,0,0,0.2)]", n === at ? "bg-white" : "bg-white/50")}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function Stepper({ qty, max, onChange }: { qty: number; max: number; onChange: (q: number) => void }) {
  if (!qty) {
    return (
      <button onClick={() => onChange(1)} className="inline-flex items-center gap-1 rounded-full border border-stone-200 px-2.5 py-1 text-xs font-medium text-stone-700 hover:bg-stone-50">
        <Plus className="size-3" /> Add
      </button>
    );
  }
  return (
    <div className="inline-flex items-center rounded-full bg-stone-800 text-white">
      <button onClick={() => onChange(qty - 1)} className="rounded-full p-1.5 hover:bg-stone-700" aria-label="One less">
        <Minus className="size-3" />
      </button>
      <span className="min-w-5 text-center text-xs font-semibold tabular-nums">{qty}</span>
      <button onClick={() => onChange(Math.min(max, qty + 1))} className="rounded-full p-1.5 hover:bg-stone-700" aria-label="One more">
        <Plus className="size-3" />
      </button>
    </div>
  );
}

function Details({ item }: { item: CatalogItem }) {
  const parts = Object.values(item.attributes ?? {}).map((v) => (Array.isArray(v) ? v.join(" · ") : String(v)));
  return parts.length ? <p className="text-xs text-stone-500">{parts.slice(0, 4).join(" · ")}</p> : null;
}

function ItemCard({
  item,
  cart,
  canPick,
  pictures,
  picks,
  onPick,
  onQty,
}: {
  item: CatalogItem;
  cart: Record<string, number>;
  canPick: boolean;
  pictures: boolean;
  picks: Record<string, string> | undefined;
  onPick: (axis: string, value: string) => void;
  onQty: (key: string, q: number) => void;
}) {
  const axes = axesOf(item);
  const variant = variantOf(item, picks);
  const key = cartKey(item.id, variant);
  const qty = cart[key] ?? 0;
  const left = stockOf(item, variant);
  const soldOut = left !== null && left <= 0;
  const picked = Object.entries(cart).some(([k, q]) => q > 0 && splitCartKey(k).id === item.id);
  return (
    <div className={cx("overflow-hidden rounded-xl border bg-white transition-colors", picked ? "border-stone-800" : "border-stone-200")}>
      {pictures && <Picture item={item} />}
      <div className="space-y-1 p-3">
        <div className="flex items-start justify-between gap-2">
          <span className="font-medium leading-snug text-stone-800">{item.name}</span>
          {item.price && <span className="shrink-0 text-sm font-medium text-stone-700 tabular-nums">{money(item.amount, item.currency) || item.price}</span>}
        </div>
        <Details item={item} />
        {item.description && <p className={cx("text-xs text-stone-500", pictures ? "line-clamp-2" : "line-clamp-4")}>{item.description}</p>}
        {axes.length > 0 && (
          <div className="flex flex-wrap gap-1.5 pt-1">
            {axes.map((a, n) => (
              <select
                key={a}
                aria-label={a}
                value={variant.split("/")[n]}
                onChange={(e) => onPick(a, e.target.value)}
                className="rounded-md border border-stone-200 bg-white px-1.5 py-1 text-xs text-stone-700"
              >
                {item.options![a].map((v) => {
                  const any = Object.entries(item.available ?? {}).some(([k, c]) => k.split("/")[n] === v && c > 0);
                  const out = !!item.available && Object.keys(item.available).length > 0 && !any;
                  return (
                    <option key={v} value={v}>
                      {v}
                      {out ? " (sold out)" : ""}
                    </option>
                  );
                })}
              </select>
            ))}
          </div>
        )}
        {left !== null && (soldOut || left <= 3) && (
          <p className={cx("text-xs", soldOut ? "text-soft-red-ink" : "text-amber-700")}>
            {soldOut ? `Sold out${variant ? ` in ${label(variant)}` : ""}` : `Only ${left} left`}
          </p>
        )}
        {!pictures && item.url && (
          <a href={item.url} target="_blank" rel="noreferrer noopener" className="inline-block text-xs font-medium text-brand-800 hover:underline">
            Open ↗
          </a>
        )}
        {canPick && !soldOut && (
          <div className="pt-1">
            <Stepper qty={qty} max={Math.min(20, left ?? 20)} onChange={(q) => onQty(key, q)} />
          </div>
        )}
      </div>
    </div>
  );
}

function cartTotal(c: ChatCatalog): { count: number; total: number | null; currency: string } {
  let count = 0;
  let total: number | null = 0;
  let currency = "";
  for (const [key, q] of Object.entries(c.cart)) {
    const item = c.items.find((i) => i.id === splitCartKey(key).id);
    if (!q || !item) continue;
    count += q;
    currency ||= item.currency;
    total = item.amount === null || total === null ? null : total + item.amount * q;
  }
  return { count, total, currency };
}

function Review({ c, onBack, onSent }: { c: ChatCatalog; onBack: () => void; onSent: (o: ChatOrder) => void }) {
  const [d, setD] = useState<OrderDetails>({ customer_name: "", customer_contact: "", pickup_time: "", note: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const { total, currency } = cartTotal(c);
  const lines = Object.entries(c.cart)
    .filter(([, q]) => q > 0)
    .map(([key, q]) => ({ key, q, variant: splitCartKey(key).variant, item: c.items.find((i) => i.id === splitCartKey(key).id) }))
    .filter((l) => l.item);
  const field = "w-full rounded-lg border border-stone-200 px-2.5 py-1.5 text-sm focus:border-brand-600 focus:outline-none";

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      onSent(await sendOrder(c, d));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="rounded-xl border border-stone-200 bg-white p-4">
      <h4 className="font-medium text-stone-800">Your order from {c.business_name}</h4>
      <ul className="mt-2 divide-y divide-line text-sm">
        {lines.map(({ key, q, variant, item }) => (
          <li key={key} className="flex justify-between py-1.5">
            <span>
              {q}× {item!.name}
              {variant && <span className="text-stone-500"> ({label(variant)})</span>}
            </span>
            <span className="tabular-nums text-stone-600">{money(item!.amount === null ? null : item!.amount * q, item!.currency) || "price on request"}</span>
          </li>
        ))}
      </ul>
      <div className="mt-1 flex justify-between border-t border-stone-200 pt-2 text-sm font-semibold">
        <span>Total</span>
        <span className="tabular-nums">{total === null ? "confirmed by the business" : money(total, currency)}</span>
      </div>
      <div className="mt-4 grid gap-2 sm:grid-cols-2">
        <input required maxLength={80} placeholder="Your name" value={d.customer_name} onChange={(e) => setD({ ...d, customer_name: e.target.value })} className={field} />
        <input required maxLength={120} placeholder="Phone or email" value={d.customer_contact} onChange={(e) => setD({ ...d, customer_contact: e.target.value })} className={field} />
        <input maxLength={40} placeholder="When? e.g. today 19:00" value={d.pickup_time} onChange={(e) => setD({ ...d, pickup_time: e.target.value })} className={field} />
        <input maxLength={300} placeholder="Note (optional)" value={d.note} onChange={(e) => setD({ ...d, note: e.target.value })} className={field} />
      </div>
      {error && <p className="mt-2 text-sm text-soft-red-ink">{error}</p>}
      <p className="mt-3 text-xs text-stone-500">{c.business_name} confirms or declines your order; you'll see the answer here. Nothing is paid now.</p>
      <div className="mt-3 flex gap-2">
        <Button type="submit" loading={busy}>
          <ShoppingBag className="size-4" /> Send order
        </Button>
        <Button type="button" variant="secondary" onClick={onBack} disabled={busy}>
          Back
        </Button>
      </div>
    </form>
  );
}

function OrderStatus({ c, onStatus }: { c: ChatCatalog; onStatus: (status: ChatOrder["status"], note: string) => void }) {
  const o = c.order!;
  // Ask every 10 s while the business hasn't answered. Refs keep the timer steady while the rest
  // of the chat re-renders (a new answer streaming in).
  const latest = useRef({ c, onStatus });
  latest.current = { c, onStatus };
  useEffect(() => {
    if (o.status !== "pending") return;
    const timer = setInterval(() => {
      const { c: now, onStatus: report } = latest.current;
      orderStatus(now).then((s) => s.status !== "pending" && report(s.status, s.owner_note), () => undefined);
    }, 10_000);
    return () => clearInterval(timer);
  }, [o.order_id, o.status]);

  const tone = o.status === "accepted" ? "border-tag-green bg-soft-green" : o.status === "declined" ? "border-tag-red bg-soft-red" : "border-stone-200 bg-stone-50";
  return (
    <div className={cx("rounded-xl border p-4 text-sm", tone)}>
      <div className="flex items-center gap-2 font-medium text-stone-800">
        {o.status === "pending" && <Loader2 className="size-4 animate-spin text-stone-500" />}
        {o.status === "accepted" && <Check className="size-4 text-emerald-700" />}
        {o.status === "declined" && <CircleX className="size-4 text-soft-red-ink" />}
        {o.status === "pending" ? `Sent to ${c.business_name}, waiting for their answer…` : o.status === "accepted" ? `${c.business_name} accepted your order` : `${c.business_name} declined your order`}
      </div>
      <p className="mt-1 text-stone-600">
        {o.lines.map((l) => `${l.quantity}× ${l.name}`).join(", ")}
        {o.total !== null && ` · ${money(o.total, o.currency)}`}
      </p>
      {o.owner_note && <p className="mt-1 text-stone-700">“{o.owner_note}”</p>}
    </div>
  );
}

/** A catalog from a business's own tool, drawn as picture cards; when the business takes orders,
 * the visitor picks quantities (and sizes, colours... for shops), reviews and sends the order to the
 * business's Oasis inbox. */
export function ItemGrid({ c, onChange }: { c: ChatCatalog; onChange: (c: ChatCatalog) => void }) {
  const [all, setAll] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [picks, setPicks] = useState<Record<string, Record<string, string>>>({});
  // Ordering needs the business's yes and a list with prices (not projects or skills).
  const canPick = c.orderable && !c.order && c.items.some((i) => i.price);
  const { count, total, currency } = cartTotal(c);
  const items = all ? c.items : c.items.slice(0, SHOWN);
  const sections = [...new Set(items.map((i) => i.section))];
  // Lists without pictures (projects, skills...) get text cards: no empty picture boxes.
  const pictures = c.items.some((i) => i.image_url);

  const pick = (item: CatalogItem, axis: string, value: string) => {
    const current = variantOf(item, picks[item.id]).split("/");
    const now = Object.fromEntries(axesOf(item).map((a, n) => [a, current[n]]));
    setPicks((p) => ({ ...p, [item.id]: { ...now, [axis]: value } }));
  };

  return (
    <div className="space-y-3">
      <div className="text-sm text-stone-500">
        <span className="font-medium text-stone-800">{c.title}</span> · {c.business_name} · {c.items.length} item{c.items.length === 1 ? "" : "s"}
      </div>
      {sections.map((section) => (
        <div key={section || "-"}>
          {sections.length > 1 && section && <h4 className="mb-1.5 text-xs font-semibold tracking-wide text-stone-500 uppercase">{section}</h4>}
          <div className={cx("grid gap-2.5", pictures ? "grid-cols-2 lg:grid-cols-3" : "sm:grid-cols-2")}>
            {items
              .filter((i) => i.section === section)
              .map((i) => (
                <ItemCard
                  key={i.id}
                  item={i}
                  cart={c.cart}
                  canPick={canPick}
                  pictures={pictures}
                  picks={picks[i.id]}
                  onPick={(axis, value) => pick(i, axis, value)}
                  onQty={(key, q) => onChange({ ...c, cart: { ...c.cart, [key]: q } })}
                />
              ))}
          </div>
        </div>
      ))}
      {c.items.length > SHOWN && (
        <button onClick={() => setAll((a) => !a)} className="text-sm font-medium text-brand-800 hover:underline">
          {all ? "Show fewer" : `Show all ${c.items.length}`}
        </button>
      )}
      {!c.orderable && c.items.some((i) => i.amount !== null) && <p className="text-xs text-stone-500">{c.business_name} doesn't take orders through Oasis. Contact them directly to order.</p>}

      {canPick && count > 0 && !reviewing && (
        <div className="sticky bottom-2 flex items-center justify-between gap-3 rounded-xl bg-stone-800 px-4 py-2.5 text-white shadow-lg">
          <span className="text-sm">
            Your order · {count} item{count === 1 ? "" : "s"}
            {total !== null && ` · ${money(total, currency)}`}
          </span>
          <button onClick={() => setReviewing(true)} className="rounded-full bg-white px-3 py-1 text-sm font-medium text-stone-800 hover:bg-stone-100">
            Review order
          </button>
        </div>
      )}
      {canPick && reviewing && <Review c={c} onBack={() => setReviewing(false)} onSent={(order) => (setReviewing(false), onChange({ ...c, order }))} />}
      {c.order && <OrderStatus c={c} onStatus={(status, owner_note) => onChange({ ...c, order: { ...c.order!, status, owner_note } })} />}
    </div>
  );
}
