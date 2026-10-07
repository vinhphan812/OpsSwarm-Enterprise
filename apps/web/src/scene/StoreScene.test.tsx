import ReactThreeTestRenderer from "@react-three/test-renderer";
import type { Object3D } from "three";
import { describe, expect, it } from "vitest";
import { StoreContents } from "./StoreScene";
import { storeFixture } from "./storeFixture";

type TestNode = {
  instance: Object3D;
  children: TestNode[];
};

function findByName(root: TestNode, name: string): TestNode | undefined {
  if (root.instance?.name === name) {
    return root;
  }
  for (const child of root.children) {
    const found = findByName(child, name);
    if (found) {
      return found;
    }
  }
  return undefined;
}

function ancestorNames(object: Object3D): string[] {
  const names: string[] = [];
  let current = object.parent;
  while (current) {
    if (current.name) {
      names.push(current.name);
    }
    current = current.parent;
  }
  return names;
}

describe("store scene graph", () => {
  it("names store, shelves, slots, and products with entity ids", async () => {
    const renderer = await ReactThreeTestRenderer.create(
      <StoreContents store={storeFixture} showLabels={false} />,
    );
    const scene = renderer.scene as unknown as TestNode;

    const required = [
      "store-001",
      "A01",
      "A02",
      "B01",
      "B02",
      "A01-S01",
      "A02-S01",
      "P001",
      "P002",
    ];

    for (const id of required) {
      const object = findByName(scene, id);
      expect(object, id).toBeTruthy();
      expect(object?.instance.userData.entityId).toBe(id);
    }

    const product = findByName(scene, "P001");
    expect(product).toBeTruthy();
    const names = ancestorNames(product!.instance);
    expect(names).toContain("A01-S01");
    expect(names).toContain("A01");
    expect(names).toContain("store-001");
  });
});
