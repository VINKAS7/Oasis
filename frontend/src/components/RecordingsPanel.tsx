import { useState } from "react";
import { Link } from "react-router-dom";
import { Circle, GitCompare, Plus, Video, Wrench } from "lucide-react";
import { api, plural, timeAgo } from "../lib/api";
import type { Recording } from "../types";
import { Badge, Button, Card, CardHeader, EmptyState } from "./ui";

export function LiveRecordingBanner({ rec, onChange }: { rec: Recording; onChange: () => void }) {
  const [busy, setBusy] = useState("");
  const stop = async (what: "finish" | "cancel") => {
    if (what === "cancel" && !confirm("Discard this recording? Nothing will be saved.")) return;
    setBusy(what);
    try {
      await api(`/api/workspaces/${rec.business_id}/recordings/${rec.id}/${what}`, { method: "POST" });
    } finally {
      setBusy("");
      onChange();
    }
  };
  const steps = rec.live_steps ?? [];
  return (
    <Card className="border-red-200 bg-red-50/40">
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
        <div className="flex items-start gap-3">
          <Circle className="mt-1 size-3 animate-pulse fill-red-500 text-red-500" />
          <div>
            <div className="font-semibold">Recording “{rec.title}”</div>
            <p className="text-sm text-stone-600">
              A browser window is open on the computer running Oasis. Do the task there, then press Finish in its panel or here.
            </p>
            <p className="mt-1 text-xs text-stone-500">
              {plural(steps.length, "step")} · {plural(rec.actions_count, "action")} · {plural(rec.requests_count, "request")} captured
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => stop("cancel")} loading={busy === "cancel"}>
            Discard
          </Button>
          <Button onClick={() => stop("finish")} loading={busy === "finish"}>
            Finish
          </Button>
        </div>
      </div>
    </Card>
  );
}

export function RecordingsPanel({
  businessId,
  recordings,
  onRecord,
  onMakeTool,
}: {
  businessId: string;
  recordings: Recording[];
  onRecord: () => void;
  onMakeTool: (recId: string) => void;
}) {
  const flows = new Map<string, Recording[]>();
  for (const r of recordings) flows.set(r.flow_name, [...(flows.get(r.flow_name) ?? []), r]);

  return (
    <Card>
      <CardHeader
        title="Recorded flows"
        description="Bookings, orders, enquiries and other actions you showed Oasis. Record each one twice with different values."
        action={
          <Button variant="secondary" onClick={onRecord}>
            <Plus className="size-4" /> Record a flow
          </Button>
        }
      />
      {recordings.length === 0 ? (
        <EmptyState icon={<Video className="size-6" />} title="No recordings yet">
          Pick an item from your to-do list, or record any other flow.
        </EmptyState>
      ) : (
        <ul className="divide-y divide-stone-100">
          {[...flows.entries()].map(([flow, recs]) => {
            const finished = recs.filter((r) => r.status === "finished");
            return (
              <li key={flow} className="px-5 py-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{recs[0].title}</span>
                    <code className="text-xs text-stone-500">{flow}</code>
                    <Badge tone={finished.length >= 2 ? "green" : "amber"}>recorded {finished.length}×</Badge>
                  </div>
                  <div className="flex items-center gap-3">
                  {finished.length >= 1 && (
                    <button onClick={() => onMakeTool(finished[0].id)} className="inline-flex items-center gap-1 text-sm font-medium text-brand-700 hover:underline">
                      <Wrench className="size-4" /> Turn into a tool
                    </button>
                  )}
                  {finished.length >= 2 && (
                    <Link to={`/workspaces/${businessId}/recordings/${finished[0].id}#compare`} className="inline-flex items-center gap-1 text-sm font-medium text-brand-700 hover:underline">
                      <GitCompare className="size-4" /> Compare recordings
                    </Link>
                  )}
                  </div>
                </div>
                <ul className="mt-2 space-y-1">
                  {recs.map((r) => (
                    <li key={r.id} className="flex flex-wrap items-center gap-2 text-sm">
                      {r.status === "finished" ? (
                        <Link to={`/workspaces/${businessId}/recordings/${r.id}`} className="text-brand-700 hover:underline">
                          {r.source === "upload" ? "Uploaded" : "Recorded"} {timeAgo(r.uploaded_at)}
                        </Link>
                      ) : (
                        <span className="text-stone-600">{timeAgo(r.uploaded_at)}</span>
                      )}
                      <span className="text-xs text-stone-500">
                        {plural(r.steps_count, "step")} · {plural(r.actions_count, "action")} · {plural(r.requests_count, "request")}
                      </span>
                      {r.status === "recording" && <Badge tone="red">recording</Badge>}
                      {r.status === "failed" && (
                        <Badge tone="red" className="max-w-md truncate">
                          failed: {r.error}
                        </Badge>
                      )}
                    </li>
                  ))}
                </ul>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
