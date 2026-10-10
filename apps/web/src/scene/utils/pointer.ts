import type { ThreeEvent } from "@react-three/fiber";
import { CLICK_SLOP_PX } from "@/constants/scene.constant";

/** A press that ended as a camera drag rather than a click. */
export function isDrag(event: ThreeEvent<MouseEvent>) {
  return event.delta > CLICK_SLOP_PX;
}
