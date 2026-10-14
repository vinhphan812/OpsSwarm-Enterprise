import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import { CanvasTexture, SRGBColorSpace, type Group, type Material, type Mesh } from "three";
import { GLAZING, STORE_FLOOR, STORE_WALL } from "@/constants/dimensions.constant";
import { exteriorLevel } from "@/scene/camera/exterior";

const T = STORE_WALL.thickness;
/** The roof covers the walls and overhangs them a little. */
const ROOF_W = STORE_FLOOR.width + 2 * T + 0.3;
const ROOF_D = STORE_FLOOR.depth + 2 * T + 0.3;
const SLAB = 0.22;
/** A parapet round the roof's edge, high enough to carry the sign. */
const PARAPET = { height: 0.9, thickness: 0.18 } as const;
const ROOF_TOP = STORE_WALL.height + STORE_WALL.cap + SLAB;
const SIGN = { text: "MINI MART", width: 6.6, height: 1.05 } as const;

const ROOF_COLOR = "#d9dbe2";
const PARAPET_COLOR = "#3a4150";
const SIGN_COLOR = "#1f8a5b";
const UNIT_COLOR = "#b9bdc8";

const noRaycast = () => {};

/** The sign's face: white letters on the brand green, with a yellow stripe below. */
function useSignTexture(): CanvasTexture {
  const texture = useMemo(() => {
    const canvas = document.createElement("canvas");
    canvas.width = 1024;
    canvas.height = Math.round((1024 * SIGN.height) / SIGN.width);
    const ctx = canvas.getContext("2d");
    if (ctx) {
      ctx.fillStyle = SIGN_COLOR;
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = "#f2c14e";
      ctx.fillRect(0, canvas.height - 18, canvas.width, 18);
      ctx.fillStyle = "#ffffff";
      ctx.font = `800 ${Math.round(canvas.height * 0.62)}px system-ui, -apple-system, "Segoe UI", sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(SIGN.text, canvas.width / 2, canvas.height * 0.46, canvas.width * 0.9);
    }
    const map = new CanvasTexture(canvas);
    map.colorSpace = SRGBColorSpace;
    map.anisotropy = 4;
    return map;
  }, []);
  useEffect(() => () => texture.dispose(), [texture]);
  return texture;
}

/** A sign board on the parapet, its face turned out from the store along `facing` (+Z when 0). */
function Sign({ position, rotationY, map }: { position: [number, number, number]; rotationY: number; map: CanvasTexture }) {
  return (
    <group position={position} rotation-y={rotationY}>
      <mesh raycast={noRaycast}>
        <boxGeometry args={[SIGN.width + 0.12, SIGN.height + 0.12, 0.08]} />
        <meshStandardMaterial color={PARAPET_COLOR} roughness={0.6} />
      </mesh>
      <mesh position-z={0.045} raycast={noRaycast}>
        <planeGeometry args={[SIGN.width, SIGN.height]} />
        <meshStandardMaterial map={map} emissive="#ffffff" emissiveMap={map} emissiveIntensity={0.35} roughness={0.5} />
      </mesh>
    </group>
  );
}

/**
 * The store's flat roof: a slab over the walls, a parapet round it with the "MINI MART" sign on the
 * front and over the door, and two air-conditioning units. Drawn only when the camera is zoomed out
 * far enough that the store reads as a building (`exteriorLevel`); it fades in and out with the zoom.
 * It takes no clicks, so it never blocks a selection.
 */
export function Roof() {
  const ref = useRef<Group>(null);
  const map = useSignTexture();
  const materials = useRef<Material[]>([]);
  const controls = useThree((state) => state.controls) as { distance?: number; maxDistance?: number } | null;

  useEffect(() => {
    const found: Material[] = [];
    ref.current?.traverse((object) => {
      const material = (object as Mesh).material as Material | undefined;
      if (material) {
        material.transparent = true;
        material.needsUpdate = true;
        found.push(material);
      }
    });
    materials.current = found;
  }, []);

  useFrame(() => {
    const group = ref.current;
    if (!group) return;
    const level =
      controls?.distance !== undefined && controls.maxDistance !== undefined
        ? exteriorLevel({ distance: controls.distance, maxDistance: controls.maxDistance })
        : 0;
    group.visible = level > 0.01;
    for (const material of materials.current) {
      material.opacity = level;
      // Opaque once fully in, so it sorts and shades like the walls.
      material.depthWrite = level > 0.99;
    }
  });

  const edgeY = ROOF_TOP + PARAPET.height / 2;
  const front = ROOF_D / 2 - PARAPET.thickness / 2;
  const side = ROOF_W / 2 - PARAPET.thickness / 2;
  return (
    <group ref={ref} name="roof" visible={false}>
      <mesh position-y={STORE_WALL.height + STORE_WALL.cap + SLAB / 2} receiveShadow raycast={noRaycast}>
        <boxGeometry args={[ROOF_W, SLAB, ROOF_D]} />
        <meshStandardMaterial color={ROOF_COLOR} roughness={0.95} />
      </mesh>
      {/* The parapet: front and back full width, the sides between them. */}
      {[front, -front].map((z) => (
        <mesh key={z} position={[0, edgeY, z]} raycast={noRaycast}>
          <boxGeometry args={[ROOF_W, PARAPET.height, PARAPET.thickness]} />
          <meshStandardMaterial color={PARAPET_COLOR} roughness={0.7} />
        </mesh>
      ))}
      {[side, -side].map((x) => (
        <mesh key={x} position={[x, edgeY, 0]} raycast={noRaycast}>
          <boxGeometry args={[PARAPET.thickness, PARAPET.height, ROOF_D - 2 * PARAPET.thickness]} />
          <meshStandardMaterial color={PARAPET_COLOR} roughness={0.7} />
        </mesh>
      ))}
      {/* Signs: on the front, toward the park and the front road, and over the door, toward the back road. */}
      <Sign position={[0, edgeY, ROOF_D / 2 + 0.05]} rotationY={0} map={map} />
      <Sign position={[GLAZING.doorX - 1.2, edgeY, -ROOF_D / 2 - 0.05]} rotationY={Math.PI} map={map} />
      {/* Air-conditioning units on the roof. */}
      {[
        [-3.5, -1.5],
        [2.5, 1.8],
      ].map(([x, z]) => (
        <group key={x} position={[x, ROOF_TOP, z]}>
          <mesh position-y={0.4} raycast={noRaycast}>
            <boxGeometry args={[1.6, 0.8, 1.1]} />
            <meshStandardMaterial color={UNIT_COLOR} roughness={0.6} />
          </mesh>
          <mesh position-y={0.81} rotation-x={-Math.PI / 2} raycast={noRaycast}>
            <circleGeometry args={[0.38, 16]} />
            <meshStandardMaterial color={PARAPET_COLOR} roughness={0.6} />
          </mesh>
        </group>
      ))}
    </group>
  );
}
