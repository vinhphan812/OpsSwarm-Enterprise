import { Html } from "@react-three/drei";
import type { HoverHandlers } from "@/hooks/hover.hook";
import type { Tuple3 } from "@/scene/utils/transform";

type HoverLabelProps = {
  title: string;
  entityId: string;
  /** Anchor in the entity's local frame. */
  position: Tuple3;
};

/** Floating tag with the category on top and the entity id below. */
export function HoverLabel({ title, entityId, position }: HoverLabelProps) {
  return (
    // The label must never take the pointer: if it covers the cursor, the canvas gets
    // pointerleave, R3F ends the hover, the label hides, and the cycle repeats.
    // Html's own `pointerEvents` prop only applies in `transform` mode, so use `style`.
    <Html position={position} center distanceFactor={8} style={{ pointerEvents: "none" }}>
      <div className="hover-label">
        <span className="hover-label__title">{title}</span>
        <span className="hover-label__id">{entityId}</span>
      </div>
    </Html>
  );
}

type HoverHitBoxProps = {
  size: Readonly<Tuple3>;
  handlers: HoverHandlers;
};

/**
 * Invisible box over the entity's whole volume, and the only mesh that takes the
 * hover. It also covers the gaps of open frames. A hidden material is skipped by
 * the renderer but still hit by the raycaster.
 */
export function HoverHitBox({ size, handlers }: HoverHitBoxProps) {
  const [w, h, d] = size;
  return (
    <mesh position={[0, h / 2, 0]} {...handlers}>
      <boxGeometry args={[w, h, d]} />
      <meshBasicMaterial visible={false} />
    </mesh>
  );
}
