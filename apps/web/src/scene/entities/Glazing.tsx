import { GLAZING } from "@/constants/dimensions.constant";
import type { Tuple3 } from "@/scene/utils/transform";
import { GLAZING_FRAME_COLOR } from "@/constants/scene.constant";

const F = GLAZING.frame;

function GlassMaterial() {
  return (
    <meshPhysicalMaterial
      color="#dce8ec"
      transparent
      opacity={0.16}
      roughness={0.05}
      metalness={0}
      envMapIntensity={1.5}
      depthWrite={false}
    />
  );
}

function FrameBar({ position, size }: { position: Tuple3; size: Tuple3 }) {
  return (
    <mesh position={position} castShadow>
      <boxGeometry args={size} />
      <meshStandardMaterial color={GLAZING_FRAME_COLOR} roughness={0.4} metalness={0.6} />
    </mesh>
  );
}

type PaneProps = {
  width: number;
  height: number;
  /** Center of the pane's bottom edge. */
  position: Tuple3;
};

/** One framed glass pane. Glass does not cast shadows, so sunlight passes through it. */
function Pane({ width, height, position }: PaneProps) {
  const [x, y, z] = position;
  return (
    <group position={[x, y, z]}>
      <mesh position={[0, height / 2, 0]} renderOrder={1}>
        <planeGeometry args={[width - F, height - F]} />
        <GlassMaterial />
      </mesh>
      <FrameBar position={[0, F / 2, 0]} size={[width, F, F]} />
      <FrameBar position={[0, height - F / 2, 0]} size={[width, F, F]} />
      <FrameBar position={[-width / 2 + F / 2, height / 2, 0]} size={[F, height, F]} />
      <FrameBar position={[width / 2 - F / 2, height / 2, 0]} size={[F, height, F]} />
    </group>
  );
}

type GlazingProps = {
  width: number;
  height: number;
  /** Center of the opening's bottom edge, in wall-local coordinates. */
  position: Tuple3;
};

/** Floor-to-lintel fixed glazing split into evenly spaced panes. */
export function CurtainWall({ width, height, position }: GlazingProps) {
  const panes = Math.max(1, Math.round(width / GLAZING.paneWidth));
  const paneWidth = width / panes;
  return (
    <group name="curtain-wall" position={position}>
      {Array.from({ length: panes }, (_, i) => (
        <Pane
          key={i}
          width={paneWidth}
          height={height}
          position={[-width / 2 + paneWidth * (i + 0.5), 0, 0]}
        />
      ))}
      {/* Transom bar across all panes. */}
      <FrameBar position={[0, GLAZING.transom, 0]} size={[width, F * 0.6, F * 0.6]} />
    </group>
  );
}

/**
 * Two-leaf sliding glass door. The leaves sit on offset tracks and overlap
 * slightly in the middle, like a real lift-and-slide door.
 */
export function SlidingDoor({ width, height, position }: GlazingProps) {
  const leaf = width / 2 + F / 2;
  const track = F * 1.2;
  return (
    <group name="sliding-door" position={position}>
      <Pane width={leaf} height={height} position={[-width / 4 + F / 4, 0, track / 2]} />
      <Pane width={leaf} height={height} position={[width / 4 - F / 4, 0, -track / 2]} />
      {/* Long pull handles on the meeting stiles. */}
      <FrameBar position={[-F * 1.5, height * 0.48, track / 2 + F]} size={[0.025, 1.1, 0.025]} />
      <FrameBar position={[F * 1.5, height * 0.48, -track / 2 + F]} size={[0.025, 1.1, 0.025]} />
    </group>
  );
}
