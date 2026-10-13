import type { CameraControls } from "@react-three/drei";
import { useThree } from "@react-three/fiber";
import { useEffect } from "react";
import { useUiStore } from "@/state/ui.store";

/**
 * Records when the user drags, pans, or zooms the camera (`ui.store.userDragging`,
 * `userActiveAt`), so the agent waits before taking the camera. A flight to a selection
 * does not count: camera-controls only reports user input. Must run inside the R3F
 * Canvas, next to the default CameraControls.
 */
export function useCameraActivity() {
  const controls = useThree((state) => state.controls) as CameraControls | null;

  useEffect(() => {
    if (!controls) return;
    const onStart = () => useUiStore.getState().markUserActivity(true);
    const onEnd = () => useUiStore.getState().markUserActivity(false);
    controls.addEventListener("controlstart", onStart);
    controls.addEventListener("controlend", onEnd);
    return () => {
      controls.removeEventListener("controlstart", onStart);
      controls.removeEventListener("controlend", onEnd);
    };
  }, [controls]);
}
