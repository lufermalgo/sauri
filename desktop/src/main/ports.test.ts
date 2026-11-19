import net from "node:net";
import { afterEach, describe, expect, it } from "vitest";
import { busyPorts, DEFAULT_API_PORT, isPortFree, portPlan, portsToCheck } from "./ports.ts";

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
  it("plans the uncommon 41750–41755 block by default, below macOS's ephemeral range", () => {
    expect(DEFAULT_API_PORT).toBe(41750);
    expect(portPlan()).toEqual({ api: 41750, asr: 41751, diar: 41752, llm: 41753, llama: 41754, host: 41755 });
    expect(portsToCheck(portPlan())).toEqual([41750, 41751, 41752, 41753, 41754, 41755]);
    expect(Math.max(...portsToCheck(portPlan()))).toBeLessThan(49152);
  });

  it("derives every port, llama-server included, from the API port", () => {
    const plan = portPlan(18100);
    expect(plan).toEqual({ api: 18100, asr: 18101, diar: 18102, llm: 18103, llama: 18104, host: 18105 });
    expect(portsToCheck(plan)).toEqual([18100, 18101, 18102, 18103, 18104, 18105]);
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
