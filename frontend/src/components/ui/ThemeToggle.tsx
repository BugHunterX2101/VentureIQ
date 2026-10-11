import { AnimatePresence, m } from "motion/react";
import { useTheme } from "../../lib/theme";

/** Light/dark switch. The icon morphs; the page reveals as a circle from the
 *  button where View Transitions are supported. */
export function ThemeToggle({ className = "" }: { className?: string }) {
  const { theme, toggle } = useTheme();
  const dark = theme === "dark";

  return (
    <button
      type="button"
      onClick={(e) => {
        const r = e.currentTarget.getBoundingClientRect();
        toggle({ x: r.left + r.width / 2, y: r.top + r.height / 2 });
      }}
      aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
      title={dark ? "Light theme" : "Dark theme"}
      className={`relative grid h-10 w-10 shrink-0 place-items-center overflow-hidden rounded-full border border-line-strong bg-surface text-ink-secondary transition-colors hover:bg-raised hover:text-ink ${className}`}
    >
      <AnimatePresence mode="wait" initial={false}>
        {dark ? (
          <m.svg
            key="moon"
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            aria-hidden
            initial={{ rotate: -90, scale: 0.4, opacity: 0 }}
            animate={{ rotate: 0, scale: 1, opacity: 1 }}
            exit={{ rotate: 90, scale: 0.4, opacity: 0 }}
            transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
          >
            <path
              d="M20.5 14.6A8.5 8.5 0 0 1 9.4 3.5a8.5 8.5 0 1 0 11.1 11.1Z"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinejoin="round"
            />
          </m.svg>
        ) : (
          <m.svg
            key="sun"
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            aria-hidden
            initial={{ rotate: 90, scale: 0.4, opacity: 0 }}
            animate={{ rotate: 0, scale: 1, opacity: 1 }}
            exit={{ rotate: -90, scale: 0.4, opacity: 0 }}
            transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
          >
            <circle cx="12" cy="12" r="4" stroke="currentColor" strokeWidth="2" />
            <path
              d="M12 2.5v2M12 19.5v2M4.6 4.6 6 6M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4 6 18M18 6l1.4-1.4"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
            />
          </m.svg>
        )}
      </AnimatePresence>
    </button>
  );
}
