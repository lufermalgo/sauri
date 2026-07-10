import { existsSync, readFileSync, unlinkSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PID_FILE = resolve(__dirname, ".backend-pid");

export default async function globalTeardown(): Promise<void> {
  if (!existsSync(PID_FILE)) return;
  const pid = Number(readFileSync(PID_FILE, "utf-8").trim());
  try {
    process.kill(-pid, "SIGTERM");
  } catch {
    try {
      process.kill(pid, "SIGTERM");
    } catch {
      // already gone
    }
  }
  unlinkSync(PID_FILE);
}
