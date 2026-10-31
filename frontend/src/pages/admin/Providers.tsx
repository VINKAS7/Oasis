import { useEffect, useState, type FormEvent } from "react";
import { Bot, CheckCircle2, KeyRound, Pencil, Plus, Trash2, XCircle, Zap } from "lucide-react";
import { api } from "../../lib/api";
import type { Provider, ProviderKind } from "../../types";
import { Badge, Button, Card, EmptyState, ErrorNote, Field, Input, PageLoader, Select, Toggle } from "../../components/ui";
import { AdminTitle } from "./AdminLayout";

interface Preset {
  label: string;
  kind: ProviderKind;
  base_url: string;
  default_model: string;
  needs_key: boolean;
  models?: string[];
}

// Model ids for providers other than Anthropic change often; the admin types them in.
const PRESETS: Preset[] = [
  { label: "Anthropic (Claude)", kind: "anthropic", base_url: "", default_model: "claude-opus-5-5", needs_key: true, models: ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1"] },
  { label: "OpenAI", kind: "openai", base_url: "", default_model: "", needs_key: true },
  { label: "Google Gemini", kind: "openai_compatible", base_url: "https://generativelanguage.googleapis.com/v1beta/openai", default_model: "", needs_key: true },
  { label: "OpenRouter", kind: "openai_compatible", base_url: "https://openrouter.ai/api/v1", default_model: "", needs_key: true },
  { label: "Groq", kind: "openai_compatible", base_url: "https://api.groq.com/openai/v1", default_model: "", needs_key: true },
  { label: "Ollama (local)", kind: "openai_compatible", base_url: "http://localhost:11434/v1", default_model: "", needs_key: false },
  { label: "Other OpenAI-compatible", kind: "openai_compatible", base_url: "", default_model: "", needs_key: false },
];

const KIND_LABEL: Record<ProviderKind, string> = { anthropic: "Anthropic", openai: "OpenAI", openai_compatible: "OpenAI-compatible" };

interface Draft {
  name: string;
  kind: ProviderKind;
  base_url: string;
  api_key: string;
  default_model: string;
  supports_vision: boolean;
  enabled: boolean;
}

function ProviderForm({ existing, onDone, onCancel }: { existing: Provider | null; onDone: () => void; onCancel: () => void }) {
  const [preset, setPreset] = useState(0);
  const [draft, setDraft] = useState<Draft>(
    existing
      ? { name: existing.name, kind: existing.kind, base_url: existing.base_url, api_key: "", default_model: existing.default_model, supports_vision: existing.supports_vision, enabled: existing.enabled }
      : { name: PRESETS[0].label, kind: PRESETS[0].kind, base_url: "", api_key: "", default_model: PRESETS[0].default_model, supports_vision: true, enabled: true },
  );
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const set = (p: Partial<Draft>) => setDraft((d) => ({ ...d, ...p }));
  const models = PRESETS.find((p) => p.kind === draft.kind && p.models)?.models;

  const pickPreset = (i: number) => {
    const p = PRESETS[i];
    setPreset(i);
    set({ name: p.label, kind: p.kind, base_url: p.base_url, default_model: p.default_model });
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setSaving(true);
    try {
      if (existing) {
        const { api_key, ...rest } = draft;
        await api(`/api/admin/providers/${existing.id}`, { method: "PATCH", json: api_key ? { ...rest, api_key } : rest });
      } else {
        await api("/api/admin/providers", { method: "POST", json: draft });
      }
      onDone();
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };

  return (
    <Card className="p-5">
      <form onSubmit={submit} className="space-y-4">
        <h3 className="font-semibold">{existing ? `Edit ${existing.name}` : "Add an AI provider"}</h3>
        {!existing && (
          <Field label="Provider">
            <Select value={preset} onChange={(e) => pickPreset(Number(e.target.value))}>
              {PRESETS.map((p, i) => (
                <option key={p.label} value={i}>
                  {p.label}
                </option>
              ))}
            </Select>
          </Field>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Display name">
            <Input required value={draft.name} onChange={(e) => set({ name: e.target.value })} />
          </Field>
          <Field label="API format">
            <Select value={draft.kind} onChange={(e) => set({ kind: e.target.value as ProviderKind })}>
              <option value="anthropic">Anthropic Messages API</option>
              <option value="openai">OpenAI Chat Completions</option>
              <option value="openai_compatible">OpenAI-compatible (Gemini, OpenRouter, Groq, Ollama…)</option>
            </Select>
          </Field>
        </div>
        <Field label="Base URL" hint={draft.kind === "openai_compatible" ? "Required. The URL that ends before /chat/completions." : "Leave empty for the official endpoint."}>
          <Input value={draft.base_url} onChange={(e) => set({ base_url: e.target.value })} placeholder={draft.kind === "anthropic" ? "https://api.anthropic.com" : "https://api.openai.com/v1"} />
        </Field>
        <Field
          label="API key"
          hint={existing?.has_key ? `A key ending in ${existing.api_key_hint || "••••"} is saved. Leave empty to keep it.` : "Stored encrypted. It is never shown again or sent to the browser."}
        >
          <Input type="password" autoComplete="off" value={draft.api_key} onChange={(e) => set({ api_key: e.target.value })} placeholder={existing?.has_key ? "••••••••" : ""} />
        </Field>
        <Field label="Default model" hint="Used by tasks that don't name their own model.">
          <Input required list="model-suggestions" value={draft.default_model} onChange={(e) => set({ default_model: e.target.value })} placeholder="model id" />
          {models && (
            <datalist id="model-suggestions">
              {models.map((m) => (
                <option key={m} value={m} />
              ))}
            </datalist>
          )}
        </Field>
        <div className="flex flex-wrap gap-6">
          <Toggle checked={draft.supports_vision} onChange={(v) => set({ supports_vision: v })} label="Accepts images" hint="Screenshots are sent only if this is on." />
          <Toggle checked={draft.enabled} onChange={(v) => set({ enabled: v })} label="Enabled" />
        </div>
        <ErrorNote>{error}</ErrorNote>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="submit" loading={saving}>
            {existing ? "Save" : "Add provider"}
          </Button>
        </div>
      </form>
    </Card>
  );
}

function ProviderCard({ p, onEdit, onChange }: { p: Provider; onEdit: () => void; onChange: () => void }) {
  const [test, setTest] = useState<{ ok: boolean; error?: string; reply?: string; model?: string } | null>(null);
  const [testing, setTesting] = useState(false);

  const runTest = async () => {
    setTesting(true);
    setTest(null);
    try {
      setTest(await api(`/api/admin/providers/${p.id}/test`, { method: "POST", json: {} }));
    } catch (e) {
      setTest({ ok: false, error: (e as Error).message });
    } finally {
      setTesting(false);
    }
  };

  const remove = async () => {
    if (!confirm(`Delete ${p.name}? Tasks routed to it fall back to the default route.`)) return;
    await api(`/api/admin/providers/${p.id}`, { method: "DELETE" });
    onChange();
  };

  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-semibold">{p.name}</h3>
            <Badge tone="teal">{KIND_LABEL[p.kind]}</Badge>
            {!p.enabled && <Badge tone="neutral">disabled</Badge>}
          </div>
          <dl className="mt-2 grid gap-x-6 gap-y-1 text-sm text-stone-600 sm:grid-cols-[auto_1fr]">
            <dt className="text-stone-400">Model</dt>
            <dd>
              <code>{p.default_model}</code>
            </dd>
            <dt className="text-stone-400">Endpoint</dt>
            <dd className="truncate">{p.base_url || "official"}</dd>
            <dt className="text-stone-400">Key</dt>
            <dd className="flex items-center gap-1">
              <KeyRound className="size-3.5" /> {p.has_key ? `•••• ${p.api_key_hint}` : "none"}
            </dd>
          </dl>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={runTest} loading={testing}>
            <Zap className="size-4" /> Test
          </Button>
          <Button variant="secondary" onClick={onEdit} title="Edit">
            <Pencil className="size-4" />
          </Button>
          <Button variant="danger" onClick={remove} title="Delete">
            <Trash2 className="size-4" />
          </Button>
        </div>
      </div>
      {test && (
        <div className={`mt-3 flex items-start gap-2 rounded-lg px-3 py-2 text-sm ${test.ok ? "bg-emerald-50 text-emerald-800" : "bg-red-50 text-red-800"}`}>
          {test.ok ? <CheckCircle2 className="mt-0.5 size-4 shrink-0" /> : <XCircle className="mt-0.5 size-4 shrink-0" />}
          {test.ok ? `Working: ${test.model} replied “${test.reply?.trim()}”` : test.error}
        </div>
      )}
    </Card>
  );
}

export function AdminProviders() {
  const [items, setItems] = useState<Provider[] | null>(null);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<Provider | "new" | null>(null);

  const load = () => api<Provider[]>("/api/admin/providers").then(setItems, (e) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!items) return <PageLoader />;

  return (
    <div className="space-y-4">
      <AdminTitle
        title="AI providers"
        description="The AI services and API keys the platform may use. The first one you add becomes the default."
        action={
          !editing && (
            <Button onClick={() => setEditing("new")}>
              <Plus className="size-4" /> Add provider
            </Button>
          )
        }
      />
      {editing && (
        <ProviderForm
          existing={editing === "new" ? null : editing}
          onCancel={() => setEditing(null)}
          onDone={() => {
            setEditing(null);
            load();
          }}
        />
      )}
      {items.length === 0 && !editing && (
        <Card>
          <EmptyState icon={<Bot className="size-6" />} title="No AI provider yet">
            Until you add one, crawls still read websites but skip the AI analysis.
          </EmptyState>
        </Card>
      )}
      {items.map((p) => (
        <ProviderCard key={p.id} p={p} onEdit={() => setEditing(p)} onChange={load} />
      ))}
    </div>
  );
}
