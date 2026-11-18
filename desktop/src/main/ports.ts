// Fixed loopback ports (Requirement 3.6) and the check that none is taken before anything starts (3.7).
import net from "node:net";

export const DEFAULT_API_PORT = 8000;
/** llama-server's port is fixed inside the LLM engine (`llm-engine/native_main.py`). */
export const LLAMA_PORT = 8004;

export interface PortPlan {
  api: number;
  asr: number;
  diar: number;
  llm: number;
  llama: number;
  host: number;
}

/** API on `apiPort` and the engines right after it: 8000–8005 by default. */
export function portPlan(apiPort = DEFAULT_API_PORT): PortPlan {
  if (!Number.isInteger(apiPort) || apiPort < 1024 || apiPort > 65530) throw new RangeError("invalid_api_port");
  return { api: apiPort, asr: apiPort + 1, diar: apiPort + 2, llm: apiPort + 3, llama: LLAMA_PORT, host: apiPort + 5 };
}

/**
 * Ports Sauri must own before starting. llama-server only joins when it sits inside the plan's range: on a
 * development plan (another API port) port 8004 belongs to the owner's own engines and is not ours to claim.
 */
export function portsToCheck(plan: PortPlan): number[] {
  const ports = [plan.api, plan.asr, plan.diar, plan.llm, plan.host];
  if (plan.llama > plan.api && plan.llama < plan.host) ports.push(plan.llama);
  return ports.sort((a, b) => a - b);
}

function canBind(port: number, host: string): Promise<boolean> {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once("error", () => resolve(false));
    server.listen({ port, host, exclusive: true }, () => server.close(() => resolve(true)));
  });
}

/** Something answers on the port: a wildcard listener (`*:port`) does not stop a loopback bind on macOS. */
function accepting(port: number, host: string): Promise<boolean> {
  return new Promise((resolve) => {
    const socket = net.connect({ port, host });
    const done = (value: boolean) => {
      socket.destroy();
      resolve(value);
    };
    socket.setTimeout(1000, () => done(true));
    socket.once("connect", () => done(true));
    socket.once("error", () => done(false));
  });
}

export async function isPortFree(port: number, host = "127.0.0.1"): Promise<boolean> {
  return !(await accepting(port, host)) && (await canBind(port, host));
}

export async function busyPorts(ports: number[], host = "127.0.0.1"): Promise<number[]> {
  const free = await Promise.all(ports.map((port) => isPortFree(port, host)));
  return ports.filter((_, index) => !free[index]);
}
