import { describe, expect, it } from "vitest";
import { contextRevision, isNewerVersion } from "@/core/api/version";

describe("context versions", () => {
  it("reads the revision from both formats in the docs", () => {
    expect(contextRevision("store-001:v23871")).toBe(23871);
    expect(contextRevision("v1")).toBe(1);
    expect(contextRevision("draft")).toBeNull();
  });

  it("compares by revision, not as text", () => {
    expect(isNewerVersion("store-001:v10", "store-001:v9")).toBe(true);
    expect(isNewerVersion("store-001:v9", "store-001:v10")).toBe(false);
    expect(isNewerVersion("store-001:v9", "store-001:v9")).toBe(false);
    expect(isNewerVersion("store-001:v1", null)).toBe(true);
  });
});
