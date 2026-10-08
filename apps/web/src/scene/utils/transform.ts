import { Euler, Matrix4, Quaternion, Vector3 } from "three";
import type { Vec3 } from "@/scene/types";

export type Tuple3 = [number, number, number];

export function toTuple({ x, y, z }: Vec3): Tuple3 {
  return [x, y, z];
}

/** Placement of a fixture on the floor: a position and a turn about Y. */
export function entityMatrix(position: Vec3, rotationY: number): Matrix4 {
  return new Matrix4().compose(
    new Vector3(position.x, position.y, position.z),
    new Quaternion().setFromEuler(new Euler(0, rotationY, 0)),
    new Vector3(1, 1, 1),
  );
}

/**
 * Rotates a point about the X axis through `pivot`. Positive angles lower +Z,
 * matching an Euler rotation of the same angle on the box itself.
 */
export function tiltX(point: Tuple3, angle: number, pivot: Tuple3): Tuple3 {
  const y = point[1] - pivot[1];
  const z = point[2] - pivot[2];
  const cos = Math.cos(angle);
  const sin = Math.sin(angle);
  return [point[0], pivot[1] + y * cos - z * sin, pivot[2] + y * sin + z * cos];
}

/** Floor corners of a `width` x `depth` footprint centered on `position` and turned by `rotationY`. */
export function footprintCorners(position: Vec3, rotationY: number, width: number, depth: number) {
  const cos = Math.cos(rotationY);
  const sin = Math.sin(rotationY);
  const corners: Array<{ x: number; z: number }> = [];
  for (const dx of [-width / 2, width / 2]) {
    for (const dz of [-depth / 2, depth / 2]) {
      corners.push({ x: position.x + dx * cos + dz * sin, z: position.z - dx * sin + dz * cos });
    }
  }
  return corners;
}
