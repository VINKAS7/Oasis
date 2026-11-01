import { useRef, useState, type ChangeEvent } from "react";
import { useNavigate } from "react-router-dom";
import { CircleAlert, CircleCheck, CircleX, FileUp, ShieldCheck, X } from "lucide-react";
import { ApiError, api } from "../lib/api";
import type { ImportResult, ScanCheck } from "../types";
import { Button, ErrorNote, cx } from "./ui";

const ICON = {
  pass: <CircleCheck className="size-4 shrink-0 text-emerald-600" />,
  warn: <CircleAlert className="size-4 shrink-0 text-amber-600" />,
  fail: <CircleX className="size-4 shrink-0 text-soft-red-ink" />,
};

export function ScanReport({ checks }: { checks: ScanCheck[] }) {
  return (
    <ul className="divide-y divide-line rounded-lg border border-stone-200 text-sm">
      {checks.map((c) => (
        <li key={c.name} className="flex gap-2.5 px-3 py-2">
          <span className="mt-0.5">{ICON[c.status]}</span>
          <span>
            <span className="font-medium text-stone-800">{c.name}</span>
            <span className="text-stone-600"> · {c.detail}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

/** Import a recording file saved by the Oasis Recorder extension. The server cleans it again and
 * runs a security scan; a file that passes becomes a recording and the AI builds a tool proposal,
 * which the owner reviews and approves (then the tool's own checks run). */
export function ImportRecording({ businessId, onClose }: { businessId: string; onClose: () => void }) {
  const navigate = useNavigate();
  const fileRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<ImportResult | null>(null);
  const [fileName, setFileName] = useState("");

  const pick = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setFileName(file.name);
    setError("");
    setResult(null);
    setBusy(true);
    try {
      const data = JSON.parse(await file.text());
      setResult(await api<ImportResult>(`/api/workspaces/${businessId}/recordings/import`, { method: "POST", json: data }));
    } catch (err) {
      setError(
        err instanceof SyntaxError || (err instanceof ApiError && err.status === 422)
          ? "That file isn't an Oasis recording. Choose a file saved by the Oasis Recorder extension (.oasis.json)."
          : (err as Error).message,
      );
    } finally {
      setBusy(false);
    }
  };

  const passed = result?.ok;
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/30" onClick={busy ? undefined : onClose} />
      <div className="relative w-full max-w-lg rounded-xl bg-white shadow-[0_16px_48px_rgba(15,15,15,0.2)]">
        <div className="flex items-start justify-between gap-3 px-5 pt-5">
          <div>
            <h2 className="text-lg font-semibold">Import a recording</h2>
            <p className="mt-0.5 text-sm text-stone-500">
              A file saved by the Oasis Recorder extension (in Downloads → oasis-recordings). Oasis checks it, then builds the tool for you to approve.
            </p>
          </div>
          <button onClick={onClose} disabled={busy} className="rounded p-1 text-stone-400 hover:bg-hover" aria-label="Close">
            <X className="size-5" />
          </button>
        </div>

        <div className="space-y-3 px-5 py-4">
          {!result && !busy && (
            <button
              onClick={() => fileRef.current?.click()}
              className="flex w-full flex-col items-center gap-1.5 rounded-lg border border-dashed border-stone-300 px-4 py-6 text-sm text-stone-600 hover:border-brand-600 hover:bg-hover"
            >
              <FileUp className="size-6 text-stone-400" />
              <span className="font-medium text-stone-800">Choose a recording file</span>
              <span className="text-xs text-stone-500">.oasis.json</span>
            </button>
          )}
          {busy && (
            <p className="flex items-center gap-2 text-sm text-stone-600">
              <ShieldCheck className="size-4 animate-pulse text-brand-700" /> Checking {fileName}…
            </p>
          )}
          {result && (
            <>
              <p className={cx("flex items-center gap-2 text-sm font-medium", passed ? "text-emerald-700" : "text-soft-red-ink")}>
                {passed ? <ShieldCheck className="size-4" /> : <CircleX className="size-4" />}
                {passed ? `${fileName} passed the security check.` : `${fileName} didn't pass the security check, so it wasn't imported.`}
              </p>
              <ScanReport checks={result.scan.checks} />
              {passed && <p className="text-sm text-stone-600">The AI is now working out the tool. Review it and approve it; its checks run right after.</p>}
            </>
          )}
          <ErrorNote>{error}</ErrorNote>
          <input ref={fileRef} type="file" accept="application/json,.json" className="hidden" onChange={pick} />
        </div>

        <div className="flex justify-end gap-2 border-t border-line px-5 py-3">
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            {passed ? "Close" : "Cancel"}
          </Button>
          {result && !passed && (
            <Button onClick={() => fileRef.current?.click()}>
              <FileUp className="size-4" /> Choose another file
            </Button>
          )}
          {passed && result.proposal_id && (
            <Button onClick={() => navigate(`/workspaces/${businessId}/proposals/${result.proposal_id}`)}>Review the tool</Button>
          )}
        </div>
      </div>
    </div>
  );
}
