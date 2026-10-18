// @vitest-environment jsdom
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TwinDemoBanner } from "@/components/layout/TwinDemoBanner";
import { TECH_STACK, TwinFooter } from "@/components/layout/TwinFooter";
import { TwinHeader } from "@/components/layout/TwinHeader";
import { VIEW_MODE } from "@/enums/ui.enum";
import { demoStoreState } from "@/fixtures/demo/store";
import { useTwinStore } from "@/state/twin.store";
import { useUiStore } from "@/state/ui.store";

const live = demoStoreState();

function at(path: string) {
  window.history.replaceState(null, "", path);
}

beforeEach(() => {
  useTwinStore.setState({ ...useTwinStore.getInitialState() }, true);
  useUiStore.getState().setViewMode(VIEW_MODE.Live);
});

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
  at("/");
});

describe("TwinHeader", () => {
  it("says what RetailTwin is, the store, and LIVE or SIMULATION", () => {
    useTwinStore.setState({ live });
    render(<TwinHeader />);
    const header = screen.getByRole("banner");
    expect(header.textContent).toContain("RetailTwin AI");
    expect(header.textContent).toContain("Autonomous Store Intelligence");
    expect(screen.getByText(live.store_id)).toBeTruthy();
    expect(screen.getByText("LIVE")).toBeTruthy();

    act(() => {
      useTwinStore.setState({ simulation: { simulation_id: "sim-1" } as never });
      useUiStore.getState().setViewMode(VIEW_MODE.Simulation);
    });
    expect(screen.getByText("SIMULATION")).toBeTruthy();
  });

  it("shows — before the Live Twin has a store", () => {
    render(<TwinHeader />);
    expect(screen.getByTitle("The store the Live Twin reports").textContent).toBe("—");
  });

  it("links the demo and the live twin to each other where the demo is allowed", () => {
    at("/demo");
    const { unmount } = render(<TwinHeader />);
    expect(screen.getByText("Demo data")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open the live twin" }).getAttribute("href")).toBe("/live");
    unmount();

    at("/live");
    render(<TwinHeader />);
    expect(screen.queryByText("Demo data")).toBeNull();
    expect(screen.getByText("Live data").dataset.source).toBe("live");
    expect(screen.getByRole("link", { name: "Open the demo" }).getAttribute("href")).toBe("/demo");
  });

  it("never carries ?twin= across: /live is plain and stays Live, whatever the query", () => {
    at("/?twin=demo&product=P001");
    const { unmount } = render(<TwinHeader />);
    expect(screen.getByText("Demo data")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open the live twin" }).getAttribute("href")).toBe("/live");
    unmount();

    at("/live?twin=demo");
    render(<TwinHeader />);
    expect(screen.queryByText("Demo data")).toBeNull();
    expect(screen.getByText("Live data").dataset.source).toBe("live");
    expect(screen.getByRole("link", { name: "Open the demo" }).getAttribute("href")).toBe("/demo");
  });

  it("has no demo link in a production build without the demo", () => {
    vi.stubEnv("DEV", false);
    render(<TwinHeader />);
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("tells demo data from live data, and claims neither for a dev twin", () => {
    at("/demo");
    const { unmount } = render(<TwinHeader />);
    expect(screen.getByText("Demo data").dataset.source).toBe("demo");
    expect(screen.queryByText("Live data")).toBeNull();
    unmount();

    at("/?twin=fixture");
    render(<TwinHeader />);
    expect(screen.queryByText("Demo data")).toBeNull();
    expect(screen.queryByText("Live data")).toBeNull();
  });
});

describe("TwinDemoBanner", () => {
  it("marks every demo route as synthetic, not live store telemetry, with a link to /live", () => {
    for (const path of ["/demo", "/?twin=demo", "/?product=P001&twin=demo"]) {
      at(path);
      const { unmount } = render(<TwinDemoBanner />);
      const note = screen.getByRole("note", { name: "Demo data notice" });
      expect(note.textContent).toContain("DEMO");
      expect(note.textContent).toContain("not live store telemetry");
      expect(screen.getByRole("link", { name: "Open the live twin" }).getAttribute("href")).toBe("/live");
      unmount();
    }
  });

  it("marks the bare URL of a hosted demo build, which opens the demo", () => {
    vi.stubEnv("DEV", false);
    vi.stubEnv("VITE_ALLOW_DEMO", "true");
    at("/");
    render(<TwinDemoBanner />);
    expect(screen.getByRole("note", { name: "Demo data notice" }).textContent).toContain("not live store telemetry");
  });

  it("is not on the live twin, on a dev twin, or in a production build without the demo", () => {
    vi.stubEnv("VITE_ALLOW_DEMO", "true");
    for (const path of ["/live", "/live?twin=demo", "/?twin=fixture"]) {
      at(path);
      const { unmount } = render(<TwinDemoBanner />);
      expect(screen.queryByRole("note")).toBeNull();
      unmount();
    }
    vi.unstubAllEnvs();
    vi.stubEnv("DEV", false);
    at("/demo");
    render(<TwinDemoBanner />);
    expect(screen.queryByRole("note")).toBeNull();
  });
});

describe("TwinFooter", () => {
  it("lists the Google Cloud stack and follows the Live Twin's context_version", () => {
    useTwinStore.setState({ live });
    render(<TwinFooter />);
    expect(screen.getByRole("contentinfo").textContent).toContain("Gemini on Vertex AI · Cloud Run · Firestore · BigQuery");
    expect(TECH_STACK).toHaveLength(4);
    expect(screen.getByTestId("footer-context").textContent).toBe(`Context ${live.context_version}`);

    // An execution moves Live on: the footer shows the new version.
    act(() => useTwinStore.setState({ live: { ...live, context_version: "store-001:v2" } }));
    expect(screen.getByTestId("footer-context").textContent).toBe("Context store-001:v2");
    expect(screen.getByTestId("footer-build").textContent).toMatch(/^Build \S+/);
  });

  it("shows — before the Live Twin has loaded", () => {
    render(<TwinFooter />);
    expect(screen.getByTestId("footer-context").textContent).toBe("Context —");
  });
});
