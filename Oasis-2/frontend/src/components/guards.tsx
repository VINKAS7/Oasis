import type { ReactNode } from "react";
import { Link, Navigate, useLocation } from "react-router-dom";
import { ShieldAlert } from "lucide-react";
import { isAdmin, useSession } from "../lib/auth-client";
import { EmptyState, PageLoader } from "./ui";

// better-auth refetches the session whenever the tab becomes visible again and, for a signed-out
// session, marks it pending meanwhile (its first fetch looks the same, so isRefetching can't tell
// them apart). Showing the loader then would swap the page for a spinner on every Alt+Tab and wipe
// what was typed into a form, so the loader shows only until the session has been checked once.
let sessionChecked = false;

function useSessionState() {
  const { data, isPending } = useSession();
  if (!isPending) sessionChecked = true;
  return { data, loading: isPending && !sessionChecked };
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { data, loading } = useSessionState();
  const location = useLocation();
  if (loading) return <PageLoader />;
  if (!data) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <>{children}</>;
}

/** Hides the admin panel from non-admins. The API enforces the same rule on every call. */
export function RequireAdmin({ children }: { children: ReactNode }) {
  const { data, loading } = useSessionState();
  if (loading) return <PageLoader />;
  if (!isAdmin((data?.user as { role?: string } | undefined)?.role)) {
    return (
      <EmptyState icon={<ShieldAlert className="size-6" />} title="Admins only">
        Your account doesn't have access to the admin panel.{" "}
        <Link to="/workspaces" className="font-medium text-brand-700 hover:underline">
          Back to your workspaces
        </Link>
      </EmptyState>
    );
  }
  return <>{children}</>;
}

export function RedirectIfSignedIn({ children }: { children: ReactNode }) {
  const { data, loading } = useSessionState();
  const from = (useLocation().state as { from?: string } | null)?.from;
  if (loading) return <PageLoader />;
  if (data) return <Navigate to={from ?? "/workspaces"} replace />;
  return <>{children}</>;
}
