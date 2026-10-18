import { afterEach, describe, expect, it, vi } from "vitest";
import { demoRequested } from "@/core/twin/demoMode";

const url = (path: string) => {
  const parsed = new URL(path, "https://retailtwin.example");
  return { pathname: parsed.pathname, search: parsed.search };
};

afterEach(() => vi.unstubAllEnvs());

describe("demoRequested", () => {
  it("asks for the demo on /demo and ?twin=demo, never on /live or another ?twin=", () => {
    expect(demoRequested(url("/demo"))).toBe(true);
    expect(demoRequested(url("/?twin=demo"))).toBe(true);
    // /live is authoritative — ?twin= never overrides it
    expect(demoRequested(url("/live?twin=demo"))).toBe(false);
    expect(demoRequested(url("/live"))).toBe(false);
    expect(demoRequested(url("/demo?twin=fixture"))).toBe(false);
    expect(demoRequested(url("/"))).toBe(false);
  });

  it("asks for the demo on the bare / of a hosted demo build only", () => {
    vi.stubEnv("VITE_ALLOW_DEMO", "true");
    expect(demoRequested(url("/"))).toBe(true);
    expect(demoRequested(url("/live"))).toBe(false);
    expect(demoRequested(url("/?twin=memory"))).toBe(false);
    expect(demoRequested(url("/unknown"))).toBe(false);
  });
});
