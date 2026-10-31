import { Check, CircleAlert, Loader2, MapPin, ShieldCheck, Sparkles, Store, X } from "lucide-react";
import type { ChatBusiness, ChatCatalog, ChatStep, ChatTurn } from "../../types";
import { ItemGrid } from "./ItemGrid";
import { Button, cx } from "../ui";

const pretty = (name: string) => name.replace(/^(get|list)_/, "").replace(/_/g, " ");

function stepLabel(step: ChatStep): string {
  const a = step.arguments;
  switch (step.tool) {
    case "find_nearby":
      return `Searching nearby${a.type ? ` ${String(a.type)}` : " places"}${a.open_at ? ` open at ${String(a.open_at)}` : ""}`;
    case "search_businesses":
      return `Searching for “${String(a.query ?? "")}”`;
    case "get_business_info":
      return "Looking up the business";
    case "list_business_tools":
      return "Checking what the business offers";
    case "call_business_tool":
      return `Asking the business: ${pretty(String(a.tool ?? "tool"))}`;
    default:
      return pretty(step.tool);
  }
}

function StepChip({ step }: { step: ChatStep }) {
  return (
    <div className="flex items-center gap-1.5 text-[13px] text-stone-500">
      {!step.done ? (
        <Loader2 className="size-3.5 animate-spin" />
      ) : step.ok ? (
        <Check className="size-3.5 text-emerald-600" />
      ) : (
        <CircleAlert className="size-3.5 text-amber-600" />
      )}
      <span>{stepLabel(step)}</span>
      {step.done && step.summary && <span className="text-stone-400">· {step.summary}</span>}
    </div>
  );
}

function distance(km?: number): string {
  if (km === undefined) return "";
  return km < 1 ? `${Math.round(km * 1000)} m` : `${km.toFixed(1)} km`;
}

function BusinessCard({ b }: { b: ChatBusiness }) {
  return (
    <div className="flex gap-3 rounded-xl border border-stone-200 bg-white p-3">
      <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-800">
        <Store className="size-4.5" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <span className="truncate font-medium text-stone-800">{b.name}</span>
          {b.distance_km !== undefined && <span className="shrink-0 text-xs text-stone-500">{distance(b.distance_km)}</span>}
        </div>
        <div className="truncate text-xs text-stone-500">
          {b.kind}
          {b.open_at_requested_time === true && <span className="text-emerald-700"> · open then</span>}
        </div>
        {b.address && (
          <div className="mt-1 flex items-center gap-1 truncate text-xs text-stone-500">
            <MapPin className="size-3 shrink-0" /> {b.address}
          </div>
        )}
      </div>
    </div>
  );
}

const URL_RE = /(https?:\/\/[^\s)]+)/g;

/** Plain text with clickable links. The model is asked for plain text, so nothing else is rendered. */
function Linkified({ text }: { text: string }) {
  return (
    <>
      {text.split(URL_RE).map((part, i) =>
        i % 2 === 1 ? (
          <a key={i} href={part} target="_blank" rel="noreferrer noopener" className="text-brand-800 underline underline-offset-2">
            {part}
          </a>
        ) : (
          part
        ),
      )}
    </>
  );
}

function ConfirmCard({ turn, onConfirm, onCancel }: { turn: ChatTurn; onConfirm: () => void; onCancel: () => void }) {
  const c = turn.confirm!;
  const details = Object.entries(c.would_send);
  return (
    <div className="rounded-xl border border-brand-100 bg-brand-50/60 p-4">
      <div className="flex items-center gap-2 font-medium text-stone-800">
        <ShieldCheck className="size-4 text-brand-800" />
        {pretty(c.tool).replace(/^./, (s) => s.toUpperCase())} at {c.business_name}
      </div>
      {details.length > 0 && (
        <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-4 gap-y-0.5 text-sm">
          {details.map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-stone-500">{k.replace(/_/g, " ")}</dt>
              <dd className="text-stone-800">{String(v)}</dd>
            </div>
          ))}
        </dl>
      )}
      {c.state === "pending" ? (
        <div className="mt-3 flex gap-2">
          <Button onClick={onConfirm}>
            <Check className="size-4" /> Confirm
          </Button>
          <Button variant="secondary" onClick={onCancel}>
            <X className="size-4" /> Cancel
          </Button>
        </div>
      ) : (
        <p className="mt-2 text-sm text-stone-500">{c.state === "confirmed" ? "You confirmed this." : "You cancelled this."}</p>
      )}
    </div>
  );
}

export function UserMessage({ turn }: { turn: ChatTurn }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%] rounded-3xl bg-stone-100 px-4 py-2.5 whitespace-pre-wrap text-stone-800">{turn.text}</div>
    </div>
  );
}

export function AssistantMessage({ turn, busy, onConfirm, onCancel, onCatalog }: { turn: ChatTurn; busy: boolean; onConfirm: () => void; onCancel: () => void; onCatalog: (c: ChatCatalog) => void }) {
  const thinking = busy && !turn.text && !turn.error && !(turn.steps ?? []).some((s) => !s.done);
  return (
    <div className="flex gap-3">
      <div className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full border border-stone-200 bg-white">
        <Sparkles className="size-3.5 text-brand-700" />
      </div>
      <div className="min-w-0 flex-1 space-y-3">
        {(turn.steps?.length ?? 0) > 0 && (
          <div className="space-y-1">
            {turn.steps!.map((s, i) => (
              <StepChip key={i} step={s} />
            ))}
          </div>
        )}
        {turn.businesses && turn.businesses.length > 0 && (
          <div className="grid gap-2 sm:grid-cols-2">
            {turn.businesses.slice(0, 6).map((b) => (
              <BusinessCard key={b.business_id} b={b} />
            ))}
          </div>
        )}
        {thinking && (
          <div className="flex items-center gap-1 py-1.5" aria-label="Thinking">
            {[0, 1, 2].map((i) => (
              <span key={i} className="size-1.5 animate-bounce rounded-full bg-stone-400" style={{ animationDelay: `${i * 150}ms` }} />
            ))}
          </div>
        )}
        {turn.text && (
          <div className={cx("leading-relaxed whitespace-pre-wrap text-stone-800")}>
            <Linkified text={turn.text} />
          </div>
        )}
        {turn.catalog && <ItemGrid c={turn.catalog} onChange={onCatalog} />}
        {turn.confirm && <ConfirmCard turn={turn} onConfirm={onConfirm} onCancel={onCancel} />}
        {turn.error && (
          <div className="flex items-start gap-2 rounded-lg bg-soft-red px-3 py-2 text-sm text-soft-red-ink">
            <CircleAlert className="mt-0.5 size-4 shrink-0" /> {turn.error}
          </div>
        )}
      </div>
    </div>
  );
}
