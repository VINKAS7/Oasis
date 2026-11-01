// Gives the local API (port 8000) the public address in backend/.env PUBLIC_API_URL through ngrok,
// so ChatGPT and Claude can reach the MCP servers (/mcp and /mcp/b/<business_id>).
// One-time setup: a free ngrok account, its free dev domain, `ngrok config add-authtoken <token>`.
import { spawn, spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const env = readFileSync(resolve(root, "backend", ".env"), "utf8");
const url = (env.match(/^PUBLIC_API_URL=(.*)$/m)?.[1] ?? "").trim();
const host = URL.canParse(url) ? new URL(url).host : "";

if (!host || /^(localhost|127\.0\.0\.1)(:|$)/.test(host)) {
  console.error(
    "PUBLIC_API_URL in backend/.env is not a public address.\n" +
      "Claim your free dev domain at https://dashboard.ngrok.com/domains and set\n" +
      "  PUBLIC_API_URL=https://<your-domain>.ngrok-free.dev",
  );
  process.exit(1);
}

const win = process.platform === "win32";
if (spawnSync(win ? "where" : "which", ["ngrok"], { stdio: "ignore" }).status !== 0) {
  console.error("ngrok is not installed. Windows: winget install ngrok.ngrok   macOS: brew install ngrok   then: ngrok config add-authtoken <token>");
  process.exit(1);
}

console.log(`Tunnel: ${url} -> http://localhost:8000`);
console.log(`MCP directory: ${url}/mcp   ·   one business: ${url}/mcp/b/<business_id>`);
const ngrok = spawn("ngrok", ["http", `--url=${host}`, "127.0.0.1:8000", "--log", "stdout", "--log-level", "warn"], { stdio: "inherit", shell: win });
ngrok.on("exit", (code) => process.exit(code ?? 0));
