import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import type { Group, QuadraticBezierCurve3 } from "three";
import { Line2 } from "three/addons/lines/Line2.js";
import { LineGeometry } from "three/addons/lines/LineGeometry.js";
import { LineMaterial } from "three/addons/lines/LineMaterial.js";
import {
  MOVE_ARROW_OPACITY,
  MOVE_ARROW_OUTLINE_OPACITY,
  MOVE_ARROW_OUTLINE_PX,
  MOVE_ARROW_WIDTH_PX,
} from "@/constants/scene.constant";
import { moveColor } from "@/core/utils/theme";
import { exteriorLevel } from "@/scene/camera/exterior";

/** Points along a move's line; enough for a smooth arc at any zoom. */
const LINE_POINTS = 40;
/** The outline under the line: dark, so the line reads over light shelves and floor. */
const OUTLINE_COLOR = "#121820";

/**
 * The line materials, made on first use once the theme stylesheet has loaded. Lines are
 * drawn over the shelves (no depth test), so a move between two gondolas is never hidden.
 * `showArrows` fades them.
 */
let materials: { line: LineMaterial; outline: LineMaterial } | null = null;
function lineMaterials() {
  const flat = { transparent: true, depthTest: false, depthWrite: false };
  materials ??= {
    line: new LineMaterial({
      ...flat,
      color: moveColor(),
      linewidth: MOVE_ARROW_WIDTH_PX,
      opacity: MOVE_ARROW_OPACITY,
    }),
    outline: new LineMaterial({
      ...flat,
      color: OUTLINE_COLOR,
      linewidth: MOVE_ARROW_OUTLINE_PX,
      opacity: MOVE_ARROW_OUTLINE_OPACITY,
    }),
  };
  return materials;
}

/** How strongly the marks of the move show, from 0 to 1, as `showArrows` last set it. */
let markLevel = 1;

/** Sets how strongly the move lines show, from 0 to 1, along with the other marks of the move. */
export function showArrows(level: number) {
  markLevel = level;
}

/**
 * How strongly a line shows: the move's own level, faded out as the roof fades in. The line is
 * drawn over everything, so once the store is a closed building it would float over the roof.
 */
export function lineLevel(mark: number, exterior: number): number {
  return mark * (1 - exterior);
}

const NO_RAYCAST = () => null;

/** A move's line along `curve`, and the outline under it, sharing one geometry. */
function lineParts(curve: QuadraticBezierCurve3, line: LineMaterial, outline: LineMaterial) {
  const positions = curve
    .getSpacedPoints(LINE_POINTS)
    .flatMap((point) => point.toArray());
  const geometry = new LineGeometry().setPositions(positions);
  return { geometry, shaft: new Line2(geometry, line), under: new Line2(geometry, outline) };
}

/**
 * One line per move, from where the product stood to where it stands: a solid line of a
 * fixed width on screen over a thin dark outline. It fades with the other marks of the move,
 * and out as the camera zooms back far enough for the roof to close the store over it
 * (`exteriorLevel`). Takes no pointer events and casts no shadow.
 */
export function MoveArrows({ curves }: { curves: QuadraticBezierCurve3[] }) {
  const { line, outline } = lineMaterials();
  const parts = useMemo(() => curves.map((curve) => lineParts(curve, line, outline)), [curves, line, outline]);
  useEffect(() => () => parts.forEach(({ geometry }) => geometry.dispose()), [parts]);
  const size = useThree((state) => state.size);
  const controls = useThree((state) => state.controls) as { distance?: number; maxDistance?: number } | null;
  const group = useRef<Group>(null);

  useFrame(() => {
    if (!parts.length) return;
    line.resolution.set(size.width, size.height);
    outline.resolution.set(size.width, size.height);
    const exterior =
      controls?.distance !== undefined && controls.maxDistance !== undefined
        ? exteriorLevel({ distance: controls.distance, maxDistance: controls.maxDistance })
        : 0;
    const level = lineLevel(markLevel, exterior);
    line.opacity = MOVE_ARROW_OPACITY * level;
    outline.opacity = MOVE_ARROW_OUTLINE_OPACITY * level;
    if (group.current) group.current.visible = level > 0.01;
  });

  return (
    <group ref={group} name="stock-arrows">
      {parts.map(({ shaft, under }, index) => (
        <group key={index} name="stock-move-arrow">
          <primitive object={under} raycast={NO_RAYCAST} renderOrder={3} />
          <primitive object={shaft} raycast={NO_RAYCAST} renderOrder={4} />
        </group>
      ))}
    </group>
  );
}
