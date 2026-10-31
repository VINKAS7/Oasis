import { createAuthClient } from "better-auth/react";
import { adminClient } from "better-auth/client/plugins";

// Same origin: Vite (dev) or FastAPI (prod) forwards /api/auth/* to the auth service.
export const authClient = createAuthClient({
  baseURL: window.location.origin,
  basePath: "/api/auth",
  plugins: [adminClient()],
});

export const { useSession, signIn, signUp, signOut } = authClient;

export function isAdmin(role: string | null | undefined): boolean {
  return (role ?? "").split(",").map((r) => r.trim()).includes("admin");
}
