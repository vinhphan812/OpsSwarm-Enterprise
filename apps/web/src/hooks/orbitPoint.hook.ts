import type { CameraControls } from "@react-three/drei";
import { useThree } from "@react-three/fiber";
import { useEffect } from "react";
import { Box3, Raycaster, Vector2, Vector3, type Intersection, type Object3D } from "three";
import { PAN_BOUNDS } from "@/constants/camera.constant";

const ORBIT_BOUNDS = new Box3(new Vector3(...PAN_BOUNDS.min), new Vector3(...PAN_BOUNDS.max));

/** False when the object or any ancestor is hidden, e.g. a wall the camera is behind. */
function isShown(object: Object3D | null): boolean {
  for (let current = object; current; current = current.parent) {
    if (!current.visible) return false;
  }
  return true;
}

/**
 * Orbits around whatever is under the pointer: a left press moves the orbit point to
 * the first visible surface it hits inside the store, keeping the camera where it is.
 * A press on the sky or the ground outside keeps the current orbit point. Must run inside the R3F Canvas, next to the
 * default CameraControls.
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

    const onPointerDown = (event: PointerEvent) => {
      if (event.button !== 0 || !event.isPrimary) return;
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
      // Settle any running transition first; setOrbitPoint must not run mid-animation.
      controls.stop();
      controls.setOrbitPoint(hit.point.x, hit.point.y, hit.point.z);
    };

    // Capture, so the orbit point is set before camera-controls starts the drag.
    element.addEventListener("pointerdown", onPointerDown, { capture: true });
    return () => element.removeEventListener("pointerdown", onPointerDown, { capture: true });
  }, [camera, controls, element, scene]);
}
