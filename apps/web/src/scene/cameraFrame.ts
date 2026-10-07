import { SHELF } from "./dimensions";
import type { StoreFixture } from "./types";

export const CAMERA_FOV = 45;
export const ORBIT_TARGET: [number, number, number] = [0, 0.8, 0];
/** Offset from the orbit target for the initial view. Y is up. */
export const INITIAL_CAMERA_OFFSET: [number, number, number] = [6, 4.2, 8];
/** High enough that a fitted phone distance is not clamped back into the shelves. */
export const MAX_CAMERA_DISTANCE = 200;

const FRAME_PADDING = 1.2;

export function shelfBoundingRadius(store: StoreFixture): number {
  const [targetX, targetY, targetZ] = ORBIT_TARGET;
  let radius = 0;
  for (const shelf of store.shelves) {
    const xs = [shelf.position.x - SHELF.width / 2, shelf.position.x + SHELF.width / 2];
    const ys = [shelf.position.y, shelf.position.y + SHELF.height];
    const zs = [shelf.position.z - SHELF.depth / 2, shelf.position.z + SHELF.depth / 2];
    for (const x of xs) {
      for (const y of ys) {
        for (const z of zs) {
          radius = Math.max(radius, Math.hypot(x - targetX, y - targetY, z - targetZ));
        }
      }
    }
  }
  return radius * FRAME_PADDING;
}

export function fitDistance(radius: number, aspect: number, fovDeg = CAMERA_FOV): number {
  const verticalHalf = ((fovDeg * Math.PI) / 180) / 2;
  const horizontalHalf = Math.atan(Math.tan(verticalHalf) * Math.max(aspect, 0.05));
  return radius / Math.sin(Math.min(verticalHalf, horizontalHalf));
}

export function cameraPositionForAspect(
  aspect: number,
  store: StoreFixture,
  direction: [number, number, number] = INITIAL_CAMERA_OFFSET,
): [number, number, number] {
  const distance = fitDistance(shelfBoundingRadius(store), aspect);
  const length = Math.hypot(direction[0], direction[1], direction[2]) || 1;
  const [targetX, targetY, targetZ] = ORBIT_TARGET;
  return [
    targetX + (direction[0] / length) * distance,
    targetY + (direction[1] / length) * distance,
    targetZ + (direction[2] / length) * distance,
  ];
}
