import { useCallback, useEffect, useState } from "react";
import { Search } from "lucide-react";
import { authClient, isAdmin, useSession } from "../../lib/auth-client";
import { timeAgo } from "../../lib/api";
import { Badge, Button, Card, ErrorNote, Input, PageLoader } from "../../components/ui";
import { AdminTitle } from "./AdminLayout";

interface AdminUser {
  id: string;
  name: string;
  email: string;
  role?: string | null;
  banned?: boolean | null;
  createdAt: string | Date;
}

// Backed by better-auth's admin plugin, which checks the admin role on every call.
export function AdminUsers() {
  const { data: session } = useSession();
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [total, setTotal] = useState(0);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  const load = useCallback(async () => {
    const { data, error } = await authClient.admin.listUsers({
      query: { limit: 100, sortBy: "createdAt", sortDirection: "desc", ...(query ? { searchValue: query, searchField: "email", searchOperator: "contains" } : {}) },
    });
    if (error) return setError(error.message ?? "Could not load users");
    setUsers(data.users as AdminUser[]);
    setTotal(data.total);
  }, [query]);

  useEffect(() => {
    load();
  }, [load]);

  const run = async (id: string, action: () => Promise<{ error: { message?: string } | null }>) => {
    setError("");
    setBusy(id);
    const { error } = await action();
    setBusy("");
    if (error) setError(error.message ?? "Action failed");
    else load();
  };

  if (!users) return error ? <ErrorNote>{error}</ErrorNote> : <PageLoader />;

  return (
    <div className="space-y-4">
      <AdminTitle title="Users" description={`${total} account${total === 1 ? "" : "s"}. Admins can open this panel and manage AI keys.`} />
      <div className="relative max-w-sm">
        <Search className="pointer-events-none absolute top-2.5 left-3 size-4 text-stone-400" />
        <Input className="pl-9" placeholder="Search by email" value={query} onChange={(e) => setQuery(e.target.value)} />
      </div>
      <ErrorNote>{error}</ErrorNote>
      <Card className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-stone-50 text-left text-xs text-stone-500 uppercase">
            <tr>
              <th className="px-5 py-2 font-medium">User</th>
              <th className="px-3 py-2 font-medium">User ID</th>
              <th className="px-3 py-2 font-medium">Role</th>
              <th className="px-3 py-2 font-medium">Joined</th>
              <th className="px-5 py-2" />
            </tr>
          </thead>
          <tbody className="divide-y divide-stone-100">
            {users.map((u) => {
              const admin = isAdmin(u.role);
              const self = u.id === session?.user.id;
              return (
                <tr key={u.id}>
                  <td className="px-5 py-3">
                    <div className="font-medium">{u.name}</div>
                    <div className="text-xs text-stone-500">{u.email}</div>
                  </td>
                  <td className="px-3 py-3">
                    <code className="text-xs text-stone-600">{u.id}</code>
                  </td>
                  <td className="px-3 py-3">
                    <div className="flex gap-1">
                      {admin ? <Badge tone="teal">admin</Badge> : <Badge>user</Badge>}
                      {u.banned && <Badge tone="red">banned</Badge>}
                    </div>
                  </td>
                  <td className="px-3 py-3 text-stone-500">{timeAgo(new Date(u.createdAt).toISOString())}</td>
                  <td className="px-5 py-3">
                    {self ? (
                      <span className="text-xs text-stone-400">you</span>
                    ) : (
                      <div className="flex justify-end gap-2">
                        <Button
                          variant="secondary"
                          disabled={busy === u.id}
                          onClick={() => run(u.id, () => authClient.admin.setRole({ userId: u.id, role: admin ? "user" : "admin" }))}
                        >
                          {admin ? "Remove admin" : "Make admin"}
                        </Button>
                        <Button
                          variant={u.banned ? "secondary" : "danger"}
                          disabled={busy === u.id}
                          onClick={() =>
                            run(u.id, () => (u.banned ? authClient.admin.unbanUser({ userId: u.id }) : authClient.admin.banUser({ userId: u.id, banReason: "Banned by an admin" })))
                          }
                        >
                          {u.banned ? "Unban" : "Ban"}
                        </Button>
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
