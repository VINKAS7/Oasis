import { useEffect, useState } from "react";
import { api, timeAgo } from "../../lib/api";
import type { ChatQuality, ChatTurnTrace } from "../../types";
import { Card, CardHeader, ErrorNote, PageLoader, Stat, cx } from "../../components/ui";
import { AdminTitle } from "./AdminLayout";

const OUTCOME_TONE: Record<string, string> = {
  reply: "text-emerald-700",
  confirm: "text-emerald-700",
  fallback: "text-amber-800",
  too_slow: "text-amber-800",
  stopped: "text-stone-500",
  error: "text-red-700",
};

const pct = (v: number | null) => (v === null ? "–" : `${Math.round(v * 100)}%`);
const secs = (ms: number | null | undefined) => (ms === null || ms === undefined ? "–" : `${(ms / 1000).toFixed(1)} s`);

function Trace({ turnId }: { turnId: string }) {
  const [data, setData] = useState<ChatTurnTrace | null>(null);
  useEffect(() => {
    api<ChatTurnTrace>(`/api/admin/chat-quality/${turnId}`).then(setData, () => undefined);
  }, [turnId]);
  if (!data) return <p className="px-5 py-3 text-xs text-stone-400">Loading…</p>;
  return (
    <div className="grid gap-4 bg-stone-50 px-5 py-3 text-xs lg:grid-cols-2">
      <ol className="space-y-1">
        {data.events.map((e, i) => (
          <li key={i} className="flex gap-2">
            <span className="w-14 shrink-0 text-right tabular-nums text-stone-400">{secs(e.ms)}</span>
            <span className="font-medium text-stone-700">{e.kind}</span>
            <span className="truncate text-stone-500">{Object.entries(e.detail).map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : v}`).join(" ")}</span>
          </li>
        ))}
      </ol>
      <ol className="space-y-1">
        {data.llm_calls.map((c, i) => (
          <li key={i} className="flex gap-2">
            <span className="w-14 shrink-0 text-right tabular-nums text-stone-400">#{c.step}</span>
            <span className={c.ok ? "text-stone-700" : "text-red-700"}>{c.model}</span>
            <span className="text-stone-500">
              {secs(c.latency_ms)} · {c.input_tokens ?? "–"}/{c.output_tokens ?? "–"} tokens{c.error ? ` · ${c.error}` : ""}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

/** How the public customer chat is doing: does it answer, how many AI calls and seconds it takes,
 *  and what goes wrong (nudges, repaired answers, failed tools...). */
export function AdminChatQuality() {
  const [days, setDays] = useState(7);
  const [data, setData] = useState<ChatQuality | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setData(null);
    api<ChatQuality>(`/api/admin/chat-quality?days=${days}`).then(setData, (e) => setError(e.message));
  }, [days]);

  if (error) return <ErrorNote>{error}</ErrorNote>;

  return (
    <div className="space-y-6">
      <AdminTitle
        title="Chat quality"
        description="Answers on the public customer chat: what worked, what the agent had to repair, and how long it took. No message text is stored."
        action={
          <select value={days} onChange={(e) => setDays(Number(e.target.value))} className="rounded-lg border border-stone-200 bg-white px-2 py-1.5 text-sm">
            {[1, 7, 30].map((d) => (
              <option key={d} value={d}>
                Last {d === 1 ? "24 hours" : `${d} days`}
              </option>
            ))}
          </select>
        }
      />
      {!data ? (
        <PageLoader />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <Stat label="Answers" value={data.turns} hint={Object.entries(data.outcomes).map(([k, v]) => `${v} ${k}`).join(" · ") || "none yet"} />
            <Stat label="Answered well" value={pct(data.success_rate)} hint="replies and confirm cards" />
            <Stat label="AI calls per answer" value={data.llm_calls_per_turn ?? "–"} hint={`${data.steps_per_turn ?? "–"} steps · ${data.llm_calls_failed} calls failed`} />
            <Stat label="Time per answer" value={secs(data.latency_ms.p50)} hint={`p95 ${secs(data.latency_ms.p95)}`} />
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <CardHeader title="What the agent had to fix" description="Nudges, repaired or retried model answers, guards that stepped in." />
              {data.problems.length === 0 ? (
                <p className="px-5 py-4 text-sm text-stone-500">Nothing to report.</p>
              ) : (
                <ul className="divide-y divide-stone-100 text-sm">
                  {data.problems.map((p) => (
                    <li key={p.kind} className="flex justify-between px-5 py-2">
                      <span className="text-stone-700">{p.kind}</span>
                      <span className="tabular-nums text-stone-500">{p.count}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            <Card>
              <CardHeader title="Tools" description="Gateway tools the chat called, and how often they failed." />
              <ul className="divide-y divide-stone-100 text-sm">
                {data.tools.map((t) => (
                  <li key={t.tool} className="flex justify-between px-5 py-2">
                    <span className="text-stone-700">{t.tool}</span>
                    <span className="tabular-nums text-stone-500">
                      {t.calls}
                      {t.failed ? <span className="text-red-700"> · {t.failed} failed</span> : null}
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
          </div>

          <Card>
            <CardHeader title="Recent answers" description="Click one to see its steps and AI calls." />
            <ul className="divide-y divide-stone-100">
              {data.recent.map((r) => (
                <li key={r.turn_id}>
                  <button onClick={() => setOpen(open === r.turn_id ? null : r.turn_id)} className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-5 py-2.5 text-left text-sm hover:bg-stone-50">
                    <span className={cx("w-16 font-medium", OUTCOME_TONE[r.outcome] ?? "text-stone-700")}>{r.outcome}</span>
                    <span className="w-14 tabular-nums text-stone-500">{secs(r.ms)}</span>
                    <span className="w-8 uppercase text-stone-400">{r.language}</span>
                    <span className="min-w-0 flex-1 truncate text-stone-600">{r.tools.join(" → ") || "no tools"}</span>
                    <span className="text-xs text-stone-400">{timeAgo(r.created_at)}</span>
                  </button>
                  {open === r.turn_id && <Trace turnId={r.turn_id} />}
                </li>
              ))}
              {data.recent.length === 0 && <li className="px-5 py-4 text-sm text-stone-500">No answers yet.</li>}
            </ul>
          </Card>
        </>
      )}
    </div>
  );
}
