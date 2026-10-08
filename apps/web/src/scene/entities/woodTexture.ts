import { CanvasTexture, RepeatWrapping, SRGBColorSpace, type Texture } from "three";
import { mulberry32, pick } from "@/core/utils/random";

/** Real-world size covered by one texture tile, in meters. */
export const WOOD_TILE_METERS = 2.4;

const SIZE = 1024;
const PLANKS_ACROSS = 9; // ~0.27 m wide planks
const PLANK_WIDTH = SIZE / PLANKS_ACROSS;

/** Pale oak tones, close to the light washed floor in the pmndrs shopping demo. */
const TONES = ["#b99f82", "#c4ab8e", "#ad9274", "#c9b298", "#a88c6d", "#bea486"];

type Plank = { x: number; y: number; length: number; tone: string };

function layoutPlanks(random: () => number): Plank[] {
  const planks: Plank[] = [];
  for (let column = 0; column < PLANKS_ACROSS; column += 1) {
    // Start each run at a random offset so joints are staggered; wrap so the tile repeats seamlessly.
    let y = -random() * SIZE;
    while (y < SIZE) {
      const length = SIZE * (0.6 + random() * 0.4);
      planks.push({
        x: column * PLANK_WIDTH,
        y,
        length,
        tone: pick(random, TONES),
      });
      y += length;
    }
  }
  return planks;
}

function drawGrain(ctx: CanvasRenderingContext2D, plank: Plank, random: () => number) {
  const lines = 10 + Math.floor(random() * 8);
  for (let i = 0; i < lines; i += 1) {
    const x = plank.x + 3 + random() * (PLANK_WIDTH - 6);
    const wobble = 1 + random() * 3;
    const phase = random() * Math.PI * 2;
    ctx.strokeStyle = random() > 0.5 ? "rgba(90,60,30,0.10)" : "rgba(255,245,230,0.12)";
    ctx.lineWidth = 0.6 + random() * 1.4;
    ctx.beginPath();
    for (let y = plank.y; y <= plank.y + plank.length; y += 8) {
      const dx = Math.sin(y / 60 + phase) * wobble;
      if (y === plank.y) ctx.moveTo(x + dx, y);
      else ctx.lineTo(x + dx, y);
    }
    ctx.stroke();
  }
  // An occasional knot.
  if (random() > 0.7) {
    const cx = plank.x + PLANK_WIDTH * (0.3 + random() * 0.4);
    const cy = plank.y + plank.length * random();
    ctx.fillStyle = "rgba(100,70,40,0.18)";
    ctx.beginPath();
    ctx.ellipse(cx, cy, 3 + random() * 3, 8 + random() * 8, 0, 0, Math.PI * 2);
    ctx.fill();
  }
}

/** Draws a plank and its copy one tile above or below, so planks crossing the edge tile cleanly. */
function forEachWrapped(plank: Plank, draw: (p: Plank) => void) {
  draw(plank);
  if (plank.y < 0) draw({ ...plank, y: plank.y + SIZE });
  if (plank.y + plank.length > SIZE) draw({ ...plank, y: plank.y - SIZE });
}

function paint(ctx: CanvasRenderingContext2D) {
  const random = mulberry32(7);
  ctx.fillStyle = TONES[0];
  ctx.fillRect(0, 0, SIZE, SIZE);

  for (const plank of layoutPlanks(random)) {
    const grainSeed = random() * 1e9;
    forEachWrapped(plank, (p) => {
      const gradient = ctx.createLinearGradient(p.x, 0, p.x + PLANK_WIDTH, 0);
      gradient.addColorStop(0, p.tone);
      gradient.addColorStop(0.5, "rgba(255,255,255,0.04)");
      gradient.addColorStop(1, p.tone);
      ctx.fillStyle = p.tone;
      ctx.fillRect(p.x, p.y, PLANK_WIDTH, p.length);
      ctx.fillStyle = gradient;
      ctx.fillRect(p.x, p.y, PLANK_WIDTH, p.length);
      drawGrain(ctx, p, mulberry32(grainSeed));
      // Seams: long edge and end joint.
      ctx.fillStyle = "rgba(70,50,30,0.35)";
      ctx.fillRect(p.x, p.y, 1.5, p.length);
      ctx.fillRect(p.x, p.y, PLANK_WIDTH, 1.5);
    });
  }
}

/**
 * Procedural light-oak plank texture. Returns null outside the browser (unit tests run in node),
 * so the floor falls back to a flat wood color there.
 */
export function createWoodTexture(): Texture | null {
  if (typeof document === "undefined") return null;
  const canvas = document.createElement("canvas");
  canvas.width = SIZE;
  canvas.height = SIZE;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  paint(ctx);

  const texture = new CanvasTexture(canvas);
  texture.colorSpace = SRGBColorSpace;
  texture.wrapS = RepeatWrapping;
  texture.wrapT = RepeatWrapping;
  texture.anisotropy = 8;
  return texture;
}
