import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Clock, FlaskConical, RefreshCw, Trash2, Wrench } from "lucide-react";
import { api, timeAgo } from "../lib/api";
import type { Tool, ToolVersion } from "../types";
import { CheckBadge, SensitivityBadge, signature } from "../components/toolLabels";
import { CheckReport, RealTestDialog } from "../components/CheckReport";
import { RulesSection } from "../components/RulesSection";
import { Badge, Button, Card, ErrorNote, PageLoader, Toggle } from "../components/ui";

function source(v: ToolVersion, businessId: string) {
  const [kind, id] = v.created_from.split(":");
  if (kind === "recording")
    return (
      <Link to={`/workspaces/${businessId}/recordings/${id}`} className="text-brand-700 hover:underline">
        a recording
      </Link>
    );
  if (kind === "crawl") return "your website";
  return "you";
}

/** What changed from the previous version, in plain words. */
function changes(v: ToolVersion, prev: ToolVersion | undefined): string[] {
  if (!prev) return [];
  const out: string[] = [];
  const before = new Set(prev.inputs.map((i) => i.name));
  const after = new Set(v.inputs.map((i) => i.name));
  const added = [...after].filter((n) => !before.has(n));
  const removed = [...before].filter((n) => !after.has(n));
  if (added.length) out.push(`Now also asks for ${added.join(", ")}.`);
  if (removed.length) out.push(`No longer asks for ${removed.join(", ")}.`);
  if (v.runner_summary !== prev.runner_summary) out.push(`Runs differently: ${v.runner_summary}`);
  if (v.description_for_ai !== prev.description_for_ai) out.push("New description for AI assistants.");
  if (v.title !== prev.title) out.push(`Renamed from “${prev.title}”.`);
  if (v.sensitivity !== prev.sensitivity) out.push("Sensitivity changed.");
  return out;
}

export function ToolPage() {
  const { id, tid } = useParams<{ id: string; tid: string }>();
  const navigate = useNavigate();
  const [tool, setTool] = useState<Tool | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<number | null>(null);
  const [realTest, setRealTest] = useState<ToolVersion | null>(null);

  const load = useCallback(() => api<Tool>(`/api/workspaces/${id}/tools/${tid}`).then(setTool, (e) => setError(e.message)), [id, tid]);
  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    if (!tool?.checking) return;
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [tool?.checking, load]);

  if (error && !tool) return <ErrorNote>{error}</ErrorNote>;
  if (!tool) return <PageLoader />;
  const versions = tool.versions ?? [];
  const current = tool.current;

  const use = async (version: number) => {
    setBusy(version);
    setError("");
    try {
      setTool(await api<Tool>(`/api/workspaces/${id}/tools/${tid}/use`, { method: "POST", json: { version } }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };
  const toggle = async (enabled: boolean) => setTool(await api<Tool>(`/api/workspaces/${id}/tools/${tid}`, { method: "PATCH", json: { enabled } }));
  const recheck = async (version: number) => {
    setError("");
    try {
      await api(`/api/workspaces/${id}/tools/${tid}/versions/${version}/check`, { method: "POST", json: {} });
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const remove = async () => {
    if (!confirm(`Remove ${tool.name}? AI assistants will no longer see it. Its history is kept.`)) return;
    await api(`/api/workspaces/${id}/tools/${tid}`, { method: "DELETE" });
    navigate(`/workspaces/${id}`);
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <Wrench className="mb-3 size-10 text-stone-700" strokeWidth={1.4} />
          <h1 className="text-[2.5rem] leading-tight font-bold tracking-tight">{current?.title ?? tool.name}</h1>
          <code className="text-sm text-stone-500">{signature(tool.name, current?.inputs ?? [])}</code>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {current && <SensitivityBadge value={current.sensitivity} />}
            {current && <CheckBadge badge={current.badge} checking={tool.checking} />}
            {current?.rate_limit && <Badge>max {current.rate_limit} calls/min</Badge>}
            <Badge>
              v{tool.current_version} in use · {versions.length} version{versions.length === 1 ? "" : "s"}
            </Badge>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <Toggle checked={tool.enabled} onChange={toggle} label={tool.enabled ? "On" : "Off"} />
          <Button variant="danger" onClick={remove} title="Remove tool">
            <Trash2 className="size-4" />
          </Button>
        </div>
      </div>

      {tool.waiting_version && (
        <div className="flex gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          <Clock className="mt-0.5 size-4 shrink-0" />
          Version {tool.waiting_version} is approved. It replaces version {tool.current_version} as soon as it passes the checks below, or when you switch to it yourself.
        </div>
      )}
      <ErrorNote>{error}</ErrorNote>

      <div className="space-y-4">
        {versions.map((v, n) => {
          const inUse = v.version === tool.current_version;
          const diff = changes(v, versions[n + 1]);
          return (
            <Card key={v.id} className={inUse ? "ring-2 ring-brand-600" : ""}>
              <div className="flex flex-wrap items-start justify-between gap-3 border-b border-stone-100 px-5 py-4">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="font-semibold">Version {v.version}</h2>
                    {inUse && <Badge tone="teal">in use</Badge>}
                    <CheckBadge badge={v.badge} checking={v.latest_check?.status === "queued" || v.latest_check?.status === "running"} />
                  </div>
                  <p className="mt-0.5 text-xs text-stone-500">
                    From {source(v, id!)}, {timeAgo(v.created_at)}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  {!inUse && (
                    <Button variant="secondary" onClick={() => use(v.version)} loading={busy === v.version}>
                      {v.version < (tool.current_version ?? 0) ? "Roll back to this version" : "Use this version"}
                    </Button>
                  )}
                </div>
              </div>
              <div className="space-y-2 px-5 py-4 text-sm">
                {v.reason && <p className="text-stone-700">{v.reason}</p>}
                {diff.length > 0 && (
                  <ul className="list-disc space-y-0.5 pl-5 text-stone-600">
                    {diff.map((d) => (
                      <li key={d}>{d}</li>
                    ))}
                  </ul>
                )}
                <p>
                  <span className="font-medium">For you: </span>
                  {v.description_for_owner}
                </p>
                <p>
                  <span className="font-medium">For AI assistants: </span>
                  {v.description_for_ai}
                </p>
                <p>
                  <span className="font-medium">How it runs: </span>
                  {v.runner_summary}
                </p>
                <div className="mt-3 rounded-lg border border-stone-200 p-3">
                  <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                    <span className="font-medium">Checks</span>
                    <div className="flex gap-2">
                      <Button variant="secondary" onClick={() => recheck(v.version)} disabled={tool.checking}>
                        <RefreshCw className="size-4" /> Check again
                      </Button>
                      {v.sensitivity !== "read_only" && (
                        <Button variant="secondary" onClick={() => setRealTest(v)} disabled={tool.checking}>
                          <FlaskConical className="size-4" /> Run a real test
                        </Button>
                      )}
                    </div>
                  </div>
                  {v.latest_check ? <CheckReport check={v.latest_check} /> : <p className="text-stone-500">Not checked yet.</p>}
                </div>
                {v.inputs.length > 0 && (
                  <p className="text-stone-600">
                    Asks for:{" "}
                    {v.inputs.map((i) => (
                      <span key={i.name} className="mr-2 inline-flex items-center gap-1">
                        <code>{i.name}</code>
                        <span className="text-xs text-stone-400">({i.type})</span>
                        {i.personal && <Badge tone="amber">personal</Badge>}
                      </span>
                    ))}
                  </p>
                )}
              </div>
            </Card>
          );
        })}
      </div>
      <RulesSection businessId={id!} toolId={tid!} inputs={current?.inputs ?? []} />
      {realTest && (
        <RealTestDialog
          businessId={id!}
          toolId={tid!}
          version={realTest}
          samples={tool.sample_inputs}
          onClose={() => setRealTest(null)}
          onStarted={() => {
            setRealTest(null);
            load();
          }}
        />
      )}
    </div>
  );
}
