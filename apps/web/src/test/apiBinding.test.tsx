import ReactThreeTestRenderer from "@react-three/test-renderer";
import { afterEach, describe, expect, it, vi } from "vitest";
import seed from "../../../../data/schemas/store-state.example.json";
import { createClient } from "@/core/api/client";
import { createApiSource } from "@/core/api/sources/apiSource";
import type { TwinSource } from "@/core/api/sources/TwinSource";
import { useTwinSource } from "@/hooks/twinSource.hook";
import { TwinStoreContents } from "@/scene/StoreScene";
import { useTwinStore } from "@/state/twin.store";
import type { StoreResponse } from "@/types/twin.type";

// Toasts need the HeroUI provider and a DOM; this test only follows the data.
vi.mock("@/core/notify", () => ({
  errorMessage: String,
  notify: { error: vi.fn(), warning: vi.fn(), info: vi.fn(), success: vi.fn() },
}));

type Seed = typeof seed;
const BASE = "http://api.test";
const POLL_MS = 10;

/**
 * apps/api over HTTP, reading the committed seed as `StoreRepository.view()` does:
 * the context version is `<store>:<version>`, and every product carries the store id
 * and the numeric version. `edit` stands in for changing the seed and restarting the API.
 */
function fakeApi() {
  let fixture: Seed = structuredClone(seed);
  const view = (): StoreResponse => ({
    store_id: fixture.store_id,
    context_version: `${fixture.store_id}:${fixture.version}`,
    version: fixture.version,
    products: fixture.products.map((product) => ({
      ...product,
      store_id: fixture.store_id,
      version: Number(fixture.version.slice(1)),
    })),
  });
  const fetch = vi.fn(async (url: RequestInfo | URL) =>
    new URL(String(url)).pathname === "/store"
      ? new Response(JSON.stringify(view()), { headers: { "content-type": "application/json" } })
      : new Response("{}", { status: 404 }),
  );
  return {
    source: (): TwinSource => createApiSource(createClient(BASE, fetch), POLL_MS),
    fetch,
    edit: (change: (fixture: Seed) => Seed) => {
      fixture = change(structuredClone(fixture));
    },
  };
}

function LiveScene({ source }: { source: TwinSource }) {
  useTwinSource(source);
  return <TwinStoreContents interactive={false} />;
}

type Renderer = Awaited<ReturnType<typeof ReactThreeTestRenderer.create>>;

/** Lets polls and renders run until `check` holds. */
async function until(check: () => boolean, timeoutMs = 2000) {
  const start = Date.now();
  while (!check()) {
    if (Date.now() - start > timeoutMs) throw new Error("timed out waiting for the scene");
    await ReactThreeTestRenderer.act(async () => {
      await new Promise((resolve) => setTimeout(resolve, POLL_MS));
    });
  }
}

/** Opens the page on a fresh twin store, as a reload does, with a new source. */
async function openPage(source: TwinSource): Promise<Renderer> {
  useTwinStore.setState(useTwinStore.getInitialState(), true);
  const renderer = await ReactThreeTestRenderer.create(<LiveScene source={source} />);
  await until(() => useTwinStore.getState().status === "ready");
  return renderer;
}

/** Where P001 is drawn and what it carries, as the scene graph shows it. */
function p001(renderer: Renderer) {
  const product = renderer.scene.instance.getObjectByName("P001");
  if (!product) return undefined;
  const slot = product.parent!;
  return { slot: slot.name, shelf: slot.parent!.name, ...product.userData };
}

describe("P001 bound to apps/api over HTTP", () => {
  let renderer: Renderer | undefined;

  afterEach(async () => {
    await renderer?.unmount();
    renderer = undefined;
  });

  it("draws the seed, follows a seed change, and a reload rebuilds the same state", async () => {
    const api = fakeApi();
    renderer = await openPage(api.source());
    expect(p001(renderer)).toMatchObject({
      entityId: "P001",
      slot: "A01-S01",
      shelf: "A01",
      facings: 3,
      shelfQuantity: 8,
      backroomQuantity: 42,
      version: 1,
    });

    // Change P001 in the seed and bump its version, then restart the API.
    api.edit((fixture) => ({
      ...fixture,
      version: "v2",
      products: fixture.products.map((product) =>
        product.sku === "P001" ? { ...product, slot_id: "A01-S02", facings: 4, shelf_quantity: 12 } : product,
      ),
    }));
    const moved = { slot: "A01-S02", shelf: "A01", facings: 4, shelfQuantity: 12, backroomQuantity: 42, version: 2 };
    await until(() => p001(renderer!)?.slot === "A01-S02");
    expect(p001(renderer)).toMatchObject(moved);
    expect(useTwinStore.getState().live?.context_version).toBe("store-001:v2");

    // Reload: nothing survives in the page; the state comes back from the API.
    await renderer.unmount();
    const callsAfterUnmount = api.fetch.mock.calls.length;
    await new Promise((resolve) => setTimeout(resolve, POLL_MS * 5));
    expect(api.fetch.mock.calls.length).toBe(callsAfterUnmount);

    renderer = await openPage(api.source());
    expect(p001(renderer)).toMatchObject(moved);
  });

  it("only ever reads from the API", async () => {
    const api = fakeApi();
    renderer = await openPage(api.source());
    await until(() => api.fetch.mock.calls.length >= 3);
    for (const [url, init] of api.fetch.mock.calls as unknown as [RequestInfo | URL, RequestInit | undefined][]) {
      expect(new URL(String(url)).pathname).toBe("/store");
      expect(init?.method ?? "GET").toBe("GET");
    }
  });
});
