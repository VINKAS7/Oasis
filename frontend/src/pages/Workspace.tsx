import { useCallback, useEffect, useState, type ReactNode } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  AlertTriangle,
  Check,
  CircleDashed,
  ClipboardList,
  Copy,
  ExternalLink,
  FileText,
  Globe,
  MapPin,
  Pencil,
  Phone,
  RefreshCw,
  Sparkles,
  Trash2,
  Wrench,
} from "lucide-react";
import { api, timeAgo } from "../lib/api";
import type { Alert, CrawlDetail, CrawlPageRow, CrawlRun, LiveInfo, Proposal, Recording, Tool, Workspace, WorkspaceInput } from "../types";
import { kindLabel, typeInfo } from "../components/businessTypes";
import { ACTIVE, CrawlBadge } from "../components/CrawlBadge";
import { PageDrawer } from "../components/PageDrawer";
import { WorkspaceForm } from "../components/WorkspaceForm";
import { RecordDialog } from "../components/RecordDialog";
import { LiveRecordingBanner, RecordingsPanel } from "../components/RecordingsPanel";
import { ProposalBanners, ToolsPanel } from "../components/ToolsPanel";
import { AlertsBanner } from "../components/AlertsBanner";
import { LivePanel } from "../components/LivePanel";
import { OrdersPanel } from "../components/OrdersPanel";
import { Badge, Button, Card, CardHeader, EmptyState, ErrorNote, PageLoader } from "../components/ui";
import { PageTitle } from "../components/Layout";

function Property({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="py-1 text-stone-500">{label}</dt>
      <dd className="flex items-center gap-1.5 py-1 text-stone-800">{children}</dd>
    </>
  );
}

function CopyId({ id }: { id: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      onClick={async () => {
        await navigator.clipboard.writeText(id);
        setDone(true);
        setTimeout(() => setDone(false), 1500);
      }}
      className="inline-flex items-center gap-1 rounded-md bg-stone-100 px-1.5 py-0.5 font-mono text-xs text-stone-700 hover:bg-stone-200"
      title="Copy business ID"
    >
      {id} {done ? <Check className="size-3 text-emerald-600" /> : <Copy className="size-3" />}
    </button>
  );
}

function Progress({ run }: { run: CrawlRun }) {
  const crawling = run.status === "crawling" || run.status === "queued";
  const total = crawling ? Math.max(run.pages_found, 1) : Math.max(run.pages_done, 1);
  const done = crawling ? run.pages_done : run.pages_analyzed;
  const pct = Math.min(100, Math.round((done / total) * 100));
  return (
    <div>
      <div className="flex justify-between text-sm">
        <span className="font-medium text-stone-800">
          {run.status === "queued" && "Starting the browser…"}
          {run.status === "crawling" && `Reading your website: ${run.pages_done} of ${run.pages_found} pages found so far`}
          {run.status === "analyzing" && `AI is reading the pages: ${run.pages_analyzed} of ${run.pages_done}`}
        </span>
        <span className="text-stone-500 tabular-nums">{pct}%</span>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-stone-100">
        <div className="h-full rounded-full bg-brand-600 transition-all duration-500" style={{ width: `${pct}%` }} />
      </div>
      <p className="mt-2 text-xs text-stone-500">Up to {run.max_pages} pages. You can leave this page; the work continues.</p>
    </div>
  );
}

type RecordTarget = { flow: string; title: string } | "new";

function timesRecorded(recordings: Recording[], flow: string): number {
  return recordings.filter((r) => r.flow_name === flow && r.status === "finished").length;
}

function Results({
  run,
  recordings,
  toolNames,
  onRecord,
  onAddTools,
}: {
  run: CrawlRun;
  recordings: Recording[];
  toolNames: Set<string>;
  onRecord: (t: RecordTarget) => void;
  onAddTools: () => void;
}) {
  const s = run.summary;
  if (!s) return null;
  return (
    <div className="space-y-5">
      {s.overview && <p className="text-sm leading-relaxed text-stone-700">{s.overview}</p>}

      {s.injection_warnings.length > 0 && (
        <div className="flex gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" />
          <div>
            Some pages contain text aimed at AI assistants (possible prompt injection). Please check: {s.injection_warnings.join(", ")}
          </div>
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader
            title={
              <span className="flex items-center gap-2">
                <Wrench className="size-4 text-emerald-600" /> Tools ready
                <Badge tone="green">{s.tools_ready.length}</Badge>
              </span>
            }
            description="Read-only: they give information and change nothing on your site."
            action={
              s.tools_ready.length > 0 && (
                <Button variant="secondary" onClick={onAddTools}>
                  Add to my tools
                </Button>
              )
            }
          />
          <ul className="divide-y divide-stone-100">
            {s.tools_ready.map((t) => (
              <li key={t.name} className="px-5 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{t.title}</span>
                  <code className="rounded bg-stone-100 px-1.5 py-0.5 text-xs text-stone-600">{t.name}()</code>
                </div>
                <p className="mt-1 text-sm text-stone-600">{t.description_for_owner}</p>
                {t.inputs.length > 0 && (
                  <p className="mt-1 text-xs text-stone-500">Asks for: {t.inputs.map((i) => i.name).join(", ")}</p>
                )}
                {t.source_urls.length > 0 && (
                  <p className="mt-1 truncate text-xs text-stone-400">From {t.source_urls.map((u) => new URL(u, run.start_url).pathname).join(", ")}</p>
                )}
              </li>
            ))}
            {s.tools_ready.length === 0 && <li className="px-5 py-6 text-sm text-stone-500">No read-only information found yet.</li>}
          </ul>
        </Card>

        <Card>
          <CardHeader
            title={
              <span className="flex items-center gap-2">
                <ClipboardList className="size-4 text-amber-600" /> To-do for you
                <Badge tone="amber">{s.todo.length}</Badge>
              </span>
            }
            description="Actions that change something. You record each one once, like a customer would."
          />
          <ul className="divide-y divide-stone-100">
            {s.todo.map((t) => {
              const times = timesRecorded(recordings, t.flow);
              return (
                <li key={t.flow} className="flex items-start justify-between gap-3 px-5 py-3">
                  <div>
                    <div className="flex flex-wrap items-center gap-2 font-medium">
                      Please record: {t.title.toLowerCase()}
                      {times > 0 && <Badge tone={times >= 2 ? "green" : "amber"}>recorded {times}×</Badge>}
                      {toolNames.has(t.flow) && <Badge tone="teal">now a tool</Badge>}
                    </div>
                    <p className="mt-1 text-sm text-stone-600">{times === 1 ? "Record it once more with different values, so we can tell what changes." : t.reason}</p>
                  </div>
                  <Button variant={times >= 2 ? "secondary" : "primary"} onClick={() => onRecord({ flow: t.flow, title: t.title })}>
                    {times === 0 ? "Record" : "Record again"}
                  </Button>
                </li>
              );
            })}
            {s.todo.length === 0 && <li className="px-5 py-6 text-sm text-stone-500">Nothing to record.</li>}
          </ul>
        </Card>
      </div>

      {s.missing.length > 0 && (
        <Card>
          <CardHeader title="Customers may also ask about" description="Things customers expect from this kind of business that your website doesn't show." />
          <ul className="divide-y divide-stone-100">
            {s.missing.map((m) => (
              <li key={m.topic} className="flex gap-2 px-5 py-3 text-sm text-stone-700">
                <CircleDashed className="mt-0.5 size-4 shrink-0 text-stone-400" /> {m.message}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

function CrawlPanel({
  workspace,
  run,
  recordings,
  toolNames,
  onChange,
  onRecord,
}: {
  workspace: Workspace;
  run: CrawlDetail | null;
  recordings: Recording[];
  toolNames: Set<string>;
  onChange: () => void;
  onRecord: (t: RecordTarget) => void;
}) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [openPage, setOpenPage] = useState<CrawlPageRow | null>(null);

  const act = async (what: "crawl" | "analyze") => {
    setError("");
    setBusy(what);
    try {
      const path = what === "crawl" ? `/api/workspaces/${workspace.id}/crawl` : `/api/workspaces/${workspace.id}/crawls/${run!.id}/analyze`;
      await api(path, { method: "POST" });
      onChange();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  };

  if (!workspace.website_url) {
    return (
      <Card>
        <EmptyState icon={<Globe className="size-6" />} title="No website yet">
          Add your website address under Edit details, and we'll read it.
        </EmptyState>
      </Card>
    );
  }
  if (!run) {
    return (
      <Card>
        <EmptyState icon={<Globe className="size-6" />} title="Your website hasn't been read yet">
          <Button className="mt-3" onClick={() => act("crawl")} loading={busy === "crawl"}>
            Read my website
          </Button>
        </EmptyState>
      </Card>
    );
  }

  const active = ACTIVE.has(run.status);
  const canAnalyze = !active && run.pages_done > 0;

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader
          title={
            <span className="flex items-center gap-2">
              What we found on your website <CrawlBadge run={run} />
            </span>
          }
          description={
            <>
              {run.start_url} · started {timeAgo(run.created_at)}
              {run.finished_at && `, finished ${timeAgo(run.finished_at)}`}
            </>
          }
          action={
            <div className="flex gap-2">
              {canAnalyze && (
                <Button variant="secondary" onClick={() => act("analyze")} loading={busy === "analyze"}>
                  <Sparkles className="size-4" /> Re-run AI analysis
                </Button>
              )}
              <Button variant="secondary" onClick={() => act("crawl")} loading={busy === "crawl"} disabled={active}>
                <RefreshCw className="size-4" /> Read again
              </Button>
            </div>
          }
        />
        <div className="space-y-4 px-5 py-4">
          <ErrorNote>{error}</ErrorNote>
          {active && <Progress run={run} />}
          {run.status === "failed" && <ErrorNote>{run.error}</ErrorNote>}
          {!active && run.ai_status === "skipped" && (
            <div className="flex gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
              <Sparkles className="mt-0.5 size-4 shrink-0" />
              <div>
                We read {run.pages_done} pages, but the AI step was skipped: {run.ai_error} Once AI is set up, press <b>Re-run AI analysis</b>.
              </div>
            </div>
          )}
          {!active && run.ai_status === "failed" && <ErrorNote>The AI analysis failed: {run.ai_error}</ErrorNote>}
          {!active && run.ai_status === "done" && (
            <Results
              run={run}
              recordings={recordings}
              toolNames={toolNames}
              onRecord={onRecord}
              onAddTools={async () => {
                setError("");
                try {
                  const p = await api<Proposal>(`/api/workspaces/${workspace.id}/proposals`, { method: "POST", json: { source: "crawl", source_id: String(run.id) } });
                  navigate(`/workspaces/${workspace.id}/proposals/${p.id}`);
                } catch (e) {
                  setError((e as Error).message);
                }
              }}
            />
          )}
        </div>
      </Card>

      {run.pages.length > 0 && (
        <Card>
          <CardHeader title={`Pages read (${run.pages.length})`} description="Click a page to see what the crawler and the AI saw." />
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-stone-50 text-left text-xs text-stone-500 uppercase">
                <tr>
                  <th className="px-5 py-2 font-medium">Page</th>
                  <th className="px-3 py-2 font-medium">Kind</th>
                  <th className="px-3 py-2 font-medium">What it's for</th>
                  <th className="px-3 py-2 text-right font-medium">Forms</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-stone-100">
                {run.pages.map((p) => (
                  <tr key={p.id} onClick={() => setOpenPage(p)} className="cursor-pointer hover:bg-stone-50">
                    <td className="max-w-xs px-5 py-2.5">
                      <div className="truncate font-medium text-stone-800">{p.title || new URL(p.url).pathname}</div>
                      <div className="truncate text-xs text-stone-500">{new URL(p.url).pathname}</div>
                    </td>
                    <td className="px-3 py-2.5">
                      {p.error ? <Badge tone="red">error</Badge> : p.page_kind ? <Badge tone="teal">{p.page_kind}</Badge> : <span className="text-stone-400">–</span>}
                      {p.injection_suspected && (
                        <Badge tone="red" className="ml-1">
                          injection?
                        </Badge>
                      )}
                    </td>
                    <td className="max-w-md px-3 py-2.5 text-stone-600">
                      <span className="line-clamp-2">{p.error || p.purpose || p.analysis_error || ""}</span>
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums text-stone-600">{p.form_count || ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {run.documents.length > 0 && (
        <Card>
          <CardHeader title="Linked documents" description="Files your site links to (PDF price lists, brochures and the like). They are not read yet." />
          <ul className="divide-y divide-stone-100">
            {run.documents.map((d) => (
              <li key={d.url} className="flex items-center gap-2 px-5 py-2.5 text-sm">
                <FileText className="size-4 shrink-0 text-stone-400" />
                <a href={d.url} target="_blank" rel="noreferrer" className="truncate text-brand-700 hover:underline">
                  {d.text || d.url}
                </a>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {openPage && <PageDrawer businessId={workspace.id} page={openPage} onClose={() => setOpenPage(null)} />}
    </div>
  );
}

export function WorkspacePage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [run, setRun] = useState<CrawlDetail | null>(null);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(false);
  const [recordings, setRecordings] = useState<Recording[]>([]);
  const [recordTarget, setRecordTarget] = useState<RecordTarget | null>(null);
  const [tools, setTools] = useState<Tool[]>([]);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [actionError, setActionError] = useState("");
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [liveInfo, setLiveInfo] = useState<LiveInfo | null>(null);

  const load = useCallback(async () => {
    try {
      const ws = await api<Workspace>(`/api/workspaces/${id}`);
      setWorkspace(ws);
      setRun(ws.latest_run ? await api<CrawlDetail>(`/api/workspaces/${id}/crawls/${ws.latest_run.id}`) : null);
      const recs = await api<Recording[]>(`/api/workspaces/${id}/recordings`);
      // The list has counts only; the live recording's detail carries its steps so far.
      const live = recs.find((r) => r.status === "recording");
      const detail = live ? await api<Recording>(`/api/workspaces/${id}/recordings/${live.id}`) : null;
      setRecordings(detail ? recs.map((r) => (r.id === detail.id ? detail : r)) : recs);
      const [ts, ps, al, li] = await Promise.all([
        api<Tool[]>(`/api/workspaces/${id}/tools`),
        api<Proposal[]>(`/api/workspaces/${id}/proposals`),
        api<Alert[]>(`/api/workspaces/${id}/alerts`),
        api<LiveInfo>(`/api/workspaces/${id}/live`),
      ]);
      setTools(ts);
      setProposals(ps);
      setAlerts(al);
      setLiveInfo(li);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  // Poll while a crawl, an analysis or a recording is running.
  const liveRecording = recordings.find((r) => r.status === "recording");
  const active = run ? ACTIVE.has(run.status) : false;
  const generating = proposals.some((p) => p.status === "generating") || tools.some((t) => t.checking);
  useEffect(() => {
    if (!active && !liveRecording && !generating) return;
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [active, liveRecording, generating, load]);

  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!workspace) return <PageLoader />;

  const { icon: Icon } = typeInfo(workspace.type);

  const save = async (value: WorkspaceInput) => {
    await api(`/api/workspaces/${workspace.id}`, { method: "PATCH", json: value });
    setEditing(false);
    load();
  };

  const remove = async () => {
    if (!confirm(`Delete ${workspace.name} and everything read from its website? This can't be undone.`)) return;
    try {
      await api(`/api/workspaces/${workspace.id}`, { method: "DELETE" });
      navigate("/workspaces");
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div className="space-y-6">
      <PageTitle
        icon={<Icon className="size-11" strokeWidth={1.4} />}
        title={workspace.name}
        actions={
          !editing && (
            <>
              <Button variant="ghost" onClick={() => setEditing(true)}>
                <Pencil className="size-4" /> Edit details
              </Button>
              <Button variant="ghost" onClick={remove} disabled={active} title="Delete workspace">
                <Trash2 className="size-4" />
              </Button>
            </>
          )
        }
      />
      <dl className="-mt-4 mb-8 grid grid-cols-[150px_1fr] gap-y-1 text-sm">
        <Property label="Kind">{kindLabel(workspace.type, workspace.category_label)}</Property>
        <Property label="Business ID">
          <CopyId id={workspace.id} />
        </Property>
        <Property label="Status">
          <Badge tone={workspace.status === "live" ? "green" : "neutral"}>{workspace.status === "live" ? "Live" : "Draft"}</Badge>
        </Property>
        {workspace.website_url && (
          <Property label="Website">
            <a href={workspace.website_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 underline decoration-stone-300 underline-offset-2 hover:decoration-stone-500">
              <Globe className="size-3.5" /> {workspace.website_url.replace(/^https?:\/\//, "")} <ExternalLink className="size-3" />
            </a>
          </Property>
        )}
        {workspace.online_only && <Property label="Location">Online only</Property>}
        {!workspace.online_only && workspace.address && (
          <Property label="Address">
            <MapPin className="size-3.5" /> {workspace.address}
          </Property>
        )}
        {workspace.phone && (
          <Property label="Phone">
            <Phone className="size-3.5" /> {workspace.phone}
          </Property>
        )}
      </dl>

      {editing ? (
        <WorkspaceForm
          initial={{
            type: workspace.type,
            category_label: workspace.category_label ?? "",
            online_only: workspace.online_only ?? false,
            name: workspace.name,
            address: workspace.address,
            lat: workspace.lat,
            lng: workspace.lng,
            phone: workspace.phone,
            hours: workspace.hours,
            website_url: workspace.website_url,
            test_url: workspace.test_url ?? "",
            description: workspace.description,
          }}
          submitLabel="Save changes"
          onSubmit={save}
          onCancel={() => setEditing(false)}
        />
      ) : (
        <div className="space-y-5">
          {liveRecording && <LiveRecordingBanner rec={liveRecording} onChange={load} />}
          <ErrorNote>{actionError}</ErrorNote>
          <AlertsBanner businessId={workspace.id} alerts={alerts} onSeen={load} />
          <ProposalBanners businessId={workspace.id} proposals={proposals} />
          <ToolsPanel businessId={workspace.id} tools={tools} onChange={load} />
          <OrdersPanel businessId={workspace.id} onChange={load} />
          {liveInfo && (
            <LivePanel
              businessId={workspace.id}
              info={liveInfo}
              onChange={(i) => {
                setLiveInfo(i);
                load();
              }}
            />
          )}
          <CrawlPanel workspace={workspace} run={run} recordings={recordings} toolNames={new Set(tools.map((t) => t.name))} onChange={load} onRecord={setRecordTarget} />
          <RecordingsPanel
            businessId={workspace.id}
            recordings={recordings}
            onRecord={() => setRecordTarget("new")}
            onMakeTool={async (recId) => {
              try {
                const p = await api<Proposal>(`/api/workspaces/${workspace.id}/proposals`, { method: "POST", json: { source: "recording", source_id: recId } });
                navigate(`/workspaces/${workspace.id}/proposals/${p.id}`);
              } catch (e) {
                setActionError((e as Error).message);
              }
            }}
          />
        </div>
      )}
      {recordTarget && (
        <RecordDialog
          workspace={workspace}
          flow={recordTarget === "new" ? undefined : recordTarget}
          timesRecorded={recordTarget === "new" ? 0 : timesRecorded(recordings, recordTarget.flow)}
          onClose={() => setRecordTarget(null)}
          onDone={(rec) => {
            setRecordTarget(null);
            if (rec.source === "upload") navigate(`/workspaces/${workspace.id}/recordings/${rec.id}`);
            else load();
          }}
        />
      )}
    </div>
  );
}
