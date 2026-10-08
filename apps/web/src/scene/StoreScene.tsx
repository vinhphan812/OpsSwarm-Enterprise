import { OrbitControls } from "@react-three/drei";
import { Canvas, useThree } from "@react-three/fiber";
import { useLayoutEffect } from "react";
import type { PerspectiveCamera } from "three";
import {
  CAMERA_FOV,
  INITIAL_CAMERA_OFFSET,
  MAX_CAMERA_DISTANCE,
  ORBIT_TARGET,
  cameraPositionForAspect,
} from "@/scene/camera/cameraFrame";
import { Floor } from "@/scene/entities/Floor";
import { Shelf } from "@/scene/entities/Shelf";
import { entityProps } from "@/scene/entities/entity";
import { storeFixture } from "@/fixtures/storeFixture";
import type { StoreFixture } from "./types";

const INITIAL_CAMERA_POSITION: [number, number, number] = [
  ORBIT_TARGET[0] + INITIAL_CAMERA_OFFSET[0],
  ORBIT_TARGET[1] + INITIAL_CAMERA_OFFSET[1],
  ORBIT_TARGET[2] + INITIAL_CAMERA_OFFSET[2],
];
/** Stop the orbit just before the camera crosses under the floor. */
const MAX_POLAR_ANGLE = Math.PI / 2 - 0.08;

function FrameCamera() {
  const camera = useThree((state) => state.camera);
  const width = useThree((state) => state.size.width);
  const height = useThree((state) => state.size.height);

  useLayoutEffect(() => {
    if (width < 1 || height < 1) {
      return;
    }
    const perspective = camera as PerspectiveCamera;
    perspective.aspect = width / height;
    perspective.fov = CAMERA_FOV;
    perspective.updateProjectionMatrix();
    const [x, y, z] = cameraPositionForAspect(width / height, storeFixture, [
      camera.position.x - ORBIT_TARGET[0],
      camera.position.y - ORBIT_TARGET[1],
      camera.position.z - ORBIT_TARGET[2],
    ]);
    camera.position.set(x, y, z);
    camera.lookAt(ORBIT_TARGET[0], ORBIT_TARGET[1], ORBIT_TARGET[2]);
    camera.updateMatrixWorld();
  }, [camera, height, width]);

  return null;
}

type StoreContentsProps = {
  store?: StoreFixture;
  showLabels?: boolean;
};

export function StoreContents({ store = storeFixture, showLabels = true }: StoreContentsProps) {
  return (
    <group {...entityProps(store.storeId, "store")}>
      <Floor />
      {store.shelves.map((shelf) => (
        <Shelf
          key={shelf.shelfId}
          shelf={shelf}
          products={store.products.filter((product) => product.shelfId === shelf.shelfId)}
          showLabels={showLabels}
        />
      ))}
    </group>
  );
}

export function StoreScene() {
  return (
    <Canvas camera={{ position: INITIAL_CAMERA_POSITION, fov: CAMERA_FOV }}>
      <color attach="background" args={["#1c2430"]} />
      <ambientLight intensity={0.55} />
      <directionalLight position={[4, 8, 3]} intensity={1.15} />
      <FrameCamera />
      <StoreContents />
      <OrbitControls
        makeDefault
        target={ORBIT_TARGET}
        enableDamping
        enablePan={false}
        minDistance={3}
        maxDistance={MAX_CAMERA_DISTANCE}
        maxPolarAngle={MAX_POLAR_ANGLE}
      />
    </Canvas>
  );
}
