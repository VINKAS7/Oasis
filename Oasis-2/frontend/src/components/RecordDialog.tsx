import { useEffect, useRef, useState, type ChangeEvent } from "react";
import { Link } from "react-router-dom";
import { MonitorPlay, PlugZap, Upload, X } from "lucide-react";
import { api } from "../lib/api";
import type { Recording, Workspace } from "../types";
import { Button, Callout, ErrorNote, Field, Input, cx } from "./ui";

function toFlow(title: string): string {
  return title
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

type Mode = "extension" | "upload" | "server";

export function RecordDialog({
  workspace,
  flow,
  timesRecorded,
  onClose,
  onDone,
}: {
  workspace: Workspace;
  flow?: { flow: string; title: string };
  timesRecorded: number;
  onClose: () => void;
  onDone: (rec: Recording) => void;
}) {
  const [mode, setMode] = useState<Mode>("extension");
  const [serverRecorder, setServerRecorder] = useState(false);
  const [title, setTitle] = useState(flow?.title ?? "");
  const [startUrl, setStartUrl] = useState(workspace.website_url);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const flowName = flow?.flow ?? toFlow(title);

  useEffect(() => {
    api<{ server_recorder: boolean }>("/api/config").then((c) => setServerRecorder(c.server_recorder), () => undefined);
  }, []);

  const startOnServer = async () => {
    setError("");
    setBusy(true);
    try {
      onDone(await api<Recording>(`/api/workspaces/${workspace.id}/recordings`, { method: "POST", json: { flow: flowName, title, start_url: startUrl } }));
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  const upload = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setError("");
    setBusy(true);
    try {
      const data = JSON.parse(await file.text());
      if (flow) data.flow = flow.flow;
      if (!data.title && title) data.title = title;
      onDone(await api<Recording>(`/api/workspaces/${workspace.id}/recordings/upload`, { method: "POST", json: data }));
    } catch (err) {
      setError(err instanceof SyntaxError ? "That file isn't valid JSON." : (err as Error).message);
      setBusy(false);
    } finally {
      e.target.value = "";
    }
  };

  const modes: [Mode, typeof PlugZap, string][] = [
    ["extension", PlugZap, "Chrome extension"],
    ["upload", Upload, "Upload a file"],
    ...(serverRecorder ? ([["server", MonitorPlay, "On this server"]] as [Mode, typeof PlugZap, string][]) : []),
  ];

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-stone-900/30" onClick={onClose} />
      <div className="relative w-full max-w-lg rounded-xl bg-white shadow-[0_16px_48px_rgba(15,15,15,0.2)]">
        <div className="flex items-start justify-between gap-3 px-5 pt-5">
          <div>
            <h2 className="text-lg font-semibold">{flow ? `Record: ${flow.title.toLowerCase()}` : "Record a flow"}</h2>
            <p className="mt-0.5 text-sm text-stone-500">
              {timesRecorded === 0 ? "Do it once like a customer would, then once more with different values." : `Recorded ${timesRecorded}× so far. Record again with different values (another date, another product, more people).`}
            </p>
          </div>
          <button onClick={onClose} className="rounded p-1 text-stone-400 hover:bg-hover" aria-label="Close">
            <X className="size-5" />
          </button>
        </div>

        <div className="space-y-4 px-5 py-4">
          <div className="flex gap-1 rounded-lg bg-stone-100 p-1">
            {modes.map(([m, Icon, label]) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={cx("flex flex-1 items-center justify-center gap-1.5 rounded-md px-2 py-1.5 text-sm", mode === m ? "bg-white font-medium shadow-sm" : "text-stone-500 hover:text-stone-800")}
              >
                <Icon className="size-4" /> {label}
              </button>
            ))}
          </div>

          {mode !== "extension" && !flow && (
            <Field label="What does the customer do?" hint={flowName ? <>Saved as <code>{flowName}</code></> : "For example: Book an appointment, Request a quote"}>
              <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Book an appointment" autoFocus />
            </Field>
          )}

          {mode === "extension" && (
            <>
              <ol className="list-decimal space-y-1.5 pl-5 text-sm text-stone-700">
                <li>Click the AgentReady Recorder icon in Chrome (log in once if it asks).</li>
                <li>
                  Choose <b>{workspace.name}</b> and {flow ? <b>{flow.title}</b> : "what you're recording"}, then press <b>Start recording</b>.
                </li>
                <li>Do the task like a customer would and write one sentence per step in the panel on the page.</li>
                <li>
                  Press <b>Finish</b>. The recording appears here, with passwords and personal details masked.
                </li>
              </ol>
              <Callout tone="yellow">What you do really happens on your site (a booking, order or message). Undo it afterwards in your own system.</Callout>
            </>
          )}
          {mode === "upload" && <p className="text-sm text-stone-600">Upload a recording file (.json) made by AgentReady, for example one you downloaded earlier. It is cleaned again on upload.</p>}
          {mode === "server" && (
            <>
              <p className="text-sm text-stone-600">Opens a browser window on the computer running the AgentReady server. Use this only when that computer is in front of you.</p>
              <Field label="Start page">
                <Input value={startUrl} onChange={(e) => setStartUrl(e.target.value)} inputMode="url" />
              </Field>
            </>
          )}
          <ErrorNote>{error}</ErrorNote>
        </div>

        <div className="flex justify-end gap-2 border-t border-line px-5 py-3">
          <Button variant="secondary" onClick={onClose}>
            {mode === "extension" ? "Done" : "Cancel"}
          </Button>
          {mode === "extension" && (
            <Link to="/extension">
              <Button>
                <PlugZap className="size-4" /> Get the extension
              </Button>
            </Link>
          )}
          {mode === "upload" && (
            <>
              <input ref={fileRef} type="file" accept="application/json,.json" className="hidden" onChange={upload} />
              <Button onClick={() => fileRef.current?.click()} loading={busy} disabled={!flowName && !flow}>
                <Upload className="size-4" /> Choose file
              </Button>
            </>
          )}
          {mode === "server" && (
            <Button onClick={startOnServer} loading={busy} disabled={!flowName}>
              Start recording
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
