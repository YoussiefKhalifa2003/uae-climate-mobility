/**
 * Start the FastAPI backend (uvicorn on :8001).
 * Used by `npm run dev` — no watchdog, no restarts, just run until Ctrl+C.
 */
import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const backendDir = join(root, "backend");
const py =
  process.platform === "win32"
    ? join(backendDir, ".venv", "Scripts", "python.exe")
    : join(backendDir, ".venv", "bin", "python");

if (!existsSync(py)) {
  console.error(
    "[backend] Missing backend/.venv — run once:\n" +
      "  cd backend && python -m venv .venv && .venv\\Scripts\\pip install -r requirements.txt",
  );
  process.exit(1);
}

const env = { ...process.env };
const dotenv = join(root, ".env");
if (existsSync(dotenv)) {
  for (const line of readFileSync(dotenv, "utf8").split(/\r?\n/)) {
    const t = line.trim();
    if (!t || t.startsWith("#") || !t.includes("=")) continue;
    const i = t.indexOf("=");
    const k = t.slice(0, i).trim();
    const v = t.slice(i + 1).trim().replace(/^["']|["']$/g, "");
    if (!(k in env)) env[k] = v;
  }
}

console.log("[backend] http://127.0.0.1:8001  (wait ~30s for geo warm-up)");

const child = spawn(
  py,
  ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8001"],
  { cwd: backendDir, env, stdio: "inherit" },
);

child.on("exit", (code) => process.exit(code ?? 1));
for (const sig of ["SIGINT", "SIGTERM"]) {
  process.on(sig, () => child.kill(sig));
}
