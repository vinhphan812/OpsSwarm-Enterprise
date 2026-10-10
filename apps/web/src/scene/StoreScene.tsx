import { CameraControls, Environment, Lightformer } from "@react-three/drei";
import { Canvas, useThree } from "@react-three/fiber";
import { useEffect, useMemo } from "react";
import { Box3, Vector3 } from "three";
import { useTwinStore } from "@/state/twin.store";
import { useUiStore } from "@/state/ui.store";
import { groupBy } from "@/core/utils/collections";
import {
  CAMERA_DRAG_SMOOTH_TIME,
  CAMERA_FOV,
  CAMERA_SMOOTH_TIME,
  INITIAL_CAMERA_POSITION,
  MAX_POLAR_ANGLE,
  MIN_CAMERA_DISTANCE,
  MIN_POLAR_ANGLE,
  PAN_BOUNDS,
} from "@/constants/camera.constant";
import { useFitCamera } from "@/hooks/fitCamera.hook";
import { useFocusSelection } from "@/hooks/focusSelection.hook";
import { useOrbitAroundPointer } from "@/hooks/orbitPoint.hook";
import { Equipment } from "./entities/equipment/Equipment";
import { Exterior } from "./entities/Exterior";
import { Floor } from "./entities/Floor";
import { Shelf } from "./entities/Shelf";
import { Stock } from "./entities/stock/Stock";
import { Walls } from "./entities/Walls";
import { SKY_COLOR } from "@/constants/scene.constant";
import { ENTITY_TYPE } from "@/enums/scene.enum";
import { entityProps } from "./entities/entity";
import { sceneOf, storeLayout } from "./layout";
import type { ProductFixture, StoreFixture } from "@/types/scene.type";

/** Keeps the camera framing the whole store as the canvas resizes, orbits around the pointer, and flies to a selection. */
function FrameCamera() {
  useFitCamera();
  useOrbitAroundPointer();
  useFocusSelection();
  return null;
}

type StoreContentsProps = {
  store: StoreFixture;
  interactive?: boolean;
};

const NO_PRODUCTS: ProductFixture[] = [];

export function StoreContents({
  store,
  interactive = true,
}: StoreContentsProps) {
  // One pass over the products instead of a filter per shelf and per slot.
  const byHolder = useMemo(
    () => groupBy(store.products, (product) => product.shelfId),
    [store.products],
  );
  const productsOf = (holderId: string) =>
    byHolder.get(holderId) ?? NO_PRODUCTS;

  return (
    <group {...entityProps(store.storeId, ENTITY_TYPE.Store)}>
      <Floor />
      <Walls />
      {store.shelves.map((shelf) => (
        <Shelf
          key={shelf.shelfId}
          shelf={shelf}
          products={productsOf(shelf.shelfId)}
          interactive={interactive}
        />
      ))}
      <Stock store={store} />
      {store.equipment.map((item) => (
        <Equipment
          key={item.equipmentId}
          equipment={item}
          products={productsOf(item.equipmentId)}
          interactive={interactive}
        />
      ))}
    </group>
  );
}

/**
 * The live twin state on the static layout. Until the first state arrives, or when it
 * cannot be loaded, the layout is drawn with empty shelves.
 */
export function LiveStoreContents({
  interactive = true,
}: {
  interactive?: boolean;
}) {
  const live = useTwinStore((state) => state.live);
  const store = useMemo(() => (live ? sceneOf(live).store : storeLayout), [live]);

  return <StoreContents store={store} interactive={interactive} />;
}

const clearSelection = () => useUiStore.getState().select(null);

/**
 * Lights and fixtures do not move, so the shadow map is drawn when the stock changes
 * (and when a wall hides or shows), not on every frame of an orbit.
 */
function StaticShadows() {
  const gl = useThree((state) => state.gl);
  const live = useTwinStore((state) => state.live);

  useEffect(() => {
    gl.shadowMap.autoUpdate = false;
    return () => {
      gl.shadowMap.autoUpdate = true;
    };
  }, [gl]);

  // Effects run after Stock's layout effect has written the new instance matrices.
  useEffect(() => {
    gl.shadowMap.needsUpdate = true;
  }, [gl, live]);

  return null;
}

/** Device pixel ratio range: crisp on retina, without rendering 4x the pixels. */
const DPR: [number, number] = [1, 1.5];

const PAN_BOX = new Box3(
  new Vector3(...PAN_BOUNDS.min),
  new Vector3(...PAN_BOUNDS.max),
);

export function StoreScene() {
  return (
    <Canvas
      shadows="soft"
      dpr={DPR}
      camera={{ position: INITIAL_CAMERA_POSITION, fov: CAMERA_FOV }}
      onPointerMissed={clearSelection}
    >
      <color attach="background" args={[SKY_COLOR]} />
      <fog attach="fog" args={[SKY_COLOR, 40, 90]} />
      <hemisphereLight args={["#fffaf2", "#cbb69c", 0.5]} />
      <ambientLight intensity={0.55} />
      {/* Warm sun through the glass wall on the left; the mullions throw stripes across the planks. */}
      <directionalLight
        position={[-9, 6, 3]}
        intensity={1.3}
        color="#fff4e6"
        castShadow
        shadow-mapSize={[2048, 2048]}
        shadow-bias={-0.0004}
        shadow-normalBias={0.02}
        shadow-camera-left={-9}
        shadow-camera-right={9}
        shadow-camera-top={9}
        shadow-camera-bottom={-9}
      />
      <directionalLight position={[6, 5, 4]} intensity={0.35} />
      {/* Studio-style reflections without downloading an HDR. */}
      <Environment resolution={256}>
        <Lightformer
          form="rect"
          intensity={2}
          position={[-8, 3, 0]}
          rotation-y={Math.PI / 2}
          scale={[10, 4, 1]}
        />
        <Lightformer
          form="rect"
          intensity={1}
          position={[0, 6, 0]}
          rotation-x={Math.PI / 2}
          scale={[12, 10, 1]}
        />
        <Lightformer
          form="rect"
          intensity={0.5}
          position={[8, 2, 0]}
          rotation-y={-Math.PI / 2}
          scale={[10, 3, 1]}
        />
      </Environment>
      <FrameCamera />
      <StaticShadows />
      <Exterior />
      <LiveStoreContents />
      {/* Left drag orbits around the point under the cursor, right drag (or two fingers) pans, the wheel zooms toward the cursor. */}
      <CameraControls
        makeDefault
        dollyToCursor
        smoothTime={CAMERA_SMOOTH_TIME}
        draggingSmoothTime={CAMERA_DRAG_SMOOTH_TIME}
        minDistance={MIN_CAMERA_DISTANCE}
        minPolarAngle={MIN_POLAR_ANGLE}
        maxPolarAngle={MAX_POLAR_ANGLE}
        boundaryEnclosesCamera={false}
        boundaryFriction={0.2}
        ref={(controls) => controls?.setBoundary(PAN_BOX)}
      />
    </Canvas>
  );
}
