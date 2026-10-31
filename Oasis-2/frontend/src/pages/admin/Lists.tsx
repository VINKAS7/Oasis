import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, timeAgo } from "../../lib/api";
import type { AICall, AdminWorkspace } from "../../types";
import { CrawlBadge } from "../../components/CrawlBadge";
import { Badge, Card, ErrorNote, PageLoader, Select } from "../../components/ui";
import { AdminTitle } from "./AdminLayout";

export function AdminWorkspaces() {
  const [items, setItems] = useState<AdminWorkspace[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api<AdminWorkspace[]>("/api/admin/workspaces").then(setItems, (e) => setError(e.message));
  }, []);
  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!items) return <PageLoader />;

  return (
    <div>
      <AdminTitle title="Workspaces" description={`All ${items.length} businesses on the platform.`} />
      <Card className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-stone-50 text-left text-xs text-stone-500 uppercase">
            <tr>
              <th className="px-5 py-2 font-medium">Business</th>
              <th className="px-3 py-2 font-medium">Owner</th>
              <th className="px-3 py-2 font-medium">Website</th>
              <th className="px-3 py-2 font-medium">Latest crawl</th>
              <th className="px-3 py-2 font-medium">Created</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-stone-100">
            {items.map((w) => (
              <tr key={w.id} className="hover:bg-stone-50">
                <td className="px-5 py-3">
                  <Link to={`/workspaces/${w.id}`} className="font-medium text-brand-700 hover:underline">
                    {w.name}
                  </Link>
                  <div className="text-xs text-stone-500">
                    {w.type} · <code>{w.id}</code>
                  </div>
                </td>
                <td className="px-3 py-3 text-stone-600">{w.owner_email ?? "—"}</td>
                <td className="max-w-xs truncate px-3 py-3 text-stone-600">{w.website_url.replace(/^https?:\/\//, "") || "—"}</td>
                <td className="px-3 py-3">{w.crawl_status ? <CrawlBadge run={{ status: w.crawl_status, ai_status: w.ai_status ?? "pending" }} /> : "—"}</td>
                <td className="px-3 py-3 text-stone-500">{timeAgo(w.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

export function AdminUsage() {
  const [items, setItems] = useState<AICall[] | null>(null);
  const [task, setTask] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api<AICall[]>(`/api/admin/ai-calls?limit=200${task ? `&task=${task}` : ""}`).then(setItems, (e) => setError(e.message));
  }, [task]);

  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!items) return <PageLoader />;

  return (
    <div>
      <AdminTitle
        title="AI usage"
        description="Every request that went through the AI gateway, newest first."
        action={
          <Select value={task} onChange={(e) => setTask(e.target.value)} className="w-48">
            <option value="">All tasks</option>
            <option value="page_analysis">page_analysis</option>
            <option value="site_summary">site_summary</option>
            <option value="tool_proposal">tool_proposal</option>
            <option value="safety_scan">safety_scan</option>
            <option value="assistant">assistant</option>
            <option value="connection_test">connection_test</option>
          </Select>
        }
      />
      <Card className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-stone-50 text-left text-xs text-stone-500 uppercase">
            <tr>
              <th className="px-5 py-2 font-medium">When</th>
              <th className="px-3 py-2 font-medium">Task</th>
              <th className="px-3 py-2 font-medium">Provider / model</th>
              <th className="px-3 py-2 font-medium">Who</th>
              <th className="px-3 py-2 text-right font-medium">Tokens in / out</th>
              <th className="px-3 py-2 text-right font-medium">Time</th>
              <th className="px-5 py-2 font-medium">Result</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-stone-100">
            {items.map((c) => (
              <tr key={c.id}>
                <td className="px-5 py-2.5 whitespace-nowrap text-stone-500">{timeAgo(c.created_at)}</td>
                <td className="px-3 py-2.5">
                  <code className="text-xs">{c.task}</code>
                </td>
                <td className="px-3 py-2.5">
                  <div>{c.provider_name ?? "deleted provider"}</div>
                  <code className="text-xs text-stone-500">{c.model}</code>
                </td>
                <td className="px-3 py-2.5 text-xs text-stone-600">{c.user_email ?? c.business_id ?? "system"}</td>
                <td className="px-3 py-2.5 text-right tabular-nums text-stone-600">
                  {c.input_tokens?.toLocaleString() ?? "–"} / {c.output_tokens?.toLocaleString() ?? "–"}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums text-stone-500">{c.latency_ms != null ? `${(c.latency_ms / 1000).toFixed(1)} s` : ""}</td>
                <td className="max-w-xs px-5 py-2.5">
                  {c.ok ? <Badge tone="green">ok</Badge> : <span className="line-clamp-2 text-xs text-red-700">{c.error}</span>}
                </td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr>
                <td colSpan={7} className="px-5 py-8 text-center text-stone-500">
                  No AI requests yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
