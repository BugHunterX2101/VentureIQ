import { useFrame, useThree, type ThreeEvent } from "@react-three/fiber";
import { useMemo, useRef, useState } from "react";
import * as THREE from "three";
import type { ConstellationData } from "../../lib/api";
import type { Theme } from "../../lib/theme";
import { SceneFrame } from "./SceneFrame";
import { PALETTE_3D, bandColor, type Palette3D } from "./palette3d";

export type { ConstellationData };

const vertex = /* glsl */ `
  attribute float size;
  attribute vec3 color;
  attribute float flag;
  uniform float uTime;
  uniform float uPixelRatio;
  uniform float uHover;
  attribute float idx;
  varying vec3 vColor;
  varying float vAlpha;
  void main() {
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    float pulse = flag > 0.5 ? 1.0 + 0.45 * (0.5 + 0.5 * sin(uTime * 2.6 + position.x * 3.0)) : 1.0;
    float hover = abs(idx - uHover) < 0.5 ? 2.4 : 1.0;
    gl_PointSize = size * pulse * hover * uPixelRatio * (30.0 / -mv.z);
    gl_Position = projectionMatrix * mv;
    vColor = color;
    vAlpha = hover > 1.0 ? 1.0 : 0.9;
  }
`;

const fragment = /* glsl */ `
  varying vec3 vColor;
  varying float vAlpha;
  void main() {
    vec2 c = gl_PointCoord - 0.5;
    float d = length(c);
    if (d > 0.5) discard;
    float core = smoothstep(0.5, 0.05, d);
    gl_FragColor = vec4(vColor, core * vAlpha);
  }
`;

/** Maps each company to a point.
 *  - angle: its sector's arm, with a gentle spiral twist
 *  - radius: composite score — the strongest companies sit nearest the core
 *  - colour: the same score bands used everywhere else; fraud-flagged
 *    companies are orange and pulse. */
function layout(data: ConstellationData, p: Palette3D) {
  const n = data.count;
  const arms = Math.max(1, data.sectors.length);
  const positions = new Float32Array(n * 3);
  const colors = new Float32Array(n * 3);
  const sizes = new Float32Array(n);
  const flags = new Float32Array(n);
  const idx = new Float32Array(n);
  const c = new THREE.Color();

  // Deterministic jitter so the layout is identical on every load.
  let seed = 7;
  const rand = () => {
    seed = (seed * 16807) % 2147483647;
    return seed / 2147483647;
  };

  for (let i = 0; i < n; i++) {
    const score = data.score[i];
    const fraud = data.fraud[i];
    const r = 0.55 + ((100 - score) / 60) * 3.1 + (rand() - 0.5) * 0.35;
    const base = (data.sector[i] / arms) * Math.PI * 2;
    const theta = base + r * 0.42 + (rand() - 0.5) * 0.34;
    positions[i * 3] = Math.cos(theta) * r;
    positions[i * 3 + 1] = (rand() - 0.5) * (0.25 + r * 0.12);
    positions[i * 3 + 2] = Math.sin(theta) * r;

    const flagged = fraud >= 35;
    c.set(flagged ? p.flagged : bandColor(p, score));
    colors[i * 3] = c.r;
    colors[i * 3 + 1] = c.g;
    colors[i * 3 + 2] = c.b;
    sizes[i] = (flagged ? 1.5 : 1) * (data.verified[i] ? 1.15 : 0.9) * (0.8 + score / 170);
    flags[i] = flagged ? 1 : 0;
    idx[i] = i;
  }
  return { positions, colors, sizes, flags, idx };
}

function Points({
  data,
  theme,
  onHover,
  onOpen,
}: {
  data: ConstellationData;
  theme: Theme;
  onHover: (i: number | null, x?: number, y?: number) => void;
  onOpen: (id: string) => void;
}) {
  const p = PALETTE_3D[theme];
  const group = useRef<THREE.Group>(null);
  const hovered = useRef(-1);
  const gl = useThree((s) => s.gl);
  const { positions, colors, sizes, flags, idx } = useMemo(() => layout(data, p), [data, p]);

  const material = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: vertex,
        fragmentShader: fragment,
        transparent: true,
        depthWrite: false,
        blending: theme === "dark" ? THREE.AdditiveBlending : THREE.NormalBlending,
        uniforms: {
          uTime: { value: 0 },
          uPixelRatio: { value: Math.min(window.devicePixelRatio, 1.75) },
          uHover: { value: -1 },
        },
      }),
    [theme],
  );

  // Faint orbit guides at composite 90 / 75 / 55.
  const rings = useMemo(
    () =>
      [90, 75, 55].map((s) => {
        const r = 0.55 + ((100 - s) / 60) * 3.1;
        const pts = Array.from({ length: 129 }, (_, k) => {
          const a = (k / 128) * Math.PI * 2;
          return new THREE.Vector3(Math.cos(a) * r, 0, Math.sin(a) * r);
        });
        return new THREE.BufferGeometry().setFromPoints(pts);
      }),
    [],
  );

  useFrame((state, delta) => {
    material.uniforms.uTime.value = state.clock.elapsedTime;
    const g = group.current;
    if (!g) return;
    // Hold still while a company is under the cursor, so it can be clicked.
    if (hovered.current < 0) g.rotation.y += delta * 0.06;
    const tx = 0.32 + state.pointer.y * 0.12;
    g.rotation.x += (tx - g.rotation.x) * 0.04;
  });

  const handleMove = (e: ThreeEvent<PointerEvent>) => {
    e.stopPropagation();
    const i = e.index ?? -1;
    if (i === hovered.current) return;
    hovered.current = i;
    material.uniforms.uHover.value = i;
    gl.domElement.style.cursor = i >= 0 ? "pointer" : "default";
    const rect = gl.domElement.getBoundingClientRect();
    onHover(i >= 0 ? i : null, e.nativeEvent.clientX - rect.left, e.nativeEvent.clientY - rect.top);
  };

  return (
    <group ref={group} rotation={[0.32, 0, 0]}>
      {rings.map((geo, k) => (
        <lineLoop key={k} geometry={geo}>
          <lineBasicMaterial color={p.grid} transparent opacity={0.45 - k * 0.1} />
        </lineLoop>
      ))}
      <mesh>
        <sphereGeometry args={[0.16, 24, 24]} />
        <meshBasicMaterial color={p.core} />
      </mesh>
      <points
        material={material}
        onPointerMove={handleMove}
        onPointerOut={() => {
          hovered.current = -1;
          material.uniforms.uHover.value = -1;
          gl.domElement.style.cursor = "default";
          onHover(null);
        }}
        onClick={(e) => {
          e.stopPropagation();
          if (e.index !== undefined) onOpen(data.id[e.index]);
        }}
      >
        <bufferGeometry>
          <bufferAttribute attach="attributes-position" args={[positions, 3]} />
          <bufferAttribute attach="attributes-color" args={[colors, 3]} />
          <bufferAttribute attach="attributes-size" args={[sizes, 1]} />
          <bufferAttribute attach="attributes-flag" args={[flags, 1]} />
          <bufferAttribute attach="attributes-idx" args={[idx, 1]} />
        </bufferGeometry>
      </points>
    </group>
  );
}

export default function Constellation({
  data,
  theme,
  onOpen,
  className = "",
}: {
  data: ConstellationData;
  theme: Theme;
  onOpen: (id: string) => void;
  className?: string;
}) {
  const [tip, setTip] = useState<{ i: number; x: number; y: number } | null>(null);
  const p = PALETTE_3D[theme];

  const fallback = (
    <div className="grid h-full place-items-center rounded-2xl border border-line bg-surface p-6 text-center text-[13px] text-ink-muted">
      3D view unavailable in this browser — {data.count.toLocaleString("en-US")} companies are listed in Discover.
    </div>
  );

  return (
    <SceneFrame
      className={className}
      label={`Constellation of ${data.count} real companies arranged by sector and composite score`}
      camera={{ position: [0, 3.2, 7.4], fov: 42 }}
      raycaster={{ params: { Points: { threshold: 0.09 } } } as never}
      fallback={fallback}
      overlay={
        tip && (
          <div
            className="overlay-panel pointer-events-none absolute z-10 w-[220px] rounded-xl p-3 text-[12.5px]"
            style={{
              left: Math.min(tip.x + 14, 9999),
              top: tip.y + 14,
              transform: tip.x > 260 ? "translateX(calc(-100% - 28px))" : undefined,
            }}
          >
            <div className="truncate text-[14px] font-bold text-ink">{data.name[tip.i]}</div>
            <div className="truncate text-ink-muted">{data.sectors[data.sector[tip.i]]}</div>
            <div className="tnum mt-1.5 flex items-center justify-between">
              <span className="text-ink-secondary">Composite</span>
              <b style={{ color: bandColor(p, data.score[tip.i]) }}>{data.score[tip.i].toFixed(1)}</b>
            </div>
            <div className="tnum flex items-center justify-between">
              <span className="text-ink-secondary">Fraud ↓</span>
              <b style={{ color: data.fraud[tip.i] >= 35 ? p.flagged : p.strong }}>{Math.round(data.fraud[tip.i])}</b>
            </div>
            <div className="mt-1.5 text-[11.5px] font-semibold text-brand-text">Click to open profile</div>
          </div>
        )
      }
    >
      <Points
        data={data}
        theme={theme}
        onOpen={onOpen}
        onHover={(i, x, y) => setTip(i === null ? null : { i, x: x ?? 0, y: y ?? 0 })}
      />
    </SceneFrame>
  );
}
