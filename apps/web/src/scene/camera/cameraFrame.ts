import { EQUIPMENT_SIZE, SHELF } from "@/constants/dimensions.constant";
import type { StoreFixture, Tuple3, Vec3 } from "@/types/scene.type";
import { footprintCorners } from "@/scene/utils/transform";
import { CAMERA_FOV, INITIAL_CAMERA_OFFSET, ORBIT_TARGET } from "@/constants/camera.constant";

/** Radius around the orbit target that holds every shelf and piece of equipment. */
function storeBoundingRadius(store: StoreFixture): number {
  const [targetX, targetY, targetZ] = ORBIT_TARGET;
  let radius = 0;
  const include = (x: number, y: number, z: number) => {
    radius = Math.max(radius, Math.hypot(x - targetX, y - targetY, z - targetZ));
  };
  const includeBox = (position: Vec3, rotationY: number, [w, h, d]: Readonly<Tuple3>) => {
    for (const { x, z } of footprintCorners(position, rotationY, w, d)) {
      include(x, position.y, z);
      include(x, position.y + h, z);
    }
  };
  for (const shelf of store.shelves) {
    includeBox(shelf.position, shelf.rotationY, [SHELF.width, SHELF.height, SHELF.depth]);
  }
  for (const item of store.equipment) {
    includeBox(item.position, item.rotationY, EQUIPMENT_SIZE[item.kind]);
  }
  return radius;
}

function fitDistance(radius: number, aspect: number, fovDeg = CAMERA_FOV): number {
  const verticalHalf = ((fovDeg * Math.PI) / 180) / 2;
  const horizontalHalf = Math.atan(Math.tan(verticalHalf) * Math.max(aspect, 0.05));
  return radius / Math.sin(Math.min(verticalHalf, horizontalHalf));
}

export function cameraPositionForAspect(
  aspect: number,
  store: StoreFixture,
  direction: Tuple3 = INITIAL_CAMERA_OFFSET,
): Tuple3 {
  const distance = fitDistance(storeBoundingRadius(store), aspect);
  const length = Math.hypot(direction[0], direction[1], direction[2]) || 1;
  const [targetX, targetY, targetZ] = ORBIT_TARGET;
  return [
    targetX + (direction[0] / length) * distance,
    targetY + (direction[1] / length) * distance,
    targetZ + (direction[2] / length) * distance,
  ];
}
