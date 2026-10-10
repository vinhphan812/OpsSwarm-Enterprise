import type { ThreeEvent } from "@react-three/fiber";
import type { HoverHandlers } from "@/hooks/hover.hook";
import type { Tuple3 } from "@/types/scene.type";

type HitBoxProps = {
  size: Readonly<Tuple3>;
  handlers: HoverHandlers;
  /** Selects the entity. */
  onClick: (event: ThreeEvent<MouseEvent>) => void;
};

/**
 * Invisible box over the entity's whole volume, and the only mesh that takes the
 * pointer: the hover (a pointer cursor) and the click that selects the entity. It
 * also covers the gaps of open frames. A hidden material is skipped by the renderer
 * but still hit by the raycaster.
 */
export function HitBox({ size, handlers, onClick }: HitBoxProps) {
  const [w, h, d] = size;
  return (
    <mesh position={[0, h / 2, 0]} {...handlers} onClick={onClick}>
      <boxGeometry args={[w, h, d]} />
      <meshBasicMaterial visible={false} />
    </mesh>
  );
}
