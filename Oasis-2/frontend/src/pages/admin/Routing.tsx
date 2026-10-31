import { useEffect, useState } from "react";
import { Check } from "lucide-react";
import { api } from "../../lib/api";
import type { Provider, RouteRow, TaskInfo } from "../../types";
import { Badge, Button, Card, ErrorNote, Field, Input, PageLoader, Select, Toggle } from "../../components/ui";
import { AdminTitle } from "./AdminLayout";

interface RoutesResponse {
  tasks: TaskInfo[];
  routes: Record<string, RouteRow>;
}

// Claude takes `effort`; OpenAI-style providers take `reasoning_effort`, where "none" turns
// thinking off (Qwen3 on Ollama answers much faster that way).
const CLAUDE_EFFORTS = ["", "low", "medium", "high", "xhigh", "max"];
const CHAT_EFFORTS = ["", "none", "low", "medium", "high"];

function RouteEditor({ task, route, providers, onSaved }: { task: TaskInfo; route?: RouteRow; providers: Provider[]; onSaved: (r: RoutesResponse) => void }) {
  const [providerId, setProviderId] = useState(route?.provider_id ?? "");
  const [model, setModel] = useState(route?.model ?? "");
  const [effort, setEffort] = useState(route?.effort ?? "");
  const [maxTokens, setMaxTokens] = useState(route?.max_tokens ? String(route.max_tokens) : "");
  const [enabled, setEnabled] = useState(route?.enabled ?? true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  const isDefault = task.task === "default";
  const provider = providers.find((p) => p.id === providerId);
  const efforts = provider?.kind === "anthropic" ? CLAUDE_EFFORTS : CHAT_EFFORTS;
  const shownEffort = efforts.includes(effort) ? effort : "";

  const save = async () => {
    setError("");
    setSaving(true);
    try {
      const r = await api<RoutesResponse>(`/api/admin/routes/${task.task}`, {
        method: "PUT",
        json: { provider_id: providerId || null, model, effort: shownEffort, max_tokens: maxTokens ? Number(maxTokens) : null, enabled },
      });
      onSaved(r);
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card className="p-5">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="font-semibold">{task.label}</h3>
            {!isDefault && <code className="text-xs text-stone-500">{task.task}</code>}
            {isDefault && <Badge tone="teal">fallback for every task</Badge>}
          </div>
          <p className="mt-0.5 text-sm text-stone-500">{task.description}</p>
        </div>
        {!isDefault && <Toggle checked={enabled} onChange={setEnabled} label="Task on" />}
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Field label="Provider">
          <Select value={providerId} onChange={(e) => setProviderId(e.target.value)}>
            <option value="">{isDefault ? "— none —" : "Use the default route"}</option>
            {providers.map((p) => (
              <option key={p.id} value={p.id} disabled={!p.enabled}>
                {p.name}
                {!p.enabled ? " (disabled)" : ""}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Model" hint={provider ? `Empty: ${provider.default_model}` : "Empty: the provider's default"}>
          <Input value={model} onChange={(e) => setModel(e.target.value)} disabled={!providerId} placeholder={provider?.default_model} />
        </Field>
        <Field label="Effort" hint={provider?.kind === "anthropic" ? "Empty: model default." : "Reasoning models only. none: no thinking."}>
          <Select value={shownEffort} onChange={(e) => setEffort(e.target.value)} disabled={!providerId}>
            {efforts.map((e) => (
              <option key={e} value={e}>
                {e || "default"}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Max output tokens" hint={task.max_tokens ? `Empty: ${task.max_tokens.toLocaleString()}` : "Empty: the task's own limit"}>
          <Input type="number" min={256} max={128000} value={maxTokens} onChange={(e) => setMaxTokens(e.target.value)} disabled={!providerId} />
        </Field>
      </div>
      <ErrorNote className="mt-3">{error}</ErrorNote>
      <div className="mt-4 flex justify-end">
        <Button onClick={save} loading={saving} variant="secondary">
          {saved ? <Check className="size-4 text-emerald-600" /> : null} Save
        </Button>
      </div>
    </Card>
  );
}

export function AdminRouting() {
  const [data, setData] = useState<RoutesResponse | null>(null);
  const [providers, setProviders] = useState<Provider[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<RoutesResponse>("/api/admin/routes").then(setData, (e) => setError(e.message));
    api<Provider[]>("/api/admin/providers").then(setProviders, (e) => setError(e.message));
  }, []);

  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!data || !providers) return <PageLoader />;

  return (
    <div className="space-y-4">
      <AdminTitle title="Task routing" description="Choose which provider and model handle each kind of AI request. Tasks without their own provider use the default." />
      {data.tasks.map((t) => (
        <RouteEditor key={t.task} task={t} route={data.routes[t.task]} providers={providers} onSaved={setData} />
      ))}
    </div>
  );
}
