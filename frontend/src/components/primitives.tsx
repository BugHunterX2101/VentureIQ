import { useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { fraudBand, scoreBand } from "../lib/format";

export function Card({
  children,
  className = "",
  lit = true,
  id,
}: {
  children: ReactNode;
  className?: string;
  lit?: boolean;
  id?: string;
}) {
  return (
    <div id={id} className={`card ${lit ? "card-lit" : ""} ${className}`}>
      {children}
    </div>
  );
}

export function SectionHeader({
  eyebrow,
  title,
  action,
  description,
}: {
  eyebrow?: string;
  title: string;
  action?: ReactNode;
  description?: string;
}) {
  return (
    <div className="mb-4 flex items-start justify-between gap-4">
      <div className="min-w-0">
        {eyebrow && <div className="eyebrow mb-1">{eyebrow}</div>}
        <h2 className="text-[17px] font-bold tracking-tight text-ink">{title}</h2>
        {description && (
          <p className="mt-1 max-w-2xl text-[13px] leading-relaxed text-ink-muted">{description}</p>
        )}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

/** Circular score gauge. The numeral is the primary read; the arc reinforces
 *  it. Pass `invert` for fraud, where a high number is bad. */
export function ScoreRing({
  value,
  size = 72,
  label,
  color,
  strokeWidth = 7,
  invert = false,
}: {
  value: number | null;
  size?: number;
  label?: string;
  color?: string;
  strokeWidth?: number;
  invert?: boolean;
}) {
  const stroke = color ?? (invert ? fraudBand(value).color : scoreBand(value).color);
  const r = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * r;
  const pct = value === null ? 0 : Math.max(0, Math.min(100, value)) / 100;

  return (
    <div className="inline-flex flex-col items-center gap-1.5">
      <div className="relative" style={{ width: size, height: size }}>
        <svg width={size} height={size} className="-rotate-90" aria-hidden>
          <circle
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke="var(--color-track)"
            strokeWidth={strokeWidth}
          />
          <circle
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke={stroke}
            strokeWidth={strokeWidth}
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={circumference * (1 - pct)}
            style={{ transition: "stroke-dashoffset 700ms cubic-bezier(0.16,1,0.3,1)" }}
          />
        </svg>
        <div className="absolute inset-0 grid place-items-center">
          <span
            className="tnum font-semibold leading-none"
            style={{ fontSize: size * 0.27, color: stroke }}
          >
            {value === null ? "—" : Math.round(value)}
          </span>
        </div>
      </div>
      {label && (
        <span className="max-w-[96px] text-center text-[11px] font-semibold leading-tight text-ink-muted">
          {label}
        </span>
      )}
    </div>
  );
}

export function ScoreBar({
  value,
  color,
  height = 4,
}: {
  value: number | null;
  color?: string;
  height?: number;
}) {
  const band = scoreBand(value);
  return (
    <div className="w-full overflow-hidden rounded-full bg-track" style={{ height }}>
      <div
        className="h-full rounded-full"
        style={{
          width: `${value === null ? 0 : Math.max(2, Math.min(100, value))}%`,
          backgroundColor: color ?? band.color,
          transition: "width 600ms cubic-bezier(0.16,1,0.3,1)",
        }}
      />
    </div>
  );
}

const BADGE_TONES: Record<string, string> = {
  neutral: "text-ink-secondary border-line bg-raised",
  good: "text-good border-good-line bg-good-tint",
  warning: "text-warning border-warning-line bg-warning-tint",
  serious: "text-serious border-serious-line bg-serious-tint",
  critical: "text-critical-text border-critical-line bg-critical-tint",
  brand: "text-brand-text border-brand-dim bg-brand-tint",
};

export function Badge({
  children,
  tone = "neutral",
  icon,
}: {
  children: ReactNode;
  tone?: "neutral" | "good" | "warning" | "serious" | "critical" | "brand";
  icon?: ReactNode;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-[11.5px] font-bold ${BADGE_TONES[tone]}`}
    >
      {icon}
      {children}
    </span>
  );
}

export function VerifiedBadge({ verified, compact = false }: { verified: boolean; compact?: boolean }) {
  if (compact) {
    return verified ? (
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-label="Registry-verified" className="shrink-0">
        <circle cx="12" cy="12" r="10" fill="var(--color-good)" />
        <path d="M7.5 12.2l3 3 6-6.4" stroke="#fff" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ) : null;
  }
  return verified ? (
    <Badge tone="good" icon={<CheckIcon />}>
      Registry-verified
    </Badge>
  ) : (
    <Badge tone="warning">Unverified</Badge>
  );
}

export function CheckIcon({ size = 12 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M5 12.5l4.5 4.5L19 7" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** Deterministic initial-letter logo, so the same company always gets the
 *  same tile. Colour is decoration only; the name carries identity. */
const TILE_COLORS = ["#1463ff", "#0b1b36", "#0e7c86", "#5b4bc4", "#1d4ed8", "#0f5c6e"];
export function LogoTile({
  name,
  size = 34,
  src,
}: {
  name: string;
  size?: number;
  /** The company's real logo, when we actually have one. Anything that fails
   *  to load falls back to the initials tile rather than a broken image. */
  src?: string | null;
}) {
  const [failed, setFailed] = useState(false);
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  const radius = Math.round(size * 0.24);

  if (src && !failed) {
    return (
      <img
        src={src}
        alt=""
        aria-hidden
        loading="lazy"
        width={size}
        height={size}
        onError={() => setFailed(true)}
        className="shrink-0 border border-line bg-surface object-contain"
        style={{ width: size, height: size, borderRadius: radius }}
      />
    );
  }
  return (
    <span
      className="logo-tile"
      aria-hidden
      style={{
        width: size,
        height: size,
        borderRadius: radius,
        fontSize: Math.round(size * 0.42),
        backgroundColor: TILE_COLORS[h % TILE_COLORS.length],
      }}
    >
      {name.trim().charAt(0).toUpperCase() || "?"}
    </span>
  );
}

/** KPI tile. `to` makes it a link to the list it summarises. */
export function Stat({
  label,
  value,
  sub,
  accent,
  to,
  delta,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  accent?: string;
  to?: string;
  delta?: { value: number; sentiment: "good" | "bad" | "neutral" };
}) {
  const body = (
    <>
      <div className="eyebrow mb-2 flex items-start gap-1.5">
        <span className="min-w-0 leading-snug">{label}</span>
        {to && (
          <svg
            className="ml-auto shrink-0 text-ink-muted transition-colors group-hover:text-brand-text"
            width="13"
            height="13"
            viewBox="0 0 24 24"
            fill="none"
            aria-hidden
          >
            <path d="M7 17L17 7M17 7H9M17 7v8" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        )}
      </div>
      <div className="flex items-baseline gap-2">
        <span
          className="tnum text-[30px] font-semibold leading-none tracking-tight"
          style={{ color: accent ?? "var(--color-ink)" }}
        >
          {value}
        </span>
        {delta && delta.value !== 0 && (
          <span
            className="tnum text-[12px] font-semibold"
            style={{
              color:
                delta.sentiment === "good"
                  ? "var(--color-good)"
                  : delta.sentiment === "bad"
                    ? "var(--color-serious)"
                    : "var(--color-ink-muted)",
            }}
          >
            {delta.value > 0 ? "↑" : "↓"} {Math.abs(delta.value)}
          </span>
        )}
      </div>
      {sub && <div className="mt-2 text-[12.5px] leading-snug text-ink-muted">{sub}</div>}
    </>
  );

  if (to) {
    return (
      <Link to={to} className="card card-lit interactive group cursor-pointer p-5">
        {body}
      </Link>
    );
  }
  return <Card className="p-5">{body}</Card>;
}

export function Empty({
  title,
  hint,
  tone = "neutral",
  action,
}: {
  title: string;
  hint?: string;
  tone?: "neutral" | "good";
  action?: ReactNode;
}) {
  return (
    <div className="px-6 py-10 text-center">
      <div
        className="mx-auto mb-3 grid h-11 w-11 place-items-center rounded-full"
        style={{
          backgroundColor: tone === "good" ? "var(--color-good-tint)" : "var(--color-raised)",
          color: tone === "good" ? "var(--color-good)" : "var(--color-ink-muted)",
        }}
      >
        {tone === "good" ? (
          <CheckIcon size={18} />
        ) : (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
            <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="2" />
            <path d="M20 20l-3.5-3.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          </svg>
        )}
      </div>
      <div
        className="text-[14.5px] font-bold"
        style={{ color: tone === "good" ? "var(--color-good)" : "var(--color-ink)" }}
      >
        {title}
      </div>
      {hint && <div className="mx-auto mt-1.5 max-w-sm text-[13px] text-ink-muted">{hint}</div>}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  );
}

export function SectionError({ message, onRetry }: { message?: string; onRetry?: () => void }) {
  return (
    <div className="px-6 py-8 text-center">
      <div className="text-[14px] font-bold text-critical">Couldn't load this section</div>
      {message && (
        <div className="mx-auto mt-1.5 max-w-md truncate text-[12.5px] text-ink-muted">{message}</div>
      )}
      {onRetry && (
        <button className="btn mt-3.5 text-[13px]" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function LabeledDivider({ children }: { children: ReactNode }) {
  return (
    <div className="divider-label py-1">
      <span className="eyebrow whitespace-nowrap">{children}</span>
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2.5 py-10 text-ink-muted">
      <svg className="animate-spin" width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
        <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" opacity="0.2" />
        <path d="M22 12a10 10 0 0 1-10 10" stroke="var(--color-brand)" strokeWidth="3" strokeLinecap="round" />
      </svg>
      {label && <span className="text-[13px]">{label}</span>}
    </div>
  );
}

export function SkeletonRows({ n = 5, height = 64 }: { n?: number; height?: number }) {
  return (
    <div className="space-y-2.5">
      {Array.from({ length: n }).map((_, i) => (
        <div key={i} className="skeleton w-full" style={{ height }} />
      ))}
    </div>
  );
}

/** Provenance marker: green = live source, amber = mocked. Never omitted. */
export function ProvenanceDot({ isMock }: { isMock: boolean }) {
  return (
    <span
      title={isMock ? "Mocked source — not independently verified" : "Live verified source"}
      className="inline-block h-2 w-2 shrink-0 rounded-full"
      style={{ backgroundColor: isMock ? "var(--color-mock)" : "var(--color-live)" }}
    />
  );
}
