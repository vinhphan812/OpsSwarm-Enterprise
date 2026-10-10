import { Box3, Matrix4, Ray, Vector3 } from "three";
import {
  CAMERA_FOV,
  FOCUS_ELEVATION,
  FOCUS_ELEVATION_STEP,
  FOCUS_FIXTURE_ELEVATION,
  FOCUS_MAX_ELEVATION,
  FOCUS_FIXTURE_MARGIN,
  FOCUS_PRODUCT_DISTANCE,
  FOCUS_WALL_CLEARANCE,
  MIN_CAMERA_DISTANCE,
} from "@/constants/camera.constant";
import { EQUIPMENT_SIZE, SHELF, STORE_FLOOR } from "@/constants/dimensions.constant";
import { ENTITY_TYPE, type FixtureKind } from "@/enums/scene.enum";
import { surfaceMatrix, surfacesOf } from "@/scene/entities/stock/surfaces";
import { entityMatrix, footprintCorners } from "@/scene/utils/transform";
import type { EquipmentFixture, ShelfFixture, StoreFixture, Tuple3 } from "@/types/scene.type";

/** Where the camera goes to look at an entity, and the point it looks at. */
export type FocusView = { position: Tuple3; target: Tuple3 };

/** A focused item sits a little above its slot's front edge. */
const ITEM_LIFT = 0.12;

type Fixture = { id: string; kind: FixtureKind; fixture: ShelfFixture | EquipmentFixture };

function fixturesOf(store: StoreFixture): Fixture[] {
  return [
    ...store.shelves.map((shelf) => ({ id: shelf.shelfId, kind: ENTITY_TYPE.Shelf as FixtureKind, fixture: shelf })),
    ...store.equipment.map((item) => ({ id: item.equipmentId, kind: item.kind as FixtureKind, fixture: item })),
  ];
}

function tuple(vector: Vector3): Tuple3 {
  return [vector.x, vector.y, vector.z];
}

/** Inner faces of the walls, less the clearance: left, right, and back. The front (+Z) is open. */
const ROOM = {
  x: STORE_FLOOR.width / 2 - FOCUS_WALL_CLEARANCE,
  back: -STORE_FLOOR.depth / 2 + FOCUS_WALL_CLEARANCE,
};

/**
 * The camera `distance` from `target` along the horizontal direction `front`, raised by
 * `elevation`, kept inside the walls: moved in toward the target along the same line
 * when it would end up behind one.
 */
function viewFrom(target: Vector3, front: Vector3, distance: number, elevation: number): FocusView {
  const offset = front
    .clone()
    .setY(0)
    .normalize()
    .multiplyScalar(Math.cos(elevation))
    .add(new Vector3(0, Math.sin(elevation), 0))
    .multiplyScalar(distance);
  let scale = 1;
  const limit = (room: number, from: number, step: number) => {
    const end = from + step;
    if (Math.abs(step) > 1e-6 && (end > room || end < -room)) {
      scale = Math.min(scale, (Math.sign(step) * room - from) / step);
    }
  };
  limit(ROOM.x, target.x, offset.x);
  if (target.z + offset.z < ROOM.back) scale = Math.min(scale, (ROOM.back - target.z) / offset.z);
  const position = offset.multiplyScalar(Math.max(0, scale)).add(target);
  return { position: tuple(position), target: tuple(target) };
}

/** Fixtures grown by this much before a line of sight is tested against them. */
const OBSTACLE_PADDING = 0.05;

/** World box of a fixture: its footprint turned with it, from the floor to its height. */
function boxOf({ kind, fixture }: Fixture): Box3 {
  const [w, h, d] = kind === ENTITY_TYPE.Shelf ? [SHELF.width, SHELF.height, SHELF.depth] : EQUIPMENT_SIZE[kind];
  const box = new Box3();
  for (const { x, z } of footprintCorners(fixture.position, fixture.rotationY, w, d)) {
    box.expandByPoint(new Vector3(x, fixture.position.y, z));
    box.expandByPoint(new Vector3(x, fixture.position.y + h, z));
  }
  return box.expandByScalar(OBSTACLE_PADDING);
}

/** True when the straight line from the camera to the target passes through a box. */
function blocked(view: FocusView, obstacles: Box3[]): boolean {
  const from = new Vector3(...view.position);
  const to = new Vector3(...view.target);
  const length = from.distanceTo(to);
  const ray = new Ray(from, to.clone().sub(from).normalize());
  const hit = new Vector3();
  return obstacles.some((box) => box.containsPoint(from) || (ray.intersectBox(box, hit) !== null && from.distanceTo(hit) < length));
}

/**
 * `viewFrom` at the lowest elevation, from `elevation` up, whose line of sight clears
 * every fixture but the focused one: in a 1.3 m aisle, a low view of a slot would look
 * at the back of the next gondola. The steepest view when nothing clears.
 */
function clearView(store: StoreFixture, holderId: string, target: Vector3, front: Vector3, distance: number, elevation: number): FocusView {
  const obstacles = fixturesOf(store)
    .filter((item) => item.id !== holderId)
    .map(boxOf)
    .filter((box) => !box.containsPoint(target));
  for (let angle = elevation; angle < FOCUS_MAX_ELEVATION; angle += FOCUS_ELEVATION_STEP) {
    const view = viewFrom(target, front, distance, angle);
    if (!blocked(view, obstacles)) return view;
  }
  return viewFrom(target, front, distance, FOCUS_MAX_ELEVATION);
}

/** World direction a fixture's front (+Z at rest) faces. */
function frontOf(rotationY: number): Vector3 {
  return new Vector3(Math.sin(rotationY), 0, Math.cos(rotationY));
}

/**
 * The view of a product's slot from in front of it: from the side its stock faces (the
 * far side of a gondola for the far side's slots), a little above, at `FOCUS_PRODUCT_DISTANCE`,
 * and higher where another fixture would block the view.
 * Null when the slot is not in the layout.
 */
export function productFocus(store: StoreFixture, shelfId: string, slotId: string): FocusView | null {
  const holder = fixturesOf(store).find((item) => item.id === shelfId);
  const slot = holder?.fixture.slots.find((item) => item.slotId === slotId);
  const surface = holder && slot ? surfacesOf(holder.kind)[slot.surface] : undefined;
  if (!holder || !slot || !surface) return null;

  const toWorld = entityMatrix(holder.fixture.position, holder.fixture.rotationY);
  const target = new Vector3(slot.position.x, slot.position.y + ITEM_LIFT, slot.position.z).applyMatrix4(toWorld);
  // The surface's own +Z is the way its stock faces.
  const front = new Vector3(0, 0, 1)
    .transformDirection(new Matrix4().multiplyMatrices(toWorld, surfaceMatrix(surface)))
    .setY(0)
    .normalize();
  return clearView(store, shelfId, target, front, FOCUS_PRODUCT_DISTANCE, FOCUS_ELEVATION);
}

/**
 * The view of a whole shelf or piece of equipment, centered and far enough back for all
 * of it to fit. Equipment is seen from its front, which faces into the room. A gondola
 * has two fronts, so it is seen from the side the camera (`from`) is already on.
 * Null when the fixture is not in the layout.
 */
export function fixtureFocus(store: StoreFixture, fixtureId: string, from: Tuple3): FocusView | null {
  const holder = fixturesOf(store).find((item) => item.id === fixtureId);
  if (!holder) return null;
  const [w, h, d] = holder.kind === ENTITY_TYPE.Shelf ? [SHELF.width, SHELF.height, SHELF.depth] : EQUIPMENT_SIZE[holder.kind];
  const { position, rotationY } = holder.fixture;
  const target = new Vector3(position.x, position.y + h / 2, position.z);
  const radius = Math.hypot(w, h, d) / 2;
  const fit = (radius / Math.sin((CAMERA_FOV * Math.PI) / 360)) * FOCUS_FIXTURE_MARGIN;

  const front = frontOf(rotationY);
  if (holder.kind === ENTITY_TYPE.Shelf && front.dot(new Vector3(...from).sub(target)) < 0) front.negate();
  return clearView(store, fixtureId, target, front, Math.max(MIN_CAMERA_DISTANCE, fit), FOCUS_FIXTURE_ELEVATION);
}
