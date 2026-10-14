import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import { Box3, DoubleSide, type Group, type Mesh } from "three";
import { ASSETS_MODE } from "@/enums/stock.enum";
import { assetsMode } from "@/scene/entities/stock/models";
import {
  BUS_STOP,
  DECOR_ITEMS,
  PAVEMENT_TOP,
  LOT_TOP,
  PARKING_LINES,
  PARKING_LOT,
  PARK_PATHS,
  PARK_PAVING_Y,
  PLAZA,
  POND,
  POND_WATER_Y,
  WALK,
} from "@/fixtures/decorFixture";
import { STORE_FLOOR } from "@/constants/dimensions.constant";

/** The lot's slab starts at the lawn's top. */
const PARKING_BASE = -(STORE_FLOOR.thickness + 0.01);
import {
  NO_DECOR,
  fitDecor,
  loadDecor,
  type DecorItem,
  type DecorModel,
  type DecorModels,
} from "./decorModels";

/** The decor GLB files, once loaded; none under `?assets=primitive`. */
function useDecorModels(items: readonly DecorItem[]): DecorModels {
  const [models, setModels] = useState<DecorModels>(NO_DECOR);
  useEffect(() => {
    if (items.length === 0 || assetsMode() === ASSETS_MODE.Primitive) return;
    let live = true;
    void loadDecor(items).then((loaded) => {
      if (live) setModels(loaded);
    });
    return () => {
      live = false;
    };
  }, [items]);
  return models;
}

/** A piece's group and its world bounds, measured once it is placed (decor never moves). */
type Placed = { group: Group; bounds: Box3 };
/** How far outside a piece the camera still hides it, in meters: a near plane's worth. */
const HIDE_MARGIN = 0.6;

function Piece({
  item,
  model,
  placed,
}: {
  item: DecorItem;
  model: DecorModel;
  placed: Map<string, Placed>;
}) {
  // Clones share the file's geometry and materials.
  const scene = useMemo(() => model.scene.clone(true), [model]);
  const { scale, offset } = fitDecor(model.size, model.base, item.fit);
  const ref = useRef<Group>(null);
  useLayoutEffect(() => {
    const group = ref.current;
    if (!group) return;
    group.updateWorldMatrix(true, true);
    placed.set(item.id, {
      group,
      bounds: new Box3().setFromObject(group).expandByScalar(HIDE_MARGIN),
    });
    return () => {
      placed.delete(item.id);
    };
  }, [item, placed, scene]);
  return (
    <group
      ref={ref}
      name={`decor-${item.id}`}
      position={[item.at[0], item.y ?? 0, item.at[1]]}
      rotation-y={item.rotationY ?? 0}
    >
      <primitive object={scene} scale={scale} position={offset} />
    </group>
  );
}

const noRaycast = () => {};

/**
 * The parking lot: a kerb slab, one asphalt surface inset in it, and the painted bay lines.
 * Drawn here rather than tiled, so the surface has no seams.
 */
function ParkingLot() {
  const [x0, x1] = PARKING_LOT.x;
  const [z0, z1] = PARKING_LOT.z;
  const { kerb } = PARKING_LOT;
  const center: [number, number] = [(x0 + x1) / 2, (z0 + z1) / 2];
  const height = LOT_TOP - PARKING_BASE;
  return (
    <group name="decor-parking-lot">
      <mesh
        position={[center[0], PARKING_BASE + height / 2, center[1]]}
        receiveShadow
        raycast={noRaycast}
      >
        <boxGeometry args={[x1 - x0, height, z1 - z0]} />
        <meshStandardMaterial color="#c9ccd6" roughness={0.95} />
      </mesh>
      <mesh
        position={[center[0], LOT_TOP + 0.02, center[1]]}
        rotation-x={-Math.PI / 2}
        receiveShadow
        raycast={noRaycast}
      >
        <planeGeometry args={[x1 - x0 - 2 * kerb, z1 - z0 - 2 * kerb]} />
        <meshStandardMaterial color="#5e6271" roughness={0.95} />
      </mesh>
      {PARKING_LINES.map(({ at, length }, i) => (
        <mesh
          key={i}
          position={[at[0], LOT_TOP + 0.04, at[1]]}
          rotation-x={-Math.PI / 2}
          raycast={noRaycast}
        >
          <planeGeometry args={[0.12, length]} />
          <meshStandardMaterial color="#f4f4ef" roughness={0.9} />
        </mesh>
      ))}
    </group>
  );
}

const PAVING = "#d8d0bf";
const STONE = "#c9ccd6";
const WATER = "#5fb3d9";

/** Water: flat-shaded, a touch of glow so it reads in shadow. */
function Water({
  radius,
  y,
  segments = 24,
}: {
  radius: number;
  y: number;
  segments?: number;
}) {
  return (
    <mesh position-y={y} rotation-x={-Math.PI / 2} raycast={noRaycast}>
      <circleGeometry args={[radius, segments]} />
      <meshStandardMaterial
        color={WATER}
        emissive={WATER}
        emissiveIntensity={0.15}
        roughness={0.15}
        metalness={0.1}
      />
    </mesh>
  );
}

/**
 * The park's centrepiece: an octagonal two-tier fountain, its jet rising and falling gently.
 * Low-poly and flat-shaded to sit with the Kenney pieces round it.
 */
function Fountain() {
  const jet = useRef<Mesh>(null);
  useFrame(({ clock }) => {
    if (jet.current)
      jet.current.scale.y = 1 + Math.sin(clock.elapsedTime * 2.2) * 0.12;
  });
  return (
    <group
      name="decor-fountain"
      position={[PLAZA.at[0], PARK_PAVING_Y, PLAZA.at[1]]}
    >
      {/* The basin: an octagonal wall, water inside it. */}
      <mesh position-y={0.25} castShadow receiveShadow raycast={noRaycast}>
        <cylinderGeometry args={[2, 2.1, 0.5, 8, 1, true]} />
        <meshStandardMaterial
          color={STONE}
          roughness={0.9}
          flatShading
          side={DoubleSide}
        />
      </mesh>
      <mesh position-y={0.5} rotation-x={-Math.PI / 2} raycast={noRaycast}>
        <ringGeometry args={[1.82, 2, 8]} />
        <meshStandardMaterial color={STONE} roughness={0.9} flatShading />
      </mesh>
      <Water radius={1.85} y={0.38} segments={8} />
      {/* The column and the upper bowl, water in it too. */}
      <mesh position-y={0.8} castShadow raycast={noRaycast}>
        <cylinderGeometry args={[0.22, 0.32, 1.1, 8]} />
        <meshStandardMaterial color={STONE} roughness={0.9} flatShading />
      </mesh>
      <mesh position-y={1.42} castShadow raycast={noRaycast}>
        <cylinderGeometry args={[0.85, 0.3, 0.3, 8]} />
        <meshStandardMaterial color={STONE} roughness={0.9} flatShading />
      </mesh>
      <Water radius={0.75} y={1.56} segments={8} />
      {/* The jet: a slim cone from the bowl, and a crown of spray. */}
      <mesh ref={jet} position-y={1.56} raycast={noRaycast}>
        <cylinderGeometry args={[0.04, 0.12, 1.1, 6]} />
        <meshStandardMaterial
          color="#cdeefc"
          emissive="#cdeefc"
          emissiveIntensity={0.3}
          transparent
          opacity={0.75}
          flatShading
        />
      </mesh>
      <mesh position-y={2.15} raycast={noRaycast}>
        <icosahedronGeometry args={[0.2, 0]} />
        <meshStandardMaterial
          color="#e6f7ff"
          emissive="#e6f7ff"
          emissiveIntensity={0.3}
          transparent
          opacity={0.8}
          flatShading
        />
      </mesh>
    </group>
  );
}

const WALK_WIDTH = 1.6;

/** A straight paved strip on the lawn. */
function Strip({
  from,
  to,
  width,
}: {
  from: readonly [number, number];
  to: readonly [number, number];
  width: number;
}) {
  const [dx, dz] = [to[0] - from[0], to[1] - from[1]];
  return (
    <mesh
      position={[(from[0] + to[0]) / 2, PARK_PAVING_Y, (from[1] + to[1]) / 2]}
      rotation-y={Math.atan2(dx, dz)}
      receiveShadow
      raycast={noRaycast}
    >
      <boxGeometry args={[width, 0.04, Math.hypot(dx, dz)]} />
      <meshStandardMaterial color={PAVING} roughness={0.95} />
    </mesh>
  );
}

/** The park's ground: the front walk, paths, the paved plaza with a darker edge, and the pond's water. */
function Park() {
  return (
    <group name="decor-park">
      {PARK_PATHS.map(({ from, to, width }, i) => (
        <Strip key={i} from={from} to={to} width={width} />
      ))}
      {/* The front walk: a strip between each pair of points, a round joint at each point. */}
      {WALK.slice(1).map((to, i) => (
        <Strip key={`walk-${i}`} from={WALK[i]} to={to} width={WALK_WIDTH} />
      ))}
      {WALK.map(([x, z], i) => (
        <mesh
          key={`joint-${i}`}
          position={[x, PARK_PAVING_Y, z]}
          receiveShadow
          raycast={noRaycast}
        >
          <cylinderGeometry args={[WALK_WIDTH / 2, WALK_WIDTH / 2, 0.04, 12]} />
          <meshStandardMaterial color={PAVING} roughness={0.95} />
        </mesh>
      ))}
      <mesh
        position={[PLAZA.at[0], PARK_PAVING_Y + 0.01, PLAZA.at[1]]}
        receiveShadow
        raycast={noRaycast}
      >
        <cylinderGeometry
          args={[PLAZA.radius + 0.25, PLAZA.radius + 0.25, 0.04, 32]}
        />
        <meshStandardMaterial color="#b9b09d" roughness={0.95} />
      </mesh>
      <mesh
        position={[PLAZA.at[0], PARK_PAVING_Y + 0.02, PLAZA.at[1]]}
        receiveShadow
        raycast={noRaycast}
      >
        <cylinderGeometry args={[PLAZA.radius, PLAZA.radius, 0.04, 32]} />
        <meshStandardMaterial color={PAVING} roughness={0.95} />
      </mesh>
      <Fountain />
      <group position={[POND.at[0], 0, POND.at[1]]}>
        <Water radius={POND.radius} y={POND_WATER_Y} />
      </group>
    </group>
  );
}

/**
 * The bus stop's shelter, open to the road (+Z): a roof on four posts, a glass back and one glass
 * end, an advert panel at the other end, and the stop's sign on a pole beside it.
 */
function BusShelter() {
  const { length, depth, height } = BUS_STOP;
  const posts: [number, number][] = [
    [-length / 2, -depth / 2],
    [length / 2, -depth / 2],
    [-length / 2, depth / 2],
    [length / 2, depth / 2],
  ];
  return (
    <group
      name="decor-bus-stop"
      position={[BUS_STOP.at[0], PAVEMENT_TOP, BUS_STOP.at[1]]}
    >
      {posts.map(([x, z], i) => (
        <mesh
          key={i}
          position={[x, height / 2, z]}
          castShadow
          raycast={noRaycast}
        >
          <boxGeometry args={[0.08, height, 0.08]} />
          <meshStandardMaterial color="#4a5060" roughness={0.6} />
        </mesh>
      ))}
      <mesh
        position-y={height + 0.05}
        castShadow
        receiveShadow
        raycast={noRaycast}
      >
        <boxGeometry args={[length + 0.3, 0.1, depth + 0.3]} />
        <meshStandardMaterial color="#4a5060" roughness={0.6} />
      </mesh>
      <mesh
        position={[0, 0.25 + (height - 0.5) / 2, -depth / 2]}
        raycast={noRaycast}
      >
        <boxGeometry args={[length, height - 0.5, 0.03]} />
        <meshStandardMaterial
          color="#bfe3f0"
          transparent
          opacity={0.4}
          roughness={0.1}
        />
      </mesh>
      <mesh
        position={[-length / 2, 0.25 + (height - 0.5) / 2, 0]}
        raycast={noRaycast}
      >
        <boxGeometry args={[0.03, height - 0.5, depth]} />
        <meshStandardMaterial
          color="#bfe3f0"
          transparent
          opacity={0.4}
          roughness={0.1}
        />
      </mesh>
      <mesh
        position={[length / 2, 0.3 + 0.9, 0]}
        castShadow
        raycast={noRaycast}
      >
        <boxGeometry args={[0.08, 1.8, depth - 0.2]} />
        <meshStandardMaterial
          color="#f2c14e"
          emissive="#f2c14e"
          emissiveIntensity={0.2}
          roughness={0.5}
        />
      </mesh>
      {/* The sign: a pole by the kerb, a blue plate with a white band. */}
      <group position={[length / 2 + 0.7, 0, depth / 2 + 0.3]}>
        <mesh position-y={1.4} castShadow raycast={noRaycast}>
          <cylinderGeometry args={[0.04, 0.04, 2.8, 8]} />
          <meshStandardMaterial color="#8a8f9c" roughness={0.6} />
        </mesh>
        <mesh position-y={2.65} castShadow raycast={noRaycast}>
          <boxGeometry args={[0.6, 0.6, 0.04]} />
          <meshStandardMaterial color="#2f6fd6" roughness={0.5} />
        </mesh>
        <mesh position={[0, 2.65, 0.025]} raycast={noRaycast}>
          <boxGeometry args={[0.6, 0.14, 0.01]} />
          <meshStandardMaterial color="#ffffff" roughness={0.5} />
        </mesh>
      </group>
    </group>
  );
}

/**
 * Plants and furnishings around the store, the lawn, the street, and the parking lot
 * (`fixtures/decorFixture.ts`). Decor
 * is not twin state: it has no entity id, takes no clicks, and appears once its files load.
 */
export function Decor({
  items = DECOR_ITEMS,
}: {
  items?: readonly DecorItem[];
}) {
  const models = useDecorModels(items);
  const gl = useThree((state) => state.gl);
  // Shadows are drawn on demand (`StaticShadows`): redraw them once the decor is in.
  useEffect(() => {
    gl.shadowMap.needsUpdate = true;
  }, [gl, models]);
  // A wide zoom-out orbits the camera through the street; a piece the camera is inside is hidden,
  // so the view never fills with the inside of a wall or a tree.
  const placed = useMemo(() => new Map<string, Placed>(), []);
  useFrame(({ camera }) => {
    for (const { group, bounds } of placed.values())
      group.visible = !bounds.containsPoint(camera.position);
  });
  return (
    <group name="decor">
      {items.map((item) => {
        const model = models.get(item.file);
        return model ? (
          <Piece key={item.id} item={item} model={model} placed={placed} />
        ) : null;
      })}
      {models.size > 0 ? (
        <>
          <ParkingLot />
          <Park />
          <BusShelter />
        </>
      ) : null}
    </group>
  );
}
