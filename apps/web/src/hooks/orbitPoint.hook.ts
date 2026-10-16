import type { CameraControls } from "@react-three/drei";
import { useThree } from "@react-three/fiber";
import { useEffect } from "react";
import { Box3, MathUtils, Raycaster, Vector2, Vector3, type Intersection, type Object3D } from "three";
import { MAX_POLAR_ANGLE, MIN_CAMERA_HEIGHT, MIN_POLAR_ANGLE, PAN_BOUNDS } from "@/constants/camera.constant";

const ORBIT_BOUNDS = new Box3(new Vector3(...PAN_BOUNDS.min), new Vector3(...PAN_BOUNDS.max));

/** False when the object or any ancestor is hidden, e.g. a wall the camera is behind. */
function isShown(object: Object3D | null): boolean {
  for (let current = object; current; current = current.parent) {
    if (!current.visible) return false;
  }
  return true;
}

/**
 * The steepest-down polar angle that lifts a camera at `height` back to `MIN_CAMERA_HEIGHT`,
 * orbiting at `radius` with polar angle `polar`; null when it is high enough. Lowering the
 * polar angle by dφ raises the camera by about radius·sin(φ)·dφ, so this takes that step,
 * a little more, and never goes past `MIN_POLAR_ANGLE`.
 */
export function polarFloor(polar: number, height: number, radius: number): number | null {
  if (height >= MIN_CAMERA_HEIGHT) return null;
  const lift = (MIN_CAMERA_HEIGHT - height) / Math.max(radius * Math.sin(polar), 1e-3);
  return Math.max(MIN_POLAR_ANGLE, polar - lift * 1.05);
}

/** What the floor needs of the controls: camera-controls' own API, so a test can drive the real thing. */
type FloorControls = Pick<CameraControls, "polarAngle" | "distance" | "maxPolarAngle" | "rotatePolarTo" | "update">;

/**
 * Puts a camera that ended up under `MIN_CAMERA_HEIGHT` back above it, by tightening the
 * polar limit to where it stands clear and applying it at once. Returns whether it moved.
 */
export function liftAboveGround(controls: FloorControls, camera: { position: { y: number } }): boolean {
  let moved = false;
  // A step or two settles it: each takes the camera most of the way, and the focal offset bends the rest.
  for (let step = 0; step < 4; step += 1) {
    const floor = polarFloor(controls.polarAngle, camera.position.y, controls.distance);
    if (floor === null) break;
    controls.maxPolarAngle = Math.min(controls.maxPolarAngle, floor);
    void controls.rotatePolarTo(controls.maxPolarAngle, false);
    controls.update(0);
    moved = true;
  }
  return moved;
}

/**
 * Orbits around whatever is under the pointer: a left press moves the orbit point to
 * the first visible surface it hits inside the store, keeping the camera where it is.
 * A press on the sky or the ground outside keeps the current orbit point. Must run inside the R3F Canvas, next to the
 * default CameraControls.
 *
 * camera-controls keeps the camera still by adding a focal offset, which its polar limit
 * does not account for: orbiting down from a point picked high up could take the camera
 * under the ground. So whenever an update leaves the camera below `MIN_CAMERA_HEIGHT`, the
 * polar limit is tightened to where it stands clear (`liftAboveGround`) and the camera is
 * put back there in the same frame. Each new press resets the limit.
 */
export function useOrbitAroundPointer() {
  const controls = useThree((state) => state.controls) as CameraControls | null;
  const camera = useThree((state) => state.camera);
  const scene = useThree((state) => state.scene);
  const element = useThree((state) => state.gl.domElement);

  useEffect(() => {
    if (!controls) return;
    const raycaster = new Raycaster();
    const pointer = new Vector2();
    const orbitPoint = new Vector3();

    const onPointerDown = (event: PointerEvent) => {
      if (event.button !== 0 || !event.isPrimary) return;
      // A new drag starts from the full polar range; the floor tightens it again if needed.
      controls.maxPolarAngle = MAX_POLAR_ANGLE;
      const rect = element.getBoundingClientRect();
      pointer.set(
        ((event.clientX - rect.left) / rect.width) * 2 - 1,
        -((event.clientY - rect.top) / rect.height) * 2 + 1,
      );
      raycaster.setFromCamera(pointer, camera);
      const hit = raycaster
        .intersectObjects(scene.children, true)
        .find((candidate: Intersection) => isShown(candidate.object));
      if (!hit || !ORBIT_BOUNDS.containsPoint(hit.point)) return;
      // Keep the orbit point on the cursor ray but within the zoom limits; otherwise
      // camera-controls pushes the camera back to minDistance (or pulls it in to
      // maxDistance) and every click looks like a zoom step.
      const distance = MathUtils.clamp(hit.distance, controls.minDistance, controls.maxDistance);
      orbitPoint.copy(raycaster.ray.direction).multiplyScalar(distance).add(raycaster.ray.origin);
      if (!ORBIT_BOUNDS.containsPoint(orbitPoint)) return;
      // Settle any running transition first; setOrbitPoint must not run mid-animation.
      controls.stop();
      controls.setOrbitPoint(orbitPoint.x, orbitPoint.y, orbitPoint.z);
    };

    let lifting = false;
    const onUpdate = () => {
      if (lifting) return;
      lifting = true;
      // Applied in this update, so no frame is drawn from under the ground.
      liftAboveGround(controls, camera);
      lifting = false;
    };

    // Capture, so the orbit point is set before camera-controls starts the drag.
    element.addEventListener("pointerdown", onPointerDown, { capture: true });
    controls.addEventListener("update", onUpdate);
    return () => {
      element.removeEventListener("pointerdown", onPointerDown, { capture: true });
      controls.removeEventListener("update", onUpdate);
    };
  }, [camera, controls, element, scene]);
}
