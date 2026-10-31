import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { AlertTriangle, Download, GitCompare, Lock, Trash2, Video, Wrench } from "lucide-react";
import { api, plural, timeAgo } from "../lib/api";
import type { FlowComparison, Proposal, RecordingAction, RecordingDetail, RecordingRequest, RecordingStep } from "../types";
import { Badge, Button, Card, CardHeader, ErrorNote, PageLoader, Textarea } from "../components/ui";

function describeAction(a: RecordingAction): string {
  const target = a.label || a.name || a.text || a.selector || "the page";
  switch (a.type) {
    case "click":
      return `Clicked “${a.text || a.label || a.selector}”`;
    case "fill":
      return a.personal ? `Typed personal details into ${target} (masked)` : `Typed “${a.value}” into ${target}`;
    case "select":
      return `Chose “${a.option_text || a.value}” in ${target}`;
    case "check":
      return `Ticked ${target}`;
    case "uncheck":
      return `Unticked ${target}`;
    case "press":
      return `Pressed ${a.key} in ${target}`;
    case "submit":
      return `Sent the form ${a.selector ?? ""}`;
    default:
      return `${a.type} ${a.selector ?? ""}`;
  }
}

function json(v: unknown): string {
  return typeof v === "string" ? v : JSON.stringify(v, null, 2);
}

function RequestRow({ r }: { r: RecordingRequest }) {
  const status = r.response?.status;
  return (
    <details className="rounded-lg border border-stone-200 text-sm">
      <summary className="flex cursor-pointer flex-wrap items-center gap-2 px-3 py-2">
        <Badge tone={r.method === "GET" ? "neutral" : "blue"}>{r.method}</Badge>
        <code className="min-w-0 flex-1 truncate text-xs">{r.url}</code>
        {r.error ? <Badge tone="red">{r.error}</Badge> : status != null && <Badge tone={status < 400 ? "green" : "red"}>{status}</Badge>}
      </summary>
      <div className="grid gap-2 border-t border-stone-100 p-3 sm:grid-cols-2">
        <div>
          <div className="mb-1 text-xs font-medium text-stone-500">Sent</div>
          <pre className="max-h-64 overflow-auto rounded bg-stone-50 p-2 text-xs">{r.body == null ? "—" : json(r.body)}</pre>
        </div>
        <div>
          <div className="mb-1 text-xs font-medium text-stone-500">Answer</div>
          <pre className="max-h-64 overflow-auto rounded bg-stone-50 p-2 text-xs">{r.response?.body == null ? "—" : json(r.response.body)}</pre>
        </div>
      </div>
    </details>
  );
}

function StepCard({ step, businessId, recId, editable, onSaveNote }: { step: RecordingStep; businessId: string; recId: string; editable: boolean; onSaveNote: (n: number, text: string) => Promise<void> }) {
  const [note, setNote] = useState(step.owner_note);
  const [saving, setSaving] = useState(false);
  useEffect(() => setNote(step.owner_note), [step.owner_note]);
  const shot = step.screenshot ? `/api/workspaces/${businessId}/recordings/${recId}/screenshots/${step.screenshot}` : null;

  return (
    <Card className="overflow-hidden">
      <div className="grid md:grid-cols-[280px_1fr]">
        <div className="border-b border-stone-100 bg-stone-50 md:border-r md:border-b-0">
          {shot ? (
            <a href={shot} target="_blank" rel="noreferrer" title="Open full size">
              <img src={shot} alt={`Step ${step.n}`} className="h-auto w-full" loading="lazy" />
            </a>
          ) : (
            <div className="flex h-full min-h-32 items-center justify-center text-xs text-stone-400">No screenshot</div>
          )}
        </div>
        <div className="space-y-3 p-4">
          <div className="flex flex-wrap items-center gap-2">
            <span className="flex size-6 items-center justify-center rounded-full bg-brand-700 text-xs font-semibold text-white">{step.n}</span>
            <code className="min-w-0 truncate text-xs text-stone-500">{step.page}</code>
          </div>
          {editable ? (
            <Textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              onBlur={async () => {
                if (note === step.owner_note) return;
                setSaving(true);
                await onSaveNote(step.n, note);
                setSaving(false);
              }}
              placeholder="In one sentence: what does the customer do on this step?"
              className={saving ? "opacity-60" : ""}
              maxLength={500}
            />
          ) : (
            step.owner_note && <p className="text-sm text-stone-700">{step.owner_note}</p>
          )}
          {step.actions.length > 0 && (
            <ol className="space-y-1 text-sm text-stone-700">
              {step.actions.map((a, i) => (
                <li key={i} className="flex items-start gap-2">
                  <span className="mt-0.5 text-xs text-stone-400 tabular-nums">{i + 1}.</span>
                  <span>
                    {describeAction(a)}
                    {a.personal && <Lock className="ml-1 inline size-3 text-stone-400" />}
                    {a.frame_url && <span className="ml-1 text-xs text-stone-400">(inside an embedded widget)</span>}
                  </span>
                </li>
              ))}
            </ol>
          )}
          {step.requests.length > 0 && (
            <div className="space-y-1.5">
              <div className="text-xs font-medium text-stone-500 uppercase">Messages to the server</div>
              {step.requests.map((r, i) => (
                <RequestRow key={i} r={r} />
              ))}
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}

function Comparison({ businessId, flow }: { businessId: string; flow: string }) {
  const [data, setData] = useState<FlowComparison | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api<FlowComparison>(`/api/workspaces/${businessId}/flows/${flow}/compare`).then(setData, (e) => setError(e.message));
  }, [businessId, flow]);
  if (error) return null; // fewer than two recordings: nothing to compare yet
  if (!data) return null;

  return (
    <Card>
      <span id="compare" />
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            <GitCompare className="size-4 text-brand-700" /> What changes between your two recordings
          </span>
        }
        description="Values that differ are what a customer's assistant must provide. Values that stay the same are built into the tool."
      />
      <div className="space-y-4 p-5">
        {data.likely_request && (
          <div className="rounded-lg border border-brand-100 bg-brand-50 px-3 py-2 text-sm text-brand-800">
            The message that most likely does the job (saves the booking, order or request): <code>{data.likely_request.method} {data.likely_request.url}</code>
            {data.likely_request.status != null && ` (answered ${data.likely_request.status})`}, in step {data.likely_request.step}.
          </div>
        )}
        {data.warnings.map((w) => (
          <div key={w} className="flex gap-2 text-sm text-amber-800">
            <AlertTriangle className="mt-0.5 size-4 shrink-0" /> {w}
          </div>
        ))}
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-stone-500 uppercase">
              <tr>
                <th className="py-2 pr-3 font-medium">Input</th>
                <th className="py-2 pr-3 font-medium">Type</th>
                <th className="py-2 pr-3 font-medium">Your values</th>
                <th className="py-2 font-medium">Found in</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-stone-100">
              {data.inputs.map((i) => (
                <tr key={i.name}>
                  <td className="py-2 pr-3">
                    <code>{i.name}</code> {i.personal && <Badge tone="amber">personal</Badge>}
                  </td>
                  <td className="py-2 pr-3 text-stone-600">{i.type}</td>
                  <td className="py-2 pr-3 text-stone-600">{i.examples.map(String).join(", ")}</td>
                  <td className="py-2 text-xs text-stone-500">{i.where.join("; ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {data.fixed.length > 0 && (
          <details className="text-sm">
            <summary className="cursor-pointer text-stone-600">{data.fixed.length} values stay the same</summary>
            <ul className="mt-2 space-y-0.5 text-xs text-stone-600">
              {data.fixed.map((f, i) => (
                <li key={i}>
                  {f.where}: <code>{String(f.value)}</code>
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </Card>
  );
}

export function RecordingPage() {
  const { id, rid } = useParams<{ id: string; rid: string }>();
  const navigate = useNavigate();
  const [rec, setRec] = useState<RecordingDetail | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => api<RecordingDetail>(`/api/workspaces/${id}/recordings/${rid}`).then(setRec, (e) => setError(e.message)), [id, rid]);
  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    if (rec?.status !== "recording") return;
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [rec?.status, load]);

  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!rec) return <PageLoader />;

  const steps = rec.document?.steps ?? rec.live_steps ?? [];
  const saveNote = async (n: number, text: string) => {
    const updated = await api<RecordingDetail>(`/api/workspaces/${id}/recordings/${rid}`, { method: "PATCH", json: { notes: { [n]: text } } });
    setRec(updated);
  };
  const remove = async () => {
    if (!confirm("Delete this recording?")) return;
    await api(`/api/workspaces/${id}/recordings/${rid}`, { method: "DELETE" });
    navigate(`/workspaces/${id}`);
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <Video className="mb-3 size-10 text-stone-700" strokeWidth={1.4} />
          <h1 className="text-[2.5rem] leading-tight font-bold tracking-tight">{rec.title}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-stone-500">
            <code>{rec.flow_name}</code>
            <span>·</span>
            <span>
              {rec.source === "extension" ? "Recorded with the extension" : rec.source === "upload" ? "Uploaded" : "Recorded"} {timeAgo(rec.uploaded_at)}
            </span>
            <span>·</span>
            <span>
              {plural(rec.steps_count, "step")}, {plural(rec.actions_count, "action")}, {plural(rec.requests_count, "request")}
            </span>
            {rec.status !== "finished" && <Badge tone="red">{rec.status}</Badge>}
          </div>
        </div>
        {rec.status === "finished" && (
          <div className="flex gap-2">
            <Button
              onClick={async () => {
                try {
                  const p = await api<Proposal>(`/api/workspaces/${id}/proposals`, { method: "POST", json: { source: "recording", source_id: rid } });
                  navigate(`/workspaces/${id}/proposals/${p.id}`);
                } catch (e) {
                  setError((e as Error).message);
                }
              }}
            >
              <Wrench className="size-4" /> Turn into a tool
            </Button>
            <a href={`/api/workspaces/${id}/recordings/${rid}/download`}>
              <Button variant="secondary">
                <Download className="size-4" /> Download JSON
              </Button>
            </a>
            <Button variant="danger" onClick={remove} title="Delete recording">
              <Trash2 className="size-4" />
            </Button>
          </div>
        )}
      </div>

      {rec.status === "failed" && <ErrorNote>{rec.error}</ErrorNote>}
      {rec.status === "recording" && <p className="text-sm text-stone-600">Recording in progress. Steps appear here as you go.</p>}

      {rec.status === "finished" && <Comparison businessId={id!} flow={rec.flow_name} />}

      <div className="space-y-4">
        {steps.map((s) => (
          <StepCard key={s.n} step={s} businessId={id!} recId={rid!} editable={rec.status === "finished"} onSaveNote={saveNote} />
        ))}
      </div>
    </div>
  );
}
