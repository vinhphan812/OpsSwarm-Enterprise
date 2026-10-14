import { useFrame } from "@react-three/fiber";
import { useLayoutEffect, useRef, type ReactNode } from "react";
import { Object3D, type Camera, type Group, type InstancedMesh } from "three";
import { GLAZING, STORE_FLOOR, STORE_WALL, WALL_SLATS } from "@/constants/dimensions.constant";
import { CurtainWall, SlidingDoor } from "./Glazing";
import type { Tuple3 } from "@/types/scene.type";
import { EXTERIOR_WALLS_AT, exteriorLevel } from "@/scene/camera/exterior";
import { WALL_CAP_COLOR, WALL_COLOR, WALL_GAP_COLOR, WALL_SLAT_COLOR } from "@/constants/scene.constant";

const HALF_W = STORE_FLOOR.width / 2;
const HALF_D = STORE_FLOOR.depth / 2;
const T = STORE_WALL.thickness;

type Opening = {
  /** Center along the wall, in wall-local X. */
  x: number;
  width: number;
  kind: "window" | "door";
};

type WallProps = {
  name: string;
  length: number;
  /** Center of the wall's inner face on the floor. */
  position: Tuple3;
  rotationY: number;
  /** True when the camera is outside this wall, so it would block the view. */
  isBehind: (camera: Camera) => boolean;
  openings?: Opening[];
  /** Fixtures mounted on the inner face; they hide with the wall. */
  children?: ReactNode;
};

const BODY_HEIGHT = STORE_WALL.height - STORE_WALL.shadowGap;

function WallMaterial() {
  return (
    <meshStandardMaterial color={WALL_COLOR} emissive={WALL_COLOR} emissiveIntensity={0.25} roughness={0.95} />
  );
}

/** A full-height run of solid wall between `from` and `to` along wall-local X. */
function Pier({ from, to }: { from: number; to: number }) {
  const width = to - from;
  const x = (from + to) / 2;
  return (
    <>
      <mesh position={[x, STORE_WALL.shadowGap + BODY_HEIGHT / 2, -T / 2]} castShadow receiveShadow>
        <boxGeometry args={[width, BODY_HEIGHT, T]} />
        <WallMaterial />
      </mesh>
      <mesh position={[x, STORE_WALL.shadowGap / 2, -T / 2 - STORE_WALL.shadowGapDepth / 2]}>
        <boxGeometry args={[width, STORE_WALL.shadowGap, T - STORE_WALL.shadowGapDepth]} />
        <meshStandardMaterial color={WALL_GAP_COLOR} roughness={0.8} />
      </mesh>
    </>
  );
}

/** Wall above an opening, from the head of the glazing to the top of the wall. */
function Lintel({ opening, height }: { opening: Opening; height: number }) {
  const lintel = STORE_WALL.height - height;
  return (
    <mesh position={[opening.x, height + lintel / 2, -T / 2]} castShadow receiveShadow>
      <boxGeometry args={[opening.width, lintel, T]} />
      <WallMaterial />
    </mesh>
  );
}

/** Solid ranges along the wall once the openings are cut out. */
function solidRuns(length: number, openings: Opening[]): Array<[number, number]> {
  const runs: Array<[number, number]> = [];
  let cursor = -length / 2;
  for (const opening of [...openings].sort((a, b) => a.x - b.x)) {
    const left = opening.x - opening.width / 2;
    if (left > cursor) runs.push([cursor, left]);
    cursor = opening.x + opening.width / 2;
  }
  if (cursor < length / 2) runs.push([cursor, length / 2]);
  return runs;
}

/**
 * A thick wall whose local +Z faces into the store, with optional glazed
 * openings. It hides itself while the camera orbits outside it, so it never
 * blocks the shelves, unless the camera is zoomed out far enough that the store
 * is drawn as a closed building.
 */
function Wall({ name, length, position, rotationY, isBehind, openings = [], children }: WallProps) {
  const ref = useRef<Group>(null);

  useFrame(({ camera, gl, controls }) => {
    if (!ref.current) return;
    // Zoomed out, the store is a closed building and every wall stands (`exteriorLevel`).
    const zoom = controls as { distance?: number; maxDistance?: number } | null;
    const closedUp =
      zoom?.distance !== undefined && zoom.maxDistance !== undefined
        ? exteriorLevel({ distance: zoom.distance, maxDistance: zoom.maxDistance }) >= EXTERIOR_WALLS_AT
        : false;
    const visible = closedUp || !isBehind(camera);
    if (ref.current.visible === visible) return;
    ref.current.visible = visible;
    // Shadows are drawn on demand (StaticShadows); a wall that comes or goes changes them.
    gl.shadowMap.needsUpdate = true;
  });

  return (
    <group ref={ref} name={name} position={position} rotation={[0, rotationY, 0]}>
      {solidRuns(length, openings).map(([from, to]) => (
        <Pier key={from} from={from} to={to} />
      ))}
      {openings.map((opening) => {
        const height = opening.kind === "door" ? GLAZING.doorHeight : GLAZING.windowHeight;
        const Glazed = opening.kind === "door" ? SlidingDoor : CurtainWall;
        return (
          <group key={opening.x}>
            <Lintel opening={opening} height={height} />
            <Glazed width={opening.width} height={height} position={[opening.x, 0, -T / 2]} />
          </group>
        );
      })}
      <mesh position={[0, STORE_WALL.height + STORE_WALL.cap / 2, -T / 2]}>
        <boxGeometry args={[length, STORE_WALL.cap, T]} />
        <meshStandardMaterial color={WALL_CAP_COLOR} roughness={0.6} />
      </mesh>
      {children}
    </group>
  );
}

/** Vertical wood battens: a modern feature panel centered on the back wall. */
function SlatPanel() {
  const ref = useRef<InstancedMesh>(null);
  const count = Math.floor(WALL_SLATS.panelWidth / WALL_SLATS.pitch);
  const height = BODY_HEIGHT;

  useLayoutEffect(() => {
    const mesh = ref.current;
    if (!mesh) return;
    const dummy = new Object3D();
    const start = -((count - 1) * WALL_SLATS.pitch) / 2;
    for (let i = 0; i < count; i += 1) {
      dummy.position.set(start + i * WALL_SLATS.pitch, STORE_WALL.shadowGap + height / 2, WALL_SLATS.depth / 2);
      dummy.updateMatrix();
      mesh.setMatrixAt(i, dummy.matrix);
    }
    mesh.instanceMatrix.needsUpdate = true;
  }, [count, height]);

  return (
    <instancedMesh ref={ref} args={[undefined, undefined, count]} castShadow receiveShadow>
      <boxGeometry args={[WALL_SLATS.width, height, WALL_SLATS.depth]} />
      <meshStandardMaterial color={WALL_SLAT_COLOR} roughness={0.6} />
    </instancedMesh>
  );
}

export function Walls() {
  return (
    <group name="walls">
      <Wall
        name="wall-back"
        length={STORE_FLOOR.width + 2 * T}
        position={[0, 0, -HALF_D]}
        rotationY={0}
        isBehind={(camera) => camera.position.z < -HALF_D}
        openings={[{ x: GLAZING.doorX, width: GLAZING.doorWidth, kind: "door" }]}
      >
        <SlatPanel />
      </Wall>
      <Wall
        name="wall-left"
        length={STORE_FLOOR.depth}
        position={[-HALF_W, 0, 0]}
        rotationY={Math.PI / 2}
        isBehind={(camera) => camera.position.x < -HALF_W}
        openings={[{ x: 0, width: STORE_FLOOR.depth - 2 * GLAZING.endPier, kind: "window" }]}
      />
      <Wall
        name="wall-front"
        length={STORE_FLOOR.width + 2 * T}
        position={[0, 0, HALF_D]}
        rotationY={Math.PI}
        isBehind={(camera) => camera.position.z > HALF_D}
        openings={[{ x: 0, width: STORE_FLOOR.width - 2 * GLAZING.endPier, kind: "window" }]}
      />
      <Wall
        name="wall-right"
        length={STORE_FLOOR.depth}
        position={[HALF_W, 0, 0]}
        rotationY={-Math.PI / 2}
        isBehind={(camera) => camera.position.x > HALF_W}
      />
    </group>
  );
}
