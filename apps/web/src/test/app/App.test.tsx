// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { notify } from "@/core/notify";
import { App } from "@/app/App";

vi.mock("@/core/notify", () => ({
  errorMessage: (error: unknown) => (error instanceof Error ? error.message : String(error)),
  notify: { error: vi.fn(), warning: vi.fn(), info: vi.fn(), success: vi.fn() },
}));

vi.mock("@/scene/StoreScene", () => ({
  StoreScene: () => null,
}));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test("reads apps/api by default, and shows an API failure without crashing", async () => {
  const fetchMock = vi.fn(async (_url: RequestInfo | URL): Promise<Response> => {
    throw new TypeError("offline");
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<App />);

  await waitFor(() => {
    expect(notify.error).toHaveBeenCalledWith(
      "The API request failed.",
      expect.objectContaining({ message: "The API is unreachable." }),
    );
  });
  const paths = fetchMock.mock.calls.map(([url]) => new URL(String(url)).pathname);
  expect(paths).toContain("/store");
  expect(paths).toContain("/health");
  // Promotions are read when their lens opens, not on load. Only today's revenue is read on
  // load, for the KPI strip; the longer windows wait for the Revenue lens.
  expect(paths).not.toContain("/promotions");
  const revenueReads = fetchMock.mock.calls.map(([url]) => new URL(String(url))).filter((url) => url.pathname === "/revenue");
  // apps/api takes `hourly` for today (#344); the lens's own "today" would be refused with a 422.
  expect(revenueReads.map((url) => url.searchParams.get("period"))).toEqual(["hourly"]);
  expect(screen.getByRole("heading", { name: "Agent Activity" })).toBeTruthy();
  expect(screen.getByRole("main")).toBeTruthy();
  expect(screen.getByRole("textbox", { name: "SKU" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Look up inventory" })).toBeTruthy();
});

test("shows the lens switch with all three lenses, Operations first", () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 404 })));
  render(<App />);
  expect(screen.getByRole("radiogroup", { name: "View" })).toBeTruthy();
  expect(screen.getByRole("radio", { name: "Operations" }).getAttribute("aria-checked")).toBe("true");
  expect(screen.getByRole("radio", { name: "Revenue" })).toBeTruthy();
  expect(screen.getByRole("radio", { name: "Promotions" })).toBeTruthy();
});

test("calls no API under ?twin=demo", async () => {
  const fetchMock = vi.fn(async () => new Response("{}", { status: 404 }));
  vi.stubGlobal("fetch", fetchMock);
  window.history.replaceState(null, "", "/?twin=demo");
  // The page picks its twin source when it loads, so load it again under the demo URL.
  vi.resetModules();
  const { App: DemoApp } = await import("@/app/App");

  render(<DemoApp />);

  expect(await screen.findByRole("heading", { name: "Agent Activity" })).toBeTruthy();
  await new Promise((resolve) => setTimeout(resolve, 50));
  expect(fetchMock).not.toHaveBeenCalled();
  window.history.replaceState(null, "", "/");
});

test("on /live, even with ?twin=demo, reads apps/api and says it failed, never falling back to the demo", async () => {
  const fetchMock = vi.fn(async (_url: RequestInfo | URL): Promise<Response> => {
    throw new TypeError("offline");
  });
  vi.stubGlobal("fetch", fetchMock);
  window.history.replaceState(null, "", "/live?twin=demo");
  // The page picks its twin source when it loads, so load it again under this URL.
  vi.resetModules();
  const { App: LiveApp } = await import("@/app/App");
  const { useTwinStore } = await import("@/state/twin.store");
  const { useAnomalyStore } = await import("@/state/anomaly.store");

  render(<LiveApp />);

  expect(await screen.findByText("Could not load the Digital Twin")).toBeTruthy();
  const paths = fetchMock.mock.calls.map(([url]) => new URL(String(url)).pathname);
  expect(paths).toContain("/store");
  expect(paths).toContain("/revenue");
  // Live, and only Live: no demo label, banner, store, simulation or anomalies stand in.
  expect(screen.getByText("Live data")).toBeTruthy();
  expect(screen.queryByText("Demo data")).toBeNull();
  expect(screen.queryByRole("note", { name: "Demo data notice" })).toBeNull();
  expect(useTwinStore.getState().live).toBeNull();
  expect(useTwinStore.getState().simulation).toBeNull();
  expect(useAnomalyStore.getState().anomalies).toEqual([]);
  window.history.replaceState(null, "", "/");
});

test("on /demo, labels the store as demo data and calls no API", async () => {
  const fetchMock = vi.fn(async () => new Response("{}", { status: 404 }));
  vi.stubGlobal("fetch", fetchMock);
  window.history.replaceState(null, "", "/demo");
  vi.resetModules();
  const { App: DemoApp } = await import("@/app/App");
  const { useTwinStore } = await import("@/state/twin.store");

  render(<DemoApp />);

  expect(await screen.findByText("Demo data")).toBeTruthy();
  expect(screen.queryByText("Live data")).toBeNull();
  await waitFor(() => expect(useTwinStore.getState().live?.products.length).toBeGreaterThan(0));
  await new Promise((resolve) => setTimeout(resolve, 50));
  expect(fetchMock).not.toHaveBeenCalled();
  window.history.replaceState(null, "", "/");
});
