import { GLAZING, STORE_FLOOR } from "@/constants/dimensions.constant";
import { mulberry32 } from "@/core/utils/random";
import type { DecorItem } from "@/scene/entities/decor/decorModels";

/**
 * Plants, furnishings, and the street around the store, placed by hand. Store frame: the
 * floor spans x -7..7 and z -5.5..5.5, the back wall (door at x = 4.4) is at z = -5.5, and the
 * glass wall is at x = -7. Presentation only, like the wooden crates: nothing here is twin
 * state. Sources and licenses: `assets/3d/README.md`.
 */

/** The lawn's top, just under the store's floor slab (`Exterior`). */
const GROUND = -(STORE_FLOOR.thickness + 0.01);
/** A pavement slab's top (tile-high flattened to 15 cm, standing on the lawn). */
export const PAVEMENT_TOP = GROUND + 0.15;
/** The pond's water, just over the lawn, inside its ring of stones. */
export const POND_WATER_Y = GROUND + 0.03;
/** The park's paving, a hair over the lawn. */
export const PARK_PAVING_Y = GROUND + 0.02;
/** Kenney's city kits are about 1 unit to 9.5 m: a road tile is a two-lane, 9.5 m square. */
const CITY = 9.5;
/** Kenney's car kit: a sedan comes out about 3.6 m long and 2.1 m wide (the kit draws cars chunky). */
const CAR = 1.4;
const TURN = Math.PI / 2;

const piece = (id: string, file: string, at: [number, number], fit: DecorItem["fit"], rotationY = 0, y = GROUND): DecorItem => ({
  id,
  file,
  at,
  fit,
  rotationY,
  y,
});
const city = (id: string, file: string, at: [number, number], rotationY = 0) =>
  piece(id, file, at, { scale: [CITY, CITY, CITY] }, rotationY);

/** Inside: plants in the free corners and by the door, the door mat, a bin, and the basket bay. */
const INSIDE: DecorItem[] = [
  piece("plant-back-left", "tinytreats/zz-plant.glb", [-6.45, -5.05], { height: 1.1 }, 0, 0),
  piece("plant-front-left", "tinytreats/sansevieria.glb", [-6.45, 5.0], { height: 1.15 }, 0, 0),
  piece("plant-front-right", "tinytreats/zz-plant.glb", [6.45, 5.0], { height: 1.1 }, TURN, 0),
  piece("plant-door", "tinytreats/sansevieria.glb", [GLAZING.doorX - GLAZING.doorWidth / 2 - 0.35, -5.1], { height: 1.05 }, 0, 0),
  piece("door-mat", "kenney-furniture/rugDoormat.glb", [GLAZING.doorX, -5.05], { width: 1.8 }, 0, 0.002),
  piece("bin-exit", "kenney-furniture/trashcan.glb", [GLAZING.doorX - GLAZING.doorWidth / 2 - 0.95, -5.15], { height: 0.75 }, 0, 0),
  // The basket bay: the railed pocket by the door, between BR02 (x = 2.7), the cross
  // rail BR05 (z = -2.2), and the door divider BR03/BR04 (x = 4.4).
  ...[0, 1, 2].map((i) =>
    piece(`basket-${i}`, "kenney-mini-market/shopping-basket.glb", [3.1, -2.75], { height: 0.28 }, 0.1 * i, 0.16 * i),
  ),
];

/** The lawn seen through the glass wall: trees at a few depths, bushes and flowers along the glass. */
const LAWN: DecorItem[] = [
  piece("tree-1", "kenney-nature/tree_oak.glb", [-11, -2.5], { height: 4.2 }, 0.4),
  piece("tree-2", "kenney-nature/tree_detailed.glb", [-14.5, 2.5], { height: 5 }, 1.2),
  piece("tree-3", "kenney-nature/tree_default.glb", [-10.5, 4.2], { height: 3.6 }, 2.1),
  piece("tree-4", "kenney-nature/tree_fat.glb", [-17, -4.5], { height: 4.5 }, 0.9),
  ...[-4, -1.5, 1, 3.5].map((z, i) =>
    piece(`bush-${i}`, i % 2 ? "kenney-nature/plant_bushLarge.glb" : "kenney-nature/plant_bushDetailed.glb", [-7.8, z], { height: 0.7 }, i),
  ),
  ...[-2.7, -0.2, 2.3, 4.6].map((z, i) =>
    piece(`flower-${i}`, i % 2 ? "kenney-nature/flower_yellowB.glb" : "kenney-nature/flower_redA.glb", [-7.6, z], { height: 0.35 }, i * 0.7),
  ),
];

/**
 * The block around the store: a loop of two-lane roads (behind the store, where the door is;
 * in front, across the park; and down both sides), pavements along them, shopfronts across the
 * back road, houses across the front one, and the town beyond.
 */
const PAVEMENT_DEPTH = 3.2;
const HALF_ROAD = CITY / 2;
const PAVEMENT_Z = -STORE_FLOOR.depth / 2 - 0.1 - PAVEMENT_DEPTH / 2;
const ROAD_Z = PAVEMENT_Z - PAVEMENT_DEPTH / 2 - HALF_ROAD;
const FAR_PAVEMENT_Z = ROAD_Z - HALF_ROAD - PAVEMENT_DEPTH / 2;
/** Road tiles every 9.5 m along x, one of them centered on the door. */
const ROAD_XS = Array.from({ length: 8 }, (_, i) => GLAZING.doorX + (i - 4) * CITY);
/** The side roads close the loop one tile past each end; the front road is four tiles from the back one. */
const WEST_X = ROAD_XS[0] - CITY;
const EAST_X = ROAD_XS[ROAD_XS.length - 1] + CITY;
const FRONT_ROAD_Z = ROAD_Z + 4 * CITY;
const MID_X = (WEST_X + EAST_X) / 2;
const MID_Z = (FRONT_ROAD_Z + ROAD_Z) / 2;
const FRONT_PAVEMENT_Z = [FRONT_ROAD_Z - HALF_ROAD - PAVEMENT_DEPTH / 2, FRONT_ROAD_Z + HALF_ROAD + PAVEMENT_DEPTH / 2] as const;
/** The parking lot's driveway tile, on the road beside the store. */
const DRIVEWAY_X = GLAZING.doorX + CITY;
/**
 * The street grid: the store's loop, every road of it carried on three tiles to an outer ring,
 * so the town around it is cut into blocks. Road center lines, west to east and north (the back,
 * -Z) to south.
 */
const GRID_XS = [WEST_X - 3 * CITY, WEST_X, EAST_X, EAST_X + 3 * CITY] as const;
const GRID_ZS = [ROAD_Z - 3 * CITY, ROAD_Z, FRONT_ROAD_Z, FRONT_ROAD_Z + 3 * CITY] as const;
const tilesAlong = (from: number, to: number) => Array.from({ length: Math.round((to - from) / CITY) + 1 }, (_, i) => from + i * CITY);
/** Which ways a junction opens: north (-Z), east (+X), south (+Z), west (-X). */
type Ways = { north: boolean; east: boolean; south: boolean; west: boolean };
/**
 * The tile and turn for a junction. Unturned, Kenney's bend joins -X and +Z (west and south), its
 * T (road-intersection) runs -X to +X with a branch to +Z (all but north), and its crossroad is
 * four-way. Turns are about Y, as three applies them.
 */
export const junction = ({ north, east, south, west }: Ways): { file: string; turn: number } => {
  const open = [north, east, south, west].filter(Boolean).length;
  if (open === 4) return { file: "kenney-city-roads/road-crossroad.glb", turn: 0 };
  if (open === 3) {
    const turn = !north ? 0 : !west ? TURN : !south ? Math.PI : -TURN;
    return { file: "kenney-city-roads/road-intersection.glb", turn };
  }
  const turn = west && south ? 0 : north && west ? -TURN : north && east ? Math.PI : TURN;
  return { file: "kenney-city-roads/road-bend.glb", turn };
};
/** The blocks between the roads, as [xMin, xMax, zMin, zMax] inside the road edges. */
const BLOCKS = GRID_XS.slice(1).flatMap((x1, i) =>
  GRID_ZS.slice(1).map((z1, j) => [GRID_XS[i] + HALF_ROAD, x1 - HALF_ROAD, GRID_ZS[j] + HALF_ROAD, z1 - HALF_ROAD] as const),
);
/** The ring's outside edge, where the outer pavement starts. */
const RING = { x: [GRID_XS[0] - HALF_ROAD, GRID_XS[3] + HALF_ROAD], z: [GRID_ZS[0] - HALF_ROAD, GRID_ZS[3] + HALF_ROAD] } as const;

/** tile-high is a 1 x 0.25 x 1 kerb block; flattened to a 15 cm pavement slab of any size. */
const pavement = (id: string, at: [number, number], size: [number, number]) =>
  piece(id, "kenney-city-roads/tile-high.glb", at, { scale: [size[0], 0.6, size[1]] });

/** A pavement round the inside of each block, and one round the outside of the ring. */
const PAVEMENTS: DecorItem[] = [
  ...BLOCKS.flatMap(([x0, x1, z0, z1], b) => {
    const [w, d] = [x1 - x0, z1 - z0];
    const [cx, cz] = [(x0 + x1) / 2, (z0 + z1) / 2];
    return [
      pavement(`pavement-${b}-n`, [cx, z0 + PAVEMENT_DEPTH / 2], [w, PAVEMENT_DEPTH]),
      pavement(`pavement-${b}-s`, [cx, z1 - PAVEMENT_DEPTH / 2], [w, PAVEMENT_DEPTH]),
      pavement(`pavement-${b}-w`, [x0 + PAVEMENT_DEPTH / 2, cz], [PAVEMENT_DEPTH, d - 2 * PAVEMENT_DEPTH]),
      pavement(`pavement-${b}-e`, [x1 - PAVEMENT_DEPTH / 2, cz], [PAVEMENT_DEPTH, d - 2 * PAVEMENT_DEPTH]),
    ];
  }),
  pavement("pavement-ring-n", [MID_X, RING.z[0] - PAVEMENT_DEPTH / 2], [RING.x[1] - RING.x[0] + 2 * PAVEMENT_DEPTH, PAVEMENT_DEPTH]),
  pavement("pavement-ring-s", [MID_X, RING.z[1] + PAVEMENT_DEPTH / 2], [RING.x[1] - RING.x[0] + 2 * PAVEMENT_DEPTH, PAVEMENT_DEPTH]),
  pavement("pavement-ring-w", [RING.x[0] - PAVEMENT_DEPTH / 2, (RING.z[0] + RING.z[1]) / 2], [PAVEMENT_DEPTH, RING.z[1] - RING.z[0]]),
  pavement("pavement-ring-e", [RING.x[1] + PAVEMENT_DEPTH / 2, (RING.z[0] + RING.z[1]) / 2], [PAVEMENT_DEPTH, RING.z[1] - RING.z[0]]),
];

/** Every road tile of the grid: junctions where lines cross, straights between. */
const ROADS: DecorItem[] = (() => {
  const items: DecorItem[] = [];
  const onX = (x: number) => GRID_XS.some((g) => Math.abs(g - x) < 0.01);
  const onZ = (z: number) => GRID_ZS.some((g) => Math.abs(g - z) < 0.01);
  // The crossroads round the store have traffic lights, so each of their arms gets a zebra crossing.
  const lit = (x: number, z: number) => GRID_XS.slice(1, 3).some((g) => Math.abs(g - x) < 0.01) && GRID_ZS.slice(1, 3).some((g) => Math.abs(g - z) < 0.01);
  const besideLit = (x: number, z: number) =>
    lit(x - CITY, z) || lit(x + CITY, z) || lit(x, z - CITY) || lit(x, z + CITY);
  const straight = (x: number, z: number) =>
    besideLit(x, z) ? "kenney-city-roads/road-crossing.glb" : "kenney-city-roads/road-straight.glb";
  for (const z of GRID_ZS) {
    for (const x of tilesAlong(GRID_XS[0], GRID_XS[3])) {
      if (onX(x)) {
        const { file, turn } = junction({ north: z > GRID_ZS[0], south: z < GRID_ZS[3], west: x > GRID_XS[0], east: x < GRID_XS[3] });
        items.push(city(`road-${x.toFixed(1)}-${z.toFixed(1)}`, file, [x, z], turn));
        continue;
      }
      // The back road has the crossing at the door and the lot's driveway.
      const file =
        z === ROAD_Z && Math.abs(x - GLAZING.doorX) < 0.01
          ? "kenney-city-roads/road-crossing.glb"
          : z === ROAD_Z && Math.abs(x - DRIVEWAY_X) < 0.01
            ? "kenney-city-roads/road-driveway-single.glb"
            : straight(x, z);
      items.push(city(`road-${x.toFixed(1)}-${z.toFixed(1)}`, file, [x, z]));
    }
  }
  for (const x of GRID_XS) {
    for (const z of tilesAlong(GRID_ZS[0], GRID_ZS[3])) {
      if (!onZ(z)) items.push(city(`road-${x.toFixed(1)}-${z.toFixed(1)}`, straight(x, z), [x, z], TURN));
    }
  }
  return items;
})();

/**
 * Street furniture: traffic lights on two facing corners of each crossroad round the store, and
 * a bus stop across the back road from the store, a little west of the door, with a bus pulled in
 * at it. The shelter is drawn by `Decor`; it opens onto the road (+Z). Another bus runs the ring.
 */
export const BUS_STOP = { at: [-12, FAR_PAVEMENT_Z - 0.3] as [number, number], length: 4.4, depth: 1.5, height: 2.5 } as const;
const BUS = "quevedo-vehicles/bus.glb";
const STREET_FURNITURE: DecorItem[] = [
  ...GRID_XS.slice(1, 3).flatMap((x) =>
    GRID_ZS.slice(1, 3).flatMap((z) =>
      ([
        [-1, -1, 0],
        [1, 1, Math.PI],
      ] as const).map(([sx, sz, turn]) =>
        city(`traffic-light-${x.toFixed(0)}-${z.toFixed(0)}-${sx}`, "kenney-city-roads/traffic-light.glb", [x + sx * (HALF_ROAD + 0.7), z + sz * (HALF_ROAD + 0.7)], turn),
      ),
    ),
  ),
  ...[-0.7, 0.7].map((dx, i) =>
    piece(`bus-stop-bench-${i}`, "kenney-furniture/bench.glb", [BUS_STOP.at[0] + dx, BUS_STOP.at[1] - 0.15], { height: 0.85 }, 0, PAVEMENT_TOP),
  ),
  piece("bus-stopped", BUS, [BUS_STOP.at[0] + 1.5, ROAD_Z - 2.3], { width: 2.55 }, TURN),
  piece("bus-ring", BUS, [GRID_XS[3] + 2.3, MID_Z + 6], { width: 2.55 }, Math.PI),
];

/** Shopfronts across the back road, along the block between the side roads. */
const SHOPS = ["building-b", "building-a", "building-c", "building-f", "building-d", "building-a", "building-c"] as const;
/** The center x of the blocks west and east of the store's loop. */
const OUTER_BLOCK_XS = [(GRID_XS[0] + GRID_XS[1]) / 2, (GRID_XS[2] + GRID_XS[3]) / 2] as const;
const SHOP_Z = FAR_PAVEMENT_Z - PAVEMENT_DEPTH / 2 - 5.5;

const STREET: DecorItem[] = [
  ...PAVEMENTS,
  ...ROADS,
  ...STREET_FURNITURE,
  // Street lights on the store's side of the back road, and street trees on the far side.
  ...[-2, 0, 2].map((k) => city(`light-${k}`, "kenney-city-roads/light-square.glb", [GLAZING.doorX + k * CITY - HALF_ROAD, PAVEMENT_Z - 1.1])),
  ...[-2.5, -0.5, 1.5].map((k) => piece(`street-tree-${k}`, "kenney-city-suburban/tree-large.glb", [k * 10, FAR_PAVEMENT_Z], { height: 5.5 })),
  // Shopfronts across the back road, held to two or three storeys so an orbit over the back never puts the camera inside one.
  ...SHOPS.map((name, i) =>
    piece(`shop-${i}`, `kenney-city-commercial/${name}.glb`, [MID_X + (i - (SHOPS.length - 1) / 2) * 10, SHOP_Z], { height: 9 + (i % 3) }),
  ),
  // One more on each corner block across the ring roads.
  ...OUTER_BLOCK_XS.map((x, i) => piece(`corner-shop-${i}`, `kenney-city-commercial/${i ? "building-f" : "building-d"}.glb`, [x, SHOP_Z], { height: 10 })),
  // A few cars on the roads, each in its lane (Kenney's cars are long along Z).
  ...([
    ["sedan", -20, ROAD_Z + 2.3, -TURN],
    ["van", 26, ROAD_Z - 2.3, TURN],
    ["taxi", -12, FRONT_ROAD_Z + 2.3, -TURN],
    ["hatchback-sports", 30, FRONT_ROAD_Z - 2.3, TURN],
    ["suv", EAST_X + 2.3, MID_Z, Math.PI],
    ["sedan", WEST_X - 2.3, MID_Z - 6, 0],
    ["van", GRID_XS[0] + 2.3, MID_Z + 4, Math.PI],
    ["taxi", GRID_XS[3] - 2.3, MID_Z - 10, 0],
    ["suv", -45, GRID_ZS[0] + 2.3, -TURN],
    ["sedan", 50, GRID_ZS[3] - 2.3, TURN],
  ] as const).map(([car, x, z, turn], i) => piece(`traffic-${i}`, `kenney-car-kit/${car}.glb`, [x, z], { scale: [CAR, CAR, CAR] }, turn)),
];

/**
 * The parking lot on the right of the store: one asphalt surface inside a kerb (drawn by
 * `Decor`, not tiled, so it has no seams), two rows of bays nosing onto a middle aisle, and the
 * driveway onto the back road.
 */
const BAY = 2.6;
const BAY_DEPTH = 5;
const AISLE = 6.5;
const BAYS_PER_ROW = 7;
const LOT_KERB = 0.4;
const LOT_X0 = DRIVEWAY_X - HALF_ROAD;
const LOT_Z0 = PAVEMENT_Z + PAVEMENT_DEPTH / 2;
const LOT_X1 = LOT_X0 + BAYS_PER_ROW * BAY + 2 * LOT_KERB;
const LOT_Z1 = LOT_Z0 + 2 * BAY_DEPTH + AISLE + 2 * LOT_KERB;
/** Center z of each row of bays: the back row, then the front one across the aisle. */
const ROW_ZS = [LOT_Z0 + LOT_KERB + BAY_DEPTH / 2, LOT_Z1 - LOT_KERB - BAY_DEPTH / 2] as const;
const bayX = (bay: number) => LOT_X0 + LOT_KERB + (bay + 0.5) * BAY;

export const PARKING_LOT = { x: [LOT_X0, LOT_X1], z: [LOT_Z0, LOT_Z1], kerb: LOT_KERB } as const;

const PARKING: DecorItem[] = [
  ...([
    [0, 0, "sedan"],
    [0, 2, "suv"],
    [0, 3, "taxi"],
    [0, 6, "van"],
    [1, 1, "hatchback-sports"],
    [1, 4, "sedan"],
    [1, 5, "taxi"],
  ] as const).map(([row, bay, car]) =>
    // Nose in: the back row faces the back, the front row the front.
    piece(`car-${row}-${bay}`, `kenney-car-kit/${car}.glb`, [bayX(bay), ROW_ZS[row]], { scale: [CAR, CAR, CAR] }, row ? 0 : Math.PI),
  ),
  ...[0.25, 0.5, 0.75].map((t, i) =>
    piece(`lot-planter-${i}`, "kenney-city-suburban/planter.glb", [LOT_X0 + t * (LOT_X1 - LOT_X0), LOT_Z1 + 1.5], { height: 0.9 }),
  ),
];

/** Painted bay lines: one at each boundary between bays, in each row. */
export const PARKING_LINES: ReadonlyArray<{ at: [number, number]; length: number }> = ROW_ZS.flatMap((z) =>
  Array.from({ length: BAYS_PER_ROW + 1 }, (_, k) => ({ at: [LOT_X0 + LOT_KERB + k * BAY, z] as [number, number], length: BAY_DEPTH - 0.4 })),
);

/**
 * In front of the store (+Z, the side the camera looks in from): a small park with a winding
 * stepping-stone walk along it, benches beside the walk facing it, flower beds, and a few
 * trees, all kept low near the camera's line of sight; then the front road, and houses across it.
 */
const PARK_Z = STORE_FLOOR.depth / 2 + 5;
/** The walk runs from the lawn by the glass wall to the lot's kerb, wiggling gently. */
const WALK_XS = Array.from({ length: 22 }, (_, i) => -12 + i * 1.0);
const walkZ = (x: number) => PARK_Z + Math.sin(x * 0.35) * 0.8;
/** Kenney's suburban houses at three quarters of the city kits' scale: 7–10 m wide, 7–10 m deep. */
const HOUSE_SCALE = 0.75 * CITY;
const house = (id: string, type: string, at: [number, number], rotationY: number) =>
  piece(id, `kenney-city-suburban/building-type-${type}.glb`, at, { scale: [HOUSE_SCALE, HOUSE_SCALE, HOUSE_SCALE] }, rotationY);
/** Front yards: a fence at the pavement, a garden, then the house. */
const YARD_FENCE_Z = FRONT_PAVEMENT_Z[1] + PAVEMENT_DEPTH / 2 + 0.4;
const HOUSE_Z = YARD_FENCE_Z + 7.4;
/** Kenney's fence panel, 0.9 m high, is this long. */
const FENCE_PANEL = 1.58;
/** A house's width along its street, with a garden's gap to the next. */
const HOUSE_PITCH = 13;
/** Houses across the front road: five along the store's block, one on each corner block (the narrower types). */
const FRONT_HOUSE_XS = [...Array.from({ length: 5 }, (_, i) => MID_X + (i - 2) * HOUSE_PITCH), ...OUTER_BLOCK_XS];
const FRONT_HOUSE_TYPES = ["a", "c", "h", "k", "p", "k", "a"] as const;
const HOUSES = ["a", "c", "f", "h", "k", "b", "d", "m", "p"] as const;

/** The walk's center line, drawn by `Decor` as one paved ribbon 1.6 m wide. */
export const WALK: ReadonlyArray<[number, number]> = WALK_XS.map((x) => [x, walkZ(x)]);

const FRONT: DecorItem[] = [
  // Benches in pairs (Kenney's is a single seat) on the far side of the walk, facing it.
  ...[-6, 1].flatMap((x, i) => [
    piece(`bench-${i}-a`, "kenney-furniture/bench.glb", [x - 0.05, walkZ(x) + 1.5], { height: 0.85 }, Math.PI),
    piece(`bench-${i}-b`, "kenney-furniture/bench.glb", [x + 0.65, walkZ(x) + 1.5], { height: 0.85 }, Math.PI),
  ]),
  // Flower beds: a bush with flowers around it, on both sides of the walk.
  ...([
    [-9, 2.2],
    [-3.2, -1.9],
    [3.8, 2.3],
    [6.5, -1.8],
  ] as const).flatMap(([x, dz], i) => [
    piece(`bed-bush-${i}`, "kenney-nature/plant_bushDetailed.glb", [x, walkZ(x) + dz], { height: 0.7 }, i),
    ...[[-0.7, 0.3], [0.6, 0.4], [0.1, -0.6], [-0.4, -0.5]].map(([fx, fz], k) =>
      piece(`bed-flower-${i}-${k}`, (i + k) % 2 ? "kenney-nature/flower_redA.glb" : "kenney-nature/flower_yellowB.glb", [x + fx, walkZ(x) + dz + fz], { height: 0.35 }, k),
    ),
  ]),
  ...[-4.5, 4.8].map((x, i) => piece(`walk-rock-${i}`, "kenney-nature/rock_smallA.glb", [x, walkZ(x) - 1.2], { height: 0.35 }, i)),
  // Shade trees at the park's west end, away from the camera's line of sight.
  piece("park-tree-0", "kenney-nature/tree_oak.glb", [-10, PARK_Z + 3.5], { height: 4.5 }, 0.7),
  piece("park-tree-1", "kenney-nature/tree_default.glb", [-7.5, PARK_Z - 2.8], { height: 3.8 }, 1.9),
  // Lights and street trees along the front road, where they stay out of the default view (it looks in over x -5..25).
  ...ROAD_XS.filter((x) => (x < -5 || x > 25) && x - HALF_ROAD > WEST_X + HALF_ROAD + 1).flatMap((x, i) => [
    city(`front-light-${i}`, "kenney-city-roads/light-square.glb", [x - HALF_ROAD, FRONT_PAVEMENT_Z[0] + 1.1], Math.PI),
    piece(`front-street-tree-${i}`, "kenney-city-suburban/tree-large.glb", [x, FRONT_PAVEMENT_Z[0]], { height: 5.5 }, i),
  ]),
  // Houses across the front road, fronts toward it, each behind a fenced garden with a small tree.
  ...FRONT_HOUSE_XS.map((x, i) => house(`house-${i}`, FRONT_HOUSE_TYPES[i], [x, HOUSE_Z], Math.PI)),
  // A picket fence along the front of each yard, open at the gate in the middle.
  ...FRONT_HOUSE_XS.flatMap((x, i) =>
    [-3.5, -2.5, -1.5, 1.5, 2.5, 3.5].map((k) =>
      piece(`yard-fence-${i}-${k}`, "kenney-city-suburban/fence.glb", [x + k * FENCE_PANEL, YARD_FENCE_Z], { height: 0.9 }),
    ),
  ),
  ...FRONT_HOUSE_XS.flatMap((x, i) => [
    piece(`garden-bush-${i}`, "kenney-nature/plant_bushLarge.glb", [x - 3.2, YARD_FENCE_Z + 1.4], { height: 0.9 }, i),
    piece(`house-tree-${i}`, "kenney-city-suburban/tree-small.glb", [x + 3.4, YARD_FENCE_Z + 1.8], { height: 4 }, i),
  ]),
];

/**
 * The park west of the store, between the glass wall and the side road: a round plaza with a
 * fountain (drawn by `Decor`), paths from it out to each pavement and to the front walk, benches
 * and lamps round the plaza, flower beds between the paths, and a lily pond in the south-west.
 */
const PARK_AREA = { x: [WEST_X + HALF_ROAD + PAVEMENT_DEPTH, -7.2], z: [PAVEMENT_Z + PAVEMENT_DEPTH / 2, FRONT_PAVEMENT_Z[0] - PAVEMENT_DEPTH / 2] } as const;
export const PLAZA = { at: [-21, 5] as [number, number], radius: 4.2 } as const;
export const POND = { at: [-27.4, 12.4] as [number, number], radius: 2.7 } as const;
/** Paths out of the plaza, as straight strips: north, south, and west to the pavements, east to the walk. */
export const PARK_PATHS: ReadonlyArray<{ from: [number, number]; to: [number, number]; width: number }> = [
  { from: PLAZA.at, to: [PLAZA.at[0], PARK_AREA.z[0]], width: 2 },
  { from: PLAZA.at, to: [PLAZA.at[0], PARK_AREA.z[1]], width: 2 },
  { from: PLAZA.at, to: [PARK_AREA.x[0], PLAZA.at[1]], width: 2 },
  { from: PLAZA.at, to: [WALK_XS[0] + 0.4, walkZ(WALK_XS[0])], width: 1.6 },
];
/** Round the plaza at this angle (radians, from +X toward +Z) a point at radius r. */
const aroundPlaza = (angle: number, r: number): [number, number] => [PLAZA.at[0] + Math.cos(angle) * r, PLAZA.at[1] + Math.sin(angle) * r];
const DIAGONALS = [1, 3, 5, 7].map((k) => (k * Math.PI) / 4);

/** Kenney's simple fence, 1 unit long and 0.35 high, stood 0.9 m high. */
const FENCE_SCALE = 0.9 / 0.345;
/**
 * The fence round the grass of the store's block: just inside its pavements, open wherever a park
 * path comes in, and round the lot's lawn sides rather than its street side, so the lot and its
 * driveway stay open to the back road. On the back the store's own wall is the edge.
 */
const BLOCK_FENCE = {
  x0: WEST_X + HALF_ROAD + PAVEMENT_DEPTH + 0.35,
  x1: EAST_X - HALF_ROAD - PAVEMENT_DEPTH - 0.35,
  z0: PAVEMENT_Z + PAVEMENT_DEPTH / 2 + 0.35,
  z1: FRONT_PAVEMENT_Z[0] - PAVEMENT_DEPTH / 2 - 0.35,
  gate: 1.4,
} as const;
/**
 * A straight run of fence from a to b along x (turn 0) or z, in sections of about 2.5 m, each
 * stretched so the run ends where it should.
 */
const fenceRun = (id: string, along: "x" | "z", at: number, from: number, to: number): DecorItem[] => {
  const count = Math.max(1, Math.round((to - from) / 2.5));
  const length = (to - from) / count;
  return Array.from({ length: count }, (_, k) => {
    const mid = from + (k + 0.5) * length;
    return piece(
      `${id}-${k}`,
      "kenney-nature/fence_simple.glb",
      along === "x" ? [mid, at] : [at, mid],
      { scale: [length, FENCE_SCALE, FENCE_SCALE] },
      along === "x" ? 0 : TURN,
    );
  });
};

const PARK: DecorItem[] = [
  // A pair of benches on each diagonal, facing the fountain.
  ...DIAGONALS.flatMap((angle, i) =>
    [-0.17, 0.17].map((da, k) =>
      piece(`plaza-bench-${i}-${k}`, "kenney-furniture/bench.glb", aroundPlaza(angle + da, PLAZA.radius - 0.7), { height: 0.85 }, -angle - TURN),
    ),
  ),
  // Lamps where the paths meet the plaza.
  ...[0, 1, 2, 3].map((k) =>
    piece(`plaza-lamp-${k}`, "kenney-city-roads/light-square.glb", aroundPlaza((k * Math.PI) / 2 + 0.38, PLAZA.radius + 0.3), { height: 3.4 }, -((k * Math.PI) / 2) + TURN),
  ),
  // Flower beds outside the plaza, between the paths.
  ...DIAGONALS.flatMap((angle, i) => [
    piece(`plaza-bed-bush-${i}`, "kenney-nature/plant_bushDetailed.glb", aroundPlaza(angle, PLAZA.radius + 1.6), { height: 0.8 }, i),
    ...[-0.32, -0.16, 0.16, 0.32].map((da, k) =>
      piece(
        `plaza-bed-flower-${i}-${k}`,
        ["kenney-nature/flower_redA.glb", "kenney-nature/flower_purpleA.glb", "kenney-nature/flower_yellowB.glb"][(i + k) % 3],
        aroundPlaza(angle + da, PLAZA.radius + 1.1 + (k % 2) * 0.5),
        { height: 0.35 },
        k,
      ),
    ),
  ]),
  // The pond: a ring of flat stones, lily pads, reeds, and a bench looking over it.
  ...Array.from({ length: 16 }, (_, k) => {
    const angle = (k / 16) * Math.PI * 2;
    const stone = ["stone_smallFlatA", "stone_smallFlatB", "stone_smallC"][k % 3];
    return piece(
      `pond-stone-${k}`,
      `kenney-nature/${stone}.glb`,
      [POND.at[0] + Math.cos(angle) * (POND.radius + 0.15), POND.at[1] + Math.sin(angle) * (POND.radius + 0.15)],
      { width: 0.9 },
      angle * 3,
    );
  }),
  ...([
    ["lily_large", -0.9, -0.4],
    ["lily_small", 0.6, 0.8],
    ["lily_large", 0.9, -0.9],
    ["lily_small", -0.3, 1.2],
    ["lily_small", 1.4, 0.1],
  ] as const).map(([lily, dx, dz], k) =>
    piece(`pond-lily-${k}`, `kenney-nature/${lily}.glb`, [POND.at[0] + dx, POND.at[1] + dz], { width: lily === "lily_large" ? 0.9 : 0.55 }, k * 1.3, POND_WATER_Y + 0.01),
  ),
  ...[2.3, 2.9, 3.5].map((angle, k) =>
    piece(`pond-bush-${k}`, "kenney-nature/plant_bushLarge.glb", [POND.at[0] + Math.cos(angle) * (POND.radius + 0.9), POND.at[1] + Math.sin(angle) * (POND.radius + 0.9)], { height: 0.6 + 0.15 * k }, k),
  ),
  // (A bench unturned faces +Z; turned by atan2(dx, dz) it faces along (dx, dz).)
  piece("pond-bench-a", "kenney-furniture/bench.glb", [POND.at[0] + 3.4, POND.at[1] - 1.9], { height: 0.85 }, Math.atan2(-3.4, 1.9)),
  piece("pond-bench-b", "kenney-furniture/bench.glb", [POND.at[0] + 3.8, POND.at[1] - 1.25], { height: 0.85 }, Math.atan2(-3.8, 1.25)),
  // Shade trees round the park's edge, clear of the paths.
  ...([
    ["tree_oak", -29.5, -2.5, 5.2],
    ["tree_fat", -25.5, -3.2, 4.4],
    ["tree_detailed", -14, -1.5, 4.8],
    ["tree_default", -29.8, 1.5, 4.2],
    ["tree_tall", -16.5, 14.6, 5.5],
    ["tree_oak", -23.4, 15, 4.6],
    ["tree_detailed", -31, 8.6, 5],
  ] as const).map(([tree, x, z, height], k) => piece(`park-edge-tree-${k}`, `kenney-nature/${tree}.glb`, [x, z], { height }, k * 0.9)),
];

const { x0, x1, z0, z1, gate } = BLOCK_FENCE;
const STORE_HALF_WIDTH = STORE_FLOOR.width / 2 + 0.2;
/** The lot's lawn sides, a little outside its kerb. */
const LOT_FENCE = { x0: LOT_X0 - 0.3, x1: LOT_X1 + 0.3, z1: LOT_Z1 + 0.3 } as const;
const WALK_END = WALK[WALK.length - 1];
const BLOCK_FENCE_ITEMS: DecorItem[] = [
  // Back: the park's corner to the store, then the strip between the store and the lot, then past the lot to the corner.
  ...fenceRun("block-fence-n-0", "x", z0, x0, PLAZA.at[0] - gate),
  ...fenceRun("block-fence-n-1", "x", z0, PLAZA.at[0] + gate, -STORE_HALF_WIDTH),
  ...fenceRun("block-fence-n-2", "x", z0, STORE_HALF_WIDTH, LOT_FENCE.x0),
  ...fenceRun("block-fence-n-3", "x", z0, LOT_FENCE.x1, x1),
  // Round the lot's three lawn sides, so the fence keeps to the grass; open on its west side where the walk comes in.
  ...fenceRun("lot-fence-w-0", "z", LOT_FENCE.x0, z0, WALK_END[1] - gate),
  ...fenceRun("lot-fence-w-1", "z", LOT_FENCE.x0, WALK_END[1] + gate, LOT_FENCE.z1),
  ...fenceRun("lot-fence-s", "x", LOT_FENCE.z1, LOT_FENCE.x0, LOT_FENCE.x1),
  ...fenceRun("lot-fence-e", "z", LOT_FENCE.x1, z0, LOT_FENCE.z1),
  // Front, open at the park's south path.
  ...fenceRun("block-fence-s-0", "x", z1, x0, PLAZA.at[0] - gate),
  ...fenceRun("block-fence-s-1", "x", z1, PLAZA.at[0] + gate, x1),
  // Sides: open at the park's west path; the east side runs whole.
  ...fenceRun("block-fence-w-0", "z", x0, z0, PLAZA.at[1] - gate),
  ...fenceRun("block-fence-w-1", "z", x0, PLAZA.at[1] + gate, z1),
  ...fenceRun("block-fence-e", "z", x1, z0, z1),
];

/**
 * The rest of the ground, so no patch of it reads empty: copses of trees inside the loop,
 * houses beyond the side roads, and blocks of town around it all (houses and pines, towers and offices
 * behind the shops). Placed from a seeded list, so it is the same on every load.
 */
const TREES = ["tree_oak", "tree_default", "tree_detailed", "tree_fat", "tree_pineRoundB", "tree_pineTallA", "tree_pineTallB", "tree_tall"] as const;
/** Ground kept clear: [xMin, xMax, zMin, zMax]. */
const CLEAR: ReadonlyArray<readonly [number, number, number, number]> = [
  // The store, its plants, and the park.
  [-13, 10, -6, PARK_Z + 3],
  // The park.
  [PARK_AREA.x[0], PARK_AREA.x[1], PARK_AREA.z[0], PARK_AREA.z[1]],
  // The lot and its planters.
  [LOT_X0 - 1, LOT_X1 + 1, LOT_Z0 - 1, LOT_Z1 + 3],
  // The default camera's line of sight, from the front-right.
  [-5, 28, 8, FRONT_PAVEMENT_Z[0]],
];
const clear = (x: number, z: number) => CLEAR.some(([x0, x1, z0, z1]) => x >= x0 && x <= x1 && z >= z0 && z <= z1);
/** Inside the loop's pavements, where copses may grow. */
const INNER = {
  x: [WEST_X + HALF_ROAD + PAVEMENT_DEPTH + 1.5, EAST_X - HALF_ROAD - PAVEMENT_DEPTH - 1.5],
  z: [PAVEMENT_Z + PAVEMENT_DEPTH, FRONT_PAVEMENT_Z[0] - PAVEMENT_DEPTH / 2 - 1.5],
} as const;

/** Where the town starts, past the ring road's outer pavement. */
const TOWN = { x: [RING.x[0] - PAVEMENT_DEPTH, RING.x[1] + PAVEMENT_DEPTH], z: [RING.z[0] - PAVEMENT_DEPTH, RING.z[1] + PAVEMENT_DEPTH] } as const;
const TOWERS = ["building-skyscraper-a", "building-skyscraper-b", "building-skyscraper-c", "building-skyscraper-e", "building-d", "building-f"] as const;

const SURROUND: DecorItem[] = (() => {
  const random = mulberry32(20261014);
  const items: DecorItem[] = [];
  for (let x = INNER.x[0]; x <= INNER.x[1]; x += 6) {
    for (let z = INNER.z[0]; z <= INNER.z[1]; z += 5.5) {
      const at: [number, number] = [x + (random() - 0.5) * 3, z + (random() - 0.5) * 3];
      const tree = TREES[Math.floor(random() * TREES.length)];
      const height = 4 + random() * 3;
      const spin = random() * Math.PI * 2;
      const skip = random() < 0.15;
      if (skip || clear(...at) || at[0] < INNER.x[0] || at[0] > INNER.x[1] || at[1] > INNER.z[1]) continue;
      items.push(piece(`copse-${items.length}`, `kenney-nature/${tree}.glb`, at, { height }, spin));
      if (random() < 0.5) items.push(piece(`copse-bush-${items.length}`, "kenney-nature/plant_bushDetailed.glb", [at[0] + 1.6, at[1] + 1], { height: 0.8 }, spin));
    }
  }
  // Two houses on each side block, facing the store's loop, with a tree between them.
  for (const [i, dz] of [-8, 8].entries()) {
    items.push(house(`side-house-w-${i}`, ["h", "k"][i], [OUTER_BLOCK_XS[0], MID_Z + dz], TURN));
    items.push(house(`side-house-e-${i}`, ["p", "a"][i], [OUTER_BLOCK_XS[1], MID_Z + dz], -TURN));
  }
  for (const [i, x] of OUTER_BLOCK_XS.entries()) items.push(piece(`side-tree-${i}`, "kenney-city-suburban/tree-large.glb", [x, MID_Z], { height: 6 }, i));
  // Past the ring road: two rows of towers and offices behind the shops; elsewhere a row of houses
  // facing the ring, and pines and houses behind them.
  const row = (from: number, to: number, step: number) => Array.from({ length: Math.floor((to - from) / step) + 1 }, (_, i) => from + i * step);
  for (const [r, z] of [TOWN.z[0] - 9, TOWN.z[0] - 25].entries()) {
    for (const x of row(TOWN.x[0] - 8, TOWN.x[1] + 8, 15)) {
      const tower = TOWERS[Math.floor(random() * TOWERS.length)];
      items.push(piece(`tower-${items.length}`, `kenney-city-commercial/${tower}.glb`, [x, z], { height: 16 + r * 10 + random() * 16 }));
    }
  }
  const homes = (first: number, along: number[], at: (along: number, depth: number) => [number, number], facing: number) => {
    for (const [r, depth] of [first, first + Math.sign(first) * 17].entries()) {
      for (const a of along) {
        const k = items.length;
        if (r === 1 && random() < 0.5) items.push(piece(`far-pine-${k}`, "kenney-nature/tree_pineTallB.glb", at(a, depth), { height: 8 + random() * 4 }, random() * 6));
        else items.push(house(`far-house-${k}`, HOUSES[k % HOUSES.length], at(a, depth), facing));
      }
    }
  };
  homes(TOWN.z[1] + 7, row(TOWN.x[0] + 4, TOWN.x[1] - 4, 17), (a, d) => [a, d], Math.PI);
  homes(TOWN.x[0] - 7, row(TOWN.z[0] + 6, TOWN.z[1] - 6, 17), (a, d) => [d, a], TURN);
  homes(-(TOWN.x[1] + 7), row(TOWN.z[0] + 6, TOWN.z[1] - 6, 17), (a, d) => [-d, a], -TURN);
  return items;
})();

export const DECOR_ITEMS: readonly DecorItem[] = [...INSIDE, ...LAWN, ...STREET, ...PARKING, ...FRONT, ...PARK, ...BLOCK_FENCE_ITEMS, ...SURROUND];

/** Where the lot's surface and painted lines sit: on a 15 cm kerbed slab. */
export const LOT_TOP = PAVEMENT_TOP;
