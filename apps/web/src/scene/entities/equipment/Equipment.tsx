import { useTranslation } from "react-i18next";
import { EQUIPMENT_LABEL } from "@/constants/scene.constant";
import { EQUIPMENT_SIZE } from "@/constants/dimensions.constant";
import { ENTITY_TYPE, EQUIPMENT_KIND, type EquipmentKind } from "@/enums/scene.enum";
import type { EquipmentFixture, ProductFixture } from "@/scene/types";
import { toTuple } from "@/scene/utils/transform";
import { entityProps } from "@/scene/entities/entity";
import { LABEL_LIFT } from "@/constants/scene.constant";
import { useHover } from "@/hooks/hover.hook";
import { HoverHitBox, HoverLabel } from "@/scene/entities/HoverLabel";
import { SlotProducts } from "@/scene/entities/SlotProducts";
import { Barrier } from "./Barrier";
import { Checkout } from "./Checkout";
import { Crate } from "./Crate";
import { GlassDoorCooler } from "./GlassDoorCooler";
import { OpenChiller } from "./OpenChiller";
import { ProduceRack } from "./ProduceRack";

function Model({ kind }: { kind: EquipmentKind }) {
  switch (kind) {
    case EQUIPMENT_KIND.ProduceRack:
      return <ProduceRack />;
    case EQUIPMENT_KIND.GlassDoorCooler:
      return <GlassDoorCooler />;
    case EQUIPMENT_KIND.OpenChiller:
      return <OpenChiller />;
    case EQUIPMENT_KIND.Checkout:
      return <Checkout />;
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
  showLabels?: boolean;
};

export function Equipment({ equipment, products, showLabels = true }: EquipmentProps) {
  const label = showLabels ? EQUIPMENT_LABEL[equipment.kind] : undefined;
  return (
    <group
      position={toTuple(equipment.position)}
      rotation={[0, equipment.rotationY, 0]}
      {...entityProps(equipment.equipmentId, ENTITY_TYPE.Equipment)}
    >
      {label ? <Labelled equipment={equipment} title={label} /> : <Model kind={equipment.kind} />}
      <SlotProducts slots={equipment.slots} products={products} />
    </group>
  );
}

type LabelKey = NonNullable<(typeof EQUIPMENT_LABEL)[EquipmentKind]>;

function Labelled({ equipment, title }: { equipment: EquipmentFixture; title: LabelKey }) {
  const { t } = useTranslation();
  const [hovered, hoverHandlers] = useHover();
  const size = EQUIPMENT_SIZE[equipment.kind];
  return (
    <group>
      <Model kind={equipment.kind} />
      <HoverHitBox size={size} handlers={hoverHandlers} />
      {hovered ? (
        <HoverLabel title={t(title)} entityId={equipment.equipmentId} position={[0, size[1] + LABEL_LIFT, 0]} />
      ) : null}
    </group>
  );
}
