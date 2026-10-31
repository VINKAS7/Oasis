import { useCallback, useEffect, useState } from "react";
import { Check, ShoppingBag, X } from "lucide-react";
import { api, timeAgo } from "../lib/api";
import { money } from "../lib/chat";
import type { Order, OrdersInfo } from "../types";
import { Badge, Button, Callout, ErrorNote, SectionTitle, Toggle } from "./ui";

function OrderRow({ businessId, order, onDone }: { businessId: string; order: Order; onDone: (i: OrdersInfo) => void }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<"" | "accepted" | "declined">("");
  const [error, setError] = useState("");
  const pending = order.status === "pending";

  const decide = async (status: "accepted" | "declined") => {
    setBusy(status);
    setError("");
    try {
      onDone(await api<OrdersInfo>(`/api/workspaces/${businessId}/orders/${order.id}`, { method: "POST", json: { status, note } }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  };

  return (
    <li className="px-4 py-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-medium text-stone-800">{order.items.map((l) => `${l.quantity}× ${l.name}`).join(", ")}</span>
            {order.status === "pending" && <Badge tone="amber">new</Badge>}
            {order.status === "accepted" && <Badge tone="green">accepted</Badge>}
            {order.status === "declined" && <Badge tone="red">declined</Badge>}
          </div>
          <div className="mt-0.5 text-sm text-stone-500">
            {order.customer_name} · {order.customer_contact}
            {order.pickup_time && ` · ${order.pickup_time}`} · {timeAgo(order.created_at)}
          </div>
          {order.note && <div className="mt-0.5 text-sm text-stone-600">“{order.note}”</div>}
          {!pending && order.owner_note && <div className="mt-0.5 text-sm text-stone-500">Your note: {order.owner_note}</div>}
        </div>
        <span className="text-sm font-semibold text-stone-800 tabular-nums">{order.total !== null ? money(order.total, order.currency) : "price to confirm"}</span>
      </div>
      {pending && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            maxLength={300}
            placeholder="Note to the customer (optional), e.g. ready at 19:00"
            className="min-w-56 flex-1 rounded-md border border-stone-200 px-2.5 py-1.5 text-sm focus:border-brand-600 focus:outline-none"
          />
          <Button onClick={() => decide("accepted")} loading={busy === "accepted"} disabled={!!busy}>
            <Check className="size-4" /> Accept
          </Button>
          <Button variant="danger" onClick={() => decide("declined")} loading={busy === "declined"} disabled={!!busy}>
            <X className="size-4" /> Decline
          </Button>
        </div>
      )}
      <ErrorNote className="mt-2">{error}</ErrorNote>
    </li>
  );
}

/** Orders customers sent through Oasis from the business's catalog (menu, products...). */
export function OrdersPanel({ businessId, onChange }: { businessId: string; onChange: () => void }) {
  const [info, setInfo] = useState<OrdersInfo | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => api<OrdersInfo>(`/api/workspaces/${businessId}/orders`).then(setInfo, (e) => setError(e.message)), [businessId]);
  useEffect(() => {
    load();
    const timer = setInterval(load, 15_000); // new orders show up without a reload
    return () => clearInterval(timer);
  }, [load]);

  if (!info || (!info.has_catalog && info.orders.length === 0)) return error ? <ErrorNote>{error}</ErrorNote> : null;

  const toggle = async (on: boolean) => {
    setError("");
    try {
      await api(`/api/workspaces/${businessId}`, { method: "PATCH", json: { accepts_orders: on } });
      await load();
      onChange();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div>
      <SectionTitle>
        <span className="flex items-center gap-2">
          Orders {info.pending > 0 && <Badge tone="amber">{info.pending} new</Badge>}
        </span>
      </SectionTitle>
      <ErrorNote>{error}</ErrorNote>
      <div className="mb-4">
        <Toggle
          checked={info.accepts_orders}
          onChange={toggle}
          label="Take orders through Oasis"
          hint="Customers pick from your catalog in the Oasis chat or any AI assistant and send you an order. You accept or decline it here; prices always come from your catalog."
        />
      </div>
      {info.orders.length === 0 ? (
        <Callout icon={<ShoppingBag className="size-4" />}>
          {info.accepts_orders ? "No orders yet. They appear here as soon as a customer sends one." : "Switch on ordering to receive orders here. Your MCP server must be published too."}
        </Callout>
      ) : (
        <ul className="divide-y divide-line rounded-lg border border-stone-200">
          {info.orders.map((o) => (
            <OrderRow key={o.id} businessId={businessId} order={o} onDone={(i) => (setInfo(i), onChange())} />
          ))}
        </ul>
      )}
    </div>
  );
}
