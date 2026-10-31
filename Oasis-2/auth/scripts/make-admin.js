// Promote an existing user to admin: npm --prefix auth run make-admin -- you@example.com
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import Database from "better-sqlite3";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
if (existsSync(resolve(root, ".env"))) process.loadEnvFile(resolve(root, ".env"));

const email = process.argv[2]?.trim().toLowerCase();
if (!email) {
  console.error("usage: npm --prefix auth run make-admin -- <email>");
  process.exit(1);
}

const db = new Database(resolve(root, process.env.DATABASE_PATH ?? "../database/agentready.sqlite"));
const result = db.prepare(`UPDATE "user" SET role = 'admin' WHERE lower(email) = ?`).run(email);
if (result.changes === 0) {
  console.error(`No user with email ${email}. Sign up first, then run this again.`);
  process.exit(1);
}
console.log(`${email} is now an admin. Sign out and back in to refresh the session.`);
