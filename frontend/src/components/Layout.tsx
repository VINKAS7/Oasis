import { useEffect, useState, type ReactNode } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  Activity,
  Bot,
  Building2,
  Check,
  ChevronRight,
  ChevronsUpDown,
  Copy,
  Globe,
  Home,
  LayoutDashboard,
  LogOut,
  Menu,
  MessageCircle,
  PlugZap,
  Plus,
  Route,
  Users,
  X,
} from "lucide-react";
import { isAdmin, signOut, useSession } from "../lib/auth-client";
import { api } from "../lib/api";
import type { Workspace } from "../types";
import { typeInfo } from "./businessTypes";
import { cx } from "./ui";

export function Logo({ className }: { className?: string }) {
  return (
    <Link to="/" className={cx("flex items-center gap-2 font-semibold text-stone-800", className)}>
      <img src="/favicon.svg" alt="" className="size-6" />
      AgentReady
    </Link>
  );
}

/** A Notion-style page header: big icon, big title, quiet subtitle, actions on the right. */
export function PageTitle({ icon, title, subtitle, actions, meta }: { icon?: ReactNode; title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; meta?: ReactNode }) {
  return (
    <div className="mb-8">
      {icon && <div className="mb-3 text-stone-700">{icon}</div>}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <h1 className="text-[2.5rem] leading-tight font-bold tracking-tight text-stone-800">{title}</h1>
        {actions && <div className="flex shrink-0 flex-wrap items-center gap-2 pt-2">{actions}</div>}
      </div>
      {subtitle && <p className="mt-2 text-stone-500">{subtitle}</p>}
      {meta && <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-sm text-stone-500">{meta}</div>}
    </div>
  );
}

const ADMIN_NAV = [
  { to: "/admin", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/admin/providers", label: "AI providers", icon: Bot },
  { to: "/admin/routing", label: "Task routing", icon: Route },
  { to: "/admin/crawler", label: "Platform settings", icon: Globe },
  { to: "/admin/users", label: "Users", icon: Users },
  { to: "/admin/workspaces", label: "All workspaces", icon: Building2 },
  { to: "/admin/usage", label: "AI usage", icon: Activity },
];

const item = ({ isActive }: { isActive: boolean }) =>
  cx("flex items-center gap-2 rounded-md px-2 py-1 text-sm", isActive ? "bg-hover font-medium text-stone-800" : "text-stone-600 hover:bg-hover");

function AccountMenu() {
  const { data } = useSession();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  if (!data) return null;
  const { user } = data;
  const first = (user.name || user.email).split(" ")[0];

  return (
    <div className="relative">
      <button onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-hover">
        <span className="flex size-5 items-center justify-center rounded bg-stone-800 text-[11px] font-semibold text-white">
          {(user.name || user.email).slice(0, 1).toUpperCase()}
        </span>
        <span className="min-w-0 flex-1 truncate font-medium">{first}'s AgentReady</span>
        <ChevronsUpDown className="size-3.5 text-stone-400" />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute top-full left-0 z-20 mt-1 w-64 rounded-lg border border-stone-200 bg-white p-1.5 shadow-[0_8px_24px_rgba(15,15,15,0.12)]">
            <div className="px-2 py-1.5">
              <div className="truncate text-sm">{user.name}</div>
              <div className="truncate text-xs text-stone-500">{user.email}</div>
            </div>
            <button
              onClick={async () => {
                await navigator.clipboard.writeText(user.id);
                setCopied(true);
                setTimeout(() => setCopied(false), 1500);
              }}
              className="flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left hover:bg-hover"
              title="Copy your user id"
            >
              <span>
                <span className="block text-xs text-stone-500">User ID</span>
                <code className="text-xs">{user.id}</code>
              </span>
              {copied ? <Check className="size-3.5 text-emerald-600" /> : <Copy className="size-3.5 text-stone-400" />}
            </button>
            <div className="my-1 border-t border-line" />
            <button
              onClick={async () => {
                await signOut();
                navigate("/login");
              }}
              className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm text-stone-600 hover:bg-hover"
            >
              <LogOut className="size-4" /> Log out
            </button>
          </div>
        </>
      )}
    </div>
  );
}

function Sidebar({ workspaces, admin, onNavigate }: { workspaces: Workspace[]; admin: boolean; onNavigate?: () => void }) {
  return (
    <nav className="flex h-full flex-col gap-4 overflow-y-auto px-2 py-3 text-stone-600" onClick={(e) => (e.target as HTMLElement).closest("a") && onNavigate?.()}>
      <AccountMenu />
      <div className="space-y-px">
        <NavLink to="/workspaces" end className={item}>
          <Home className="size-4" /> Home
        </NavLink>
        <NavLink to="/extension" className={item}>
          <PlugZap className="size-4" /> Recorder extension
        </NavLink>
        <a href="/chat" target="_blank" rel="noreferrer" className={item({ isActive: false })} title="The public chat your customers use, in a new tab">
          <MessageCircle className="size-4" /> Customer chat
        </a>
      </div>

      <div>
        <div className="group flex items-center justify-between px-2 pb-1 text-xs font-medium text-stone-500">
          Workspaces
          <Link to="/workspaces/new" className="rounded p-0.5 text-stone-400 hover:bg-hover hover:text-stone-700" title="New workspace">
            <Plus className="size-3.5" />
          </Link>
        </div>
        <div className="space-y-px">
          {workspaces.map((w) => {
            const Icon = typeInfo(w.type).icon;
            return (
              <NavLink key={w.id} to={`/workspaces/${w.id}`} className={item}>
                <Icon className="size-4 shrink-0" />
                <span className="truncate">{w.name}</span>
              </NavLink>
            );
          })}
          {workspaces.length === 0 && <p className="px-2 py-1 text-xs text-stone-400">No workspaces yet</p>}
          <NavLink to="/workspaces/new" className={item}>
            <Plus className="size-4" /> New workspace
          </NavLink>
        </div>
      </div>

      {admin && (
        <div>
          <div className="px-2 pb-1 text-xs font-medium text-stone-500">Admin</div>
          <div className="space-y-px">
            {ADMIN_NAV.map(({ to, label, icon: Icon, end }) => (
              <NavLink key={to} to={to} end={end} className={item}>
                <Icon className="size-4" /> {label}
              </NavLink>
            ))}
          </div>
        </div>
      )}
    </nav>
  );
}

const SECTION_NAMES: Record<string, string> = { tools: "Tools", recordings: "Recordings", proposals: "Suggested changes" };
const ADMIN_NAMES: Record<string, string> = { providers: "AI providers", routing: "Task routing", crawler: "Platform settings", users: "Users", workspaces: "All workspaces", usage: "AI usage" };

function Breadcrumbs({ workspaces }: { workspaces: Workspace[] }) {
  const parts = useLocation().pathname.split("/").filter(Boolean);
  const crumbs: { label: string; to: string }[] = [];
  if (parts[0] === "workspaces") {
    crumbs.push({ label: "Home", to: "/workspaces" });
    if (parts[1] === "new") crumbs.push({ label: "New workspace", to: "/workspaces/new" });
    else if (parts[1]) {
      crumbs.push({ label: workspaces.find((w) => w.id === parts[1])?.name ?? parts[1], to: `/workspaces/${parts[1]}` });
      if (parts[2]) crumbs.push({ label: SECTION_NAMES[parts[2]] ?? parts[2], to: `/workspaces/${parts[1]}/${parts[2]}/${parts[3] ?? ""}` });
    }
  } else if (parts[0] === "admin") {
    crumbs.push({ label: "Admin", to: "/admin" });
    if (parts[1]) crumbs.push({ label: ADMIN_NAMES[parts[1]] ?? parts[1], to: `/admin/${parts[1]}` });
  } else if (parts[0] === "extension") {
    crumbs.push({ label: "Recorder extension", to: "/extension" });
  }
  return (
    <div className="flex min-w-0 items-center gap-1 text-sm text-stone-600">
      {crumbs.map((c, i) => (
        <span key={c.to} className="flex min-w-0 items-center gap-1">
          {i > 0 && <ChevronRight className="size-3.5 shrink-0 text-stone-400" />}
          <Link to={c.to} className="truncate rounded px-1 py-0.5 hover:bg-hover">
            {c.label}
          </Link>
        </span>
      ))}
    </div>
  );
}

export function AppLayout() {
  const { data } = useSession();
  const admin = isAdmin((data?.user as { role?: string } | undefined)?.role);
  const location = useLocation();
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [mobileOpen, setMobileOpen] = useState(false);

  // Refresh the sidebar list on navigation, so new or deleted workspaces show up.
  useEffect(() => {
    api<Workspace[]>("/api/workspaces").then(setWorkspaces, () => undefined);
  }, [location.pathname]);

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 bg-sidebar md:block">
        <Sidebar workspaces={workspaces} admin={admin} />
      </aside>
      {mobileOpen && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div className="absolute inset-0 bg-stone-900/30" onClick={() => setMobileOpen(false)} />
          <aside className="relative h-full w-64 bg-sidebar shadow-xl">
            <button onClick={() => setMobileOpen(false)} className="absolute top-3 right-2 rounded p-1 text-stone-500 hover:bg-hover" aria-label="Close menu">
              <X className="size-4" />
            </button>
            <Sidebar workspaces={workspaces} admin={admin} onNavigate={() => setMobileOpen(false)} />
          </aside>
        </div>
      )}
      <div className="min-w-0 flex-1">
        <header className="sticky top-0 z-30 flex h-11 items-center gap-2 bg-white/95 px-3 backdrop-blur">
          <button onClick={() => setMobileOpen(true)} className="rounded p-1 text-stone-500 hover:bg-hover md:hidden" aria-label="Open menu">
            <Menu className="size-4" />
          </button>
          <Breadcrumbs workspaces={workspaces} />
        </header>
        <main className="mx-auto max-w-[960px] px-6 pt-10 pb-24 sm:px-12">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
