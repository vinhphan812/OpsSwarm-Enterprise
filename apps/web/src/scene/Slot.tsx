import type { ReactNode } from "react";
import { entityProps } from "./entity";
import type { SlotFixture } from "./types";

type SlotProps = {
  slot: SlotFixture;
  children?: ReactNode;
};

export function Slot({ slot, children }: SlotProps) {
  return (
    <group
      position={[slot.position.x, slot.position.y, slot.position.z]}
      {...entityProps(slot.slotId, "slot")}
    >
      {children}
    </group>
  );
}
