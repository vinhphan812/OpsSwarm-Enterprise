import type { ReactNode } from "react";
import { ENTITY_TYPE } from "@/enums/scene.enum";
import { entityProps } from "./entity";
import type { SlotFixture } from "@/types/scene.type";
import { toTuple } from "@/scene/utils/transform";

type SlotProps = {
  slot: SlotFixture;
  children?: ReactNode;
};

export function Slot({ slot, children }: SlotProps) {
  return (
    <group
      position={toTuple(slot.position)}
      {...entityProps(slot.slotId, ENTITY_TYPE.Slot)}
    >
      {children}
    </group>
  );
}
