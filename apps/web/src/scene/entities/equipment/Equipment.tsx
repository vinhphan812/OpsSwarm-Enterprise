import { useRef } from "react";
import type { Group } from "three";
import { EQUIPMENT_TITLE } from "@/constants/scene.constant";
import { EQUIPMENT_SIZE } from "@/constants/dimensions.constant";
import { ENTITY_TYPE, EQUIPMENT_KIND, type EquipmentKind } from "@/enums/scene.enum";
import type { EquipmentFixture, ProductFixture } from "@/types/scene.type";
import { toTuple } from "@/scene/utils/transform";
import { entityProps } from "@/scene/entities/entity";
import { useHover } from "@/hooks/hover.hook";
import { useSelectOnClick } from "@/hooks/selectEntity.hook";
import { useSelectionGlow } from "@/hooks/selectionGlow.hook";
import { isSelected, useUiStore } from "@/state/ui.store";
import { HitBox } from "@/scene/entities/HitBox";
import { SlotProducts } from "@/scene/entities/SlotProducts";
import { Barrier } from "./Barrier";
import { Checkout } from "./Checkout";
import { Crate } from "./Crate";
import { GlassDoorCooler } from "./GlassDoorCooler";
import { OpenChiller } from "./OpenChiller";
import { ProduceRack } from "./ProduceRack";

function Model({ kind, equipmentId }: { kind: EquipmentKind; equipmentId: string }) {
  switch (kind) {
    case EQUIPMENT_KIND.ProduceRack:
      return <ProduceRack />;
    case EQUIPMENT_KIND.GlassDoorCooler:
      return <GlassDoorCooler />;
    case EQUIPMENT_KIND.OpenChiller:
      return <OpenChiller />;
    case EQUIPMENT_KIND.Checkout:
      return <Checkout checkoutId={equipmentId} />;
    case EQUIPMENT_KIND.CratePlastic:
      return <Crate variant="plastic" />;
    case EQUIPMENT_KIND.CrateWood:
      return <Crate variant="wood" />;
    case EQUIPMENT_KIND.Barrier:
      return <Barrier />;
  }
}

type EquipmentProps = {
  equipment: EquipmentFixture;
  /** Products whose shelfId is this equipment. */
  products: ProductFixture[];
  /** Takes the pointer: hover and click-to-select. Off in tests, which have no pointer. */
  interactive?: boolean;
};

/**
 * One piece of equipment. Kinds with a card title (racks, coolers, chillers, checkouts)
 * take the pointer: a click selects the equipment and lights it up.
 */
export function Equipment({ equipment, products, interactive = true }: EquipmentProps) {
  const selectable = interactive && EQUIPMENT_TITLE[equipment.kind] !== undefined;
  const ref = useRef<Group>(null);
  const selected = useUiStore((state) => isSelected(state, equipment.equipmentId, ENTITY_TYPE.Equipment));
  useSelectionGlow(ref, selected);
  return (
    <group
      ref={ref}
      position={toTuple(equipment.position)}
      rotation={[0, equipment.rotationY, 0]}
      {...entityProps(equipment.equipmentId, ENTITY_TYPE.Equipment)}
    >
      <Model kind={equipment.kind} equipmentId={equipment.equipmentId} />
      {selectable ? <EquipmentHitBox equipment={equipment} /> : null}
      <SlotProducts slots={equipment.slots} products={products} />
    </group>
  );
}

function EquipmentHitBox({ equipment }: { equipment: EquipmentFixture }) {
  const [, hoverHandlers] = useHover();
  const onClick = useSelectOnClick(equipment.equipmentId, ENTITY_TYPE.Equipment);
  return <HitBox size={EQUIPMENT_SIZE[equipment.kind]} handlers={hoverHandlers} onClick={onClick} />;
}
