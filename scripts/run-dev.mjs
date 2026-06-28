/**
 * Run backend + frontend together. No concurrently, no npm.ps1 needed.
 * Usage:  node scripts/run-dev.mjs
 */
import { execSync, spawn } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const BACKEND_PORT = 8001;
const FRONTEND_PORT = 5173;
const npm = process.platform === "win32" ? "npm.cmd" : "npm";

function killPort(port) {
  try {
    if (process.platform === "win32") {
      const out = execSync("netstat -ano", { encoding: "utf8", stdio: ["pipe", "pipe", "ignore"] });
      const pids = new Set();
      for (const line of out.split(/\r?\n/)) {
        if (!line.includes("LISTENING")) continue;
        if (!line.includes(`:${port} `)) continue;
        const pid = line.trim().split(/\s+/).pop();
        if (pid && /^\d+$/.test(pid) && pid !== "0") pids.add(pid);
      }
      for (const pid of pids) {
        try {
          execSync(`taskkill /F /PID ${pid}`, { stdio: "ignore" });
          console.log(`[setup] Freed port ${port} (was PID ${pid})`);
        } catch {
          /* already gone */
        }
      }
    } else {
      execSync(`lsof -ti :${port} | xargs -r kill -9`, { stdio: "ignore" });
    }
  } catch {
    /* nothing listening */
  }
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

console.log(`[setup] Clearing ports ${BACKEND_PORT} / ${FRONTEND_PORT} …`);
killPort(BACKEND_PORT);
killPort(FRONTEND_PORT);
await sleep(800);

console.log(`Starting backend (:${BACKEND_PORT}) + frontend (:${FRONTEND_PORT}) …`);
console.log(`Wait ~30s for geo warm-up, then open http://127.0.0.1:${FRONTEND_PORT}`);
console.log("Press Ctrl+C to stop both.\n");

const backend = spawn(process.execPath, ["scripts/run-backend.mjs"], {
  cwd: root,
  stdio: "inherit",
});

const frontend = spawn(
  npm,
  ["run", "dev", "--", "--host", "127.0.0.1", "--port", String(FRONTEND_PORT), "--strictPort"],
  {
    cwd: join(root, "frontend"),
    stdio: "inherit",
    shell: process.platform === "win32",
  },
);

let stopping = false;
function shutdown(code = 0) {
  if (stopping) return;
  stopping = true;
  backend.kill("SIGTERM");
  frontend.kill("SIGTERM");
  setTimeout(() => process.exit(code), 500);
}

process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));
backend.on("exit", (code) => {
  if (!stopping) {
    console.log(`[dev] backend exited (${code ?? 0}) — stopping frontend too`);
    shutdown(code ?? 1);
  }
});
frontend.on("exit", (code) => {
  if (!stopping) {
    console.log(`[dev] frontend exited (${code ?? 0}) — stopping backend too`);
    shutdown(code ?? 1);
  }
});
