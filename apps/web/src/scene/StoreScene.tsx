import { OrbitControls } from "@react-three/drei";
import { Canvas } from "@react-three/fiber";
import { Floor } from "./Floor";
import { Shelf } from "./Shelf";
import { entityProps } from "./entity";
import { storeFixture } from "./storeFixture";
import type { StoreFixture } from "./types";

const CAMERA_POSITION: [number, number, number] = [6, 5, 8];
const ORBIT_TARGET: [number, number, number] = [0, 0.8, 0];
/** Stop the orbit just before the camera crosses under the floor. */
const MAX_POLAR_ANGLE = Math.PI / 2 - 0.08;

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
    <Canvas camera={{ position: CAMERA_POSITION, fov: 45 }}>
      <color attach="background" args={["#1c2430"]} />
      <ambientLight intensity={0.55} />
      <directionalLight position={[4, 8, 3]} intensity={1.15} />
      <StoreContents />
      <OrbitControls
        target={ORBIT_TARGET}
        enableDamping
        minDistance={3}
        maxDistance={16}
        maxPolarAngle={MAX_POLAR_ANGLE}
      />
    </Canvas>
  );
}
