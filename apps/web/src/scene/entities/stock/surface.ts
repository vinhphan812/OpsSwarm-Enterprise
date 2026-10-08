import type { StockKind } from "@/enums/scene.enum";
import type { Tuple3 } from "@/scene/utils/transform";

/**
 * A flat area that stock stands on, in the fixture's local frame. Items are laid
 * out across `width` (X) and back from the front edge over `depth` (Z), so the
 * surface front faces +Z after `rotationY`. `tilt` lowers the front edge.
 */
export type StockSurface = {
  kind: StockKind;
  /** Center of the top face. */
  center: Tuple3;
  width: number;
  depth: number;
  /** Clear height above the surface. */
  maxHeight: number;
  rotationY?: number;
  tilt?: number;
  /** Slots the surface is split into, side by side across its width. */
  slots: number;
};
