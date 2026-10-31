import { useEffect, useState } from "react";
import { ExternalLink, X } from "lucide-react";
import { api } from "../lib/api";
import type { CrawlPageRow, PageDetail } from "../types";
import { Badge, ErrorNote, Spinner, cx } from "./ui";

type Tab = "analysis" | "forms" | "text" | "data";

export function PageDrawer({ businessId, page, onClose }: { businessId: string; page: CrawlPageRow; onClose: () => void }) {
  const [detail, setDetail] = useState<PageDetail | null>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<Tab>("analysis");

  useEffect(() => {
    api<PageDetail>(`/api/workspaces/${businessId}/pages/${page.id}`).then(setDetail, (e) => setError(e.message));
  }, [businessId, page.id]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const a = detail?.analysis && !detail.analysis.error ? detail.analysis : null;

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <aside className="relative flex h-full w-full max-w-2xl flex-col bg-white shadow-xl">
        <div className="flex items-start justify-between gap-3 border-b border-stone-200 px-5 py-4">
          <div className="min-w-0">
            <h2 className="truncate font-semibold">{page.title || page.url}</h2>
            <a href={page.url} target="_blank" rel="noreferrer" className="inline-flex max-w-full items-center gap-1 truncate text-xs text-brand-700 hover:underline">
              {page.url} <ExternalLink className="size-3 shrink-0" />
            </a>
          </div>
          <button onClick={onClose} className="rounded-lg p-1.5 text-stone-500 hover:bg-stone-100" aria-label="Close">
            <X className="size-5" />
          </button>
        </div>

        <div className="flex gap-1 border-b border-stone-200 px-5">
          {(
            [
              ["analysis", "AI analysis"],
              ["forms", "Forms & buttons"],
              ["text", "Text"],
              ["data", "Structured data"],
            ] as [Tab, string][]
          ).map(([t, label]) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={cx("border-b-2 px-3 py-2 text-sm font-medium", tab === t ? "border-brand-700 text-brand-800" : "border-transparent text-stone-500 hover:text-stone-800")}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
          <ErrorNote>{error || page.error}</ErrorNote>
          {!detail && !error && <Spinner />}

          {detail && tab === "analysis" && (
            <>
              {detail.analysis?.error && <ErrorNote>The AI could not analyse this page: {detail.analysis.error}</ErrorNote>}
              {!detail.analysis && <p className="text-sm text-stone-500">Not analysed by AI yet.</p>}
              {a && (
                <>
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone="teal">{a.page_kind}</Badge>
                    {a.injection_suspected && <Badge tone="red">possible prompt injection</Badge>}
                  </div>
                  <p className="text-sm text-stone-700">{a.purpose}</p>
                  {a.information.map((i) => (
                    <section key={i.topic} className="rounded-lg border border-stone-200 p-3">
                      <h3 className="text-sm font-semibold">{i.topic}</h3>
                      <p className="mt-0.5 text-sm text-stone-600">{i.summary}</p>
                      {i.facts.length > 0 && (
                        <ul className="mt-2 list-disc space-y-0.5 pl-5 text-sm text-stone-700">
                          {i.facts.map((f, n) => (
                            <li key={n}>{f}</li>
                          ))}
                        </ul>
                      )}
                    </section>
                  ))}
                  {a.actions.length > 0 && (
                    <section>
                      <h3 className="mb-2 text-sm font-semibold">Actions a visitor can take</h3>
                      <ul className="space-y-2">
                        {a.actions.map((act) => (
                          <li key={act.name} className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm">
                            <div className="flex items-center gap-2">
                              <code className="text-xs">{act.name}</code> <Badge tone="amber">{act.kind}</Badge>
                            </div>
                            <p className="mt-1 text-stone-700">{act.description}</p>
                          </li>
                        ))}
                      </ul>
                    </section>
                  )}
                </>
              )}
              {detail.has_screenshot && (
                <img
                  src={`/api/workspaces/${businessId}/pages/${page.id}/screenshot`}
                  alt={`Screenshot of ${page.url}`}
                  className="w-full rounded-lg border border-stone-200"
                  loading="lazy"
                />
              )}
            </>
          )}

          {detail && tab === "forms" && (
            <>
              {detail.forms.length === 0 && <p className="text-sm text-stone-500">No forms on this page.</p>}
              {detail.forms.map((f) => (
                <section key={f.ref} className="rounded-lg border border-stone-200 p-3 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <code className="text-xs">{f.ref}</code>
                    <Badge>{f.method.toUpperCase()}</Badge>
                    {f.action && <span className="truncate text-xs text-stone-500">{f.action}</span>}
                  </div>
                  <ul className="mt-2 space-y-1">
                    {f.fields.map((fl, n) => (
                      <li key={n} className="flex flex-wrap gap-2 text-stone-700">
                        <code className="text-xs">{fl.name || fl.id}</code>
                        <span className="text-xs text-stone-500">
                          {fl.tag}
                          {fl.type && fl.type !== fl.tag ? `/${fl.type}` : ""}
                          {fl.required ? ", required" : ""}
                        </span>
                        {fl.label && <span className="text-xs">“{fl.label}”</span>}
                        {fl.options && <span className="text-xs text-stone-500">options: {fl.options.join(", ")}</span>}
                      </li>
                    ))}
                  </ul>
                </section>
              ))}
              {detail.buttons.length > 0 && (
                <section>
                  <h3 className="mb-2 text-sm font-semibold">Buttons</h3>
                  <div className="flex flex-wrap gap-1.5">
                    {detail.buttons.map((b) => (
                      <Badge key={b}>{b}</Badge>
                    ))}
                  </div>
                </section>
              )}
            </>
          )}

          {detail && tab === "text" && (
            <>
              {detail.headings.length > 0 && (
                <ul className="space-y-0.5 text-sm">
                  {detail.headings.map((h, n) => (
                    <li key={n} className={cx(h.level === "h1" ? "font-semibold" : h.level === "h2" ? "pl-3 font-medium" : "pl-6 text-stone-600")}>
                      {h.text}
                    </li>
                  ))}
                </ul>
              )}
              <pre className="rounded-lg bg-stone-50 p-3 text-xs whitespace-pre-wrap text-stone-700">{detail.text || "No visible text."}</pre>
            </>
          )}

          {detail && tab === "data" && (
            <>
              {detail.meta_description && (
                <p className="text-sm">
                  <span className="font-medium">Meta description:</span> {detail.meta_description}
                </p>
              )}
              {detail.json_ld.length === 0 && <p className="text-sm text-stone-500">No JSON-LD structured data on this page.</p>}
              {detail.json_ld.map((j, n) => (
                <pre key={n} className="overflow-x-auto rounded-lg bg-stone-50 p-3 text-xs text-stone-700">
                  {pretty(j)}
                </pre>
              ))}
            </>
          )}
        </div>
      </aside>
    </div>
  );
}

function pretty(raw: string): string {
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return raw;
  }
}
