import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import type { PlatformSettings } from "../../types";
import { Button, Card, CardHeader, ErrorNote, Field, Input, PageLoader, Toggle } from "../../components/ui";
import { AdminTitle } from "./AdminLayout";

export function AdminCrawlerSettings() {
  const [values, setValues] = useState<PlatformSettings | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api<PlatformSettings>("/api/admin/settings").then(setValues, (e) => setError(e.message));
  }, []);

  if (!values) return error ? <ErrorNote>{error}</ErrorNote> : <PageLoader />;
  const set = <K extends keyof PlatformSettings>(k: K, v: PlatformSettings[K]) => setValues({ ...values, [k]: v });
  const num = (k: keyof PlatformSettings, label: string, hint: string, min: number, max: number) => (
    <Field label={label} hint={hint}>
      <Input type="number" min={min} max={max} value={values[k] as number} onChange={(e) => set(k, Number(e.target.value) as never)} />
    </Field>
  );

  const save = async () => {
    setError("");
    setSaving(true);
    try {
      setValues(await api<PlatformSettings>("/api/admin/settings", { method: "PUT", json: values }));
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      <AdminTitle title="Platform settings" description="Limits for reading websites and recording flows, and what is sent to the AI." />
      <Card>
        <CardHeader title="Crawler" />
        <div className="grid gap-4 p-5 sm:grid-cols-3">
          {num("crawler.max_pages", "Max pages per crawl", "1 to 200", 1, 200)}
          {num("crawler.max_depth", "Max link depth", "Clicks away from the home page", 0, 10)}
          {num("crawler.page_timeout_s", "Page timeout (seconds)", "Per page", 5, 120)}
        </div>
        <div className="space-y-4 border-t border-stone-100 p-5">
          <Toggle checked={values["crawler.respect_robots"]} onChange={(v) => set("crawler.respect_robots", v)} label="Respect robots.txt" />
          <Toggle
            checked={values["crawler.allow_private_urls"]}
            onChange={(v) => set("crawler.allow_private_urls", v)}
            label="Allow local and private network addresses"
            hint="Needed to crawl a demo site on localhost. Leave off on a public server: it lets owners point the crawler at your internal network."
          />
        </div>
      </Card>
      <Card>
        <CardHeader title="Recorder" />
        <div className="space-y-4 p-5">
          <Toggle
            checked={values["recorder.enabled"]}
            onChange={(v) => set("recorder.enabled", v)}
            label="Allow live recording"
            hint="Opens a visible browser window on the computer running the API. Fine on your own laptop; turn off on a shared server (owners can still upload recordings)."
          />
          <div className="max-w-xs">{num("recorder.max_minutes", "Recording time limit (minutes)", "Saved automatically when reached", 1, 120)}</div>
        </div>
      </Card>
      <Card>
        <CardHeader title="AI" />
        <div className="space-y-4 p-5">
          <Toggle checked={values["ai.analyze_pages"]} onChange={(v) => set("ai.analyze_pages", v)} label="Analyse crawled pages with AI" hint="Off: crawls only collect pages; no AI calls." />
          <Toggle
            checked={values["ai.send_screenshots"]}
            onChange={(v) => set("ai.send_screenshots", v)}
            label="Send page screenshots to the AI"
            hint="Better understanding of image-heavy sites, at a higher token cost. Only for providers that accept images."
          />
          <div className="max-w-xs">{num("ai.user_requests_per_minute", "Owner AI requests per minute", "Per user, for /api/ai/complete", 1, 600)}</div>
        </div>
      </Card>
      <ErrorNote>{error}</ErrorNote>
      <div className="flex justify-end">
        <Button onClick={save} loading={saving}>
          {saved ? "Saved" : "Save settings"}
        </Button>
      </div>
    </div>
  );
}
