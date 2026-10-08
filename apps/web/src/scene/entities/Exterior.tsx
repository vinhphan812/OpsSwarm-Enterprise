import { STORE_FLOOR } from "@/constants/dimensions.constant";
import { GROUND_SIZE, LAWN_COLOR } from "@/constants/scene.constant";

/** Lawn seen through the glass. The sky comes from the scene background. */
export function Exterior() {
  return (
    <group name="exterior">
      <mesh rotation-x={-Math.PI / 2} position={[0, -STORE_FLOOR.thickness - 0.01, 0]} receiveShadow>
        <planeGeometry args={[GROUND_SIZE, GROUND_SIZE]} />
        <meshStandardMaterial color={LAWN_COLOR} roughness={1} />
      </mesh>
    </group>
  );
}
