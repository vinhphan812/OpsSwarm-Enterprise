import type { CameraControls } from "@react-three/drei";
import { useThree } from "@react-three/fiber";
import { useEffect } from "react";
import { prefersReducedMotion } from "@/core/utils/motion";
import { VIEW_MODE } from "@/enums/ui.enum";
import { cameraPositionForAspect } from "@/scene/camera/cameraFrame";
import { simulationView } from "@/scene/camera/exterior";
import { storeLayout } from "@/scene/layout";
import { useUiStore } from "@/state/ui.store";
import { flyTo } from "./focusSelection.hook";

/**
 * Pressing Simulation while zoomed out to the closed building flies the camera back to the
 * view the app opens on (`simulationView`), so the roof lifts and the proposal's changes show.
 * Nearer than that, the camera stays where the user put it. Must run inside the R3F Canvas,
 * next to the default CameraControls.
 */
export function useSimulationZoom() {
  const controls = useThree((state) => state.controls) as CameraControls | null;
  const width = useThree((state) => state.size.width);
  const height = useThree((state) => state.size.height);

  useEffect(
    () =>
      useUiStore.subscribe((ui, before) => {
        if (!controls || ui.viewMode === before.viewMode || ui.viewMode !== VIEW_MODE.Simulation) return;
        if (width < 1 || height < 1) return;
        const view = simulationView(cameraPositionForAspect(width / height, storeLayout), {
          distance: controls.distance,
          maxDistance: controls.maxDistance,
        });
        if (view) flyTo(controls, view, !prefersReducedMotion());
      }),
    [controls, width, height],
  );
}
