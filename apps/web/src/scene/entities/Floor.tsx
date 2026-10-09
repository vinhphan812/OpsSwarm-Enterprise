import type { Texture } from "three";
import { STORE_FLOOR, STORE_WALL } from "@/constants/dimensions.constant";
import { WOOD_TILE_METERS, createWoodTexture } from "./woodTexture";
import { FLOOR_WOOD_COLOR } from "@/constants/scene.constant";

/** The slab runs under the walls so they stand on it rather than past its edge. */
const SLAB_WIDTH = STORE_FLOOR.width + 2 * STORE_WALL.thickness;
const SLAB_DEPTH = STORE_FLOOR.depth + STORE_WALL.thickness;

let floorTexture: Texture | null | undefined;

/**
 * The plank texture, painted on first use and then shared. Painting a 1024px canvas is
 * slow, and the floor remounts when the first twin state arrives, so it is never redone.
 */
function woodFloorTexture(): Texture | null {
  if (floorTexture === undefined) {
    floorTexture = createWoodTexture();
    if (floorTexture) {
      // Planks run along X, across the camera's view, like the shopping demo.
      floorTexture.center.set(0.5, 0.5);
      floorTexture.rotation = Math.PI / 2;
      floorTexture.repeat.set(SLAB_WIDTH / WOOD_TILE_METERS, SLAB_DEPTH / WOOD_TILE_METERS);
    }
  }
  return floorTexture;
}

export function Floor() {
  const wood = woodFloorTexture();

  return (
    <group name="floor">
      <mesh position={[0, -STORE_FLOOR.thickness / 2, -STORE_WALL.thickness / 2]} receiveShadow>
        <boxGeometry args={[SLAB_WIDTH, STORE_FLOOR.thickness, SLAB_DEPTH]} />
        <meshStandardMaterial
          map={wood}
          color={wood ? "#eee6dc" : FLOOR_WOOD_COLOR}
          roughness={0.55}
          metalness={0}
          envMapIntensity={0.6}
        />
      </mesh>
    </group>
  );
}
