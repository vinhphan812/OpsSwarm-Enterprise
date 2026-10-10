import type { CameraControls } from "@react-three/drei";
import { useThree } from "@react-three/fiber";
import { useEffect, useRef } from "react";
import { PANEL_WIDTH } from "@/constants/app.constant";
import { CAMERA_FOV, CAMERA_SMOOTH_TIME, FOCUS_SMOOTH_TIME } from "@/constants/camera.constant";
import { ENTITY_TYPE } from "@/enums/scene.enum";
import { fixtureFocus, productFocus, type FocusView } from "@/scene/camera/focus";
import { sceneOf, storeLayout } from "@/scene/layout";
import { usePanelStore } from "@/state/panel.store";
import { prefersReducedMotion } from "@/core/utils/motion";
import { useTwinStore } from "@/state/twin.store";
import { useUiStore } from "@/state/ui.store";

/** The open Agent Activity panel covers this many pixels on the right of the canvas, gap included. */
const PANEL_COVER_PX = PANEL_WIDTH + 24;

/**
 * Sideways focal offset, in meters at the target, that moves the target `shiftPx` to the
 * left on screen: into the middle of what the panel leaves visible.
 */
export function panelOffset(view: FocusView, canvasHeightPx: number, shiftPx: number): number {
  if (canvasHeightPx <= 0 || shiftPx <= 0) return 0;
  const [px, py, pz] = view.position;
  const [tx, ty, tz] = view.target;
  const distance = Math.hypot(px - tx, py - ty, pz - tz);
  const metersPerPx = (2 * distance * Math.tan((CAMERA_FOV * Math.PI) / 360)) / canvasHeightPx;
  return shiftPx * metersPerPx;
}

/**
 * Moves the camera to `view`, with the target `offsetX` meters left of the screen center
 * (to clear the side panel). A slower glide for the flight, back to the usual smoothing
 * once it lands or the user takes over. Orbiting around the pointer (setOrbitPoint)
 * leaves a focal offset behind; it is replaced, or the camera would land where it
 * should but look past the entity by that offset.
 */
export function flyTo(controls: CameraControls, view: FocusView, animate: boolean, offsetX = 0) {
  controls.smoothTime = FOCUS_SMOOTH_TIME;
  const restore = () => {
    controls.smoothTime = CAMERA_SMOOTH_TIME;
    controls.removeEventListener("rest", restore);
    controls.removeEventListener("controlstart", restore);
  };
  controls.addEventListener("rest", restore);
  controls.addEventListener("controlstart", restore);
  void controls.setFocalOffset(offsetX, 0, 0, animate);
  void controls.setLookAt(...view.position, ...view.target, animate);
  if (!animate) restore();
}

/**
 * Flies the camera to whatever gets selected: a product's slot from the front, or a
 * whole shelf or piece of equipment. Once per selection: a later twin update does not
 * move the camera again. A product selected before the twin has loaded (`?product=`)
 * is focused when it arrives. Must run inside the R3F Canvas, next to the default
 * CameraControls.
 */
export function useFocusSelection() {
  const controls = useThree((state) => state.controls) as CameraControls | null;
  const camera = useThree((state) => state.camera);
  const id = useUiStore((state) => state.selectedEntityId);
  const type = useUiStore((state) => state.selectedEntityType);
  const live = useTwinStore((state) => state.live);
  const panelOpen = usePanelStore((state) => state.open);
  const size = useThree((state) => state.size);
  const focused = useRef<string | null>(null);

  useEffect(() => {
    if (!id || !type) {
      focused.current = null;
      return;
    }
    const key = `${type}:${id}`;
    if (!controls || focused.current === key) return;

    let view: FocusView | null = null;
    if (type === ENTITY_TYPE.Product) {
      const product = live ? sceneOf(live).store.products.find((item) => item.productId === id) : undefined;
      if (product) view = productFocus(storeLayout, product.shelfId, product.slotId);
    } else {
      view = fixtureFocus(storeLayout, id, camera.position.toArray());
    }
    if (!view) return;
    focused.current = key;

    // Half the panel's width: the target lands in the middle of the part it leaves visible.
    const shift = panelOpen && size.width > PANEL_COVER_PX * 2 ? PANEL_COVER_PX / 2 : 0;
    flyTo(controls, view, !prefersReducedMotion(), panelOffset(view, size.height, shift));
    // The panel and canvas size are read when a selection is focused, not followed after.
  }, [camera, controls, id, type, live]);
}
