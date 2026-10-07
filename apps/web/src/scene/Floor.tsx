import { STORE_FLOOR } from "./dimensions";

export function Floor() {
  return (
    <mesh name="floor" position={[0, -STORE_FLOOR.thickness / 2, 0]}>
      <boxGeometry args={[STORE_FLOOR.width, STORE_FLOOR.thickness, STORE_FLOOR.depth]} />
      <meshStandardMaterial color="#c4b6a2" />
    </mesh>
  );
}
