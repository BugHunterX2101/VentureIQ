import { useFrame, useThree } from "@react-three/fiber";
import { useMemo, useRef, type RefObject } from "react";
import * as THREE from "three";
import type { Theme } from "../../lib/theme";
import { SceneFrame } from "./SceneFrame";
import { PALETTE_3D } from "./palette3d";

export interface AgentStep {
  source: string;
  live: boolean;
  status: string;
}

const RADIUS = 2.25;
const STEP_S = 1.1;

function nodePosition(i: number, n: number) {
  const a = (i / n) * Math.PI * 2 - Math.PI / 2;
  return new THREE.Vector3(Math.cos(a) * RADIUS, Math.sin(a * 2) * 0.25, Math.sin(a) * RADIUS);
}

function Graph({
  steps,
  theme,
  labels,
}: {
  steps: AgentStep[];
  theme: Theme;
  labels: RefObject<(HTMLDivElement | null)[]>;
}) {
  const p = PALETTE_3D[theme];
  const group = useRef<THREE.Group>(null);
  const shell = useRef<THREE.Mesh>(null);
  const pulse = useRef<THREE.Mesh>(null);
  const nodes = useRef<(THREE.Mesh | null)[]>([]);
  const size = useThree((s) => s.size);
  const n = steps.length;
  const positions = useMemo(() => steps.map((_, i) => nodePosition(i, n)), [steps, n]);
  const lines = useMemo(() => {
    const mat = new THREE.LineBasicMaterial({ color: p.edge, transparent: true, opacity: 0.7 });
    return positions.map(
      (v) => new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0, 0, 0), v]), mat),
    );
  }, [positions, p.edge]);
  const tmp = useMemo(() => new THREE.Vector3(), []);

  useFrame((state, delta) => {
    const g = group.current;
    if (!g || !n) return;
    g.rotation.y += delta * 0.12;
    g.rotation.x += (0.38 + state.pointer.y * 0.1 - g.rotation.x) * 0.05;
    if (shell.current) shell.current.rotation.y -= delta * 0.4;

    // One pulse per source, in plan order, travelling agent → source.
    const t = state.clock.elapsedTime / STEP_S;
    const active = Math.floor(t) % n;
    const f = t % 1;
    if (pulse.current) {
      pulse.current.position.copy(positions[active]).multiplyScalar(f);
      const m = pulse.current.material as THREE.MeshBasicMaterial;
      m.color.set(steps[active].live ? p.live : p.mock);
    }
    nodes.current.forEach((node, i) => {
      if (!node) return;
      const s = i === active ? 1 + Math.max(0, f - 0.75) * 2.4 : 1;
      node.scale.setScalar(node.scale.x + (s - node.scale.x) * 0.2);
    });

    // Keep the HTML labels pinned to their nodes.
    const els = labels.current;
    positions.forEach((pos, i) => {
      const el = els?.[i];
      if (!el) return;
      tmp.copy(pos).applyMatrix4(g.matrixWorld).project(state.camera);
      // Clamp so labels near the edge stay inside the frame.
      const half = el.offsetWidth / 2 + 6;
      const x = Math.min(size.width - half, Math.max(half, (tmp.x * 0.5 + 0.5) * size.width));
      const y = (-tmp.y * 0.5 + 0.5) * size.height;
      el.style.transform = `translate(-50%, -140%) translate(${x.toFixed(1)}px, ${y.toFixed(1)}px)`;
      el.style.opacity = tmp.z < 1 ? "1" : "0";
    });
  });

  return (
    <group ref={group}>
      <mesh>
        <icosahedronGeometry args={[0.42, 1]} />
        <meshStandardMaterial color={p.brand} roughness={0.3} metalness={0.2} emissive={p.brand} emissiveIntensity={0.25} />
      </mesh>
      <mesh ref={shell}>
        <icosahedronGeometry args={[0.66, 1]} />
        <meshBasicMaterial color={p.brand} wireframe transparent opacity={0.28} />
      </mesh>
      {lines.map((line, i) => (
        <primitive key={i} object={line} />
      ))}
      {positions.map((pos, i) => (
        <mesh key={steps[i].source} ref={(m) => void (nodes.current[i] = m)} position={pos}>
          <sphereGeometry args={[0.2, 24, 24]} />
          <meshStandardMaterial
            color={steps[i].live ? p.live : p.mock}
            emissive={steps[i].live ? p.live : p.mock}
            emissiveIntensity={0.35}
            roughness={0.4}
          />
        </mesh>
      ))}
      <mesh ref={pulse}>
        <sphereGeometry args={[0.08, 16, 16]} />
        <meshBasicMaterial color={p.live} />
      </mesh>
    </group>
  );
}

export default function AgentGraph({
  steps,
  theme,
  className = "",
}: {
  steps: AgentStep[];
  theme: Theme;
  className?: string;
}) {
  const labels = useRef<(HTMLDivElement | null)[]>([]);

  const fallback = (
    <div className="flex h-full flex-wrap content-center justify-center gap-2 p-4">
      {steps.map((s) => (
        <span key={s.source} className="chip">
          {s.source} · {s.live ? "live" : "mocked"}
        </span>
      ))}
    </div>
  );

  return (
    <SceneFrame
      className={className}
      label={`Verification agent graph with ${steps.length} sources: ${steps
        .map((s) => `${s.source} ${s.live ? "live" : "mocked"}`)
        .join(", ")}`}
      camera={{ position: [0, 2.4, 6.4], fov: 40 }}
      fallback={fallback}
      overlay={
        <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden>
          {steps.map((s, i) => (
            <div
              key={s.source}
              ref={(el) => void (labels.current[i] = el)}
              className="tnum absolute left-0 top-0 whitespace-nowrap rounded-md border border-panel-line bg-panel px-1.5 py-0.5 text-[11px] font-semibold text-panel-ink"
              style={{ opacity: 0 }}
            >
              {s.source}
              <span className={s.live ? "ml-1 text-panel-accent" : "ml-1 text-panel-warn"}>
                {s.live ? "live" : "mock"}
              </span>
            </div>
          ))}
        </div>
      }
    >
      <ambientLight intensity={0.7} />
      <directionalLight position={[3, 5, 4]} intensity={1.4} />
      <Graph steps={steps} theme={theme} labels={labels} />
    </SceneFrame>
  );
}
