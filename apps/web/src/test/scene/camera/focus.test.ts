import { Vector3 } from "three";
import { describe, expect, it } from "vitest";
import { MIN_CAMERA_DISTANCE } from "@/constants/camera.constant";
import { STORE_FLOOR } from "@/constants/dimensions.constant";
import { fixtureFocus, productFocus } from "@/scene/camera/focus";
import { storeLayout } from "@/scene/layout";
import type { Tuple3 } from "@/types/scene.type";

const distance = (a: Tuple3, b: Tuple3) => new Vector3(...a).distanceTo(new Vector3(...b));

describe("productFocus", () => {
  it("looks at a front-side gondola slot from the front, above it", () => {
    const view = productFocus(storeLayout, "A01", "A01-S01")!;
    const shelf = storeLayout.shelves.find((item) => item.shelfId === "A01")!;
    // A01 faces +Z, so the camera stands on the +Z side of the slot.
    expect(view.target[2]).toBeGreaterThan(shelf.position.z);
    expect(view.position[2]).toBeGreaterThan(view.target[2]);
    expect(view.position[1]).toBeGreaterThan(view.target[1]);
    expect(distance(view.position, view.target)).toBeGreaterThan(MIN_CAMERA_DISTANCE - 1);
  });

  it("goes round to the far side for the far side's slots", () => {
    const view = productFocus(storeLayout, "A01", "A01-S37")!;
    expect(view.position[2]).toBeLessThan(view.target[2]);
  });

  it("looks into equipment from its front", () => {
    // The coolers stand on the right wall facing -X, into the room.
    const view = productFocus(storeLayout, "GDC01", "GDC01-S01")!;
    expect(view.position[0]).toBeLessThan(view.target[0]);
  });

  it("is null for a slot the layout does not have", () => {
    expect(productFocus(storeLayout, "A01", "A01-S99")).toBeNull();
    expect(productFocus(storeLayout, "ZZ9", "ZZ9-S01")).toBeNull();
  });
});

describe("fixtureFocus", () => {
  const inside = ([x, , z]: Tuple3) => Math.abs(x) < STORE_FLOOR.width / 2 && z > -STORE_FLOOR.depth / 2;

  it("looks at wall equipment from inside the room, whatever side the camera was on", () => {
    // GDC02 stands on the right wall facing -X. A camera out past that wall must not stay there.
    const view = fixtureFocus(storeLayout, "GDC02", [12, 5, -2])!;
    const cooler = storeLayout.equipment.find((item) => item.equipmentId === "GDC02")!;
    expect(view.position[0]).toBeLessThan(cooler.position.x);
    expect(inside(view.position)).toBe(true);
    expect(view.position[1]).toBeGreaterThan(view.target[1]);
  });

  it("sees a gondola from the side the camera is on, centered and fitted", () => {
    const shelf = storeLayout.shelves.find((item) => item.shelfId === "B02")!;
    const fromFront = fixtureFocus(storeLayout, "B02", [0, 5, 9])!;
    const fromBack = fixtureFocus(storeLayout, "B02", [0, 5, -4])!;
    expect(fromFront.target[0]).toBeCloseTo(shelf.position.x);
    expect(fromFront.position[2]).toBeGreaterThan(shelf.position.z);
    expect(fromBack.position[2]).toBeLessThan(shelf.position.z);
    expect(distance(fromFront.position, fromFront.target)).toBeGreaterThanOrEqual(MIN_CAMERA_DISTANCE);
  });

  it("keeps every fixture's view inside the walls", () => {
    for (const id of [...storeLayout.shelves.map((s) => s.shelfId), ...storeLayout.equipment.map((e) => e.equipmentId)]) {
      for (const from of [[12, 5, 0], [-12, 5, 0], [0, 5, -12], [0, 5, 12]] as Tuple3[]) {
        expect(inside(fixtureFocus(storeLayout, id, from)!.position), `${id} from ${from}`).toBe(true);
      }
    }
  });

  it("is null for an unknown id", () => {
    expect(fixtureFocus(storeLayout, "NOPE", [0, 5, 9])).toBeNull();
  });
});

describe("productFocus inside the walls", () => {
  it("never puts the camera behind a wall, even for a slot right against one", () => {
    const inside = ([x, , z]: Tuple3) => Math.abs(x) < STORE_FLOOR.width / 2 && z > -STORE_FLOOR.depth / 2;
    for (const holder of [...storeLayout.shelves, ...storeLayout.equipment]) {
      const id = "shelfId" in holder ? holder.shelfId : holder.equipmentId;
      for (const slot of holder.slots) {
        const view = productFocus(storeLayout, id, slot.slotId)!;
        expect(inside(view.position), slot.slotId).toBe(true);
      }
    }
  });
});

describe("line of sight", () => {
  const boxes = () =>
    [...storeLayout.shelves.map((s) => ({ id: s.shelfId, x: s.position.x, z: s.position.z, w: 2.4, d: 0.92, h: 1.8, r: s.rotationY }))];

  /** True when the segment from the camera to the target crosses another gondola. */
  function crossesOtherGondola(view: { position: Tuple3; target: Tuple3 }, own: string) {
    const from = new Vector3(...view.position);
    const to = new Vector3(...view.target);
    for (let i = 1; i < 100; i += 1) {
      const p = from.clone().lerp(to, i / 100);
      for (const b of boxes()) {
        if (b.id === own) continue;
        if (Math.abs(p.x - b.x) < b.w / 2 && Math.abs(p.z - b.z) < b.d / 2 && p.y < b.h) return true;
      }
    }
    return false;
  }

  it("rises over the next gondola to see a bottom slot across a narrow aisle", () => {
    // P001's slot: A01's front bottom deck, facing B01 across the aisle.
    const view = productFocus(storeLayout, "A01", "A01-S01")!;
    expect(crossesOtherGondola(view, "A01")).toBe(false);
    expect(view.position[1]).toBeGreaterThan(1.8);
  });

  it("keeps every gondola slot in sight", () => {
    for (const shelf of storeLayout.shelves) {
      for (const slot of shelf.slots) {
        expect(crossesOtherGondola(productFocus(storeLayout, shelf.shelfId, slot.slotId)!, shelf.shelfId), slot.slotId).toBe(false);
      }
    }
  });
});
