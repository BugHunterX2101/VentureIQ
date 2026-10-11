import { useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";
import type { Theme } from "../../lib/theme";
import { SceneFrame } from "./SceneFrame";
import { PALETTE_3D, bandColor, fraudColor } from "./palette3d";

export interface TowerScore {
  label: string;
  value: number;
  invert?: boolean;
}

const MAX_H = 2.6;
const SPACING = 1.15;

function Tower({ x, value, color, ghost, delay }: { x: number; value: number; color: string; ghost: string; delay: number }) {
  const mesh = useRef<THREE.Mesh>(null);
  const cap = useRef<THREE.Mesh>(null);
  const h = useRef(0.001);
  const target = Math.max(0.04, (value / 100) * MAX_H);
  const edges = useMemo(() => new THREE.EdgesGeometry(new THREE.BoxGeometry(0.72, MAX_H, 0.72)), []);

  useFrame((state) => {
    if (state.clock.elapsedTime < delay) return;
    h.current += (target - h.current) * 0.06;
    if (mesh.current) {
      mesh.current.scale.y = h.current;
      mesh.current.position.y = h.current / 2;
    }
    if (cap.current) cap.current.position.y = h.current + 0.012;
  });

  return (
    <group position={[x, 0, 0]}>
      {/* Ghost outline of the full 100-point scale. */}
      <lineSegments geometry={edges} position={[0, MAX_H / 2, 0]}>
        <lineBasicMaterial color={ghost} transparent opacity={0.35} />
      </lineSegments>
      <mesh ref={mesh} scale={[1, 0.001, 1]}>
        <boxGeometry args={[0.72, 1, 0.72]} />
        <meshStandardMaterial color={color} roughness={0.35} metalness={0.15} transparent opacity={0.92} />
      </mesh>
      <mesh ref={cap} rotation={[-Math.PI / 2, 0, 0]}>
        <planeGeometry args={[0.72, 0.72]} />
        <meshBasicMaterial color={color} transparent opacity={0.55} />
      </mesh>
    </group>
  );
}

function Rig() {
  useFrame((state) => {
    const t = state.clock.elapsedTime;
    const a = Math.sin(t * 0.25) * 0.28 + state.pointer.x * 0.2;
    state.camera.position.x = Math.sin(a) * 6.2;
    state.camera.position.z = Math.cos(a) * 6.2;
    state.camera.position.y = 2.6 + state.pointer.y * 0.4;
    state.camera.lookAt(0, 1.05, 0);
  });
  return null;
}

export default function ScoreTowers({
  scores,
  theme,
  className = "",
}: {
  scores: TowerScore[];
  theme: Theme;
  className?: string;
}) {
  const p = PALETTE_3D[theme];
  const offset = ((scores.length - 1) * SPACING) / 2;

  const fallback = (
    <div className="grid h-full grid-cols-4 items-end gap-2 p-4">
      {scores.map((s) => (
        <div key={s.label} className="rounded-t-md" style={{ height: `${Math.max(3, s.value)}%`, background: s.invert ? fraudColor(p, s.value) : bandColor(p, s.value) }} />
      ))}
    </div>
  );

  return (
    <SceneFrame
      className={className}
      label={`3D bars of four scores: ${scores.map((s) => `${s.label} ${Math.round(s.value)}`).join(", ")}`}
      camera={{ position: [0, 2.6, 6.2], fov: 38 }}
      fallback={fallback}
    >
      <ambientLight intensity={theme === "dark" ? 0.55 : 0.9} />
      <directionalLight position={[3, 6, 4]} intensity={theme === "dark" ? 1.6 : 1.3} />
      <directionalLight position={[-4, 3, -2]} intensity={0.4} color={p.brand} />
      <gridHelper args={[7, 14, p.grid, p.grid]} position={[0, 0, 0]} />
      {scores.map((s, i) => (
        <Tower
          key={s.label}
          x={i * SPACING - offset}
          value={s.value}
          color={s.invert ? fraudColor(p, s.value) : bandColor(p, s.value)}
          ghost={p.ghost}
          delay={0.15 + i * 0.12}
        />
      ))}
      <Rig />
    </SceneFrame>
  );
}
