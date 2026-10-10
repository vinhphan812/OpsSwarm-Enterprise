// @vitest-environment jsdom
import type { CameraControls as DreiCameraControls } from "@react-three/drei";
import CameraControls from "camera-controls";
import * as THREE from "three";
import { PerspectiveCamera, Vector3 } from "three";
import { describe, expect, it } from "vitest";
import { flyTo, panelOffset } from "@/hooks/focusSelection.hook";
import { productFocus } from "@/scene/camera/focus";
import { storeLayout } from "@/scene/layout";

CameraControls.install({ THREE });

/** Where the camera looks: straight ahead from its position, at the target's distance. */
function lookPoint(camera: PerspectiveCamera, distance: number) {
  camera.updateMatrixWorld();
  return camera.getWorldDirection(new Vector3()).multiplyScalar(distance).add(camera.position);
}

describe("flyTo", () => {
  it("looks straight at the entity even after orbiting around a clicked point", () => {
    const camera = new PerspectiveCamera(45, 1.5, 0.1, 200);
    camera.position.set(6, 5, 8.8);
    const controls = new CameraControls(camera, document.createElement("div"));
    void controls.setLookAt(6, 5, 8.8, 0, 0.8, 0, false);
    // A press on the scene moves the orbit point, which leaves a focal offset behind.
    controls.setOrbitPoint(3, 1, -2);
    controls.update(0);

    const view = productFocus(storeLayout, "A02", "A02-S19")!;
    flyTo(controls as unknown as DreiCameraControls, view, false);
    controls.update(0);

    const target = new Vector3(...view.target);
    expect(camera.position.distanceTo(new Vector3(...view.position))).toBeLessThan(1e-3);
    expect(lookPoint(camera, camera.position.distanceTo(target)).distanceTo(target)).toBeLessThan(1e-3);
    controls.dispose();
  });
});

describe("panelOffset", () => {
  it("puts the target in the middle of what the panel leaves visible", () => {
    const camera = new PerspectiveCamera(45, 1600 / 900, 0.1, 200);
    const controls = new CameraControls(camera, document.createElement("div"));
    const view = productFocus(storeLayout, "A02", "A02-S19")!;
    const shift = 202;
    flyTo(controls as unknown as DreiCameraControls, view, false, panelOffset(view, 900, shift));
    controls.update(0);
    camera.updateMatrixWorld();

    // The target projects `shift` pixels left of the canvas center.
    const ndc = new Vector3(...view.target).project(camera);
    expect(ndc.x * (1600 / 2)).toBeCloseTo(-shift, 0);
    expect(ndc.y).toBeCloseTo(0, 3);
    expect(panelOffset(view, 900, 0)).toBe(0);
    controls.dispose();
  });
});
