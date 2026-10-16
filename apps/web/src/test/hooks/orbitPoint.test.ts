// @vitest-environment jsdom
import CameraControlsImpl from "camera-controls";
import * as THREE from "three";
import { describe, expect, it } from "vitest";
import { MAX_POLAR_ANGLE, MIN_CAMERA_HEIGHT, MIN_POLAR_ANGLE } from "@/constants/camera.constant";
import { liftAboveGround, polarFloor } from "@/hooks/orbitPoint.hook";

CameraControlsImpl.install({ THREE });

/** Camera height for an orbit point at `pivotY`, a vertical focal offset `offsetY`, and polar angle `polar`. */
const heightAt = (pivotY: number, offsetY: number, radius: number, polar: number) => pivotY + radius * Math.cos(polar) + offsetY;

describe("polarFloor", () => {
  it("leaves a camera at or above the minimum height alone", () => {
    expect(polarFloor(1.2, MIN_CAMERA_HEIGHT, 6)).toBeNull();
    expect(polarFloor(1.5, 4, 6)).toBeNull();
  });

  it("lifts a camera that an orbit point's offset took under the ground back above it", () => {
    // Orbit point on a wall 2 m up, a focal offset 3 m down, orbiting low: the camera ends up below the floor.
    const [pivotY, offsetY, radius] = [2, -3, 6];
    const polar = 1.45;
    const below = heightAt(pivotY, offsetY, radius, polar);
    expect(below).toBeLessThan(0);

    let floor = polarFloor(polar, below, radius)!;
    expect(floor).toBeLessThan(polar);
    // A step or two settles it, as the update loop would.
    for (let step = 0; step < 3; step += 1) floor = polarFloor(floor, heightAt(pivotY, offsetY, radius, floor), radius) ?? floor;
    expect(heightAt(pivotY, offsetY, radius, floor)).toBeGreaterThanOrEqual(MIN_CAMERA_HEIGHT);
  });

  it("never tilts past the top limit", () => {
    expect(polarFloor(0.2, -50, 6)).toBe(MIN_POLAR_ANGLE);
  });
});

describe("liftAboveGround, on the real camera-controls", () => {
  /**
   * The view from high up, an orbit point picked on the floor's far corner, at the edge of
   * the view, then an orbit down as far as the polar limit allows: the case that put the
   * camera under the ground.
   */
  function orbitDownFromHighPoint() {
    const camera = new THREE.PerspectiveCamera(45, 16 / 9, 0.5, 1000);
    const controls = new CameraControlsImpl(camera, document.createElement("div"));
    controls.minPolarAngle = MIN_POLAR_ANGLE;
    controls.maxPolarAngle = MAX_POLAR_ANGLE;
    controls.minDistance = 3.5;
    void controls.setLookAt(0, 8, 12, 0, 0.8, 0, false);
    controls.update(0);
    // What useOrbitAroundPointer does on a press on the floor's far corner.
    controls.setOrbitPoint(-7, 0, -5.5);
    controls.update(0);
    void controls.rotateTo(0, MAX_POLAR_ANGLE, false);
    controls.update(0);
    return { camera, controls };
  }

  it("reproduces the bug: the polar limit alone lets the focal offset take the camera under the ground", () => {
    const { camera, controls } = orbitDownFromHighPoint();
    expect(controls.polarAngle).toBeLessThanOrEqual(MAX_POLAR_ANGLE + 1e-9);
    expect(camera.position.y).toBeLessThan(0);
  });

  it("puts the camera back above the minimum height, and holds it there on the next orbit down", () => {
    const { camera, controls } = orbitDownFromHighPoint();
    expect(liftAboveGround(controls, camera)).toBe(true);
    expect(camera.position.y).toBeGreaterThanOrEqual(MIN_CAMERA_HEIGHT - 1e-6);

    // The next drag down is clamped at the tightened limit.
    void controls.rotatePolarTo(controls.maxPolarAngle + 0.3, false);
    controls.update(0);
    expect(camera.position.y).toBeGreaterThanOrEqual(MIN_CAMERA_HEIGHT - 1e-6);
  });

  it("leaves a camera above the ground alone", () => {
    const camera = new THREE.PerspectiveCamera(45, 16 / 9, 0.5, 1000);
    const controls = new CameraControlsImpl(camera, document.createElement("div"));
    void controls.setLookAt(6, 5, 8, 0, 0.8, 0, false);
    controls.update(0);
    expect(liftAboveGround(controls, camera)).toBe(false);
    expect(controls.maxPolarAngle).toBe(Math.PI);
  });
});
