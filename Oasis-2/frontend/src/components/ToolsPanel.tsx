import { Link } from "react-router-dom";
import { ArrowRight, Clock, Loader2, Sparkles, Wrench } from "lucide-react";
import { api } from "../lib/api";
import type { Proposal, Tool } from "../types";
import { CheckBadge, SensitivityBadge, signature } from "./toolLabels";
import { Badge, Card, CardHeader, EmptyState, Toggle } from "./ui";

export function ProposalBanners({ businessId, proposals }: { businessId: string; proposals: Proposal[] }) {
  const open = proposals.filter((p) => p.status === "generating" || p.status === "pending");
  if (open.length === 0) return null;
  return (
    <div className="space-y-2">
      {open.map((p) => {
        const count = p.items.filter((i) => i.decision === null).length;
        return (
          <Link key={p.id} to={`/workspaces/${businessId}/proposals/${p.id}`} className="block">
            <Card className="flex items-center justify-between gap-3 border-brand-100 bg-brand-50/60 px-5 py-3 hover:bg-brand-50">
              <span className="flex items-center gap-2 text-sm text-brand-800">
                {p.status === "generating" ? <Loader2 className="size-4 animate-spin" /> : <Sparkles className="size-4" />}
                {p.status === "generating"
                  ? "Working out a tool from your recording…"
                  : `${count} suggested change${count === 1 ? "" : "s"} to your tools from ${p.source === "crawl" ? "your website" : "a recording"}. Review them.`}
              </span>
              <ArrowRight className="size-4 text-brand-700" />
            </Card>
          </Link>
        );
      })}
    </div>
  );
}

export function ToolsPanel({ businessId, tools, onChange }: { businessId: string; tools: Tool[]; onChange: () => void }) {
  const toggle = async (t: Tool, enabled: boolean) => {
    await api(`/api/workspaces/${businessId}/tools/${t.id}`, { method: "PATCH", json: { enabled } });
    onChange();
  };

  return (
    <Card>
      <CardHeader title="Your tools" description="What AI assistants will be able to do at your business. Every change is a new version you can roll back." />
      {tools.length === 0 ? (
        <EmptyState icon={<Wrench className="size-6" />} title="No tools yet">
          Add the tools found on your website, or turn a recorded flow into a tool.
        </EmptyState>
      ) : (
        <ul className="divide-y divide-stone-100">
          {tools.map((t) => (
            <li key={t.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
              <Link to={`/workspaces/${businessId}/tools/${t.id}`} className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium hover:text-brand-700">{t.current?.title ?? t.name}</span>
                  {t.current && <SensitivityBadge value={t.current.sensitivity} />}
                  {t.current && <CheckBadge badge={t.current.badge} checking={t.checking} />}
                  <Badge>v{t.current_version}</Badge>
                  {t.waiting_version && (
                    <Badge tone="amber">
                      <Clock className="size-3" /> v{t.waiting_version} waiting
                    </Badge>
                  )}
                </div>
                <code className="text-xs text-stone-500">{signature(t.name, t.current?.inputs ?? [])}</code>
                {t.current && <p className="mt-0.5 text-sm text-stone-600">{t.current.description_for_owner}</p>}
              </Link>
              <Toggle checked={t.enabled} onChange={(v) => toggle(t, v)} label={t.enabled ? "On" : "Off"} />
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
