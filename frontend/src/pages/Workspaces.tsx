import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Globe, Home, Package, Plus, PlugZap, ShoppingBag, Shirt, Sparkles, Store, UtensilsCrossed } from "lucide-react";
import { api, timeAgo } from "../lib/api";
import { useSession } from "../lib/auth-client";
import type { ShopTemplateKey, Workspace, WorkspaceInput } from "../types";
import { useShopTemplates } from "../components/ProductsPanel";
import { kindLabel, typeInfo } from "../components/businessTypes";
import { CrawlBadge } from "../components/CrawlBadge";
import { PageTitle } from "../components/Layout";
import { EMPTY_WORKSPACE, WorkspaceForm } from "../components/WorkspaceForm";
import { Badge, Button, Callout, EmptyState, ErrorNote, PageLoader, SectionTitle, cx } from "../components/ui";

function greeting(): string {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

export function WorkspacesPage() {
  const { data } = useSession();
  const [items, setItems] = useState<Workspace[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<Workspace[]>("/api/workspaces").then(setItems, (e) => setError(e.message));
  }, []);

  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!items) return <PageLoader />;
  const first = (data?.user.name || "").split(" ")[0];

  return (
    <div>
      <PageTitle
        icon={<Home className="size-10" strokeWidth={1.5} />}
        title={`${greeting()}${first ? `, ${first}` : ""}`}
        subtitle="Each workspace is one business or website of any kind. Oasis reads the site, you record what only you know, and AI assistants can then find it and act for its customers."
      />

      <SectionTitle
        action={
          <Link to="/workspaces/new">
            <Button variant="ghost">
              <Plus className="size-4" /> New
            </Button>
          </Link>
        }
      >
        Workspaces
      </SectionTitle>

      {items.length === 0 ? (
        <EmptyState icon={<Store className="size-8" strokeWidth={1.5} />} title="No workspace yet">
          Create one for your business. We'll read your website and suggest the first tools.
          <div className="mt-4">
            <Link to="/workspaces/new">
              <Button>
                <Plus className="size-4" /> Create a workspace
              </Button>
            </Link>
          </div>
        </EmptyState>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {items.map((w) => {
            const { icon: Icon } = typeInfo(w.type);
            const label = kindLabel(w.type, w.category_label);
            return (
              <Link key={w.id} to={`/workspaces/${w.id}`} className="group rounded-lg border border-stone-200 p-4 transition-colors hover:bg-stone-50">
                <div className="flex items-start justify-between gap-3">
                  <Icon className="size-7 text-stone-600" strokeWidth={1.5} />
                  <div className="flex flex-wrap justify-end gap-1">
                    {w.pending_orders > 0 && <Badge tone="amber">{w.pending_orders} new order{w.pending_orders === 1 ? "" : "s"}</Badge>}
                    {w.status === "live" && <Badge tone="green">MCP server live</Badge>}
                    {w.latest_run && <CrawlBadge run={w.latest_run} />}
                  </div>
                </div>
                <h3 className="mt-3 font-semibold text-stone-800">{w.name}</h3>
                <p className="text-xs text-stone-500">
                  {label} · <code>{w.id}</code>
                </p>
                {w.website_url && (
                  <p className="mt-2 flex items-center gap-1.5 truncate text-sm text-stone-500">
                    <Globe className="size-3.5 shrink-0" /> {w.website_url.replace(/^https?:\/\//, "")}
                  </p>
                )}
                <p className="mt-2 text-xs text-stone-400">Created {timeAgo(w.created_at)}</p>
              </Link>
            );
          })}
        </div>
      )}

      <SectionTitle>Recording flows</SectionTitle>
      <Callout icon={<PlugZap className="size-4" />}>
        Bookings, orders, enquiries and other actions are recorded with the{" "}
        <Link to="/extension" className="font-medium underline decoration-stone-300 underline-offset-2 hover:decoration-stone-500">
          Oasis Recorder extension
        </Link>{" "}
        for Chrome: you do the task once on your own website, and it saves the steps to your workspace.
      </Callout>
    </div>
  );
}

const SHOP_ICONS: Record<ShopTemplateKey, typeof Shirt> = { clothing: Shirt, menu: UtensilsCrossed, services: Sparkles, general: Package };
const SHOP_TYPES: Record<ShopTemplateKey, WorkspaceInput["type"]> = { clothing: "shop", menu: "restaurant", services: "services", general: "shop" };

export function NewWorkspacePage() {
  const navigate = useNavigate();
  const templates = useShopTemplates();
  const [path, setPath] = useState<"" | "website" | "shop">("");
  const [template, setTemplate] = useState<ShopTemplateKey | "">("");
  const create = async (value: WorkspaceInput) => {
    const ws = await api<Workspace>("/api/workspaces", { method: "POST", json: value });
    navigate(`/workspaces/${ws.id}`);
  };
  const choice = (active: boolean) =>
    cx("flex flex-col gap-1.5 rounded-xl border p-4 text-left transition-colors", active ? "border-brand-700 bg-brand-50" : "border-stone-200 hover:border-stone-400 hover:bg-hover");

  return (
    <div>
      <PageTitle
        icon={<Store className="size-10" strokeWidth={1.5} />}
        title="New workspace"
        subtitle={path === "shop" ? "Your shop lives in Oasis: add products, and AI assistants can show and sell them. No website needed." : "Tell us about the business."}
      />
      <div className="mb-6 grid gap-3 sm:grid-cols-2">
        <button onClick={() => setPath("website")} className={choice(path === "website")}>
          <Globe className="size-5 text-stone-600" />
          <span className="font-medium">I have a website</span>
          <span className="text-sm text-stone-500">Oasis reads it and turns what it offers into tools for AI assistants.</span>
        </button>
        <button onClick={() => setPath("shop")} className={choice(path === "shop")}>
          <ShoppingBag className="size-5 text-stone-600" />
          <span className="font-medium">Create a shop on Oasis</span>
          <span className="text-sm text-stone-500">No website: add products with photos and prices here, and publish them as your own MCP server.</span>
        </button>
      </div>

      {path === "shop" && (
        <div className="mb-6">
          <h3 className="mb-2 text-sm font-medium text-stone-800">What will you sell?</h3>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {templates &&
              (Object.keys(SHOP_ICONS) as ShopTemplateKey[]).map((k) => {
                const Icon = SHOP_ICONS[k];
                return (
                  <button key={k} onClick={() => setTemplate(k)} className={choice(template === k)}>
                    <Icon className="size-5 text-stone-600" />
                    <span className="font-medium">{templates[k].label}</span>
                    <span className="text-xs text-stone-500">{templates[k].description}</span>
                  </button>
                );
              })}
          </div>
        </div>
      )}

      {path === "website" && (
        <WorkspaceForm initial={EMPTY_WORKSPACE} submitLabel="Create workspace and read website" onSubmit={create} onCancel={() => navigate("/workspaces")} />
      )}
      {path === "shop" && template && (
        <WorkspaceForm
          key={template}
          initial={{ ...EMPTY_WORKSPACE, shop_template: template, type: SHOP_TYPES[template], online_only: template !== "menu", crawl_enabled: false }}
          submitLabel="Create shop"
          onSubmit={create}
          onCancel={() => navigate("/workspaces")}
        />
      )}
    </div>
  );
}
