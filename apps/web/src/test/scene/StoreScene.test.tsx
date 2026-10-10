import ReactThreeTestRenderer from "@react-three/test-renderer";
import type { Object3D } from "three";
import { describe, expect, it } from "vitest";
import { TwinStoreContents, StoreContents } from "@/scene/StoreScene";
import { sampleStoreState } from "@/test/sampleState";
import { toSceneStore } from "@/scene/layout";
import { TWIN_STATUS } from "@/enums/twin.enum";
import { useTwinStore } from "@/state/twin.store";

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
  it("names store, shelves, slots, products, and equipment with entity ids", async () => {
    const renderer = await ReactThreeTestRenderer.create(
      <StoreContents store={toSceneStore(sampleStoreState()).store} interactive={false} />,
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
      "CK01",
      "GDC01",
      "OC01",
      "PR01",
      "CW01",
      "CP01",
      "BR01",
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

  it("draws the layout with empty shelves when the twin could not be loaded", async () => {
    useTwinStore.setState({ live: null, status: TWIN_STATUS.Error });
    const renderer = await ReactThreeTestRenderer.create(<TwinStoreContents interactive={false} />);
    const scene = renderer.scene as unknown as TestNode;

    for (const id of ["store-001", "A01", "A01-S01", "CK01", "GDC01"]) {
      expect(findByName(scene, id), id).toBeTruthy();
    }
    expect(findByName(scene, "P001")).toBeUndefined();
  });
});
