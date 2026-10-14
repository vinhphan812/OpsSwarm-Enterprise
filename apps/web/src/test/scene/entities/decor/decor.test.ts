import { BoxGeometry, Group, Mesh, MeshStandardMaterial, Raycaster, Vector3 } from "three";
import { describe, expect, it } from "vitest";
import { fitDecor, prepareDecor } from "@/scene/entities/decor/decorModels";
import { junction } from "@/fixtures/decorFixture";

describe("fitDecor", () => {
  it("scales a model to a height and stands its base on the origin", () => {
    const { scale, offset } = fitDecor([2, 4, 2], [1, -0.5, 3], { height: 1.2 });
    scale.forEach((v) => expect(v).toBeCloseTo(0.3));
    offset.forEach((v, i) => expect(v).toBeCloseTo([-0.3, 0.15, -0.9][i]));
  });

  it("scales to a width, or by a scale per axis", () => {
    expect(fitDecor([0.5, 0.02, 0.3], [0, 0, 0], { width: 1.5 }).scale[0]).toBeCloseTo(3);
    const tile = fitDecor([1, 0.25, 1], [0, 0, 0.5], { scale: [76, 0.6, 3] });
    expect(tile.scale).toEqual([76, 0.6, 3]);
    expect(tile.offset[2]).toBeCloseTo(-1.5);
  });
});

describe("prepareDecor", () => {
  const scene = new Group();
  const pot = new Mesh(new BoxGeometry(0.4, 1, 0.4), new MeshStandardMaterial());
  pot.position.set(2, 0.5, 0);
  scene.add(pot);
  const model = prepareDecor(scene);

  it("measures the model and the center of its footprint", () => {
    model.size.forEach((v, i) => expect(v).toBeCloseTo([0.4, 1, 0.4][i]));
    model.base.forEach((v, i) => expect(v).toBeCloseTo([2, 0, 0][i]));
  });

  it("takes no pointer events and casts shadows", () => {
    const ray = new Raycaster(new Vector3(2, 0.5, 5), new Vector3(0, 0, -1));
    expect(ray.intersectObject(scene, true)).toHaveLength(0);
    expect(pot.castShadow).toBe(true);
  });
});

describe("junction", () => {
  const ways = (north: boolean, east: boolean, south: boolean, west: boolean) => ({ north, east, south, west });

  it("picks a crossroad where four roads meet", () => {
    expect(junction(ways(true, true, true, true))).toEqual({ file: "kenney-city-roads/road-crossroad.glb", turn: 0 });
  });

  it("turns the T so its missing arm is the closed side", () => {
    expect(junction(ways(false, true, true, true))).toEqual({ file: "kenney-city-roads/road-intersection.glb", turn: 0 });
    expect(junction(ways(true, true, true, false)).turn).toBeCloseTo(Math.PI / 2);
    expect(junction(ways(true, true, false, true)).turn).toBeCloseTo(Math.PI);
    expect(junction(ways(true, false, true, true)).turn).toBeCloseTo(-Math.PI / 2);
  });

  it("turns the bend to join its two open sides", () => {
    expect(junction(ways(false, false, true, true))).toEqual({ file: "kenney-city-roads/road-bend.glb", turn: 0 });
    expect(junction(ways(true, false, false, true)).turn).toBeCloseTo(-Math.PI / 2);
    expect(junction(ways(true, true, false, false)).turn).toBeCloseTo(Math.PI);
    expect(junction(ways(false, true, true, false)).turn).toBeCloseTo(Math.PI / 2);
  });
});
