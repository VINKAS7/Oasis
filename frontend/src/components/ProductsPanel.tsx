import { useCallback, useEffect, useRef, useState, type ChangeEvent, type DragEvent } from "react";
import { ImagePlus, Package, Plus, Star, Trash2, X } from "lucide-react";
import { api } from "../lib/api";
import { money } from "../lib/chat";
import type { Product, ShopField, ShopTemplate, ShopTemplateKey, Workspace } from "../types";
import { Badge, Button, Card, CardHeader, EmptyState, ErrorNote, Field, Input, Textarea, Toggle, cx } from "./ui";

let templatesCache: Record<ShopTemplateKey, ShopTemplate> | null = null;

export function useShopTemplates(): Record<ShopTemplateKey, ShopTemplate> | null {
  const [t, setT] = useState(templatesCache);
  useEffect(() => {
    if (!templatesCache) api<Record<ShopTemplateKey, ShopTemplate>>("/api/shop/templates").then((r) => setT((templatesCache = r)));
  }, []);
  return t;
}

const plural = (noun: string) => noun + (/(s|sh|ch|x)$/.test(noun) ? "es" : "s");

const variantKeys = (options: Record<string, string[]>) =>
  Object.values(options).reduce<string[]>((acc, values) => acc.flatMap((k) => values.map((v) => (k ? `${k}/${v}` : v))), [""]);

function stockSummary(p: Product): { text: string; tone: "neutral" | "amber" | "red" | "green" } | null {
  const values = Object.values(p.stock);
  if (!values.length) return null;
  const total = values.reduce((a, b) => a + b, 0);
  if (total === 0) return { text: "Sold out", tone: "red" };
  if (values.some((v) => v === 0)) return { text: `${total} in stock · some sizes out`, tone: "amber" };
  return { text: `${total} in stock`, tone: "green" };
}

// --- the editor -------------------------------------------------------------------------------

function OptionChips({ label, values, suggestions, onChange }: { label: string; values: string[]; suggestions: string[]; onChange: (v: string[]) => void }) {
  const [draft, setDraft] = useState("");
  const add = (v: string) => {
    const x = v.trim();
    if (x && !values.includes(x)) onChange([...values, x]);
    setDraft("");
  };
  const extra = suggestions.filter((s) => !values.includes(s));
  return (
    <Field label={label} hint="Click a suggestion or type your own and press Enter.">
      <div className="flex flex-wrap items-center gap-1.5 rounded-md border border-stone-200 p-1.5">
        {values.map((v) => (
          <span key={v} className="inline-flex items-center gap-1 rounded-full bg-stone-800 px-2 py-0.5 text-xs text-white">
            {v}
            <button type="button" onClick={() => onChange(values.filter((x) => x !== v))} aria-label={`Remove ${v}`}>
              <X className="size-3" />
            </button>
          </span>
        ))}
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === ",") {
              e.preventDefault();
              add(draft);
            }
          }}
          onBlur={() => draft && add(draft)}
          placeholder={values.length ? "" : "Add…"}
          className="min-w-20 flex-1 bg-transparent px-1 text-sm outline-none"
        />
      </div>
      {extra.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {extra.map((s) => (
            <button key={s} type="button" onClick={() => add(s)} className="rounded-full border border-stone-200 px-2 py-0.5 text-xs text-stone-600 hover:bg-hover">
              + {s}
            </button>
          ))}
        </div>
      )}
    </Field>
  );
}

function AttributeField({ f, value, onChange }: { f: ShopField; value: unknown; onChange: (v: unknown) => void }) {
  if (f.kind === "tags") {
    const on = Array.isArray(value) ? (value as string[]) : [];
    return (
      <Field label={f.label}>
        <div className="flex flex-wrap gap-1.5">
          {(f.choices ?? []).map((c) => (
            <button
              key={c}
              type="button"
              onClick={() => onChange(on.includes(c) ? on.filter((x) => x !== c) : [...on, c])}
              className={cx("rounded-full border px-2.5 py-0.5 text-xs", on.includes(c) ? "border-brand-700 bg-brand-50 text-brand-800" : "border-stone-200 text-stone-600 hover:bg-hover")}
            >
              {c}
            </button>
          ))}
        </div>
      </Field>
    );
  }
  if (f.kind === "select") {
    return (
      <Field label={f.label}>
        <select value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} className="w-full rounded-md border border-stone-200 bg-white px-2.5 py-1.5 text-sm">
          <option value="">—</option>
          {(f.choices ?? []).map((c) => (
            <option key={c}>{c}</option>
          ))}
        </select>
      </Field>
    );
  }
  if (f.kind === "longtext") {
    return (
      <Field label={f.label} hint={f.hint}>
        <Textarea rows={3} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} />
      </Field>
    );
  }
  return (
    <Field label={f.label} hint={f.hint}>
      <Input type={f.kind === "number" ? "number" : "text"} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} />
    </Field>
  );
}

type Photo = { kind: "saved"; name: string; url: string } | { kind: "new"; file: File; url: string };

function ProductEditor({
  businessId,
  template,
  product,
  onClose,
  onSaved,
}: {
  businessId: string;
  template: ShopTemplate;
  product: Product | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(product?.name ?? "");
  const [price, setPrice] = useState(product?.price_amount != null ? String(product.price_amount) : "");
  const [currency, setCurrency] = useState(product?.currency ?? "CHF");
  const [category, setCategory] = useState(product?.category ?? "");
  const [description, setDescription] = useState(product?.description ?? "");
  const [attributes, setAttributes] = useState<Record<string, unknown>>(product?.attributes ?? {});
  const [options, setOptions] = useState<Record<string, string[]>>(product?.options ?? {});
  const [stock, setStock] = useState<Record<string, string>>(
    Object.fromEntries(Object.entries(product?.stock ?? {}).map(([k, v]) => [k, String(v)])),
  );
  const [active, setActive] = useState(product?.active ?? true);
  const [photos, setPhotos] = useState<Photo[]>((product?.images ?? []).map((n, i) => ({ kind: "saved", name: n, url: product!.image_urls[i] })));
  const [removed, setRemoved] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const cleanOptions = Object.fromEntries(template.variants.map((v) => [v.key, options[v.key] ?? []]).filter(([, vals]) => (vals as string[]).length));
  const keys = template.stock ? variantKeys(cleanOptions) : [];

  const addFiles = (files: FileList | File[]) => {
    const list = [...files].filter((f) => /^image\/(jpeg|png|webp)$/.test(f.type)).slice(0, 8 - photos.length);
    setPhotos((p) => [...p, ...list.map((file) => ({ kind: "new" as const, file, url: URL.createObjectURL(file) }))]);
  };
  const removePhoto = (i: number) => {
    const p = photos[i];
    if (p.kind === "saved") setRemoved((r) => [...r, p.name]);
    setPhotos((all) => all.filter((_, n) => n !== i));
  };
  const makeMain = (i: number) => setPhotos((all) => [all[i], ...all.filter((_, n) => n !== i)]);

  const save = async () => {
    if (!name.trim()) return setError(`Give the ${template.item} a name.`);
    setBusy(true);
    setError("");
    try {
      const body = {
        name: name.trim(),
        description,
        category,
        price_amount: price.trim() === "" ? null : Number(price),
        currency,
        attributes,
        options: cleanOptions,
        stock: Object.fromEntries(keys.filter((k) => stock[k] !== undefined && stock[k] !== "").map((k) => [k, Number(stock[k])])),
        active,
      };
      const base = `/api/workspaces/${businessId}/products`;
      const saved = product
        ? await api<Product>(`${base}/${product.id}`, { method: "PATCH", json: body })
        : await api<Product>(base, { method: "POST", json: body });
      for (const n of removed) await api(`${base}/${saved.id}/images/${n}`, { method: "DELETE" });
      // Upload new photos in their place, then put every photo in the order shown.
      const names: string[] = [];
      for (const p of photos) {
        if (p.kind === "saved") names.push(p.name);
        else {
          const form = new FormData();
          form.append("file", p.file);
          const res = await fetch(`${base}/${saved.id}/images`, { method: "POST", body: form, credentials: "include" });
          if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? "A photo could not be uploaded");
          const after = (await res.json()) as Product;
          names.push(after.images[after.images.length - 1]);
        }
      }
      if (names.length) await api(`${base}/${saved.id}/images/order`, { method: "POST", json: { ids: names } });
      onSaved();
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!product || !confirm(`Delete “${product.name}”? Customers will no longer see it.`)) return;
    setBusy(true);
    try {
      await api(`/api/workspaces/${businessId}/products/${product.id}`, { method: "DELETE" });
      onSaved();
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/30" onClick={busy ? undefined : onClose} />
      <div className="relative flex max-h-[calc(100vh-2rem)] w-full max-w-2xl flex-col rounded-xl bg-white shadow-[0_16px_48px_rgba(15,15,15,0.2)]">
        <div className="flex items-center justify-between px-5 pt-5">
          <h2 className="text-lg font-semibold">{product ? `Edit ${template.item}` : `New ${template.item}`}</h2>
          <button onClick={onClose} disabled={busy} className="rounded p-1 text-stone-400 hover:bg-hover" aria-label="Close">
            <X className="size-5" />
          </button>
        </div>
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-4">
          <div
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e: DragEvent) => {
              e.preventDefault();
              addFiles(e.dataTransfer.files);
            }}
          >
            <div className="mb-1.5 text-sm font-medium text-stone-700">Photos</div>
            <div className="flex flex-wrap gap-2">
              {photos.map((p, i) => (
                <div key={p.url} className="group relative size-24 overflow-hidden rounded-lg border border-stone-200">
                  <img src={p.url} alt="" className="size-full object-cover" />
                  {i === 0 && <span className="absolute top-1 left-1 rounded bg-black/60 px-1 text-[11px] text-white">Main</span>}
                  <div className="absolute inset-x-0 bottom-0 flex justify-between bg-black/50 p-1 opacity-0 group-hover:opacity-100">
                    {i > 0 ? (
                      <button type="button" onClick={() => makeMain(i)} title="Make main photo" className="text-white">
                        <Star className="size-3.5" />
                      </button>
                    ) : (
                      <span />
                    )}
                    <button type="button" onClick={() => removePhoto(i)} title="Remove photo" className="text-white">
                      <Trash2 className="size-3.5" />
                    </button>
                  </div>
                </div>
              ))}
              {photos.length < 8 && (
                <button
                  type="button"
                  onClick={() => fileRef.current?.click()}
                  className="flex size-24 flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-stone-300 text-xs text-stone-500 hover:border-brand-600 hover:bg-hover"
                >
                  <ImagePlus className="size-5" /> Add photos
                </button>
              )}
            </div>
            <p className="mt-1 text-xs text-stone-500">JPEG, PNG or WebP, up to 8 photos. Drag them here or click Add. The first is the main photo.</p>
            <input
              ref={fileRef}
              type="file"
              multiple
              accept="image/jpeg,image/png,image/webp"
              className="hidden"
              onChange={(e: ChangeEvent<HTMLInputElement>) => {
                if (e.target.files) addFiles(e.target.files);
                e.target.value = "";
              }}
            />
          </div>

          <div className="grid gap-3 sm:grid-cols-[1fr_140px_90px]">
            <Field label="Name">
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder={template.item === "dish" ? "Margherita" : template.item === "service" ? "Haircut & styling" : "Linen shirt"} autoFocus />
            </Field>
            <Field label="Price" hint="Empty: price on request">
              <Input type="number" min={0} step="0.05" value={price} onChange={(e) => setPrice(e.target.value)} />
            </Field>
            <Field label="Currency">
              <Input value={currency} maxLength={3} onChange={(e) => setCurrency(e.target.value.toUpperCase())} />
            </Field>
          </div>
          <Field label={template.category_label}>
            <Input value={category} onChange={(e) => setCategory(e.target.value)} list="shop-categories" placeholder={template.category_examples[0] ?? ""} />
            <datalist id="shop-categories">
              {template.category_examples.map((c) => (
                <option key={c} value={c} />
              ))}
            </datalist>
          </Field>
          <Field label="Description">
            <Textarea rows={3} value={description} onChange={(e) => setDescription(e.target.value)} placeholder={`What makes this ${template.item} special?`} />
          </Field>
          {template.fields.length > 0 && (
            <div className="grid gap-3 sm:grid-cols-2">
              {template.fields.map((f) => (
                <AttributeField key={f.key} f={f} value={attributes[f.key]} onChange={(v) => setAttributes((a) => ({ ...a, [f.key]: v }))} />
              ))}
            </div>
          )}
          {template.variants.map((v) => (
            <OptionChips key={v.key} label={v.label} values={options[v.key] ?? []} suggestions={v.suggestions} onChange={(vals) => setOptions((o) => ({ ...o, [v.key]: vals }))} />
          ))}
          {template.stock && (
            <Field label="Stock" hint="How many you have of each. Leave empty if you don't keep count; 0 shows as sold out.">
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                {keys.map((k) => (
                  <div key={k || "-"} className="flex items-center gap-2 rounded-md border border-stone-200 px-2 py-1 text-sm">
                    <span className="min-w-0 flex-1 truncate text-stone-600">{k ? k.split("/").join(" · ") : "In stock"}</span>
                    <input
                      type="number"
                      min={0}
                      aria-label={`Stock ${k ? k.split("/").join(" · ") : ""}`.trim()}
                      value={stock[k] ?? ""}
                      onChange={(e) => setStock((s) => ({ ...s, [k]: e.target.value }))}
                      className="w-16 rounded border border-stone-200 bg-white px-1.5 py-0.5 text-right tabular-nums"
                    />
                  </div>
                ))}
              </div>
            </Field>
          )}
          <Toggle checked={active} onChange={setActive} label="Visible to customers" hint={active ? undefined : "Hidden: assistants and the chat don't show it."} />
          <ErrorNote>{error}</ErrorNote>
        </div>
        <div className="flex items-center justify-between gap-2 border-t border-line px-5 py-3">
          {product ? (
            <Button variant="ghost" onClick={remove} disabled={busy}>
              <Trash2 className="size-4" /> Delete
            </Button>
          ) : (
            <span />
          )}
          <div className="flex gap-2">
            <Button variant="secondary" onClick={onClose} disabled={busy}>
              Cancel
            </Button>
            <Button onClick={save} loading={busy}>
              {product ? "Save" : `Add ${template.item}`}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

// --- the panel ----------------------------------------------------------------------------------

/** An Oasis shop's products: what its MCP server offers, with photos, prices, sizes and stock. */
export function ProductsPanel({ workspace, onChange }: { workspace: Workspace; onChange: () => void }) {
  const templates = useShopTemplates();
  const [products, setProducts] = useState<Product[] | null>(null);
  const [editing, setEditing] = useState<Product | "new" | null>(null);
  const [error, setError] = useState("");
  const template = templates?.[(workspace.shop_template || "general") as ShopTemplateKey];

  const load = useCallback(() => api<Product[]>(`/api/workspaces/${workspace.id}/products`).then(setProducts, (e) => setError(e.message)), [workspace.id]);
  useEffect(() => {
    load();
  }, [load]);

  if (!template) return null;
  const noun = template.item;
  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            {noun === "dish" ? "Menu" : noun === "service" ? "Services" : "Products"} <Badge>{template.label}</Badge>
          </span>
        }
        description={`Everything here is what AI assistants and the Oasis chat offer customers, with photos and prices. ${products?.length ?? 0} ${products?.length === 1 ? noun : plural(noun)}.`}
        action={
          <Button onClick={() => setEditing("new")}>
            <Plus className="size-4" /> Add {noun}
          </Button>
        }
      />
      <ErrorNote>{error}</ErrorNote>
      {products && products.length === 0 ? (
        <EmptyState icon={<Package className="size-6" />} title={`No ${plural(noun)} yet`}>
          Add your first {noun} with a photo, price and description. Your shop's tool for AI assistants is made as soon as there is one.
        </EmptyState>
      ) : (
        <div className="grid grid-cols-2 gap-3 p-4 sm:grid-cols-3 lg:grid-cols-4">
          {(products ?? []).map((p) => {
            const s = stockSummary(p);
            return (
              <button key={p.id} onClick={() => setEditing(p)} className={cx("flex flex-col justify-start overflow-hidden rounded-xl border border-stone-200 bg-white text-left hover:border-stone-400", !p.active && "opacity-60")}>
                {p.image_urls[0] ? (
                  <img src={p.image_urls[0]} alt="" className="aspect-[4/3] w-full object-cover" />
                ) : (
                  <div className="flex aspect-[4/3] items-center justify-center bg-stone-100 text-stone-300">
                    <ImagePlus className="size-6" />
                  </div>
                )}
                <div className="space-y-1 p-2.5">
                  <div className="flex items-start justify-between gap-2 text-sm">
                    <span className="font-medium text-stone-800">{p.name}</span>
                    <span className="shrink-0 tabular-nums text-stone-600">{money(p.price_amount, p.currency) || "on request"}</span>
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {p.category && <Badge>{p.category}</Badge>}
                    {s && <Badge tone={s.tone}>{s.text}</Badge>}
                    {!p.active && <Badge>hidden</Badge>}
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      )}
      {editing && (
        <ProductEditor
          businessId={workspace.id}
          template={template}
          product={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            load();
            onChange();
          }}
        />
      )}
    </Card>
  );
}
