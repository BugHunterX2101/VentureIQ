export function compactUsd(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  const abs = Math.abs(n);
  if (abs >= 1e9) return `$${(n / 1e9).toFixed(abs >= 1e10 ? 0 : 1)}B`;
  if (abs >= 1e6) return `$${(n / 1e6).toFixed(abs >= 1e7 ? 0 : 1)}M`;
  if (abs >= 1e3) return `$${(n / 1e3).toFixed(0)}K`;
  return `$${n.toFixed(0)}`;
}

export function compactNum(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  const abs = Math.abs(n);
  if (abs >= 1e9) return `${(n / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return String(Math.round(n));
}

export const STAGE_LABEL: Record<string, string> = {
  idea: "Idea",
  seed: "Seed",
  series_a: "Series A",
  series_b_plus: "Series B+",
  growth: "Growth",
};

export function stageLabel(s: string | null | undefined): string {
  if (!s) return "—";
  return STAGE_LABEL[s] ?? s.replace(/_/g, " ");
}

/** Score → status band. The number is always rendered beside the colour, so
 *  meaning is never carried by hue alone. */
export function scoreBand(v: number | null | undefined): {
  tone: "good" | "neutral" | "warning" | "critical";
  color: string;
  label: string;
} {
  if (v === null || v === undefined)
    return { tone: "neutral", color: "var(--color-ink-muted)", label: "Unscored" };
  if (v >= 75) return { tone: "good", color: "var(--color-good)", label: "Strong" };
  if (v >= 55) return { tone: "neutral", color: "var(--color-series-1)", label: "Moderate" };
  if (v >= 35) return { tone: "warning", color: "var(--color-warning)", label: "Weak" };
  return { tone: "critical", color: "var(--color-critical)", label: "Poor" };
}

/** Fraud runs the other way: high is bad. */
export function fraudBand(v: number | null | undefined): {
  color: string;
  label: string;
} {
  if (v === null || v === undefined)
    return { color: "var(--color-ink-muted)", label: "Unknown" };
  if (v >= 60) return { color: "var(--color-critical)", label: "High risk" };
  if (v >= 35) return { color: "var(--color-serious)", label: "Elevated" };
  if (v >= 15) return { color: "var(--color-warning)", label: "Some signals" };
  return { color: "var(--color-good)", label: "Clean" };
}

export const SEVERITY_COLOR: Record<string, string> = {
  high: "var(--color-critical)",
  medium: "var(--color-serious)",
  low: "var(--color-warning)",
};

/** The API stores naive UTC timestamps; read them as UTC, not local time. */
export function apiDate(iso: string): Date {
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);
}

export function relativeTime(iso: string): string {
  const then = apiDate(iso).getTime();
  const secs = Math.floor((Date.now() - then) / 1000);
  if (secs < 60) return "just now";
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
}

export function titleCase(s: string): string {
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
