// AgentReady auth service: better-auth (email + password, admin plugin) on the shared SQLite file.
// The browser reaches it through the Vite proxy (/api/auth/*); the Python API calls
// /api/auth/get-session with the user's cookie to learn who is asking.
import { createServer } from "node:http";
import { existsSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { randomBytes } from "node:crypto";
import Database from "better-sqlite3";
import { betterAuth } from "better-auth";
import { admin, bearer } from "better-auth/plugins";
import { getMigrations } from "better-auth/db/migration";
import { toNodeHandler } from "better-auth/node";

const here = dirname(fileURLToPath(import.meta.url));
if (existsSync(resolve(here, ".env"))) process.loadEnvFile(resolve(here, ".env"));

const PORT = Number(process.env.AUTH_PORT ?? 3001);
const DB_PATH = resolve(here, process.env.DATABASE_PATH ?? "../database/agentready.sqlite");
const PUBLIC_URL = process.env.BETTER_AUTH_URL ?? "http://localhost:5173";
const ADMIN_EMAILS = (process.env.ADMIN_EMAILS ?? "")
  .split(",")
  .map((e) => e.trim().toLowerCase())
  .filter(Boolean);

mkdirSync(dirname(DB_PATH), { recursive: true });
const db = new Database(DB_PATH);
db.pragma("journal_mode = WAL");
db.pragma("busy_timeout = 5000");

// Readable, collision-safe ids: users get "usr_" so a uid is recognisable in logs and the API.
const ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789";
function randomId(size = 24) {
  const bytes = randomBytes(size);
  let out = "";
  for (const b of bytes) out += ALPHABET[b % ALPHABET.length];
  return out;
}

export const auth = betterAuth({
  appName: "AgentReady",
  baseURL: PUBLIC_URL,
  basePath: "/api/auth",
  secret: process.env.BETTER_AUTH_SECRET,
  database: db,
  trustedOrigins: [
    PUBLIC_URL,
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    ...(process.env.TRUSTED_ORIGINS ?? "").split(",").map((o) => o.trim()).filter(Boolean),
  ],
  emailAndPassword: {
    enabled: true,
    minPasswordLength: 8,
    autoSignIn: true,
  },
  rateLimit: { enabled: true, window: 60, max: 100 },
  advanced: {
    database: {
      generateId: ({ model }) => (model === "user" ? `usr_${randomId()}` : randomId(32)),
    },
  },
  databaseHooks: {
    user: {
      create: {
        // Emails listed in ADMIN_EMAILS become admins when they sign up.
        before: async (user) => {
          if (ADMIN_EMAILS.includes(String(user.email).toLowerCase())) {
            return { data: { ...user, role: "admin" } };
          }
        },
      },
    },
  },
  // bearer: the Chrome extension signs in with "Authorization: Bearer <session token>"
  // instead of cookies (it gets the token from the website's /extension/connect page).
  plugins: [admin({ defaultRole: "user", adminRoles: ["admin"] }), bearer()],
});

const { toBeCreated, toBeAdded, runMigrations } = await getMigrations(auth.options);
if (toBeCreated.length || toBeAdded.length) {
  await runMigrations();
  console.log(`[auth] migrated tables: ${[...toBeCreated, ...toBeAdded].map((t) => t.table).join(", ")}`);
}

const handler = toNodeHandler(auth);
createServer((req, res) => {
  if (req.url === "/health") {
    res.writeHead(200, { "content-type": "application/json" }).end('{"ok":true}');
    return;
  }
  handler(req, res);
}).listen(PORT, "127.0.0.1", () => {
  console.log(`[auth] listening on http://127.0.0.1:${PORT} (db: ${DB_PATH})`);
  if (!process.env.BETTER_AUTH_SECRET) console.warn("[auth] BETTER_AUTH_SECRET is not set; run `npm run init-env` at the repo root.");
  if (!ADMIN_EMAILS.length) console.warn("[auth] ADMIN_EMAILS is empty; promote an admin with `npm --prefix auth run make-admin -- you@example.com`.");
});
