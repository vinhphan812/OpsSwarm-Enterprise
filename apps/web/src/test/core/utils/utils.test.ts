import { describe, expect, it } from "vitest";
import { groupBy } from "@/core/utils/collections";
import { padId } from "@/core/utils/ids";
import { mulberry32, pick } from "@/core/utils/random";

describe("padId", () => {
  it("pads the number to the given width", () => {
    expect(padId("S", 3)).toBe("S03");
    expect(padId("P", 42, 3)).toBe("P042");
    expect(padId("A", 123)).toBe("A123");
  });
});

describe("groupBy", () => {
  it("buckets by key and keeps order", () => {
    const groups = groupBy(["a1", "b1", "a2"], (s) => s[0]);
    expect([...groups.keys()]).toEqual(["a", "b"]);
    expect(groups.get("a")).toEqual(["a1", "a2"]);
  });
});

describe("seeded random", () => {
  it("repeats for the same seed and differs across seeds", () => {
    const run = (seed: number) => Array.from({ length: 5 }, mulberry32(seed));
    expect(run(1)).toEqual(run(1));
    expect(run(1)).not.toEqual(run(2));
  });

  it("picks only from the list", () => {
    const random = mulberry32(1);
    for (let i = 0; i < 50; i += 1) expect(["x", "y", "z"]).toContain(pick(random, ["x", "y", "z"]));
  });
});
