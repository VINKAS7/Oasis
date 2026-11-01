import { useState } from "react";
import { Bot, Check, CircleDot, Copy, Radio, Server, TrendingUp } from "lucide-react";
import { api, timeAgo } from "../lib/api";
import type { LiveInfo } from "../types";
import { Badge, Button, Callout, ErrorNote, SectionTitle } from "./ui";

const OUTCOME: Record<string, { label: string; tone: "green" | "amber" | "red" | "neutral" }> = {
  ok: { label: "done", tone: "green" },
  needs_confirmation: { label: "asked the customer first", tone: "neutral" },
  rule: { label: "stopped by your rule", tone: "amber" },
  failed: { label: "failed", tone: "red" },
  rate_limited: { label: "too many calls", tone: "amber" },
  bad_input: { label: "bad input", tone: "amber" },
  not_published: { label: "not published", tone: "neutral" },
};

function CopyText({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      onClick={async () => {
        await navigator.clipboard.writeText(text);
        setDone(true);
        setTimeout(() => setDone(false), 1500);
      }}
      className="inline-flex max-w-full items-center gap-1.5 rounded bg-stone-100 px-2 py-1 font-mono text-xs text-stone-700 hover:bg-stone-200"
    >
      <span className="truncate">{text}</span>
      {done ? <Check className="size-3 shrink-0 text-emerald-600" /> : <Copy className="size-3 shrink-0" />}
    </button>
  );
}

export function LivePanel({ businessId, info, onChange }: { businessId: string; info: LiveInfo; onChange: (i: LiveInfo) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const live = info.status === "live";
  // Tools that passed their checks: on the server while it is live, ready for it while it isn't.
  const published = info.tools.filter((t) => t.published);
  const readyCount = published.length;
  const serverName = businessId.replace(/^biz_/, "").replace(/_/g, "-");
  const desktopConfig = JSON.stringify({ mcpServers: { [serverName]: { command: "npx", args: ["-y", "mcp-remote", info.server_url] } } }, null, 2);

  const toggle = async () => {
    if (live && !confirm("Unpublish your MCP server? AI assistants and the customer chat will no longer find or use this business.")) return;
    setBusy(true);
    setError("");
    try {
      onChange(await api<LiveInfo>(`/api/workspaces/${businessId}/publish`, { method: "POST", json: { live: !live } }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <SectionTitle
        action={
          <Button variant={live ? "secondary" : "primary"} onClick={toggle} loading={busy}>
            {live ? "Unpublish" : <><Radio className="size-4" /> Publish MCP server</>}
          </Button>
        }
      >
        <span className="flex items-center gap-2">
          MCP server {live ? <Badge tone="green">live</Badge> : <Badge>not published</Badge>}
        </span>
      </SectionTitle>
      <ErrorNote>{error}</ErrorNote>

      {live ? (
        <Callout tone="green" icon={<CircleDot className="size-4" />} className="mb-4">
          Published {timeAgo(info.published_at)}. Your MCP server offers {published.length} tool{published.length === 1 ? "" : "s"}, and customers can find you in the Oasis chat and directory.
        </Callout>
      ) : (
        <Callout icon={<Bot className="size-4" />} className="mb-4">
          {readyCount > 0
            ? `Not published yet. Publishing gives your business its own MCP server with the ${readyCount} tool${readyCount === 1 ? "" : "s"} that passed their checks, and lists it in the Oasis chat and directory, so AI assistants can answer about you.`
            : "Not published yet. Approve your tools and run their checks first: only checked tools go on your MCP server."}
        </Callout>
      )}

      <div className="grid gap-6 md:grid-cols-2">
        <div className="space-y-2 text-sm">
          <h3 className="font-medium text-stone-800">Tools on your MCP server</h3>
          <ul className="space-y-1">
            {info.tools.map((t) => (
              <li key={t.id} className="flex items-center justify-between gap-2">
                <span className="truncate">{t.title ?? t.name}</span>
                {t.published ? <Badge tone="green">{live ? "published" : "ready"}</Badge> : <Badge>{t.reason}</Badge>}
              </li>
            ))}
            {info.tools.length === 0 && <li className="text-stone-500">No tools yet.</li>}
          </ul>
        </div>
        <div className="space-y-2 text-sm">
          <h3 className="flex items-center gap-1.5 font-medium text-stone-800">
            <Server className="size-4" /> Your MCP server
          </h3>
          <p className="text-stone-500">
            {live ? "Give this address to any AI assistant (MCP, streamable HTTP). It has your tools only:" : "Your address, once published (MCP, streamable HTTP):"}
          </p>
          <CopyText text={info.server_url} />
          {info.public ? (
            <>
              <details className="text-stone-500">
                <summary className="cursor-pointer">Add to ChatGPT</summary>
                <p className="mt-1">
                  Settings → Apps &amp; Connectors → Advanced settings → turn on Developer mode. Then Create, paste the address above, choose No authentication and
                  save. In a chat, pick it under + → Developer mode.
                </p>
              </details>
              <details className="text-stone-500">
                <summary className="cursor-pointer">Add to Claude</summary>
                <p className="mt-1">Settings → Connectors → Add custom connector, paste the address above and add it. It works in Claude on the web, desktop and mobile.</p>
              </details>
            </>
          ) : (
            <>
              <p className="text-xs text-stone-500">
                Only this computer can reach this address. To add it to ChatGPT or Claude, give Oasis a public address (<code>PUBLIC_API_URL</code>) and start it
                with <code>npm run dev:public</code>.
              </p>
              <details className="text-stone-500">
                <summary className="cursor-pointer">Claude Desktop on this computer</summary>
                <p className="mt-1">
                  Add this to <code>claude_desktop_config.json</code> and restart Claude:
                </p>
                <pre className="mt-1 overflow-x-auto rounded bg-stone-100 p-2 text-xs text-stone-700">{desktopConfig}</pre>
              </details>
            </>
          )}
          <p className="pt-1 text-xs text-stone-500">
            Assistants connected to the shared Oasis directory find you too: <code>{info.mcp_url}</code>
          </p>
        </div>
      </div>

      <h3 className="mt-6 mb-2 text-sm font-medium text-stone-800">
        Activity <span className="font-normal text-stone-500">· {info.stats_7d.calls} calls in 7 days, {info.stats_7d.ok} done</span>
      </h3>
      {info.activity.length === 0 ? (
        <p className="text-sm text-stone-500">No AI assistant has used your tools yet.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-stone-200">
          <table className="w-full text-sm">
            <tbody className="divide-y divide-line">
              {info.activity.map((c) => {
                const o = OUTCOME[c.outcome] ?? { label: c.outcome, tone: "neutral" as const };
                return (
                  <tr key={c.id}>
                    <td className="px-3 py-2 whitespace-nowrap text-stone-500">{timeAgo(c.created_at)}</td>
                    <td className="px-3 py-2">
                      <code className="text-xs">{c.tool_name}</code>
                    </td>
                    <td className="max-w-xs truncate px-3 py-2 text-xs text-stone-500">
                      {Object.entries(c.inputs)
                        .map(([k, v]) => `${k}: ${v}`)
                        .join(", ")}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <Badge tone={o.tone}>{o.label}</Badge>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <h3 className="mt-6 mb-2 flex items-center gap-1.5 text-sm font-medium text-stone-800">
        <TrendingUp className="size-4" /> Demand you missed <span className="font-normal text-stone-500">· last 7 days</span>
      </h3>
      {info.demand.length === 0 ? (
        <p className="text-sm text-stone-500">Nothing yet. When assistants nearby look for something your business doesn't mention, it shows up here.</p>
      ) : (
        <ul className="flex flex-wrap gap-2 text-sm">
          {info.demand.map((d) => (
            <li key={d.keyword} className="rounded-md border border-stone-200 px-2.5 py-1">
              “{d.keyword}” <span className="text-stone-500">· asked {d.n}×</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
