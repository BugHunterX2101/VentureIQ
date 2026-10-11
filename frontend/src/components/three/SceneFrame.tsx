import { Canvas, type CanvasProps } from "@react-three/fiber";
import { useEffect, useState, type ReactNode } from "react";
import { prefersReducedMotion, useVisible } from "../ui/effects";

export function hasWebGL(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}

/** Shared canvas wrapper.
 *
 *  - Renders continuously only while on screen; offscreen it drops to
 *    on-demand, so a scene below the fold costs nothing per frame.
 *  - Under prefers-reduced-motion it renders a still frame.
 *  - Pixel ratio is capped so high-DPI laptops don't render 4x the pixels.
 *  - Without WebGL, the caller's HTML fallback is shown instead. */
export function SceneFrame({
  children,
  overlay,
  fallback,
  className = "",
  camera,
  onReady,
  raycaster,
  label,
}: {
  children: ReactNode;
  overlay?: ReactNode;
  fallback: ReactNode;
  className?: string;
  camera?: CanvasProps["camera"];
  onReady?: () => void;
  raycaster?: CanvasProps["raycaster"];
  label: string;
}) {
  const [ref, visible] = useVisible<HTMLDivElement>("120px");
  const [supported] = useState(hasWebGL);
  const [reduce, setReduce] = useState(prefersReducedMotion);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const on = () => setReduce(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);

  if (!supported) return <div className={className}>{fallback}</div>;

  return (
    <div ref={ref} className={`relative ${className}`} role="img" aria-label={label}>
      <Canvas
        frameloop={visible && !reduce ? "always" : "demand"}
        dpr={[1, 1.75]}
        gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
        camera={camera}
        raycaster={raycaster}
        onCreated={() => onReady?.()}
        style={{ position: "absolute", inset: 0 }}
      >
        {children}
      </Canvas>
      {overlay}
    </div>
  );
}
