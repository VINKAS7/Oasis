import type { ChatCatalog, ChatEvent, ChatOrder, ChatThread, ChatTurn } from "../types";
import { ApiError, api } from "./api";

/** POSTs to the chat API and calls onEvent for each NDJSON line as it streams in. */
export async function streamChat(path: string, body: unknown, onEvent: (e: ChatEvent) => void, signal?: AbortSignal): Promise<void> {
  const res = await fetch(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body), signal });
  if (!res.ok || !res.body) {
    const data = await res.json().catch(() => null);
    const detail = data && typeof data.detail === "string" ? data.detail : `The assistant isn't answering (${res.status}).`;
    throw new ApiError(res.status, detail);
  }
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    let nl: number;
    while ((nl = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, nl).trim();
      buffer = buffer.slice(nl + 1);
      if (line) onEvent(JSON.parse(line) as ChatEvent);
    }
  }
}

/** What the API needs from the conversation: plain user and assistant text. */
export function toMessages(turns: ChatTurn[]): { role: "user" | "assistant"; content: string }[] {
  return turns.filter((t) => t.text.trim()).map((t) => ({ role: t.role, content: t.text.slice(0, 4000) })).slice(-30);
}

/** Businesses already shown in this chat, so follow-up questions use their real ids. */
export function knownBusinesses(turns: ChatTurn[]): { business_id: string; name: string }[] {
  const seen = new Map<string, string>();
  for (const t of turns) for (const b of t.businesses ?? []) seen.set(b.business_id, b.name);
  return [...seen].slice(-20).map(([business_id, name]) => ({ business_id, name }));
}

// Chats are kept in this browser only: the public chat has no accounts.
const KEY = "agentready.chats.v1";

export function loadThreads(): ChatThread[] {
  try {
    const data = JSON.parse(localStorage.getItem(KEY) ?? "[]");
    return Array.isArray(data) ? data : [];
  } catch {
    return [];
  }
}

export function saveThreads(threads: ChatThread[]): void {
  localStorage.setItem(KEY, JSON.stringify(threads.slice(0, 30)));
}

export const newId = () => Math.random().toString(36).slice(2, 10);

export interface OrderDetails {
  customer_name: string;
  customer_contact: string;
  pickup_time: string;
  note: string;
}

/** A cart line's key: the item id, plus the chosen variant for items with options ("prd_1::M/Black"). */
export const cartKey = (id: string, variant = "") => (variant ? `${id}::${variant}` : id);

export function splitCartKey(key: string): { id: string; variant: string } {
  const at = key.indexOf("::");
  return at < 0 ? { id: key, variant: "" } : { id: key.slice(0, at), variant: key.slice(at + 2) };
}

/** Sends the order the visitor reviewed. Their click on Send order is the confirmation. */
export function sendOrder(c: ChatCatalog, details: OrderDetails): Promise<ChatOrder> {
  const items = Object.entries(c.cart)
    .filter(([, q]) => q > 0)
    .map(([key, quantity]) => {
      const { id, variant } = splitCartKey(key);
      const axes = Object.keys(c.items.find((i) => i.id === id)?.options ?? {});
      const values = variant ? variant.split("/") : [];
      return { id, quantity, ...(variant ? { options: Object.fromEntries(axes.map((a, n) => [a, values[n] ?? ""])) } : {}) };
    });
  return api<ChatOrder>("/api/chat/order", { method: "POST", json: { business_id: c.business_id, items, ...details } });
}

export function orderStatus(c: ChatCatalog): Promise<{ status: ChatOrder["status"]; owner_note: string }> {
  const o = c.order!;
  const q = new URLSearchParams({ business_id: c.business_id, token: o.status_token });
  return api(`/api/chat/orders/${o.order_id}?${q}`);
}

export function money(amount: number | null | undefined, currency: string, locale?: string): string {
  if (amount === null || amount === undefined) return "";
  try {
    return new Intl.NumberFormat(locale, { style: "currency", currency: currency || "CHF" }).format(amount);
  } catch {
    return `${currency} ${amount.toFixed(2)}`.trim();
  }
}
