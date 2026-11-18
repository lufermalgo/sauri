import net from "node:net";
import { afterEach, describe, expect, it } from "vitest";
import { busyPorts, isPortFree, LLAMA_PORT, portPlan, portsToCheck } from "./ports.ts";

const servers: net.Server[] = [];

function listen(host: string): Promise<number> {
  return new Promise((resolve) => {
    const server = net.createServer();
    servers.push(server);
    server.listen(0, host, () => resolve((server.address() as net.AddressInfo).port));
  });
}

afterEach(async () => {
  await Promise.all(servers.splice(0).map((server) => new Promise((resolve) => server.close(resolve))));
});

describe("ports", () => {
  it("plans 8000–8005 by default", () => {
    expect(portPlan()).toEqual({ api: 8000, asr: 8001, diar: 8002, llm: 8003, llama: 8004, host: 8005 });
    expect(portsToCheck(portPlan())).toEqual([8000, 8001, 8002, 8003, 8004, 8005]);
  });

  it("moves the block for development without claiming the fixed llama-server port", () => {
    const plan = portPlan(18100);
    expect(plan).toEqual({ api: 18100, asr: 18101, diar: 18102, llm: 18103, llama: LLAMA_PORT, host: 18105 });
    expect(portsToCheck(plan)).toEqual([18100, 18101, 18102, 18103, 18105]);
  });

  it.each([0, 80, 65535, 8000.5, Number.NaN])("rejects API port %s", (port) => {
    expect(() => portPlan(port)).toThrow(RangeError);
  });

  it("reports a port taken on loopback", async () => {
    const port = await listen("127.0.0.1");
    expect(await isPortFree(port)).toBe(false);
  });

  it("reports a port taken by a wildcard listener", async () => {
    const port = await listen("0.0.0.0");
    expect(await isPortFree(port)).toBe(false);
  });

  it("lists exactly the busy ports", async () => {
    const taken = await listen("127.0.0.1");
    const free = await listen("127.0.0.1");
    await new Promise((resolve) => servers.pop()?.close(resolve));
    expect(await busyPorts([taken, free])).toEqual([taken]);
  });
});
