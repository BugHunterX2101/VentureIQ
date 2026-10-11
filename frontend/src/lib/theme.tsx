import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { flushSync } from "react-dom";

export type ThemePref = "light" | "dark" | "system";
export type Theme = "light" | "dark";

const KEY = "viq.theme";

function readPref(): ThemePref {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" || v === "system" ? v : "system";
  } catch {
    return "system";
  }
}

const systemTheme = (): Theme =>
  typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";

function apply(theme: Theme) {
  const root = document.documentElement;
  root.dataset.theme = theme;
  root.style.colorScheme = theme;
}

interface Ctx {
  pref: ThemePref;
  theme: Theme;
  setPref: (p: ThemePref, origin?: { x: number; y: number }) => void;
  toggle: (origin?: { x: number; y: number }) => void;
}

const ThemeContext = createContext<Ctx>({
  pref: "system",
  theme: "light",
  setPref: () => {},
  toggle: () => {},
});

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [pref, setPrefState] = useState<ThemePref>(readPref);
  const [theme, setTheme] = useState<Theme>(() =>
    pref === "system" ? systemTheme() : pref,
  );

  // Follow the OS while the preference is "system".
  useEffect(() => {
    if (pref !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      const t = mq.matches ? "dark" : "light";
      setTheme(t);
      apply(t);
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [pref]);

  const setPref = useCallback((p: ThemePref, origin?: { x: number; y: number }) => {
    const next: Theme = p === "system" ? systemTheme() : p;
    try {
      localStorage.setItem(KEY, p);
    } catch {
      /* storage unavailable — the choice lasts for this page only */
    }

    const commit = () => {
      flushSync(() => {
        setPrefState(p);
        setTheme(next);
      });
      apply(next);
    };

    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const doc = document as Document & {
      startViewTransition?: (cb: () => void) => { ready: Promise<void> };
    };

    // Circular reveal from the toggle, where the browser supports it.
    if (doc.startViewTransition && origin && !reduce) {
      const r = Math.hypot(
        Math.max(origin.x, window.innerWidth - origin.x),
        Math.max(origin.y, window.innerHeight - origin.y),
      );
      const vt = doc.startViewTransition(commit);
      vt.ready
        .then(() => {
          document.documentElement.animate(
            {
              clipPath: [
                `circle(0px at ${origin.x}px ${origin.y}px)`,
                `circle(${r}px at ${origin.x}px ${origin.y}px)`,
              ],
            },
            { duration: 520, easing: "cubic-bezier(0.16, 1, 0.3, 1)", pseudoElement: "::view-transition-new(root)" },
          );
        })
        .catch(() => {});
      return;
    }

    // Fallback: a short colour cross-fade.
    const root = document.documentElement;
    if (!reduce) root.classList.add("theme-anim");
    commit();
    window.setTimeout(() => root.classList.remove("theme-anim"), 320);
  }, []);

  const toggle = useCallback(
    (origin?: { x: number; y: number }) => setPref(theme === "dark" ? "light" : "dark", origin),
    [theme, setPref],
  );

  return (
    <ThemeContext.Provider value={{ pref, theme, setPref, toggle }}>{children}</ThemeContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export const useTheme = () => useContext(ThemeContext);
