import { useEffect, useRef, useState, type FormEvent } from "react";
import { Check, CircleX, ImageOff, Loader2, Minus, Plus, ShoppingBag } from "lucide-react";
import { money, orderStatus, sendOrder, type OrderDetails } from "../../lib/chat";
import type { CatalogItem, ChatCatalog, ChatOrder } from "../../types";
import { Button, cx } from "../ui";

const SHOWN = 9;

/** The business's own picture, loaded straight from its site. No referrer is sent, and a broken
 * or missing picture becomes a quiet placeholder. */
function Picture({ item }: { item: CatalogItem }) {
  const [failed, setFailed] = useState(false);
  if (!item.image_url || failed) {
    return (
      <div className="flex aspect-[4/3] items-center justify-center bg-stone-100 text-stone-300">
        <ImageOff className="size-6" />
      </div>
    );
  }
  return <img src={item.image_url} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(true)} className="aspect-[4/3] w-full object-cover" />;
}

function Stepper({ qty, onChange }: { qty: number; onChange: (q: number) => void }) {
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
      <button onClick={() => onChange(Math.min(20, qty + 1))} className="rounded-full p-1.5 hover:bg-stone-700" aria-label="One more">
        <Plus className="size-3" />
      </button>
    </div>
  );
}

function ItemCard({ item, qty, canPick, pictures, onQty }: { item: CatalogItem; qty: number; canPick: boolean; pictures: boolean; onQty: (q: number) => void }) {
  return (
    <div className={cx("overflow-hidden rounded-xl border bg-white transition-colors", qty ? "border-stone-800" : "border-stone-200")}>
      {pictures && <Picture item={item} />}
      <div className="space-y-1 p-3">
        <div className="flex items-start justify-between gap-2">
          <span className="font-medium leading-snug text-stone-800">{item.name}</span>
          {item.price && <span className="shrink-0 text-sm font-medium text-stone-700 tabular-nums">{money(item.amount, item.currency) || item.price}</span>}
        </div>
        {item.description && <p className={cx("text-xs text-stone-500", pictures ? "line-clamp-2" : "line-clamp-4")}>{item.description}</p>}
        {!pictures && item.url && (
          <a href={item.url} target="_blank" rel="noreferrer noopener" className="inline-block text-xs font-medium text-brand-800 hover:underline">
            Open ↗
          </a>
        )}
        {canPick && (
          <div className="pt-1">
            <Stepper qty={qty} onChange={onQty} />
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
  for (const item of c.items) {
    const q = c.cart[item.id] ?? 0;
    if (!q) continue;
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
  const picked = c.items.filter((i) => c.cart[i.id]);
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
        {picked.map((i) => (
          <li key={i.id} className="flex justify-between py-1.5">
            <span>
              {c.cart[i.id]}× {i.name}
            </span>
            <span className="tabular-nums text-stone-600">{money(i.amount === null ? null : i.amount * c.cart[i.id], i.currency) || "price on request"}</span>
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
 * the visitor picks quantities, reviews and sends the order to the business's Oasis inbox. */
export function ItemGrid({ c, onChange }: { c: ChatCatalog; onChange: (c: ChatCatalog) => void }) {
  const [all, setAll] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const canPick = c.orderable && !c.order;
  const { count, total, currency } = cartTotal(c);
  const items = all ? c.items : c.items.slice(0, SHOWN);
  const sections = [...new Set(items.map((i) => i.section))];
  // Lists without pictures (projects, skills...) get text cards: no empty picture boxes.
  const pictures = c.items.some((i) => i.image_url);

  return (
    <div className="space-y-3">
      <div className="text-sm text-stone-500">
        <span className="font-medium text-stone-800">{c.title}</span> · {c.business_name} · {c.items.length} item{c.items.length === 1 ? "" : "s"}
      </div>
      {sections.map((section) => (
        <div key={section || "-"}>
          {sections.length > 1 && section && <h4 className="mb-1.5 text-xs font-semibold tracking-wide text-stone-500 uppercase">{section}</h4>}
          <div className={cx("grid gap-2.5", pictures ? "grid-cols-2 lg:grid-cols-3" : "sm:grid-cols-2")}>
            {items.filter((i) => i.section === section).map((i) => (
              <ItemCard key={i.id} item={i} qty={c.cart[i.id] ?? 0} canPick={canPick} pictures={pictures} onQty={(q) => onChange({ ...c, cart: { ...c.cart, [i.id]: q } })} />
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
