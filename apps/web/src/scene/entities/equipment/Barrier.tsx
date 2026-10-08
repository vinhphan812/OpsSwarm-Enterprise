import { BARRIER } from "@/constants/dimensions.constant";
import { Parts, partBuilder } from "./parts";

const { length: L, height: H } = BARRIER;
const TUBE = 0.035;

/** Freestanding guide rail: posts on weighted feet with a top and a bottom rail. Long axis along X. */
const PARTS = (() => {
  const { parts, add } = partBuilder();
  for (const x of [-L / 2, 0, L / 2]) {
    add("steel", [x, H / 2, 0], [TUBE, H, TUBE]);
    add("cabinetDark", [x, 0.015, 0], [0.1, 0.03, 0.1]);
  }
  add("steel", [0, H - TUBE / 2, 0], [L + TUBE, TUBE, TUBE]);
  add("steel", [0, 0.2, 0], [L, TUBE * 0.8, TUBE * 0.8]);
  return parts;
})();

export function Barrier() {
  return <Parts parts={PARTS} />;
}
