import { Color, MeshBasicMaterial, MeshPhysicalMaterial, MeshStandardMaterial, type Material } from "three";
import { CHECKOUT, LANE_LIGHT } from "@/constants/dimensions.constant";
import { goodColor, warningColor } from "@/core/utils/theme";
import { CHECKOUT_STATUS, type CheckoutStatus } from "@/enums/checkout.enum";
import { useCheckoutSummary } from "@/hooks/checkout.hook";
import { MAT, Parts, partBuilder } from "./parts";

const { length: L, depth: D, height: H } = CHECKOUT;
const RIM = 0.04;
const RIM_H = 0.025;
const TOP = H - RIM_H;
/** Worktop slab the stations are set into. */
const WORKTOP = 0.02;
/** Recessed dark plinth at the floor. */
const PLINTH = 0.09;
const PLINTH_INSET = 0.03;

/** Belt, then the scanner-scale, then the bagging well, left to right: the way goods travel. */
const BELT = { from: -L / 2 + RIM, to: -0.1 };
const SCALE = { from: -0.1, to: 0.3 };
const BAGGING = { from: 0.3, to: L / 2 - RIM };

/**
 * Checkout counter. Shoppers stand at the front (+Z); the cashier stands behind it.
 * Long axis along X. A warm white body on a recessed dark plinth, an accent stripe
 * on the shopper side, and a satin steel worktop holding a dark belt, a flush
 * scanner-scale with its scanner tower, and a steel bagging well. The customer
 * display and card terminal face the shopper; the register faces the cashier.
 */
const PARTS = (() => {
  const { parts, add } = partBuilder();
  const span = (r: { from: number; to: number }) => ({ x: (r.from + r.to) / 2, w: r.to - r.from });

  add("laminate", [0, PLINTH + (TOP - WORKTOP - PLINTH) / 2, 0], [L, TOP - WORKTOP - PLINTH, D]);
  add("cabinetDark", [0, PLINTH / 2, 0], [L - 2 * PLINTH_INSET, PLINTH, D - 2 * PLINTH_INSET]);
  add("worktop", [0, TOP - WORKTOP / 2, 0], [L + 0.01, WORKTOP, D + 0.01]);
  // Accent stripe under the worktop on the shopper side, wrapping onto the belt end.
  add("accent", [0, TOP - WORKTOP - 0.05, D / 2 + 0.002], [L - 0.002, 0.045, 0.004]);
  add("accent", [-L / 2 - 0.002, TOP - WORKTOP - 0.05, 0], [0.004, 0.045, D - 0.002]);

  // Raised rim around the top and between the stations.
  add("steel", [0, H - RIM_H / 2, D / 2 - RIM / 2], [L, RIM_H, RIM]);
  add("steel", [0, H - RIM_H / 2, -D / 2 + RIM / 2], [L, RIM_H, RIM]);
  for (const x of [-L / 2 + RIM / 2, L / 2 - RIM / 2, SCALE.from, SCALE.to]) {
    add("steel", [x, H - RIM_H / 2, 0], [RIM * 0.6, RIM_H, D - 2 * RIM]);
  }

  const belt = span(BELT);
  add("rubber", [belt.x, TOP + 0.004, 0], [belt.w - 0.02, 0.008, D - 2 * RIM - 0.02]);
  // Belt rollers at each end.
  for (const x of [BELT.from + 0.04, BELT.to - 0.04]) {
    add("cabinetDark", [x, TOP + 0.01, 0], [0.04, 0.02, D - 2 * RIM - 0.02]);
  }

  // Scanner-scale: a glass plate set flush into the worktop in a steel bezel, and a
  // vertical scanner tower on the shopper side whose window faces the cashier.
  const scale = span(SCALE);
  add("steel", [scale.x, TOP + 0.002, -0.05], [scale.w - 0.06, 0.004, 0.4]);
  add("screen", [scale.x, TOP + 0.005, -0.05], [scale.w - 0.1, 0.004, 0.34]);
  const towerZ = D / 2 - RIM - 0.07;
  const towerW = scale.w - 0.1;
  add("cabinetDark", [scale.x, TOP + 0.085, towerZ], [towerW, 0.17, 0.06]);
  add("screen", [scale.x, TOP + 0.095, towerZ - 0.031], [towerW - 0.06, 0.11, 0.004]);

  const bagging = span(BAGGING);
  add("steel", [bagging.x, TOP + 0.003, 0], [bagging.w - 0.02, 0.006, D - 2 * RIM - 0.02]);
  add("steel", [bagging.x, H - RIM_H / 2, 0], [bagging.w, RIM_H, RIM * 0.6]);

  // Shopper side at the head of the bagging well: the customer display on a pole,
  // then the card terminal, both tilted back toward the shopper (+Z).
  const shopperZ = D / 2 - RIM - 0.07;
  const displayX = BAGGING.from + 0.09;
  add("frame", [displayX, TOP + 0.18, shopperZ], [0.035, 0.36, 0.035]);
  add("frame", [displayX, TOP + 0.43, shopperZ], [0.26, 0.17, 0.035], [-0.2, 0, 0]);
  add("screen", [displayX, TOP + 0.434, shopperZ + 0.018], [0.22, 0.13, 0.004], [-0.2, 0, 0]);
  const cardX = BAGGING.from + 0.3;
  add("frame", [cardX, TOP + 0.03, shopperZ], [0.03, 0.06, 0.03]);
  add("frame", [cardX, TOP + 0.11, shopperZ], [0.09, 0.14, 0.03], [-0.5, 0, 0]);
  add("screen", [cardX, TOP + 0.144, shopperZ + 0.001], [0.07, 0.05, 0.004], [-0.5, 0, 0]);

  // Cash register on the cashier half of the bagging well: drawer, keyboard
  // nearest the cashier, and a screen tilted back toward them.
  const posX = bagging.x;
  const drawerTop = TOP + 0.1;
  add("cabinetDark", [posX, TOP + 0.05, -0.27], [0.42, 0.1, 0.36]);
  add("frame", [posX, drawerTop + 0.01, -0.38], [0.3, 0.02, 0.1]);
  add("frame", [posX, drawerTop + 0.08, -0.16], [0.04, 0.16, 0.04]);
  add("frame", [posX, drawerTop + 0.24, -0.16], [0.32, 0.22, 0.03], [0.25, 0, 0]);
  add("screen", [posX, drawerTop + 0.236, -0.177], [0.28, 0.18, 0.004], [0.25, 0, 0]);
  return parts;
})();

type LampState = CheckoutStatus | "unknown";

/** Shade and core materials per lane status. Made on first use, once the theme stylesheet has loaded. */
const lampMaterials = new Map<LampState, { shade: Material; core: Material }>();

/** Status color of a lit lane; null for a dark one. */
function litColor(status: CheckoutStatus | null): string | null {
  if (status === CHECKOUT_STATUS.Open) return goodColor();
  if (status === CHECKOUT_STATUS.Paused) return warningColor();
  return null;
}

function lampMaterialsFor(status: CheckoutStatus | null) {
  const key: LampState = status ?? "unknown";
  let materials = lampMaterials.get(key);
  if (!materials) {
    const lit = litColor(status);
    materials = lit
      ? {
          // A frosted shade washed toward white, with the status color glowing through it.
          shade: new MeshPhysicalMaterial({
            color: new Color(lit).lerp(new Color("#ffffff"), 0.45),
            emissive: lit,
            emissiveIntensity: 0.55,
            roughness: 0.35,
            transmission: 0.35,
            thickness: 0.02,
            transparent: true,
            opacity: 0.92,
          }),
          // Drawn past the tone mapper, so it reads as a light source rather than paint.
          core: new MeshBasicMaterial({ color: new Color(lit).lerp(new Color("#ffffff"), 0.25), toneMapped: false }),
        }
      : {
          shade: new MeshStandardMaterial({ color: "#8a9096", roughness: 0.45, metalness: 0.05 }),
          core: new MeshBasicMaterial({ color: "#3a3d40" }),
        };
    lampMaterials.set(key, materials);
  }
  return materials;
}

/** Marks the shade and core for the selection glow. One object, so a re-render never re-applies the mesh props. */
const KEEP_COLOR = { keepColor: true } as const;

const POLE_X = -L / 2 + LANE_LIGHT.inset;
const POLE_Z = -D / 2 + LANE_LIGHT.inset;

/**
 * Lane light on a pole at the belt end, on the cashier side: green while the lane is
 * open, amber while paused, dark while closed or unknown. A brushed-steel pole on a
 * flange, then a frosted shade between a dark collar and cap, lit by a core inside.
 * The shade and core keep their color when the checkout is selected.
 */
function LaneLight({ status }: { status: CheckoutStatus | null }) {
  const {
    poleHeight,
    poleRadius,
    baseRadius,
    baseHeight,
    collarRadius,
    collarHeight,
    diffuserRadius,
    diffuserHeight,
    coreRadius,
  } = LANE_LIGHT;
  const { shade, core } = lampMaterialsFor(status);
  const shadeY = poleHeight + collarHeight + diffuserHeight / 2;
  return (
    <group position={[POLE_X, H, POLE_Z]} name="lane-light" userData={{ status }}>
      <mesh position={[0, baseHeight / 2, 0]} material={MAT.steel}>
        <cylinderGeometry args={[baseRadius, baseRadius, baseHeight, 20]} />
      </mesh>
      <mesh position={[0, poleHeight / 2, 0]} material={MAT.steel} castShadow>
        <cylinderGeometry args={[poleRadius, poleRadius, poleHeight, 12]} />
      </mesh>
      <mesh position={[0, poleHeight + collarHeight / 2, 0]} material={MAT.cabinetDark} castShadow>
        <cylinderGeometry args={[collarRadius, collarRadius * 0.85, collarHeight, 24]} />
      </mesh>
      <mesh name="lane-lamp" position={[0, shadeY, 0]} material={shade} userData={KEEP_COLOR}>
        <cylinderGeometry args={[diffuserRadius, diffuserRadius, diffuserHeight, 24, 1, true]} />
      </mesh>
      <mesh position={[0, shadeY, 0]} material={core} userData={KEEP_COLOR}>
        <cylinderGeometry args={[coreRadius, coreRadius, diffuserHeight * 0.9, 16]} />
      </mesh>
      <mesh position={[0, shadeY + diffuserHeight / 2 + collarHeight / 2, 0]} material={MAT.cabinetDark} castShadow>
        <cylinderGeometry args={[collarRadius * 0.85, collarRadius, collarHeight, 24]} />
      </mesh>
    </group>
  );
}

/** Checkout counter with its lane light. TODO(BE): the lane status is sample data (`useCheckoutSummary`). */
export function Checkout({ checkoutId }: { checkoutId: string }) {
  const status = useCheckoutSummary(checkoutId)?.status ?? null;
  return (
    <>
      <Parts parts={PARTS} />
      <LaneLight status={status} />
    </>
  );
}
