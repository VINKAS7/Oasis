// Creates auth/.env and backend/.env from their examples, filling in fresh secrets.
// Existing files are left alone, so this is safe to run again.
import { copyFileSync, existsSync, readFileSync, writeFileSync } from "node:fs";
import { randomBytes } from "node:crypto";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function init(dir, fill) {
  const env = resolve(root, dir, ".env");
  if (existsSync(env)) return console.log(`${dir}/.env exists, leaving it as is`);
  copyFileSync(resolve(root, dir, ".env.example"), env);
  let text = readFileSync(env, "utf8");
  for (const [key, value] of Object.entries(fill)) text = text.replace(new RegExp(`^${key}=.*$`, "m"), `${key}=${value}`);
  writeFileSync(env, text);
  console.log(`created ${dir}/.env`);
}

init("auth", { BETTER_AUTH_SECRET: randomBytes(32).toString("base64url") });
// Fernet keys are 32 url-safe base64 bytes.
init("backend", { SECRETS_KEY: randomBytes(32).toString("base64url") + "=" });
