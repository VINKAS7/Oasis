import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { AlertTriangle, Ban, Bot, CheckCircle2, GitMerge, Info, Loader2, Sparkles, XCircle } from "lucide-react";
import { api } from "../lib/api";
import type { Proposal, ProposalFlag, ProposalItem, Tool } from "../types";
import { SensitivityBadge, signature } from "../components/toolLabels";
import { Badge, Button, Card, ErrorNote, Input, PageLoader, cx } from "../components/ui";

type Choice = { decision: "approve" | "reject"; resolution?: "separate" | "new_version"; rename_to?: string; target_tool_id?: string };

const FLAG_STYLE: Record<ProposalFlag["kind"], { icon: typeof Info; cls: string }> = {
  blocked: { icon: Ban, cls: "text-red-700" },
  conflict: { icon: GitMerge, cls: "text-amber-800" },
  warning: { icon: AlertTriangle, cls: "text-amber-800" },
  note: { icon: Info, cls: "text-stone-600" },
};

function heading(item: ProposalItem, toolNames: Record<string, string>): string {
  const title = item.tool?.title ?? item.tool_name;
  if (item.action === "add") return `New: ${title}`;
  if (item.action === "update") return `Changed: ${toolNames[item.target_tool_id ?? ""] ?? item.tool_name}`;
  return `No change: ${item.tool_name}`;
}

function ItemCard({ item, choice, onChoice, toolNames, businessId }: { item: ProposalItem; choice?: Choice; onChoice: (c: Choice | undefined) => void; toolNames: Record<string, string>; businessId: string }) {
  const blocked = item.flags.some((f) => f.kind === "blocked");
  const conflicts = item.flags.filter((f) => f.kind === "conflict");
  const decided = item.decision !== null;
  const inputs = item.tool ? Object.entries(item.tool.input_schema.properties) : [];

  return (
    <Card className={cx(choice?.decision === "approve" && "ring-2 ring-brand-600", choice?.decision === "reject" && "opacity-60")}>
      <div className="flex flex-wrap items-start justify-between gap-3 px-5 py-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-semibold">{heading(item, toolNames)}</h3>
            {item.tool && <SensitivityBadge value={item.tool.sensitivity} />}
          </div>
          {item.tool && <code className="text-xs text-stone-500">{signature(item.tool.name, inputs.map(([name]) => ({ name })))}</code>}
          {item.reason && <p className="mt-1 text-sm text-stone-700">{item.reason}</p>}
        </div>
        {decided ? (
          item.decision === "approved" ? (
            <Badge tone="green">
              <CheckCircle2 className="size-3" /> approved{item.result && ` as v${item.result.version}${item.result.in_use ? ", in use" : ", waiting for checks"}`}
            </Badge>
          ) : item.decision === "rejected" ? (
            <Badge tone="neutral">
              <XCircle className="size-3" /> rejected
            </Badge>
          ) : null
        ) : (
          <div className="flex gap-2">
            <Button variant={choice?.decision === "reject" ? "primary" : "secondary"} onClick={() => onChoice(choice?.decision === "reject" ? undefined : { decision: "reject" })}>
              Reject
            </Button>
            <Button
              variant={choice?.decision === "approve" ? "primary" : "secondary"}
              disabled={blocked}
              title={blocked ? "This breaks a platform rule" : undefined}
              onClick={() => onChoice(choice?.decision === "approve" ? undefined : { decision: "approve", ...(conflicts.length ? { resolution: "separate", rename_to: item.tool_name } : {}) })}
            >
              Approve
            </Button>
          </div>
        )}
      </div>

      {item.flags.length > 0 && (
        <ul className="space-y-1 border-t border-stone-100 px-5 py-3 text-sm">
          {item.flags.map((f, i) => {
            const { icon: Icon, cls } = FLAG_STYLE[f.kind];
            return (
              <li key={i} className={cx("flex items-start gap-2", cls)}>
                <Icon className="mt-0.5 size-4 shrink-0" /> {f.message}
              </li>
            );
          })}
        </ul>
      )}

      {conflicts.length > 0 && choice?.decision === "approve" && (
        <div className="space-y-2 border-t border-stone-100 bg-amber-50/50 px-5 py-3 text-sm">
          <div className="font-medium">How should this be added?</div>
          <label className="flex flex-wrap items-center gap-2">
            <input type="radio" checked={choice.resolution === "separate"} onChange={() => onChoice({ decision: "approve", resolution: "separate", rename_to: choice.rename_to ?? item.tool_name })} className="accent-brand-700" />
            As a separate tool named
            <span className="w-56">
              <Input value={choice.rename_to ?? item.tool_name} onChange={(e) => onChoice({ ...choice, resolution: "separate", rename_to: e.target.value })} className="py-1" />
            </span>
          </label>
          {conflicts.map((c) => (
            <label key={c.tool_id} className="flex items-center gap-2">
              <input type="radio" checked={choice.resolution === "new_version" && choice.target_tool_id === c.tool_id} onChange={() => onChoice({ decision: "approve", resolution: "new_version", target_tool_id: c.tool_id })} className="accent-brand-700" />
              As a new version of <code>{toolNames[c.tool_id ?? ""] ?? c.tool_id}</code>
            </label>
          ))}
        </div>
      )}

      {item.tool && (
        <details className="border-t border-stone-100 px-5 py-3 text-sm">
          <summary className="cursor-pointer text-stone-600">Details</summary>
          <div className="mt-3 space-y-3">
            <p>
              <span className="font-medium">For you: </span>
              {item.tool.description_for_owner}
            </p>
            <p>
              <span className="font-medium">For AI assistants: </span>
              {item.tool.description_for_ai}
            </p>
            <p>
              <span className="font-medium">How it runs: </span>
              {item.runner_summary}
            </p>
            {inputs.length > 0 && (
              <table className="w-full text-xs">
                <thead className="text-left text-stone-500">
                  <tr>
                    <th className="py-1 pr-3 font-medium">Asks the customer for</th>
                    <th className="py-1 pr-3 font-medium">Type</th>
                    <th className="py-1 font-medium">Meaning</th>
                  </tr>
                </thead>
                <tbody>
                  {inputs.map(([name, p]) => (
                    <tr key={name} className="border-t border-stone-100">
                      <td className="py-1 pr-3">
                        <code>{name}</code> {p["x-personal"] && <Badge tone="amber">personal</Badge>}
                      </td>
                      <td className="py-1 pr-3">{p.format ?? p.type}</td>
                      <td className="py-1 text-stone-600">{p.description}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {item.result && (
              <Link to={`/workspaces/${businessId}/tools/${item.result.tool_id}`} className="font-medium text-brand-700 hover:underline">
                Open the tool
              </Link>
            )}
          </div>
        </details>
      )}
    </Card>
  );
}

export function ProposalPage() {
  const { id, pid } = useParams<{ id: string; pid: string }>();
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [toolNames, setToolNames] = useState<Record<string, string>>({});
  const [choices, setChoices] = useState<Record<number, Choice>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [p, tools] = await Promise.all([api<Proposal>(`/api/workspaces/${id}/proposals/${pid}`), api<Tool[]>(`/api/workspaces/${id}/tools`)]);
      setProposal(p);
      setToolNames(Object.fromEntries(tools.map((t) => [t.id, t.name])));
    } catch (e) {
      setError((e as Error).message);
    }
  }, [id, pid]);

  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    if (proposal?.status !== "generating") return;
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [proposal?.status, load]);

  if (error && !proposal) return <ErrorNote>{error}</ErrorNote>;
  if (!proposal) return <PageLoader />;

  const open = proposal.items.filter((i) => i.decision === null);
  const chosen = Object.entries(choices).map(([index, c]) => ({ index: Number(index), ...c }));

  const apply = async () => {
    setError("");
    setBusy(true);
    try {
      setProposal(await api<Proposal>(`/api/workspaces/${id}/proposals/${pid}/decide`, { method: "POST", json: { decisions: chosen } }));
      setChoices({});
      load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const dismiss = async () => {
    if (!confirm("Dismiss this proposal? Nothing in it will be applied.")) return;
    setProposal(await api<Proposal>(`/api/workspaces/${id}/proposals/${pid}/dismiss`, { method: "POST" }));
  };

  return (
    <div className="space-y-6">
      <div>
        <Sparkles className="mb-3 size-10 text-stone-700" strokeWidth={1.4} />
        <h1 className="text-[2.5rem] leading-tight font-bold tracking-tight">Suggested changes</h1>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-stone-500">
          <span>From {proposal.source === "crawl" ? "your website" : "your recording"}</span>
          {proposal.written_by === "ai" && (
            <Badge tone="teal">
              <Bot className="size-3" /> written by AI
            </Badge>
          )}
          {proposal.written_by === "platform" && <Badge>drafted without AI</Badge>}
          <Badge tone={proposal.status === "applied" ? "green" : proposal.status === "failed" ? "red" : "neutral"}>{proposal.status}</Badge>
        </div>
      </div>

      {proposal.status === "generating" && (
        <Card className="flex items-center gap-3 px-5 py-6 text-sm text-stone-600">
          <Loader2 className="size-5 animate-spin text-brand-700" /> The AI is reading your recording and your current tools…
        </Card>
      )}
      {proposal.status === "failed" && <ErrorNote>{proposal.error}</ErrorNote>}

      {proposal.summary && <p className="text-sm leading-relaxed text-stone-700">{proposal.summary}</p>}

      <div className="space-y-4">
        {proposal.items.map((item) => (
          <ItemCard
            key={item.index}
            item={item}
            choice={choices[item.index]}
            toolNames={toolNames}
            businessId={id!}
            onChoice={(c) =>
              setChoices((cur) => {
                const next = { ...cur };
                if (c) next[item.index] = c;
                else delete next[item.index];
                return next;
              })
            }
          />
        ))}
      </div>

      <ErrorNote>{error}</ErrorNote>
      {proposal.status === "pending" && (
        <div className="sticky bottom-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-stone-200 bg-white px-5 py-3 shadow-lg">
          <span className="text-sm text-stone-600">
            {chosen.length} of {open.length} decided. A tool is never removed by a proposal; only you can remove one.
          </span>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={dismiss}>
              Dismiss all
            </Button>
            <Button onClick={apply} loading={busy} disabled={chosen.length === 0}>
              Apply my decisions
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
