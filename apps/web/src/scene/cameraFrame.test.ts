import { PerspectiveCamera, Vector3 } from "three";
import { describe, expect, it } from "vitest";
import { SHELF } from "./dimensions";
import {
  CAMERA_FOV,
  INITIAL_CAMERA_OFFSET,
  ORBIT_TARGET,
  cameraPositionForAspect,
} from "./cameraFrame";
import { storeFixture } from "./storeFixture";

function shelfCornerNdc(width: number, height: number, position: [number, number, number]): number[] {
  const camera = new PerspectiveCamera(CAMERA_FOV, width / height, 0.1, 500);
  camera.position.set(position[0], position[1], position[2]);
  camera.lookAt(ORBIT_TARGET[0], ORBIT_TARGET[1], ORBIT_TARGET[2]);
  camera.updateProjectionMatrix();
  camera.updateMatrixWorld(true);

  const coords: number[] = [];
  for (const shelf of storeFixture.shelves) {
    const xs = [shelf.position.x - SHELF.width / 2, shelf.position.x + SHELF.width / 2];
    const ys = [shelf.position.y, shelf.position.y + SHELF.height];
    const zs = [shelf.position.z - SHELF.depth / 2, shelf.position.z + SHELF.depth / 2];
    for (const x of xs) {
      for (const y of ys) {
        for (const z of zs) {
          const projected = new Vector3(x, y, z).project(camera);
          coords.push(projected.x, projected.y);
        }
      }
    }
  }
  return coords;
}

describe("camera framing", () => {
  it("keeps every shelf corner inside the frame on desktop and on a 390px canvas", () => {
    for (const [width, height] of [
      [960, 800],
      [1280, 800],
      [390, 664],
    ] as const) {
      const position = cameraPositionForAspect(width / height, storeFixture);
      const coords = shelfCornerNdc(width, height, position);
      for (const value of coords) {
        expect(Math.abs(value), `${width}x${height}`).toBeLessThanOrEqual(1);
      }
    }
  });

  it("clips shelf corners when the desktop camera distance is used on a 390x664 canvas", () => {
    const [targetX, targetY, targetZ] = ORBIT_TARGET;
    const fixed: [number, number, number] = [
      targetX + INITIAL_CAMERA_OFFSET[0],
      targetY + INITIAL_CAMERA_OFFSET[1],
      targetZ + INITIAL_CAMERA_OFFSET[2],
    ];
    const coords = shelfCornerNdc(390, 664, fixed);
    expect(Math.max(...coords.map((value) => Math.abs(value)))).toBeGreaterThan(1);
  });
});
