import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { CheckCircle2, Download, Loader2, PlugZap, XCircle } from "lucide-react";
import { authClient } from "../lib/auth-client";
import { Button, Card } from "../components/ui";
import { PageTitle } from "../components/Layout";

/** Opened by the extension's "Log in" button. Hands the signed-in session to the extension
 *  through its content script (window.postMessage on this exact page). */
export function ExtensionConnectPage() {
  const [state, setState] = useState<"looking" | "connected" | "missing" | "rejected">("looking");
  const [reason, setReason] = useState("");

  useEffect(() => {
    let token = "";
    let user: { id: string; email: string; name: string } | null = null;
    const onMessage = (e: MessageEvent) => {
      if (e.source !== window || e.origin !== window.location.origin || e.data?.source !== "agentready-extension") return;
      if (e.data.type === "present" && token) {
        window.postMessage({ source: "agentready-app", type: "token", token, user }, window.location.origin);
      } else if (e.data.type === "connected") {
        setState("connected");
      } else if (e.data.type === "rejected") {
        setReason(e.data.reason);
        setState("rejected");
      }
    };
    window.addEventListener("message", onMessage);
    authClient.getSession().then(({ data }) => {
      token = data?.session.token ?? "";
      user = data ? { id: data.user.id, email: data.user.email, name: data.user.name } : null;
      window.postMessage({ source: "agentready-app", type: "ping" }, window.location.origin);
    });
    const timer = setTimeout(() => setState((s) => (s === "looking" ? "missing" : s)), 2500);
    return () => {
      window.removeEventListener("message", onMessage);
      clearTimeout(timer);
    };
  }, []);

  return (
    <div className="mx-auto max-w-xl pt-10">
      <PageTitle icon={<PlugZap className="size-9" />} title="Connect the recorder" />
      <Card className="p-6">
        {state === "looking" && (
          <p className="flex items-center gap-2 text-stone-600">
            <Loader2 className="size-4 animate-spin" /> Looking for the Oasis Recorder extension…
          </p>
        )}
        {state === "connected" && (
          <div className="space-y-2">
            <p className="flex items-center gap-2 font-medium text-emerald-700">
              <CheckCircle2 className="size-5" /> The extension is connected to your account.
            </p>
            <p className="text-stone-600">You can close this tab. Click the extension's icon to start recording on your website.</p>
          </div>
        )}
        {state === "rejected" && (
          <p className="flex items-start gap-2 text-red-700">
            <XCircle className="mt-0.5 size-5 shrink-0" /> The extension refused this page: {reason} Open its Settings and set this address.
          </p>
        )}
        {state === "missing" && (
          <div className="space-y-3">
            <p className="text-stone-600">The extension isn't installed in this browser yet.</p>
            <Link to="/extension">
              <Button>
                <Download className="size-4" /> Get the extension
              </Button>
            </Link>
          </div>
        )}
      </Card>
    </div>
  );
}

export function ExtensionPage() {
  const steps = [
    <>
      <a href="/api/extension/download" className="font-medium text-brand-700 hover:underline">
        Download the extension
      </a>{" "}
      and unzip it.
    </>,
    <>
      Open <code className="rounded bg-stone-100 px-1">chrome://extensions</code> and switch on <b>Developer mode</b> (top right).
    </>,
    <>
      Click <b>Load unpacked</b> and choose the unzipped <code className="rounded bg-stone-100 px-1">oasis-recorder</code> folder.
    </>,
    <>
      Click the extension's icon (pin it from the puzzle-piece menu). Logging in is optional: it lists your workspaces and the flows each one still needs.
    </>,
    <>
      Say what you're recording, press <b>Start recording</b>, and do the task like a customer would. Press <b>Next step</b> in the panel on the page after each step, and <b>Finish</b> at the end: the
      recording is saved as a file in Downloads (oasis-recordings).
    </>,
    <>
      In your workspace, under Your tools, press <b>Import recording</b> and choose the file. Oasis runs a security check and builds the tool for you to
      approve.
    </>,
  ];
  return (
    <div className="mx-auto max-w-2xl">
      <PageTitle icon={<PlugZap className="size-9" />} title="Oasis Recorder" subtitle="A Chrome extension that records a flow on your own website, in your own browser." />
      <ol className="space-y-3">
        {steps.map((s, i) => (
          <li key={i} className="flex gap-3">
            <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-stone-100 text-xs font-semibold text-stone-600">{i + 1}</span>
            <span className="pt-0.5 text-stone-700">{s}</span>
          </li>
        ))}
      </ol>
      <div className="mt-8 rounded-md bg-soft-gray px-4 py-3 text-sm text-stone-700">
        While recording, Chrome shows “Oasis Recorder started debugging this browser”: that is how the extension sees the messages your website sends
        to its server. It only watches the requests; it never changes them. If a site still misbehaves, switch off <b>Capture network requests</b> before you
        start. Passwords and personal details are masked before the file is saved, and again when you import it. For logging in, the extension talks to{" "}
        <code className="rounded bg-white px-1">{window.location.origin}</code>; if that's not its default (http://localhost:5173), set it under the extension's
        Settings.
      </div>
    </div>
  );
}
