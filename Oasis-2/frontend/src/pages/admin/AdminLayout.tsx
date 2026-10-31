import type { ReactNode } from "react";
import { Outlet } from "react-router-dom";
import { PageTitle } from "../../components/Layout";

// The admin pages are listed in the sidebar; this only renders the chosen one.
export function AdminLayout() {
  return <Outlet />;
}

export function AdminTitle({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return <PageTitle title={title} subtitle={description} actions={action} />;
}
