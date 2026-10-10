import { useLayoutEffect, type RefObject } from "react";
import { Color, MeshStandardMaterial, type Material, type Mesh, type Object3D } from "three";
import { SELECTION_GLOW, SELECTION_STATUS_BOOST } from "@/constants/scene.constant";
import { selectionColor } from "@/core/utils/theme";

/** One glowing copy per shared material, made on first use and kept, like the materials themselves. */
const glowing = new WeakMap<Material, Material>();
/** One brighter copy per status-light material. */
const boosted = new WeakMap<Material, Material>();

function glowOf(material: Material): Material {
  let glow = glowing.get(material);
  if (!glow) {
    glow = material.clone();
    if ((glow as MeshStandardMaterial).isMeshStandardMaterial) {
      const standard = glow as MeshStandardMaterial;
      // Added to any glow the part already has (cooler lights, screens).
      standard.emissive = new Color(selectionColor());
      standard.emissiveIntensity = SELECTION_GLOW;
    }
    glowing.set(material, glow);
  }
  return glow;
}

/** The same status color, burning brighter. A dark (unlit) light stays dark. */
function boostOf(material: Material): Material {
  let boost = boosted.get(material);
  if (!boost) {
    boost = material.clone();
    if ((boost as MeshStandardMaterial).isMeshStandardMaterial) (boost as MeshStandardMaterial).emissiveIntensity *= SELECTION_STATUS_BOOST;
    boosted.set(material, boost);
  }
  return boost;
}

/**
 * Lights up every visible part under `ref` while `active`. Fixture parts share module
 * materials, so each mesh gets a glowing copy and has its own material back afterwards.
 * Hidden meshes (hit boxes) are left alone. Meshes that carry status in their color
 * (`userData.keepColor`, such as a checkout's lane light) keep it and burn brighter instead.
 */
export function useSelectionGlow(ref: RefObject<Object3D>, active: boolean) {
  useLayoutEffect(() => {
    const root = ref.current;
    if (!active || !root) return;
    const swapped: Array<[Mesh, Material]> = [];
    root.traverse((object) => {
      // `isMesh`, not instanceof: a second copy of three in the bundle makes instanceof miss meshes.
      if (!(object as Mesh).isMesh) return;
      const mesh = object as Mesh;
      if (Array.isArray(mesh.material)) return;
      const material = mesh.material;
      if (!material.visible) return;
      swapped.push([mesh, material]);
      mesh.material = mesh.userData.keepColor ? boostOf(material) : glowOf(material);
    });
    return () => {
      for (const [mesh, material] of swapped) mesh.material = material;
    };
  }, [ref, active]);
}
