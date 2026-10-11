import { AnimatePresence, m } from "motion/react";
import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";

type Tone = "info" | "good" | "warning";
interface ToastItem {
  id: number;
  title: string;
  body?: string;
  tone: Tone;
}

const ToastContext = createContext<(t: Omit<ToastItem, "id" | "tone"> & { tone?: Tone }) => void>(() => {});

const TONE: Record<Tone, string> = {
  info: "var(--color-brand)",
  good: "var(--color-good)",
  warning: "var(--color-warning)",
};

/** Transient confirmations for actions whose effect isn't otherwise visible
 *  (a behavioural event recorded, an agent run finished). Announced politely
 *  to screen readers. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const next = useRef(1);

  const push = useCallback((t: Omit<ToastItem, "id" | "tone"> & { tone?: Tone }) => {
    const id = next.current++;
    setItems((xs) => [...xs.slice(-2), { id, tone: t.tone ?? "info", title: t.title, body: t.body }]);
    window.setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), 3800);
  }, []);

  return (
    <ToastContext.Provider value={push}>
      {children}
      <div
        aria-live="polite"
        className="pointer-events-none fixed bottom-4 right-4 z-[80] flex w-[min(360px,calc(100vw-2rem))] flex-col gap-2"
      >
        <AnimatePresence initial={false}>
          {items.map((t) => (
            <m.div
              key={t.id}
              layout
              initial={{ opacity: 0, y: 16, scale: 0.97 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, x: 24, transition: { duration: 0.18 } }}
              transition={{ type: "spring", stiffness: 420, damping: 32 }}
              className="overlay-panel pointer-events-auto flex gap-3 rounded-xl p-3.5"
            >
              <span className="mt-1 h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: TONE[t.tone] }} />
              <div className="min-w-0">
                <div className="text-[13.5px] font-bold text-ink">{t.title}</div>
                {t.body && <div className="mt-0.5 text-[12.5px] leading-snug text-ink-muted">{t.body}</div>}
              </div>
            </m.div>
          ))}
        </AnimatePresence>
      </div>
    </ToastContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export const useToast = () => useContext(ToastContext);
