import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Check, Copy, Server } from "lucide-react";
import { api, timeAgo } from "../../lib/api";
import type { AdminMcpServer } from "../../types";
import { kindLabel } from "../../components/businessTypes";
import { Badge, Card, EmptyState, ErrorNote, PageLoader, cx } from "../../components/ui";
import { AdminTitle } from "./AdminLayout";

function CopyUrl({ url, muted }: { url: string; muted: boolean }) {
  const [done, setDone] = useState(false);
  return (
    <button
      onClick={async () => {
        await navigator.clipboard.writeText(url);
        setDone(true);
        setTimeout(() => setDone(false), 1500);
      }}
      className={cx("inline-flex max-w-full items-center gap-1.5 rounded bg-stone-100 px-2 py-1 font-mono text-xs hover:bg-stone-200", muted ? "text-stone-400" : "text-stone-700")}
      title="Copy the address"
    >
      <span className="truncate">{url}</span>
      {done ? <Check className="size-3 shrink-0 text-emerald-600" /> : <Copy className="size-3 shrink-0" />}
    </button>
  );
}

/** Every business's own MCP server: who published it and which tools it offers. */
export function AdminMcpServers() {
  const [items, setItems] = useState<AdminMcpServer[] | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    api<AdminMcpServer[]>("/api/admin/mcp-servers").then(setItems, (e) => setError(e.message));
  }, []);
  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!items) return <PageLoader />;

  const live = items.filter((s) => s.status === "live");
  const shown = showAll ? items : live;

  return (
    <div>
      <AdminTitle
        title="MCP servers"
        description={`${live.length} published of ${items.length} businesses. Each published business has its own MCP server with its checked tools.`}
        action={
          <div className="flex rounded-md border border-stone-200 p-0.5 text-sm">
            {[false, true].map((all) => (
              <button key={String(all)} onClick={() => setShowAll(all)} className={cx("rounded px-2.5 py-1", showAll === all ? "bg-hover font-medium text-stone-800" : "text-stone-500")}>
                {all ? `All (${items.length})` : `Published (${live.length})`}
              </button>
            ))}
          </div>
        }
      />
      {shown.length === 0 ? (
        <Card>
          <EmptyState icon={<Server className="size-6" />} title="No MCP server is published yet">
            Owners publish theirs from their workspace, under MCP server, once their tools have passed their checks.
          </EmptyState>
        </Card>
      ) : (
        <div className="space-y-3">
          {shown.map((s) => {
            const isLive = s.status === "live";
            return (
              <Card key={s.id} className="p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <Link to={`/workspaces/${s.id}`} className="font-semibold text-brand-700 hover:underline">
                        {s.name}
                      </Link>
                      {isLive ? <Badge tone="green">live</Badge> : <Badge>not published</Badge>}
                    </div>
                    <div className="mt-0.5 text-xs text-stone-500">
                      {kindLabel(s.type, s.category_label)}
                      {s.online_only && " · online only"} · owner {s.owner_email ?? "unknown"}
                      {isLive && s.published_at && ` · published ${timeAgo(s.published_at)}`} · {s.calls_7d} call{s.calls_7d === 1 ? "" : "s"} in 7 days
                    </div>
                  </div>
                  <CopyUrl url={s.server_url} muted={!isLive} />
                </div>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {s.tools.map((t) => (
                    <span
                      key={t.id}
                      title={t.published ? (isLive ? "On the server" : "Checked, goes on the server when published") : `Not on the server (${t.enabled ? t.badge ?? "unchecked" : "switched off"})`}
                      className={cx(
                        "inline-flex items-center gap-1 rounded border px-1.5 py-0.5 font-mono text-xs",
                        t.published ? "border-[#dbeddb] bg-[#edf3ec] text-[#1c3829]" : "border-stone-200 text-stone-400 line-through",
                      )}
                    >
                      {t.name}
                      {t.sensitivity && t.sensitivity !== "read_only" && <span className="font-sans text-[10px] no-underline">· confirm</span>}
                    </span>
                  ))}
                  {s.tools.length === 0 && <span className="text-xs text-stone-400">No tools yet</span>}
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
