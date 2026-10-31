import type { ChatEvent, ChatThread, ChatTurn } from "../types";
import { ApiError } from "./api";

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
