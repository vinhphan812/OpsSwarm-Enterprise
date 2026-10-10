import { useLayoutEffect, useRef } from "react";
import {
  BoxGeometry,
  MeshPhysicalMaterial,
  MeshStandardMaterial,
  Object3D,
  type InstancedMesh,
  type Material,
} from "three";
import type { Tuple3 } from "@/types/scene.type";

/** One box part: center, size, and optional Euler rotation, all in the model's local frame. */
export type BoxSpec = {
  p: Tuple3;
  s: Tuple3;
  r?: Tuple3;
};

/**
 * Low-poly store equipment is built from boxes. Every box shares this unit cube and is
 * sized by its instance matrix, so a whole model is a handful of draw calls.
 */
const UNIT_BOX = new BoxGeometry(1, 1, 1);

/** Shared materials. Module singletons, so they are never disposed. */
export const MAT = {
  /** Charcoal powder-coated steel: shelf and rack frames. */
  frame: new MeshStandardMaterial({ color: "#33363b", roughness: 0.45, metalness: 0.55 }),
  /** Brushed aluminium: barriers, door frames, trims. */
  steel: new MeshStandardMaterial({ color: "#b8bdc3", roughness: 0.3, metalness: 0.8 }),
  /** Light birch ply for shelf boards and produce trays. */
  wood: new MeshStandardMaterial({ color: "#d9c29a", roughness: 0.7 }),
  /** Stained slats of the wooden crate. */
  woodDark: new MeshStandardMaterial({ color: "#7a5236", roughness: 0.8 }),
  /** Painted cabinet sheet metal of coolers and the checkout. */
  cabinet: new MeshStandardMaterial({ color: "#4a4d52", roughness: 0.6, metalness: 0.2 }),
  cabinetDark: new MeshStandardMaterial({ color: "#2a2c30", roughness: 0.7, metalness: 0.1 }),
  /** Warm white laminate of the checkout counter's body. */
  laminate: new MeshStandardMaterial({ color: "#ebe7e1", roughness: 0.55 }),
  /** Satin stainless worktop the checkout's stations sit in. */
  worktop: new MeshStandardMaterial({ color: "#c7ccd1", roughness: 0.35, metalness: 0.6 }),
  /** Store accent stripe along the checkout's shopper side. */
  accent: new MeshStandardMaterial({ color: "#2f8f83", roughness: 0.5 }),
  /** Rubber belt and well bottoms. */
  rubber: new MeshStandardMaterial({ color: "#1d1f22", roughness: 0.9 }),
  /** Cooler shelves. */
  rack: new MeshStandardMaterial({ color: "#5c6065", roughness: 0.5, metalness: 0.4 }),
  /** Lit white cooler interior. */
  interior: new MeshStandardMaterial({
    color: "#e9eef1",
    emissive: "#e3edf3",
    emissiveIntensity: 0.35,
    roughness: 0.6,
  }),
  /** LED strips and backlit header panels. */
  light: new MeshStandardMaterial({ color: "#d6e6ee", emissive: "#cfe4ef", emissiveIntensity: 0.9 }),
  /** Display and scanner glass. */
  screen: new MeshStandardMaterial({
    color: "#1a1c1f",
    emissive: "#22343f",
    emissiveIntensity: 0.6,
    roughness: 0.2,
  }),
  glass: new MeshPhysicalMaterial({
    color: "#dce8ec",
    transparent: true,
    opacity: 0.18,
    roughness: 0.05,
    metalness: 0,
    envMapIntensity: 1.5,
    depthWrite: false,
  }),
  /** Teal polypropylene crate. */
  plastic: new MeshStandardMaterial({ color: "#4aa3a8", roughness: 0.55 }),
  /** Darker teal inset that reads as a cut-out vent in the crate wall. */
  plasticShade: new MeshStandardMaterial({ color: "#245d61", roughness: 0.8 }),
} satisfies Record<string, Material>;

type BoxesProps = {
  boxes: readonly BoxSpec[];
  material: Material;
  castShadow?: boolean;
  receiveShadow?: boolean;
  renderOrder?: number;
};

/** All boxes of one material as a single instanced mesh. */
export function Boxes({ boxes, material, castShadow = true, receiveShadow = true, renderOrder }: BoxesProps) {
  const ref = useRef<InstancedMesh>(null);

  useLayoutEffect(() => {
    const mesh = ref.current;
    if (!mesh) return;
    const dummy = new Object3D();
    boxes.forEach((box, index) => {
      dummy.position.set(...box.p);
      dummy.rotation.set(...(box.r ?? [0, 0, 0]));
      dummy.scale.set(...box.s);
      dummy.updateMatrix();
      mesh.setMatrixAt(index, dummy.matrix);
    });
    mesh.instanceMatrix.needsUpdate = true;
    // Instances extend past the unit cube, so frustum culling needs the real bounds.
    mesh.computeBoundingSphere();
  }, [boxes]);

  return (
    <instancedMesh
      ref={ref}
      args={[UNIT_BOX, material, boxes.length]}
      castShadow={castShadow}
      receiveShadow={receiveShadow}
      renderOrder={renderOrder}
    />
  );
}

/** Model parts keyed by material name. */
type PartList = Partial<Record<keyof typeof MAT, BoxSpec[]>>;

/** Materials that let light through, so they never cast shadows and draw after opaque parts. */
const SEE_THROUGH = new Set<keyof typeof MAT>(["glass"]);

/** Renders a part list built once at module load. */
export function Parts({ parts }: { parts: PartList }) {
  return (
    <>
      {(Object.keys(parts) as Array<keyof typeof MAT>).map((key) => {
        const boxes = parts[key];
        if (!boxes || boxes.length === 0) return null;
        const seeThrough = SEE_THROUGH.has(key);
        return (
          <Boxes
            key={key}
            boxes={boxes}
            material={MAT[key]}
            castShadow={!seeThrough}
            receiveShadow={!seeThrough}
            renderOrder={seeThrough ? 1 : undefined}
          />
        );
      })}
    </>
  );
}

/** Collects boxes into a part list. */
export function partBuilder() {
  const parts: PartList = {};
  const add = (key: keyof typeof MAT, p: Tuple3, s: Tuple3, r?: Tuple3) => {
    (parts[key] ??= []).push(r ? { p, s, r } : { p, s });
  };
  return { parts, add };
}
