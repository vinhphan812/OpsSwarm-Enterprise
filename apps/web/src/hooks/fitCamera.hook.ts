import type { CameraControls } from "@react-three/drei";
import { useThree } from "@react-three/fiber";
import { useLayoutEffect } from "react";
import type { PerspectiveCamera } from "three";
import { CAMERA_FOV, MAX_DISTANCE_FACTOR, ORBIT_TARGET } from "@/constants/camera.constant";
import { cameraPositionForAspect } from "@/scene/camera/cameraFrame";
import { storeLayout } from "@/scene/layout";

/**
 * Fits the store into the canvas on every resize, keeping the user's current
 * viewing direction, and caps zoom-out a little past that fit. Must run inside the
 * R3F Canvas, next to the default CameraControls.
 */
export function useFitCamera() {
  const camera = useThree((state) => state.camera);
  const controls = useThree((state) => state.controls) as CameraControls | null;
  const width = useThree((state) => state.size.width);
  const height = useThree((state) => state.size.height);

  useLayoutEffect(() => {
    if (width < 1 || height < 1) {
      return;
    }
    const perspective = camera as PerspectiveCamera;
    perspective.aspect = width / height;
    perspective.fov = CAMERA_FOV;
    perspective.updateProjectionMatrix();
    const [x, y, z] = cameraPositionForAspect(width / height, storeLayout, [
      camera.position.x - ORBIT_TARGET[0],
      camera.position.y - ORBIT_TARGET[1],
      camera.position.z - ORBIT_TARGET[2],
    ]);
    const fitted = Math.hypot(x - ORBIT_TARGET[0], y - ORBIT_TARGET[1], z - ORBIT_TARGET[2]);

    if (controls) {
      controls.maxDistance = fitted * MAX_DISTANCE_FACTOR;
      void controls.setLookAt(x, y, z, ORBIT_TARGET[0], ORBIT_TARGET[1], ORBIT_TARGET[2], false);
      return;
    }
    camera.position.set(x, y, z);
    camera.lookAt(ORBIT_TARGET[0], ORBIT_TARGET[1], ORBIT_TARGET[2]);
    camera.updateMatrixWorld();
  }, [camera, controls, height, width]);
}
