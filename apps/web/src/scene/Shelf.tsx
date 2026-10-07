import { Html } from "@react-three/drei";
import { MIDDLE_DECK_TOP, SHELF } from "./dimensions";
import { entityProps } from "./entity";
import { Product } from "./Product";
import { Slot } from "./Slot";
import type { ProductFixture, ShelfFixture } from "./types";

const DECK_TOPS = [0.08, MIDDLE_DECK_TOP, 1.68] as const;

type ShelfProps = {
  shelf: ShelfFixture;
  products: ProductFixture[];
  showLabels?: boolean;
};

export function Shelf({ shelf, products, showLabels = true }: ShelfProps) {
  const postX = SHELF.width / 2 - SHELF.post / 2;
  const deckWidth = SHELF.width - SHELF.post * 2;

  return (
    <group
      position={[shelf.position.x, shelf.position.y, shelf.position.z]}
      {...entityProps(shelf.shelfId, "shelf")}
    >
      {[-postX, postX].map((x) => (
        <mesh key={x} position={[x, SHELF.height / 2, 0]}>
          <boxGeometry args={[SHELF.post, SHELF.height, SHELF.depth]} />
          <meshStandardMaterial color={shelf.color} />
        </mesh>
      ))}
      {DECK_TOPS.map((top) => (
        <mesh key={top} position={[0, top - SHELF.board / 2, 0]}>
          <boxGeometry args={[deckWidth, SHELF.board, SHELF.depth]} />
          <meshStandardMaterial color={shelf.color} />
        </mesh>
      ))}
      <mesh position={[0, SHELF.height / 2, -SHELF.depth / 2 + 0.01]}>
        <boxGeometry args={[deckWidth, SHELF.height - 0.08, 0.02]} />
        <meshStandardMaterial color={shelf.color} />
      </mesh>
      {shelf.slots.map((slot) => (
        <Slot key={slot.slotId} slot={slot}>
          {products
            .filter((product) => product.slotId === slot.slotId)
            .map((product) => (
              <Product key={product.productId} product={product} showLabels={showLabels} />
            ))}
        </Slot>
      ))}
      {showLabels ? (
        <Html position={[0, SHELF.height + 0.16, 0]} center distanceFactor={8} style={{ pointerEvents: "none" }}>
          <span className="entity-label">{shelf.shelfId}</span>
        </Html>
      ) : null}
    </group>
  );
}
