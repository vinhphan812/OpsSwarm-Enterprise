import { useMemo } from "react";
import { BackSide, Color, IcosahedronGeometry, MeshStandardMaterial, ShaderMaterial } from "three";
import { SKY_COLOR, SKY_ZENITH_COLOR } from "@/constants/scene.constant";
import { mulberry32 } from "@/core/utils/random";

const DOME_RADIUS = 400;

/** Horizon color at and below the horizon, fading to the zenith color overhead. Ignores fog and lights. */
function domeMaterial() {
  return new ShaderMaterial({
    side: BackSide,
    depthWrite: false,
    fog: false,
    uniforms: { horizon: { value: new Color(SKY_COLOR) }, zenith: { value: new Color(SKY_ZENITH_COLOR) } },
    vertexShader: /* glsl */ `
      varying float vHeight;
      void main() {
        vHeight = normalize(position).y;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
      }`,
    fragmentShader: /* glsl */ `
      uniform vec3 horizon;
      uniform vec3 zenith;
      varying float vHeight;
      void main() {
        gl_FragColor = vec4(mix(horizon, zenith, pow(clamp(vHeight, 0.0, 1.0), 0.6)), 1.0);
      }`,
  });
}

/** A low-poly cloud: a few flat-shaded balls in a row. */
type Puff = { position: [number, number, number]; scale: [number, number, number] };
type Cloud = { position: [number, number, number]; puffs: Puff[] };

/** Clouds in a ring well outside the street, the same on every load. */
function cloudsOf(count: number): Cloud[] {
  const random = mulberry32(20261014);
  return Array.from({ length: count }, (_, i) => {
    const angle = (i / count) * Math.PI * 2 + random() * 0.4;
    const distance = 110 + random() * 80;
    const size = 6 + random() * 6;
    const puffs = Array.from({ length: 3 + Math.floor(random() * 3) }, (_, k): Puff => {
      const r = size * (0.6 + random() * 0.5);
      return { position: [(k - 1.5) * size * 0.9, random() * size * 0.3, random() * size * 0.4], scale: [r * 1.3, r * 0.75, r] };
    });
    return { position: [Math.cos(angle) * distance, 38 + random() * 22, Math.sin(angle) * distance], puffs };
  });
}

const PUFF_GEOMETRY = new IcosahedronGeometry(1, 1);
/** Lit from above by the sun, so the tops would be the only bright side: a white glow keeps the undersides white too. */
const CLOUD_MATERIAL = new MeshStandardMaterial({
  color: "#ffffff",
  emissive: "#ffffff",
  emissiveIntensity: 0.55,
  flatShading: true,
  roughness: 1,
  fog: false,
});

/** A gradient sky dome and a ring of low-poly clouds. Decor: takes no pointer events and casts no shadows. */
export function Sky() {
  const dome = useMemo(domeMaterial, []);
  const clouds = useMemo(() => cloudsOf(14), []);
  const noRaycast = () => {};
  return (
    <group name="sky">
      <mesh material={dome} raycast={noRaycast} renderOrder={-1}>
        <sphereGeometry args={[DOME_RADIUS, 32, 16]} />
      </mesh>
      {clouds.map((cloud, i) => (
        <group key={i} position={cloud.position}>
          {cloud.puffs.map((puff, k) => (
            <mesh key={k} geometry={PUFF_GEOMETRY} material={CLOUD_MATERIAL} position={puff.position} scale={puff.scale} raycast={noRaycast} />
          ))}
        </group>
      ))}
    </group>
  );
}
