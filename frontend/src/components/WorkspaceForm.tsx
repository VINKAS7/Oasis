import { useState, type FormEvent, type ReactNode } from "react";
import { MapPin, Search } from "lucide-react";
import { api } from "../lib/api";
import { DAYS, type Day, type DayHours, type WorkspaceInput } from "../types";
import { BUSINESS_TYPES, typeInfo } from "./businessTypes";
import { Button, Card, ErrorNote, Field, Input, Textarea, Toggle, cx } from "./ui";

const DAY_LABELS: Record<Day, string> = { mon: "Monday", tue: "Tuesday", wed: "Wednesday", thu: "Thursday", fri: "Friday", sat: "Saturday", sun: "Sunday" };

// A common starting point; owners change it, or switch opening hours off.
const DEFAULT_HOURS: WorkspaceInput["hours"] = Object.fromEntries(
  DAYS.map((d) => [d, d === "sun" ? { closed: true, open: "", close: "" } : d === "sat" ? { closed: false, open: "10:00", close: "16:00" } : { closed: false, open: "09:00", close: "18:00" }]),
);

export const EMPTY_WORKSPACE: WorkspaceInput = {
  type: "other",
  category_label: "",
  online_only: false,
  name: "",
  address: "",
  lat: null,
  lng: null,
  phone: "",
  hours: DEFAULT_HOURS,
  website_url: "",
  test_url: "",
  description: "",
};

const hasHours = (hours: WorkspaceInput["hours"]) => Object.values(hours).some((d) => d && (d.closed || d.open));

function Section({ title, description, children }: { title: string; description: string; children: ReactNode }) {
  return (
    <Card className="grid gap-6 p-5 md:grid-cols-3">
      <div>
        <h2 className="text-sm font-semibold text-stone-900">{title}</h2>
        <p className="mt-1 text-sm text-stone-500">{description}</p>
      </div>
      <div className="space-y-4 md:col-span-2">{children}</div>
    </Card>
  );
}

function MapPreview({ lat, lng }: { lat: number; lng: number }) {
  const d = 0.004;
  const src = `https://www.openstreetmap.org/export/embed.html?bbox=${lng - d},${lat - d / 1.6},${lng + d},${lat + d / 1.6}&layer=mapnik&marker=${lat},${lng}`;
  return <iframe title="Map" src={src} className="h-56 w-full rounded-lg border border-stone-200" loading="lazy" />;
}

function AddressField({ value, onChange }: { value: WorkspaceInput; onChange: (patch: Partial<WorkspaceInput>) => void }) {
  const [results, setResults] = useState<{ label: string; lat: number; lng: number }[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState("");

  const search = async () => {
    setError("");
    setSearching(true);
    try {
      const found = await api<{ label: string; lat: number; lng: number }[]>(`/api/geocode?q=${encodeURIComponent(value.address)}`);
      setResults(found);
      if (found.length === 0) setError("No match. Try adding the city, or enter the coordinates yourself.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSearching(false);
    }
  };

  return (
    <div className="space-y-3">
      <Field label="Address">
        <div className="flex gap-2">
          <Input value={value.address} onChange={(e) => onChange({ address: e.target.value })} placeholder="Street and number, postcode, city" />
          <Button type="button" variant="secondary" onClick={search} loading={searching} disabled={value.address.trim().length < 3}>
            <Search className="size-4" /> Find on map
          </Button>
        </div>
      </Field>
      {results && results.length > 0 && (
        <ul className="divide-y divide-stone-100 rounded-lg border border-stone-200 bg-white text-sm">
          {results.map((r) => (
            <li key={`${r.lat},${r.lng}`}>
              <button
                type="button"
                onClick={() => {
                  onChange({ lat: r.lat, lng: r.lng });
                  setResults(null);
                }}
                className="flex w-full items-start gap-2 px-3 py-2 text-left hover:bg-stone-50"
              >
                <MapPin className="mt-0.5 size-4 shrink-0 text-brand-700" /> {r.label}
              </button>
            </li>
          ))}
        </ul>
      )}
      <ErrorNote>{error}</ErrorNote>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Latitude">
          <Input type="number" step="any" value={value.lat ?? ""} onChange={(e) => onChange({ lat: e.target.value === "" ? null : Number(e.target.value) })} />
        </Field>
        <Field label="Longitude">
          <Input type="number" step="any" value={value.lng ?? ""} onChange={(e) => onChange({ lng: e.target.value === "" ? null : Number(e.target.value) })} />
        </Field>
      </div>
      {value.lat !== null && value.lng !== null && <MapPreview lat={value.lat} lng={value.lng} />}
    </div>
  );
}

function HoursEditor({ hours, onChange }: { hours: WorkspaceInput["hours"]; onChange: (h: WorkspaceInput["hours"]) => void }) {
  const set = (day: Day, patch: Partial<DayHours>) => {
    const current = hours[day] ?? { closed: false, open: "", close: "" };
    onChange({ ...hours, [day]: { ...current, ...patch } });
  };
  const copyMonday = () => {
    const mon = hours.mon ?? { closed: false, open: "", close: "" };
    onChange({ ...hours, ...Object.fromEntries((["tue", "wed", "thu", "fri"] as Day[]).map((d) => [d, { ...mon }])) });
  };

  return (
    <div>
      <div className="mb-2 flex justify-end">
        <button type="button" onClick={copyMonday} className="text-xs font-medium text-brand-700 hover:underline">
          Copy Monday to weekdays
        </button>
      </div>
      <div className="divide-y divide-stone-100 rounded-lg border border-stone-200">
        {DAYS.map((day) => {
          const h = hours[day] ?? { closed: false, open: "", close: "" };
          return (
            <div key={day} className="flex flex-wrap items-center gap-3 px-3 py-2">
              <span className="w-24 text-sm">{DAY_LABELS[day]}</span>
              <label className="flex items-center gap-1.5 text-sm text-stone-600">
                <input type="checkbox" checked={h.closed} onChange={(e) => set(day, { closed: e.target.checked })} className="accent-brand-700" />
                Closed
              </label>
              {!h.closed && (
                <div className="flex items-center gap-2">
                  <Input type="time" value={h.open} onChange={(e) => set(day, { open: e.target.value })} className="w-32 py-1" />
                  <span className="text-stone-400">to</span>
                  <Input type="time" value={h.close} onChange={(e) => set(day, { close: e.target.value })} className="w-32 py-1" />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function WorkspaceForm({
  initial,
  submitLabel,
  onSubmit,
  onCancel,
}: {
  initial: WorkspaceInput;
  submitLabel: string;
  onSubmit: (value: WorkspaceInput) => Promise<void>;
  onCancel?: () => void;
}) {
  const [value, setValue] = useState<WorkspaceInput>({ ...EMPTY_WORKSPACE, ...initial });
  const [showHours, setShowHours] = useState(hasHours(initial.hours));
  const [filter, setFilter] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const patch = (p: Partial<WorkspaceInput>) => setValue((v) => ({ ...v, ...p }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setSaving(true);
    try {
      await onSubmit({ ...value, hours: showHours ? value.hours : {}, ...(value.online_only ? { address: "", lat: null, lng: null } : {}) });
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-5">
      <Section title="What kind of business?" description="Any local business or website. This sets what customers' AI assistants will expect from you.">
        <Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Search: barber, dentist, plumber, yoga, web shop…" />
        <div className="grid max-h-80 gap-1 overflow-y-auto sm:grid-cols-2">
          {BUSINESS_TYPES.filter((t) => `${t.label} ${t.examples}`.toLowerCase().includes(filter.trim().toLowerCase()) || t.value === "other").map(
            ({ value: t, label, examples, icon: Icon }) => (
              <button
                key={t}
                type="button"
                onClick={() => {
                  patch({ type: t, ...(t === "online" ? { online_only: true } : {}) });
                  if (t === "online") setShowHours(false);
                }}
                className={cx(
                  "flex items-start gap-2.5 rounded-md border px-3 py-2 text-left transition-colors",
                  value.type === t ? "border-brand-600 bg-brand-50 ring-1 ring-brand-600" : "border-transparent hover:bg-hover",
                )}
              >
                <Icon className="mt-0.5 size-4 shrink-0 text-stone-600" />
                <span className="min-w-0">
                  <span className="block text-sm font-medium text-stone-800">{label}</span>
                  <span className="block truncate text-xs text-stone-500">{examples}</span>
                </span>
              </button>
            ),
          )}
        </div>
        <Field label="In your own words (optional)" hint="Helps assistants match you, for example: bike repair shop, vegan bakery, family dentist.">
          <Input value={value.category_label} onChange={(e) => patch({ category_label: e.target.value })} maxLength={80} placeholder={value.type === "other" ? "e.g. bike repair shop" : typeInfo(value.type).examples.split(",")[0]} />
        </Field>
      </Section>

      <Section title="The basics" description="What customers and their assistants see first.">
        <Field label="Business name">
          <Input required value={value.name} onChange={(e) => patch({ name: e.target.value })} placeholder={typeInfo(value.type).placeholder} />
        </Field>
        <Field label="Phone (optional)">
          <Input type="tel" value={value.phone} onChange={(e) => patch({ phone: e.target.value })} placeholder="+41 61 123 45 67" />
        </Field>
        <Field label="About the business" hint="A few sentences: what you offer, who it's for, what makes you different.">
          <Textarea value={value.description} onChange={(e) => patch({ description: e.target.value })} maxLength={2000} />
        </Field>
      </Section>

      <Section title="Location" description="Used when an assistant looks for businesses nearby.">
        <Toggle
          checked={value.online_only}
          onChange={(v) => {
            patch({ online_only: v });
            if (v) setShowHours(false);
          }}
          label="Online only, no place customers visit"
          hint="Assistants still find you by what you offer, just not by distance."
        />
        {!value.online_only && <AddressField value={value} onChange={patch} />}
      </Section>

      <Section title="Opening hours" description="Your own hours, even if the website doesn't list them.">
        <Toggle checked={showHours} onChange={setShowHours} label="We have opening hours" hint={showHours ? undefined : "Switch on if customers can visit or call at set times."} />
        {showHours && <HoursEditor hours={hasHours(value.hours) ? value.hours : DEFAULT_HOURS} onChange={(hours) => patch({ hours })} />}
      </Section>

      <Section title="Website" description="After you save, Oasis reads your website page by page.">
        <Field label="Website address" hint="We visit up to 30 pages on this site. Nothing on your site is changed.">
          <Input value={value.website_url} onChange={(e) => patch({ website_url: e.target.value })} placeholder="https://your-business.ch" inputMode="url" />
        </Field>
        <Field
          label="Test copy of your system (optional)"
          hint="If you have a staging or test version of your site, tools that book, order or send are tested against it, so a test never reaches a real customer."
        >
          <Input value={value.test_url} onChange={(e) => patch({ test_url: e.target.value })} placeholder="https://test.your-business.ch" inputMode="url" />
        </Field>
      </Section>

      <ErrorNote>{error}</ErrorNote>
      <div className="flex justify-end gap-2">
        {onCancel && (
          <Button type="button" variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
        )}
        <Button type="submit" loading={saving}>
          {submitLabel}
        </Button>
      </div>
    </form>
  );
}
