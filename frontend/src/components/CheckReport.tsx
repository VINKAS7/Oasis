import { useState } from "react";
import { AlertTriangle, Check, FlaskConical, ShieldCheck, X } from "lucide-react";
import { api, timeAgo } from "../lib/api";
import type { ToolCheck, ToolVersion } from "../types";
import { Badge, Button, ErrorNote, Field, Input, cx } from "./ui";
import { CheckBadge } from "./toolLabels";

const RULES: Record<string, string> = {
  right_address: "Right address only",
  no_dangerous_powers: "No dangerous powers",
  no_secrets: "No secrets in the tool",
  no_personal_data: "No customer details in the tool",
  inputs_match: "Inputs match",
  sensitivity: "Sensitivity label",
  limits: "Limits",
};

function json(v: unknown): string {
  return typeof v === "string" ? v : JSON.stringify(v, null, 2);
}

export function CheckReport({ check }: { check: ToolCheck }) {
  if (check.status === "queued" || check.status === "running") {
    return <p className="text-sm text-stone-500">{check.status === "queued" ? "Waiting for its turn…" : "Running the checks…"}</p>;
  }
  if (check.status === "error") return <ErrorNote>The check itself failed: {check.error}</ErrorNote>;
  const t = check.test;
  return (
    <div className="space-y-4 text-sm">
      <div className="flex flex-wrap items-center gap-2 text-xs text-stone-500">
        <CheckBadge badge={check.badge ?? "unchecked"} />
        <span>
          Checked {timeAgo(check.finished_at)} ·{" "}
          {{ change: "after a change", daily: "daily check", owner: "you asked", live_test: "your real test" }[check.trigger]}
        </span>
        {t?.promoted && <Badge tone="teal">now in use</Badge>}
      </div>
      {t?.owner_message && (
        <div className={cx("flex gap-2 rounded-lg px-3 py-2", check.badge === "blocked" || check.badge === "not_working" ? "bg-red-50 text-red-800" : "bg-amber-50 text-amber-900")}>
          <AlertTriangle className="mt-0.5 size-4 shrink-0" /> {t.owner_message}
        </div>
      )}

      <div>
        <h4 className="mb-1.5 flex items-center gap-1.5 font-medium">
          <ShieldCheck className="size-4 text-brand-700" /> Security
        </h4>
        <ul className="space-y-1">
          {check.security.map((f) => (
            <li key={f.rule} className="flex items-start gap-2">
              {f.ok ? <Check className="mt-0.5 size-4 shrink-0 text-emerald-600" /> : <X className="mt-0.5 size-4 shrink-0 text-red-600" />}
              <span>
                <span className="font-medium">{RULES[f.rule] ?? f.rule}:</span> <span className="text-stone-600">{f.message}</span>
              </span>
            </li>
          ))}
        </ul>
      </div>

      {t?.mode && (
        <div>
          <h4 className="mb-1.5 flex items-center gap-1.5 font-medium">
            <FlaskConical className="size-4 text-brand-700" /> Test run
          </h4>
          <p className="text-stone-600">{t.mode_text}</p>
          {t.mode !== "security_only" && (
            <>
              <p className={cx("mt-1 flex items-start gap-2", t.ok ? "text-emerald-700" : "text-red-700")}>
                {t.ok ? <Check className="mt-0.5 size-4 shrink-0" /> : <X className="mt-0.5 size-4 shrink-0" />} {t.message}
              </p>
              {t.cancelled && <p className={cx("mt-1", t.cancelled.ok ? "text-stone-600" : "text-amber-800")}>{t.cancelled.message}</p>}
              {t.injection && (
                <p className={cx("mt-1", t.injection.suspicious ? "text-red-700" : "text-stone-600")}>
                  Prompt-injection scan ({t.injection.by.join(" + ")}): {t.injection.suspicious ? `found “${t.injection.quotes[0]}”` : "nothing found"}.
                  {t.injection.note && <span className="text-stone-400"> {t.injection.note}</span>}
                </p>
              )}
              <details className="mt-2">
                <summary className="cursor-pointer text-stone-500">What was sent and returned</summary>
                <div className="mt-2 grid gap-2 sm:grid-cols-2">
                  <div>
                    <div className="mb-1 text-xs text-stone-500">Test values</div>
                    <pre className="max-h-56 overflow-auto rounded bg-stone-50 p-2 text-xs">{json(t.request ?? t.inputs ?? {})}</pre>
                  </div>
                  <div>
                    <div className="mb-1 text-xs text-stone-500">Answer</div>
                    <pre className="max-h-56 overflow-auto rounded bg-stone-50 p-2 text-xs">{t.output == null ? "—" : json(t.output)}</pre>
                  </div>
                </div>
              </details>
            </>
          )}
        </div>
      )}
    </div>
  );
}

export function RealTestDialog({
  businessId,
  toolId,
  version,
  samples,
  onClose,
  onStarted,
}: {
  businessId: string;
  toolId: string;
  version: ToolVersion;
  samples: Record<string, string | number | boolean>;
  onClose: () => void;
  onStarted: () => void;
}) {
  const [values, setValues] = useState<Record<string, string>>(() => Object.fromEntries(version.inputs.map((i) => [i.name, String(samples[i.name] ?? "")])));
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const start = async () => {
    setBusy(true);
    setError("");
    try {
      await api(`/api/workspaces/${businessId}/tools/${toolId}/versions/${version.version}/check`, { method: "POST", json: { live: true, confirm: true, inputs: values } });
      onStarted();
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/40" onClick={busy ? undefined : onClose} />
      {/* Header and buttons stay put; the inputs scroll when a tool asks for many. */}
      <div className="relative flex max-h-[calc(100vh-2rem)] w-full max-w-lg flex-col rounded-xl bg-white shadow-xl">
        <div className="space-y-3 px-5 pt-5">
          <h2 className="font-semibold">Run a real test of “{version.title}”</h2>
          <p className="rounded-lg bg-soft-yellow px-3 py-2 text-sm text-soft-yellow-ink">
            This really happens on your site: the booking, order or message is sent to your system. Undo it there afterwards. To test without that, add a test copy of your system under Edit details, or a cancel tool.
          </p>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-3">
          {version.inputs.length === 0 ? (
            <p className="text-sm text-stone-500">This tool asks for nothing.</p>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2">
              {version.inputs.map((i) => (
                <Field key={i.name} label={i.name} hint={i.personal ? "personal: use test details" : i.type}>
                  <Input value={values[i.name] ?? ""} onChange={(e) => setValues({ ...values, [i.name]: e.target.value })} />
                </Field>
              ))}
            </div>
          )}
        </div>
        <div className="space-y-3 border-t border-line px-5 py-4">
          <label className="flex items-start gap-2 text-sm">
            <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} className="mt-0.5 accent-brand-700" />I understand this really happens on my site, and I will undo it.
          </label>
          <ErrorNote>{error}</ErrorNote>
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={onClose} disabled={busy}>
              Cancel
            </Button>
            <Button onClick={start} disabled={!confirmed} loading={busy}>
              Run the real test
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
