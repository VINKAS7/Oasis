import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// /api/auth/* goes to the better-auth service, everything else under /api to FastAPI.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // The auth service trusts only this origin (BETTER_AUTH_URL), so fail loudly instead of
    // moving to 5174 when the port is taken, where sign-up and login would quietly break.
    strictPort: true,
    proxy: {
      "/api/auth": { target: "http://127.0.0.1:3001" },
      // xfwd: the API rate-limits the public chat by the visitor's IP (X-Forwarded-For).
      "/api": { target: "http://127.0.0.1:8000", xfwd: true },
    },
  },
});
