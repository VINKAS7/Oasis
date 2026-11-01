import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Link } from "react-router-dom";
import { ArrowUp, Building2, LocateFixed, MapPin, Menu, SquarePen, Square, Trash2, X } from "lucide-react";
import { AssistantMessage, UserMessage } from "../components/chat/Message";
import { OasisLogo, OasisMark } from "../components/Brand";
import { ThemeToggle } from "../components/ThemeToggle";
import { cx } from "../components/ui";
import { knownBusinesses, loadThreads, newId, saveThreads, streamChat, toMessages } from "../lib/chat";
import type { ChatEvent, ChatThread, ChatTurn } from "../types";

const SUGGESTIONS = ["What's the nearest restaurant?", "Which restaurants are open now near me?", "Find a vegetarian lunch nearby", "Any café near me with Wi-Fi?"];

interface Place {
  label: string;
  value: string; // "lat, lng" or a place name, passed to find_nearby
}

const PLACE_KEY = "agentready.chat.place";

function loadPlace(): Place | null {
  try {
    return JSON.parse(localStorage.getItem(PLACE_KEY) ?? "null");
  } catch {
    return null;
  }
}

/** Applies one streamed event to the assistant turn being written. */
function applyEvent(turn: ChatTurn, e: ChatEvent): ChatTurn {
  switch (e.type) {
    case "step":
      return { ...turn, steps: [...(turn.steps ?? []), { tool: e.tool, arguments: e.arguments, done: false }] };
    case "result": {
      const steps = [...(turn.steps ?? [])];
      const i = steps.map((s) => s.tool === e.tool && !s.done).lastIndexOf(true);
      if (i >= 0) steps[i] = { ...steps[i], done: true, ok: e.ok, summary: e.summary };
      return { ...turn, steps, businesses: e.businesses?.length ? e.businesses : turn.businesses };
    }
    case "confirm": {
      const { type: _type, ...confirm } = e;
      return { ...turn, confirm: { ...confirm, state: "pending" } };
    }
    case "reply":
      return { ...turn, text: e.text };
    case "items": {
      const { type: _type, ...catalog } = e;
      return { ...turn, catalog: { ...catalog, cart: {} } };
    }
    case "error":
      return { ...turn, error: e.message };
    default:
      return turn;
  }
}

function LocationPill({ place, onChange }: { place: Place | null; onChange: (p: Place | null) => void }) {
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [error, setError] = useState("");
  const [locating, setLocating] = useState(false);

  const useMine = () => {
    setError("");
    if (!navigator.geolocation) return setError("Your browser can't share its location. Type a place instead.");
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLocating(false);
        onChange({ label: "Your location", value: `${pos.coords.latitude.toFixed(5)}, ${pos.coords.longitude.toFixed(5)}` });
        setOpen(false);
      },
      () => {
        setLocating(false);
        setError("Location was blocked. Type a street, area or city instead.");
      },
      { timeout: 10000 },
    );
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!typed.trim()) return;
    onChange({ label: typed.trim(), value: typed.trim() });
    setTyped("");
    setOpen(false);
  };

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={cx(
          "flex items-center gap-1.5 rounded-full border px-3 py-1 text-[14px] transition-colors",
          place ? "border-brand-100 bg-brand-50 text-brand-800" : "border-stone-200 text-stone-500 hover:bg-hover",
        )}
      >
        <MapPin className="size-3.5" />
        {place ? place.label : "Set your location"}
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute top-full right-0 z-20 mt-2 w-72 rounded-xl border border-stone-200 bg-white p-3 shadow-[0_8px_24px_rgba(15,15,15,0.12)]">
            <button
              type="button"
              onClick={useMine}
              disabled={locating}
              className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-sm hover:bg-hover disabled:opacity-60"
            >
              <LocateFixed className="size-4 text-brand-700" /> {locating ? "Finding you…" : "Use my current location"}
            </button>
            <form onSubmit={submit} className="mt-2 flex gap-2">
              <input
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                placeholder="Or type a place, e.g. Marktplatz Basel"
                className="min-w-0 flex-1 rounded-lg border border-stone-200 px-2.5 py-1.5 text-sm focus:border-brand-600 focus:outline-none"
              />
              <button type="submit" className="rounded-lg bg-stone-800 px-2.5 text-sm text-white">
                Set
              </button>
            </form>
            {error && <p className="mt-2 text-xs text-soft-red-ink">{error}</p>}
            {place && (
              <button type="button" onClick={() => (onChange(null), setOpen(false))} className="mt-2 text-xs text-stone-500 hover:underline">
                Forget my location
              </button>
            )}
            <p className="mt-2 text-[12px] leading-snug text-stone-400">Used only to search nearby places, never stored on our side.</p>
          </div>
        </>
      )}
    </div>
  );
}

function ThreadList({ threads, activeId, onPick, onNew, onDelete }: { threads: ChatThread[]; activeId: string | null; onPick: (id: string) => void; onNew: () => void; onDelete: (id: string) => void }) {
  return (
    <div className="flex h-full flex-col px-2 py-3">
      <div className="flex items-center justify-between px-2 pb-3">
        <span className="flex items-center gap-2 font-semibold text-stone-800">
          <OasisLogo />
        </span>
      </div>
      <button onClick={onNew} className="flex items-center gap-2 rounded-lg px-2 py-2 text-sm text-stone-700 hover:bg-hover">
        <SquarePen className="size-4" /> New chat
      </button>
      <div className="mt-4 px-2 pb-1 text-xs font-medium text-stone-500">Recent</div>
      <div className="min-h-0 flex-1 space-y-px overflow-y-auto">
        {threads.map((t) => (
          <div key={t.id} className={cx("group flex items-center rounded-lg", t.id === activeId ? "bg-hover" : "hover:bg-hover")}>
            <button onClick={() => onPick(t.id)} className="min-w-0 flex-1 truncate px-2 py-1.5 text-left text-sm text-stone-700">
              {t.title}
            </button>
            <button onClick={() => onDelete(t.id)} className="mr-1 hidden rounded p-1 text-stone-400 group-hover:block hover:text-stone-700" title="Delete chat">
              <Trash2 className="size-3.5" />
            </button>
          </div>
        ))}
        {threads.length === 0 && <p className="px-2 py-1 text-xs text-stone-400">Your chats stay in this browser.</p>}
      </div>
      <Link to="/login" className="mt-2 flex items-center gap-2 rounded-lg px-2 py-2 text-sm text-stone-500 hover:bg-hover hover:text-stone-700">
        <Building2 className="size-4" /> For businesses →
      </Link>
    </div>
  );
}

export function ChatPage() {
  const [threads, setThreads] = useState<ChatThread[]>(loadThreads);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [place, setPlace] = useState<Place | null>(loadPlace);
  const [menuOpen, setMenuOpen] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLTextAreaElement>(null);

  const thread = useMemo(() => threads.find((t) => t.id === activeId) ?? null, [threads, activeId]);
  const turns = thread?.turns ?? [];

  useEffect(() => {
    saveThreads(threads);
  }, [threads]);
  useEffect(() => {
    if (place) localStorage.setItem(PLACE_KEY, JSON.stringify(place));
    else localStorage.removeItem(PLACE_KEY);
  }, [place]);
  // Braces matter: newer browsers return a Promise from smooth scrollIntoView, and an effect
  // that returns anything but a cleanup function crashes React on the next update.
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);

  const updateTurn = (threadId: string, turnId: string, change: (t: ChatTurn) => ChatTurn) =>
    setThreads((all) => all.map((th) => (th.id !== threadId ? th : { ...th, updated_at: new Date().toISOString(), turns: th.turns.map((t) => (t.id === turnId ? change(t) : t)) })));

  /** Adds turns to a thread (creating it if needed), streams the answer into the new assistant turn. */
  const run = async (path: string, history: ChatTurn[], extra: Record<string, unknown>, newTurns: ChatTurn[], title: string) => {
    const threadId = activeId ?? newId();
    const reply: ChatTurn = { id: newId(), role: "assistant", text: "", steps: [] };
    setThreads((all) => {
      const existing = all.find((t) => t.id === threadId);
      const updated: ChatThread = existing
        ? { ...existing, turns: [...existing.turns, ...newTurns, reply], updated_at: new Date().toISOString() }
        : { id: threadId, title, turns: [...newTurns, reply], updated_at: new Date().toISOString() };
      return [updated, ...all.filter((t) => t.id !== threadId)];
    });
    setActiveId(threadId);
    setBusy(true);
    abort.current = new AbortController();
    try {
      await streamChat(path, { messages: toMessages(history), location: place?.value ?? "", businesses: knownBusinesses(history), ...extra }, (e) => updateTurn(threadId, reply.id, (t) => applyEvent(t, e)), abort.current.signal);
    } catch (err) {
      const stopped = (err as Error).name === "AbortError";
      updateTurn(threadId, reply.id, (t) => (stopped ? { ...t, text: t.text || "Stopped.", steps: t.steps?.map((s) => ({ ...s, done: true })) } : { ...t, error: (err as Error).message }));
    } finally {
      setBusy(false);
      abort.current = null;
    }
  };

  const send = (text: string) => {
    const content = text.trim();
    if (!content || busy) return;
    setInput("");
    const mine: ChatTurn = { id: newId(), role: "user", text: content };
    void run("/api/chat", [...turns, mine], {}, [mine], content.length > 48 ? `${content.slice(0, 48)}…` : content);
  };

  const confirm = (turn: ChatTurn) => {
    if (!thread || !turn.confirm || busy) return;
    const c = turn.confirm;
    updateTurn(thread.id, turn.id, (t) => ({ ...t, confirm: { ...c, state: "confirmed" } }));
    const yes: ChatTurn = { id: newId(), role: "user", text: "Yes, go ahead." };
    void run("/api/chat/confirm", [...turns, yes], { business_id: c.business_id, tool: c.tool, inputs: c.inputs }, [yes], thread.title);
  };

  const cancel = (turn: ChatTurn) => {
    if (!thread || !turn.confirm) return;
    updateTurn(thread.id, turn.id, (t) => ({ ...t, confirm: { ...t.confirm!, state: "cancelled" } }));
    setThreads((all) =>
      all.map((th) => (th.id !== thread.id ? th : { ...th, turns: [...th.turns, { id: newId(), role: "user", text: "No, cancel that." }, { id: newId(), role: "assistant", text: "Okay, I won't do that. Anything else?" }] })),
    );
  };

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      send(input);
    }
  };

  // Grow the box with its text, up to about eight lines.
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [input]);

  const newChat = () => {
    if (busy) abort.current?.abort();
    setActiveId(null);
    setMenuOpen(false);
    box.current?.focus();
  };

  const list = (
    <ThreadList
      threads={threads}
      activeId={activeId}
      onPick={(id) => (setActiveId(id), setMenuOpen(false))}
      onNew={newChat}
      onDelete={(id) => (setThreads((all) => all.filter((t) => t.id !== id)), id === activeId && setActiveId(null))}
    />
  );

  return (
    <div className="flex h-screen bg-white">
      <aside className="hidden w-64 shrink-0 bg-sidebar md:block">{list}</aside>
      {menuOpen && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div className="absolute inset-0 bg-black/30" onClick={() => setMenuOpen(false)} />
          <aside className="relative h-full w-72 bg-sidebar shadow-xl">
            <button onClick={() => setMenuOpen(false)} className="absolute top-3 right-2 rounded p-1 text-stone-500 hover:bg-hover" aria-label="Close menu">
              <X className="size-4" />
            </button>
            {list}
          </aside>
        </div>
      )}

      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 shrink-0 items-center justify-between gap-2 px-3">
          <div className="flex items-center gap-1">
            <button onClick={() => setMenuOpen(true)} className="rounded p-1.5 text-stone-500 hover:bg-hover md:hidden" aria-label="Open menu">
              <Menu className="size-4" />
            </button>
            <button onClick={newChat} className="rounded p-1.5 text-stone-500 hover:bg-hover md:hidden" aria-label="New chat">
              <SquarePen className="size-4" />
            </button>
          </div>
          <div className="flex items-center gap-1">
            <ThemeToggle />
            <LocationPill place={place} onChange={setPlace} />
          </div>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto">
          {turns.length === 0 ? (
            <div className="mx-auto flex h-full max-w-2xl flex-col items-center justify-center px-4 pb-16 text-center">
              <OasisMark className="mb-5 size-12 text-stone-900" />
              <h1 className="text-3xl font-semibold tracking-tight text-stone-800">What are you looking for?</h1>
              <p className="mt-2 text-stone-500">Find places nearby, check menus, prices and opening hours, and book, all by asking.</p>
              <div className="mt-8 grid w-full gap-2 sm:grid-cols-2">
                {SUGGESTIONS.map((s) => (
                  <button key={s} onClick={() => send(s)} className="rounded-xl border border-stone-200 px-4 py-3 text-left text-sm text-stone-700 hover:bg-stone-50">
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="mx-auto max-w-3xl space-y-6 px-4 py-6">
              {turns.map((t, i) =>
                t.role === "user" ? (
                  <UserMessage key={t.id} turn={t} />
                ) : (
                  <AssistantMessage
                    key={t.id}
                    turn={t}
                    busy={busy && i === turns.length - 1}
                    onConfirm={() => confirm(t)}
                    onCancel={() => cancel(t)}
                    onCatalog={(catalog) => thread && updateTurn(thread.id, t.id, (x) => ({ ...x, catalog }))}
                  />
                ),
              )}
              <div ref={bottom} />
            </div>
          )}
        </div>

        <div className="shrink-0 px-4 pb-4">
          <form
            onSubmit={(e) => (e.preventDefault(), send(input))}
            className="mx-auto flex max-w-3xl items-end gap-2 rounded-3xl border border-stone-200 bg-white px-4 py-2.5 shadow-[0_2px_12px_rgba(15,15,15,0.06)] focus-within:border-stone-300"
          >
            <textarea
              ref={box}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKey}
              rows={1}
              maxLength={4000}
              autoFocus
              placeholder={place ? "Ask about places near you…" : "Ask anything, e.g. what's the nearest restaurant?"}
              className="max-h-[200px] min-h-6 flex-1 resize-none bg-transparent py-1 text-[15px] text-stone-800 placeholder:text-stone-400 focus:outline-none"
            />
            {busy ? (
              <button type="button" onClick={() => abort.current?.abort()} className="flex size-8 shrink-0 items-center justify-center rounded-full bg-stone-800 text-white" aria-label="Stop">
                <Square className="size-3 fill-current" />
              </button>
            ) : (
              <button type="submit" disabled={!input.trim()} className="flex size-8 shrink-0 items-center justify-center rounded-full bg-stone-800 text-white disabled:bg-stone-200" aria-label="Send">
                <ArrowUp className="size-4" />
              </button>
            )}
          </form>
          <p className="mt-2 text-center text-xs text-stone-400">Answers come from the businesses' own Oasis tools. Bookings always wait for your OK.</p>
        </div>
      </main>
    </div>
  );
}
