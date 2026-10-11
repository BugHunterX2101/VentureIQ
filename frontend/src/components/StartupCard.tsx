import { Link } from "react-router-dom";
import type { StartupSummary } from "../lib/api";
import { compactNum, compactUsd, fraudBand, scoreBand, stageLabel } from "../lib/format";
import { Badge, LogoTile, ScoreBar, VerifiedBadge } from "./primitives";

function MiniScore({
  label,
  value,
  invert = false,
  emphasised = true,
}: {
  label: string;
  value: number | null;
  invert?: boolean;
  /** false dims this dimension while another one is being sorted on. */
  emphasised?: boolean;
}) {
  const color = invert ? fraudBand(value).color : scoreBand(value).color;
  return (
    <div className="min-w-0" style={{ opacity: emphasised ? 1 : 0.5 }}>
      <div className="mb-1 flex items-baseline justify-between gap-1">
        <span
          className="truncate text-[11px] font-medium"
          style={{ color: emphasised ? "var(--color-ink-secondary)" : "var(--color-ink-muted)" }}
        >
          {label}
        </span>
        <span className="tnum shrink-0 text-[12px]" style={{ color, fontWeight: emphasised ? 700 : 500 }}>
          {value === null ? "—" : Math.round(value)}
        </span>
      </div>
      <ScoreBar value={value} color={color} height={4} />
    </div>
  );
}

export function StartupCard({
  s,
  onOpen,
  matchScore,
  reasons,
  sortKey,
}: {
  s: StartupSummary;
  onOpen?: () => void;
  matchScore?: number;
  reasons?: string[];
  sortKey?: string;
}) {
  const emph = (k: string) => !sortKey || sortKey === k;
  const band = scoreBand(s.composite_score);
  const fraud = fraudBand(s.fraud_likelihood_score);
  const flagged = (s.fraud_likelihood_score ?? 0) >= 35;

  return (
    <Link
      to={`/startup/${s.startup_id}`}
      onClick={onOpen}
      className="card card-lit interactive group flex h-full min-w-0 flex-col gap-3.5 p-5"
    >
      <div className="flex min-w-0 items-start gap-3">
        <LogoTile name={s.legal_name} src={s.logo_url} size={42} />
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-1.5">
            <h3 className="truncate text-[15.5px] font-bold tracking-tight text-ink transition-colors group-hover:text-brand-text">
              {s.legal_name}
            </h3>
            <VerifiedBadge verified={s.verified} compact />
          </div>
          <p className="mt-0.5 truncate text-[12.5px] text-ink-muted">
            {s.sector} · {stageLabel(s.stage)}
            {s.hq_city ? ` · ${s.hq_city}` : ""}
          </p>
        </div>
        <div className="shrink-0 text-right">
          {matchScore !== undefined ? (
            <>
              <div className="tnum text-[24px] font-semibold leading-none text-brand-text">{Math.round(matchScore)}</div>
              <div className="mt-1 text-[10px] font-bold uppercase tracking-wide text-ink-muted">match</div>
            </>
          ) : (
            <>
              <div className="tnum text-[24px] font-semibold leading-none" style={{ color: band.color }}>
                {s.composite_score === null ? "—" : Math.round(s.composite_score)}
              </div>
              <div className="mt-1 text-[10px] font-bold uppercase tracking-wide text-ink-muted">score</div>
            </>
          )}
        </div>
      </div>

      <p className="line-clamp-2 text-[13.5px] leading-relaxed text-ink-secondary">
        {s.one_liner ?? s.sub_vertical ?? "No description provided."}
      </p>

      {(flagged || s.status === "acquired" || s.status === "public" || s.status === "inactive") && (
        <div className="flex flex-wrap items-center gap-1.5">
          {flagged && (
            <Badge tone={fraud.label === "High risk" ? "critical" : "serious"}>{fraud.label}</Badge>
          )}
          {s.status === "acquired" && <Badge tone="good">Acquired</Badge>}
          {s.status === "public" && <Badge tone="good">Public</Badge>}
          {s.status === "inactive" && <Badge tone="neutral">Inactive</Badge>}
        </div>
      )}

      {reasons && reasons.length > 0 && (
        <ul className="space-y-1 rounded-lg bg-plane px-3 py-2.5">
          {reasons.slice(0, 2).map((r, i) => (
            <li key={i} className="flex gap-2 text-[12.5px] leading-snug text-ink-secondary">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden className="mt-px shrink-0 text-brand-text">
                <path d="M5 12l4.5 4.5L19 7" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              {r}
            </li>
          ))}
        </ul>
      )}

      <div className="mt-auto grid grid-cols-2 gap-x-4 gap-y-2.5 border-t border-line pt-3.5 sm:grid-cols-4 sm:gap-3">
        <MiniScore label="Growth" value={s.growth_potential_score} emphasised={emph("growth")} />
        <MiniScore label="Safety" value={s.risk_level_score} emphasised={emph("risk")} />
        <MiniScore label="Founder" value={s.founder_credibility_score} emphasised={emph("founder")} />
        {/* Fraud is inverted — high is bad — and never dimmed. */}
        <MiniScore label="Fraud ↓" value={s.fraud_likelihood_score} invert />
      </div>

      <div className="flex items-center justify-between text-[12px] text-ink-muted">
        <span>{s.employee_count ? `${compactNum(s.employee_count)} employees` : "Headcount not reported"}</span>
        <span className="tnum font-medium text-ink-secondary">
          {s.total_funding_usd ? `${compactUsd(s.total_funding_usd)} raised` : ""}
        </span>
      </div>
    </Link>
  );
}
