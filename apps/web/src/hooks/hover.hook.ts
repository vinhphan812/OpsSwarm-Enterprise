import type { ThreeEvent } from "@react-three/fiber";
import { useEffect, useState } from "react";

/**
 * Hover state for one entity. Only the entity's HoverHitBox takes these handlers,
 * so over/out come from a single mesh. Handlers on the whole group would fire per
 * bar and per instance, and the label would flicker as the pointer crossed them.
 */
export function useHover() {
  const [hovered, setHovered] = useState(false);

  useEffect(() => {
    if (!hovered) return;
    document.body.style.cursor = "pointer";
    return () => {
      document.body.style.cursor = "";
    };
  }, [hovered]);

  const handlers = {
    onPointerOver: (event: ThreeEvent<PointerEvent>) => {
      // Only the front-most entity under the pointer is hovered.
      event.stopPropagation();
      // Not while dragging the camera: labels popping in and out as the pointer sweeps
      // across shelves re-render whole fixtures mid-drag and stutter the orbit.
      if (event.buttons !== 0) return;
      setHovered(true);
    },
    onPointerOut: () => setHovered(false),
  };
  return [hovered, handlers] as const;
}

export type HoverHandlers = ReturnType<typeof useHover>[1];
