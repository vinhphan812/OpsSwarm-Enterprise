import { Html } from "@react-three/drei";
import { entityProps } from "./entity";
import type { ProductFixture } from "@/scene/types";

const FACING_W = 0.16;
const FACING_H = 0.22;
const FACING_D = 0.12;
const GAP = 0.02;

type ProductProps = {
  product: ProductFixture;
  showLabels?: boolean;
};

export function Product({ product, showLabels = true }: ProductProps) {
  const count = Math.max(1, product.facings);
  const total = count * FACING_W + (count - 1) * GAP;

  return (
    <group {...entityProps(product.productId, "product")}>
      {Array.from({ length: count }, (_, index) => {
        const x = -total / 2 + FACING_W / 2 + index * (FACING_W + GAP);
        return (
          <mesh key={index} position={[x, FACING_H / 2 + 0.005, 0]}>
            <boxGeometry args={[FACING_W, FACING_H, FACING_D]} />
            <meshStandardMaterial color={product.color} />
          </mesh>
        );
      })}
      {showLabels ? (
        <Html position={[0, FACING_H + 0.12, 0]} center distanceFactor={6} style={{ pointerEvents: "none" }}>
          <span className="entity-label">{product.productId}</span>
        </Html>
      ) : null}
    </group>
  );
}
