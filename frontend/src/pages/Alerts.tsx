import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Alert } from "../lib/api";
import { relativeTime, SEVERITY_COLOR, titleCase } from "../lib/format";
import { Badge, Card, Empty, SectionError, SkeletonRows } from "../components/primitives";

export default function Alerts() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [severity, setSeverity] = useState<string>("");

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    api
      .alerts(60)
      .then(setAlerts)
      .catch((e) => setError(String(e?.message ?? e)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => load(), [load]);

  const shown = severity ? alerts.filter((a) => a.severity === severity) : alerts;
  const counts = {
    high: alerts.filter((a) => a.severity === "high").length,
    medium: alerts.filter((a) => a.severity === "medium").length,
  };

  return (
    <div className="space-y-5 animate-in">
      <div>
        <h1 className="text-[28px] font-extrabold tracking-tight leading-tight">
          Fraud &amp; risk alerts
        </h1>
        <p className="text-[13.5px] text-ink-muted mt-1.5 max-w-2xl leading-relaxed">
          Raised by deterministic cross-source rules and by unsupervised anomaly detection.
          The system never auto-rejects a startup — every alert is a request for human review.
        </p>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        {[
          { v: "", l: `All (${alerts.length})` },
          { v: "high", l: `High (${counts.high})` },
          { v: "medium", l: `Medium (${counts.medium})` },
        ].map((f) => (
          <button
            key={f.v}
            onClick={() => setSeverity(f.v)}
            aria-pressed={severity === f.v}
            className={`btn text-[12.5px] ${
              severity === f.v ? "bg-brand-tint! border-brand! text-brand-text!" : ""
            }`}
          >
            {f.l}
          </button>
        ))}
      </div>

      {error ? (
        <Card>
          <SectionError message={error} onRetry={load} />
        </Card>
      ) : loading ? (
        <SkeletonRows n={6} height={84} />
      ) : shown.length === 0 ? (
        <Card>
          <Empty
            tone="good"
            title={
              severity
                ? `No ${severity}-severity alerts`
                : "No companies currently flagged for review"
            }
            hint="Every cross-source consistency check passed for the companies in view."
          />
        </Card>
      ) : (
        <div className="space-y-2.5">
          {shown.map((a) => (
            <Card key={a.signal_id} className="p-4">
              <div className="flex items-start gap-3.5">
                <span
                  className="mt-1.5 w-2 h-2 rounded-full shrink-0"
                  style={{ backgroundColor: SEVERITY_COLOR[a.severity] }}
                />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <Link
                      to={`/startup/${a.startup_id}`}
                      className="text-[14px] font-medium text-ink hover:text-brand-text transition-colors"
                    >
                      {a.startup_name}
                    </Link>
                    <Badge tone={a.severity === "high" ? "critical" : a.severity === "medium" ? "serious" : "warning"}>
                      {a.severity}
                    </Badge>
                    <span className="chip">{a.sector}</span>
                    <span className="chip">{titleCase(a.detector)}</span>
                  </div>
                  <p className="text-[12.5px] text-ink-secondary mt-2 leading-relaxed">
                    {a.explanation}
                  </p>
                  {a.flagged_fields?.length ? (
                    <div className="flex gap-1.5 mt-2 flex-wrap">
                      {a.flagged_fields.map((f) => (
                        <span key={f} className="chip text-[10.5px]">
                          {f}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>
                <div className="text-right shrink-0">
                  <div className="tnum text-[13px] text-ink-secondary">
                    {a.anomaly_score.toFixed(2)}
                  </div>
                  <div className="text-[10.5px] text-ink-muted mt-0.5">
                    {relativeTime(a.run_at)}
                  </div>
                  <div className="mt-2">
                    <Badge tone={a.reviewed_by_human ? "good" : "neutral"}>
                      {a.reviewed_by_human ? "Reviewed" : "Pending review"}
                    </Badge>
                  </div>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
