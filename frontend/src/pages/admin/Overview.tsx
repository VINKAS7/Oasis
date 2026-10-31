import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { CheckCircle2, CircleAlert } from "lucide-react";
import { api, timeAgo } from "../../lib/api";
import type { Alert, Overview } from "../../types";
import { Button, Card, CardHeader, ErrorNote, PageLoader, Stat } from "../../components/ui";
import { AdminTitle } from "./AdminLayout";

const TASK_LABELS: Record<string, string> = {
  page_analysis: "Page analysis (crawler)",
  site_summary: "Site summary (tools and to-do lists)",
  tool_proposal: "Tool proposal (recording to tool)",
  safety_scan: "Safety scan (tool output)",
  assistant: "Owner assistant (/api/ai/complete)",
};

export function AdminOverview() {
  const [data, setData] = useState<Overview | null>(null);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api<Overview>("/api/admin/overview").then(setData, (e) => setError(e.message));
    api<Alert[]>("/api/admin/alerts?limit=10").then(setAlerts, () => undefined);
  }, []);

  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!data) return <PageLoader />;

  return (
    <div className="space-y-6">
      <AdminTitle title="Overview" description="The platform at a glance." />
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Users" value={data.users} hint={`${data.admins} admin${data.admins === 1 ? "" : "s"}`} />
        <Stat label="Workspaces" value={data.workspaces} hint={`${data.tools} tools`} />
        <Stat label="Crawls" value={data.crawls} hint={data.crawls_running ? `${data.crawls_running} running now` : "none running"} />
        <Stat
          label="AI calls (24 h)"
          value={data.ai_24h.calls}
          hint={`${data.ai_24h.errors} failed · ${(data.ai_24h.input_tokens + data.ai_24h.output_tokens).toLocaleString()} tokens`}
        />
      </div>

      <Card>
        <CardHeader title="Tool alerts" description={`Blocked or broken tools on any workspace. ${data.alerts_24h} in the last 24 hours.`} />
        {alerts.length === 0 ? (
          <p className="px-5 py-4 text-sm text-stone-500">No alerts.</p>
        ) : (
          <ul className="divide-y divide-stone-100">
            {alerts.map((a) => (
              <li key={a.id} className="px-5 py-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <span className={a.level === "blocked" ? "font-medium text-red-700" : "font-medium text-amber-800"}>{a.level}</span>
                  <Link to={`/workspaces/${a.business_id}/tools/${a.tool_id}`} className="text-brand-700 hover:underline">
                    {a.business_name} · {a.tool_name}
                  </Link>
                  <span className="text-xs text-stone-400">{timeAgo(a.created_at)}</span>
                </div>
                <p className="text-stone-600">{a.message}</p>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card>
        <CardHeader
          title="AI readiness"
          description="Each task needs a working provider, either its own route or the default."
          action={
            data.providers === 0 && (
              <Link to="/admin/providers">
                <Button>Add an AI provider</Button>
              </Link>
            )
          }
        />
        <ul className="divide-y divide-stone-100">
          {Object.entries(data.ai_ready).map(([task, ok]) => (
            <li key={task} className="flex items-center justify-between px-5 py-3 text-sm">
              <span>{TASK_LABELS[task] ?? task}</span>
              {ok ? (
                <span className="flex items-center gap-1.5 text-emerald-700">
                  <CheckCircle2 className="size-4" /> Ready
                </span>
              ) : (
                <Link to="/admin/routing" className="flex items-center gap-1.5 text-amber-700 hover:underline">
                  <CircleAlert className="size-4" /> Not configured
                </Link>
              )}
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
