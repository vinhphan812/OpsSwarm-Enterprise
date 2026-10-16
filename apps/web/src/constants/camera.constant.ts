import { STORE_FLOOR, STORE_WALL } from "@/constants/dimensions.constant";
import type { Tuple3 } from "@/types/scene.type";

export const CAMERA_FOV = 45;
/**
 * Clipping planes. The near plane sits well inside the closest zoom (MIN_CAMERA_DISTANCE), and no
 * nearer than it must: depth precision falls with distance / near, and the ground's layers (lot,
 * paths, water) are only centimetres apart, so a small near plane makes them flicker when zoomed out.
 */
export const CAMERA_NEAR = 0.5;
export const CAMERA_FAR = 1000;
export const ORBIT_TARGET: Tuple3 = [0, 0.8, 0];
/** Offset from the orbit target for the initial view. Y is up. */
export const INITIAL_CAMERA_OFFSET: Tuple3 = [6, 4.2, 8];
/** Close enough to read a shelf label, far enough to stay out of the gondolas. */
export const MIN_CAMERA_DISTANCE = 3.5;
/** Zoom-out room past the distance that fits the whole store; recomputed on resize. */
export const MAX_DISTANCE_FACTOR = 2.4;
/**
 * Zoomed out this far (as multiples of the distance that fits the store), the store closes up
 * into a building: the roof and its sign fade in between the two, and every wall stands.
 * The fitted view, where the app opens, stays open.
 */
export const EXTERIOR_VIEW = { from: 1.25, to: 1.6 } as const;


export const INITIAL_CAMERA_POSITION: Tuple3 = [
  ORBIT_TARGET[0] + INITIAL_CAMERA_OFFSET[0],
  ORBIT_TARGET[1] + INITIAL_CAMERA_OFFSET[1],
  ORBIT_TARGET[2] + INITIAL_CAMERA_OFFSET[2],
];
/** Stop the orbit just before the camera crosses under the floor. */
export const MAX_POLAR_ANGLE = Math.PI / 2 - 0.08;
/** Keep a slight tilt at the top so a straight-down view never flips the azimuth. */
export const MIN_POLAR_ANGLE = 0.12;
/**
 * Lowest the camera may go, in meters above the ground. `MAX_POLAR_ANGLE` holds the camera
 * above its orbit point only; an orbit point picked under the cursor adds a focal offset
 * that the polar limit does not see, so the camera is also held above this height.
 */
export const MIN_CAMERA_HEIGHT = 0.3;

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
  max: [
    STORE_FLOOR.width / 2,
    STORE_WALL.height,
    STORE_FLOOR.depth / 2,
  ] as Tuple3,
} as const;

/** Camera distance from a focused product's slot: the minimum zoom, so a whole bay is in view. */
export const FOCUS_PRODUCT_DISTANCE = MIN_CAMERA_DISTANCE;
/** Height of the camera's view over a focused product, as an angle above the horizontal. */
export const FOCUS_ELEVATION = 0.42;
/** Angle above the horizontal of the view of a focused shelf or piece of equipment: higher, to take in all of it. */
export const FOCUS_FIXTURE_ELEVATION = 0.6;
/** A focused view keeps the camera this far inside the walls, so it never looks at the back of one. */
export const FOCUS_WALL_CLEARANCE = 0.4;
/** Steepest view a focus may take to see over other fixtures, as an angle above the horizontal. */
export const FOCUS_MAX_ELEVATION = 1.3;
/** Step the focus raises its view by while another fixture blocks the line of sight. */
export const FOCUS_ELEVATION_STEP = 0.04;
/** Room around a focused shelf or piece of equipment, as a share of its size. */
export const FOCUS_FIXTURE_MARGIN = 1.2;
/** Seconds the camera takes to fly to a selected entity; slower than a wheel step, so the move reads. */
export const FOCUS_SMOOTH_TIME = 0.55;
/** The agent leaves the camera alone while the user drags it, and for this long after they last used it. */
export const AGENT_FOCUS_IDLE_MS = 5000;
