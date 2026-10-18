// @vitest-environment jsdom
import { afterEach, expect, test, vi } from "vitest";
import { ApiError, createClient } from "@/core/api/client";

const review = { base_context_version: "store-001:v1", proposal_context_version: "store-001:v1-sim" };

function at(path: string) {
  window.history.replaceState(null, "", path);
}

afterEach(() => {
  vi.unstubAllEnvs();
  at("/");
});

test("the demo never writes to apps/api, even through a shared client", async () => {
  const fetchImpl = vi.fn(async () => new Response("{}", { status: 200 }));
  const client = createClient("https://api.example", fetchImpl);

  for (const path of ["/demo", "/?twin=demo"]) {
    at(path);
    await expect(client.reviewSimulation("sim-1", "approve", review)).rejects.toMatchObject({ code: "demo_read_only" });
  }
  // A hosted demo build: the bare URL is the demo too.
  vi.stubEnv("DEV", false);
  vi.stubEnv("VITE_ALLOW_DEMO", "true");
  at("/");
  await expect(client.reviewSimulation("sim-1", "reject", review)).rejects.toBeInstanceOf(ApiError);
  expect(fetchImpl).not.toHaveBeenCalled();

  // Reads still go out.
  await client.health();
  expect(fetchImpl).toHaveBeenCalledTimes(1);
});

test("the live twin of a demo build still posts its reviews", async () => {
  vi.stubEnv("DEV", false);
  vi.stubEnv("VITE_ALLOW_DEMO", "true");
  at("/live");
  const fetchImpl = vi.fn(async () => new Response("{}", { status: 200 }));
  await createClient("https://api.example", fetchImpl).reviewSimulation("sim-1", "approve", review);
  expect(fetchImpl).toHaveBeenCalledWith(
    "https://api.example/simulations/sim-1/approve",
    expect.objectContaining({ method: "POST" }),
  );
});
