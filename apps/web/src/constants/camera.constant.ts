import { STORE_FLOOR, STORE_WALL } from "@/constants/dimensions.constant";
import type { Tuple3 } from "@/types/scene.type";

export const CAMERA_FOV = 45;
export const ORBIT_TARGET: Tuple3 = [0, 0.8, 0];
/** Offset from the orbit target for the initial view. Y is up. */
export const INITIAL_CAMERA_OFFSET: Tuple3 = [6, 4.2, 8];
/** Close enough to read a shelf label, far enough to stay out of the gondolas. */
export const MIN_CAMERA_DISTANCE = 3.5;
/** Zoom-out room past the distance that fits the whole store; recomputed on resize. */
export const MAX_DISTANCE_FACTOR = 1.4;

export const INITIAL_CAMERA_POSITION: Tuple3 = [
  ORBIT_TARGET[0] + INITIAL_CAMERA_OFFSET[0],
  ORBIT_TARGET[1] + INITIAL_CAMERA_OFFSET[1],
  ORBIT_TARGET[2] + INITIAL_CAMERA_OFFSET[2],
];
/** Stop the orbit just before the camera crosses under the floor. */
export const MAX_POLAR_ANGLE = Math.PI / 2 - 0.08;
/** Keep a slight tilt at the top so a straight-down view never flips the azimuth. */
export const MIN_POLAR_ANGLE = 0.12;

/** Seconds for the camera to settle after a wheel step or a drag. */
export const CAMERA_SMOOTH_TIME = 0.25;
export const CAMERA_DRAG_SMOOTH_TIME = 0.1;

/**
 * Box the orbit target may move within: the store floor, from the floor up to the top
 * of the walls, so an orbit point picked on a wall is not clamped. The camera itself
 * may still sit outside it.
 */
export const PAN_BOUNDS = {
  min: [-STORE_FLOOR.width / 2, 0, -STORE_FLOOR.depth / 2] as Tuple3,
  max: [STORE_FLOOR.width / 2, STORE_WALL.height, STORE_FLOOR.depth / 2] as Tuple3,
} as const;
