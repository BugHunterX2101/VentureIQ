/* Lightweight interaction effects.

   None of these pull in an animation library: they use CSS, requestAnimationFrame
   and IntersectionObserver, so they can sit on every card without cost. All of
   them stand still under prefers-reduced-motion. */

import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ElementType,
  type ReactNode,
} from "react";

export const prefersReducedMotion = () =>
  typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** True once the element has entered the viewport (and stays true). */
export function useInView<T extends Element>(rootMargin = "0px") {
  const ref = useRef<T>(null);
  const [inView, setInView] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || inView) return;
    if (typeof IntersectionObserver === "undefined") {
      setInView(true);
      return;
    }
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setInView(true);
          io.disconnect();
        }
      },
      { rootMargin },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [inView, rootMargin]);
  return [ref, inView] as const;
}

/** Tracks whether an element is currently on screen (both directions). */
export function useVisible<T extends Element>(rootMargin = "0px") {
  const ref = useRef<T>(null);
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting), { rootMargin });
    io.observe(el);
    return () => io.disconnect();
  }, [rootMargin]);
  return [ref, visible] as const;
}

/** Counts up to `value` the first time it scrolls into view. The final text is
 *  always the exact value, so nothing is ever shown rounded or invented. */
export function NumberTicker({
  value,
  format = (n) => Math.round(n).toLocaleString("en-US"),
  duration = 1100,
  className = "",
  style,
}: {
  value: number | null | undefined;
  format?: (n: number) => string;
  duration?: number;
  className?: string;
  style?: CSSProperties;
}) {
  const [ref, inView] = useInView<HTMLSpanElement>("-40px");
  const [shown, setShown] = useState<number | null>(null);

  useEffect(() => {
    if (value === null || value === undefined || !inView) return;
    if (prefersReducedMotion()) {
      setShown(value);
      return;
    }
    let raf = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      setShown(t === 1 ? value : value * eased);
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value, inView, duration]);

  return (
    <span ref={ref} className={className} style={style}>
      {value === null || value === undefined ? "—" : format(shown ?? 0)}
    </span>
  );
}

/** A card whose surface lights up under the cursor (Aceternity-style spotlight).
 *  The glow is a CSS radial gradient driven by two custom properties. */
export function Spotlight({
  as: Tag = "div",
  children,
  className = "",
  color = "var(--color-brand)",
  size = 340,
  ...rest
}: {
  as?: ElementType;
  children: ReactNode;
  className?: string;
  color?: string;
  size?: number;
  [key: string]: unknown;
}) {
  const ref = useRef<HTMLElement>(null);
  const onMove = (e: React.PointerEvent) => {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    el.style.setProperty("--sx", `${e.clientX - r.left}px`);
    el.style.setProperty("--sy", `${e.clientY - r.top}px`);
    el.style.setProperty("--so", "1");
  };
  const onLeave = () => ref.current?.style.setProperty("--so", "0");
  // Polymorphic tag; its props are the caller's responsibility.
  const Comp = Tag as "div";

  return (
    // `isolate` + a negative z-index keeps the glow above the card's own
    // background but beneath its content.
    <Comp ref={ref as React.RefObject<HTMLDivElement>} onPointerMove={onMove} onPointerLeave={onLeave} className={`relative isolate overflow-hidden ${className}`} {...rest}>
      <span
        aria-hidden
        className="pointer-events-none absolute inset-0 -z-10 transition-opacity duration-300"
        style={{
          opacity: "var(--so, 0)",
          background: `radial-gradient(${size}px circle at var(--sx, 50%) var(--sy, 50%), color-mix(in srgb, ${color} 12%, transparent), transparent 70%)`,
        }}
      />
      {children}
    </Comp>
  );
}

/** Subtle 3D tilt toward the cursor. Pure CSS transform, one rAF per move. */
export function Tilt({
  children,
  className = "",
  max = 6,
}: {
  children: ReactNode;
  className?: string;
  max?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const frame = useRef(0);
  const onMove = (e: React.PointerEvent) => {
    if (e.pointerType !== "mouse" || prefersReducedMotion()) return;
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const px = (e.clientX - r.left) / r.width - 0.5;
    const py = (e.clientY - r.top) / r.height - 0.5;
    cancelAnimationFrame(frame.current);
    frame.current = requestAnimationFrame(() => {
      el.style.transform = `perspective(1100px) rotateX(${(-py * max).toFixed(2)}deg) rotateY(${(px * max).toFixed(2)}deg)`;
    });
  };
  const onLeave = () => {
    cancelAnimationFrame(frame.current);
    if (ref.current) ref.current.style.transform = "";
  };
  return (
    <div
      ref={ref}
      onPointerMove={onMove}
      onPointerLeave={onLeave}
      className={className}
      style={{ transition: "transform 300ms cubic-bezier(0.16,1,0.3,1)", transformStyle: "preserve-3d" }}
    >
      {children}
    </div>
  );
}

/** Primary CTA with a light sheen that sweeps across on hover. */
export function Sheen({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <span className={`group/sheen relative inline-flex overflow-hidden ${className}`}>
      {children}
      <span
        aria-hidden
        className="pointer-events-none absolute inset-y-0 left-0 w-1/3 bg-gradient-to-r from-transparent via-white/35 to-transparent opacity-0 group-hover/sheen:animate-[sheen_900ms_ease] group-hover/sheen:opacity-100"
      />
    </span>
  );
}
