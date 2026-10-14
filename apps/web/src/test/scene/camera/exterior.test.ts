import { describe, expect, it } from "vitest";
import { EXTERIOR_VIEW, MAX_DISTANCE_FACTOR } from "@/constants/camera.constant";
import { exteriorLevel } from "@/scene/camera/exterior";

/** Zoom at `times` the distance that fits the store, with the cap `useFitCamera` sets. */
const zoom = (times: number, fitted = 20) => ({ distance: fitted * times, maxDistance: fitted * MAX_DISTANCE_FACTOR });

describe("exteriorLevel", () => {
  it("leaves the store open at the fitted view and closer", () => {
    expect(exteriorLevel(zoom(1))).toBe(0);
    expect(exteriorLevel(zoom(0.3))).toBe(0);
    expect(exteriorLevel(zoom(EXTERIOR_VIEW.from))).toBe(0);
  });

  it("closes it up fully from the far end of the range out to the zoom cap", () => {
    expect(exteriorLevel(zoom(EXTERIOR_VIEW.to))).toBe(1);
    expect(exteriorLevel(zoom(MAX_DISTANCE_FACTOR))).toBe(1);
  });

  it("eases in between, rising with the distance", () => {
    const mid = exteriorLevel(zoom((EXTERIOR_VIEW.from + EXTERIOR_VIEW.to) / 2));
    expect(mid).toBeCloseTo(0.5);
    expect(exteriorLevel(zoom(EXTERIOR_VIEW.from + 0.05))).toBeLessThan(mid);
  });

  it("stays open without a zoom cap", () => {
    expect(exteriorLevel({ distance: 50, maxDistance: Infinity })).toBe(0);
    expect(exteriorLevel({ distance: 50, maxDistance: 0 })).toBe(0);
  });

  it("does not depend on the window size, only on the zoom against the fit", () => {
    expect(exteriorLevel(zoom(1.5, 12))).toBeCloseTo(exteriorLevel(zoom(1.5, 40)));
  });
});
