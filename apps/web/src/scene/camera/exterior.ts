import { EXTERIOR_VIEW, MAX_DISTANCE_FACTOR, ORBIT_TARGET } from "@/constants/camera.constant";
import type { Tuple3 } from "@/types/scene.type";
import type { FocusView } from "./focus";

/** The camera controls' distance and zoom-out cap, as `CameraControls` has them. */
type Zoom = { distance: number; maxDistance: number };

/**
 * How closed up the store is drawn, from 0 (open: no roof, the walls between the camera and the
 * shelves hidden) to 1 (a building: roof, sign, and every wall). Read from how far the camera is
 * zoomed out against the distance that fits the store (`useFitCamera` sets the cap from it).
 */
export function exteriorLevel({ distance, maxDistance }: Zoom): number {
  const fitted = maxDistance / MAX_DISTANCE_FACTOR;
  if (!Number.isFinite(fitted) || fitted <= 0) return 0;
  const t = (distance / fitted - EXTERIOR_VIEW.from) / (EXTERIOR_VIEW.to - EXTERIOR_VIEW.from);
  const clamped = Math.min(1, Math.max(0, t));
  return clamped * clamped * (3 - 2 * clamped);
}

/** At or past this level the store counts as closed up: every wall stands. */
export const EXTERIOR_WALLS_AT = 0.5;

/**
 * Where the camera goes when the Simulation view opens: back to `home`, the view the app opens
 * on (the whole store, open, from the usual angle). Null when the store is already open (no
 * roof showing), so a camera the user has brought in stays where it is.
 */
export function simulationView(home: Tuple3, zoom: Zoom): FocusView | null {
  return exteriorLevel(zoom) > 0 ? { position: home, target: ORBIT_TARGET } : null;
}
