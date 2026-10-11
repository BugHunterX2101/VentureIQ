import type { Theme } from "../../lib/theme";

/** Scene colours per theme. They mirror the CSS status tokens so a point in the
 *  constellation means the same thing as a badge elsewhere in the product. */
export const PALETTE_3D = {
  light: {
    strong: "#12a150",
    moderate: "#1463ff",
    weak: "#d58a00",
    poor: "#d33b3b",
    flagged: "#ea580c",
    brand: "#1463ff",
    live: "#16a34a",
    mock: "#d97706",
    grid: "#cdd6e4",
    ghost: "#9aa9c2",
    edge: "#9fb4d9",
    core: "#1463ff",
  },
  dark: {
    strong: "#3fcf85",
    moderate: "#5b9df0",
    weak: "#f2b84b",
    poor: "#f07878",
    flagged: "#f5905e",
    brand: "#5b9df0",
    live: "#3fcf85",
    mock: "#f2b84b",
    grid: "#2f3d58",
    ghost: "#46577a",
    edge: "#3a5b94",
    core: "#7db2f5",
  },
} as const;

export type Palette3D = (typeof PALETTE_3D)[Theme];

export function bandColor(p: Palette3D, score: number): string {
  if (score >= 75) return p.strong;
  if (score >= 55) return p.moderate;
  if (score >= 35) return p.weak;
  return p.poor;
}

/** Fraud runs the other way: high is bad. */
export function fraudColor(p: Palette3D, fraud: number): string {
  if (fraud >= 60) return p.poor;
  if (fraud >= 35) return p.flagged;
  if (fraud >= 15) return p.weak;
  return p.strong;
}
