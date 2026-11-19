// Loopback ports (Requirement 3.6) and the check that none is taken before anything starts (3.7).
import net from "node:net";

/**
 * Base of the installed app's block (41750–41755): uncommon, so it does not collide with the usual development
 * ports (8000 belongs to the Docker stack), and below macOS's ephemeral range (49152–65535), so the system never
 * hands one of these ports to an outgoing connection.
 */
export const DEFAULT_API_PORT = 41750;

export interface PortPlan {
  api: number;
  asr: number;
  diar: number;
  llm: number;
  llama: number;
  host: number;
}

/** Every port derives from the API's: the engines, llama-server and the host service follow it (+1 to +5). */
export function portPlan(apiPort = DEFAULT_API_PORT): PortPlan {
  if (!Number.isInteger(apiPort) || apiPort < 1024 || apiPort > 65530) throw new RangeError("invalid_api_port");
  return { api: apiPort, asr: apiPort + 1, diar: apiPort + 2, llm: apiPort + 3, llama: apiPort + 4, host: apiPort + 5 };
}

/** Ports Sauri must own before starting: the whole block. */
export function portsToCheck(plan: PortPlan): number[] {
  return [plan.api, plan.asr, plan.diar, plan.llm, plan.llama, plan.host].sort((a, b) => a - b);
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
