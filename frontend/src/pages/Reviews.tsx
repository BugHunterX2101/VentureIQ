import { useCallback, useEffect, useState } from "react";
import { m } from "motion/react";
import { api, type KycCase } from "../lib/api";
import { relativeTime } from "../lib/format";
import { Badge, Card, Empty, SectionError, SkeletonRows } from "../components/primitives";
import { useToast } from "../components/ui/Toast";

/** The compliance queue.
 *
 *  Automated checks can only get a case as far as `passed_checks`: proving that
 *  a person is who they say they are needs a licensed identity provider, which
 *  this project does not have. A named reviewer makes that call instead, and
 *  every decision is written to the audit log. This page is where they make it.
 */

const CHECK_TONE = {
  passed: "good",
  failed: "critical",
  review: "warning",
} as const;

function CaseCard({ item, onDecide }: { item: KycCase & { submitted_by?: { name: string | null; email: string | null } }; onDecide: (id: string, approve: boolean, note: string) => Promise<void> }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const failed = item.checks.filter((c) => c.status === "failed");

  async function decide(approve: boolean) {
    setBusy(approve ? "approve" : "reject");
    try {
      await onDecide(item.case_id, approve, note.trim());
    } finally {
      setBusy(null);
    }
  }

  return (
    <m.div layout initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
      <Card className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-[16px] font-bold tracking-tight">
                {item.legal_name || item.submitted_by?.name || "Unnamed applicant"}
              </h3>
              <Badge tone={item.status === "failed_checks" ? "critical" : "good"}>
                {item.status === "failed_checks" ? "Checks failed" : "Checks passed"}
              </Badge>
            </div>
            <p className="mt-1 text-[13px] text-ink-secondary">
              {item.submitted_by?.email ?? "—"} · submitted {relativeTime(item.submitted_at)}
              {item.pan && <> · PAN <span className="tnum">{item.pan}</span></>}
              {item.document_type && <> · {item.document_type.replace(/_/g, " ")}</>}
            </p>
          </div>
        </div>

        <ul className="mt-4 space-y-2 border-t border-line pt-4">
          {item.checks.length === 0 && (
            <li className="text-[13px] text-ink-muted">No automated checks were recorded.</li>
          )}
          {item.checks.map((c, i) => (
            <li key={i} className="flex gap-3">
              <span className="mt-0.5 shrink-0">
                <Badge tone={CHECK_TONE[c.status]}>{c.status}</Badge>
              </span>
              <span className="text-[13px] leading-snug text-ink-secondary">
                <span className="font-medium text-ink">{c.check.replace(/_/g, " ")}</span> — {c.detail}
              </span>
            </li>
          ))}
        </ul>

        <div className="mt-4 rounded-xl bg-plane p-3.5">
          <p className="text-[12.5px] leading-relaxed text-ink-secondary">
            {failed.length > 0
              ? `${failed.length} check${failed.length > 1 ? "s" : ""} did not pass. Approving anyway is recorded against your name.`
              : "Every automated check passed. What remains is the identity decision, which is yours to make."}
          </p>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <input
            className="field h-11 min-w-0 flex-1"
            placeholder="Note for the audit log (optional)"
            value={note}
            maxLength={500}
            onChange={(e) => setNote(e.target.value)}
          />
          <button
            className="btn btn-primary h-11"
            disabled={busy !== null}
            onClick={() => decide(true)}
          >
            {busy === "approve" ? "Approving…" : "Approve"}
          </button>
          <button
            className="btn h-11"
            disabled={busy !== null}
            onClick={() => decide(false)}
          >
            {busy === "reject" ? "Rejecting…" : "Reject"}
          </button>
        </div>
      </Card>
    </m.div>
  );
}

export default function Reviews() {
  const toast = useToast();
  const [cases, setCases] = useState<KycCase[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setCases(await api.kycQueue());
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function decide(caseId: string, approve: boolean, note: string) {
    try {
      await api.kycDecide(caseId, approve, note || undefined);
      setCases((prev) => (prev ?? []).filter((c) => c.case_id !== caseId));
      toast({
        title: approve ? "Identity verified" : "Case rejected",
        body: "Recorded in the audit log against your account.",
        tone: approve ? "good" : "warning",
      });
    } catch (e) {
      toast({ title: "Couldn't record that", body: (e as Error).message.slice(0, 200), tone: "warning" });
    }
  }

  return (
    <div className="animate-in space-y-5">
      <div>
        <div className="eyebrow mb-1">Compliance</div>
        <h1 className="text-[28px] font-extrabold leading-tight tracking-tight">KYC review queue</h1>
        <p className="mt-1 max-w-2xl text-[14px] text-ink-secondary">
          Automated checks verify what can be checked — the PAN's structure, the name, a SEBI
          registration, the document itself. Confirming that an applicant is really that person
          needs a licensed identity provider, so the last step is a human one, and it is audited.
        </p>
      </div>

      {error ? (
        <Card>
          <SectionError message={error} onRetry={load} />
        </Card>
      ) : cases === null ? (
        <SkeletonRows n={3} height={220} />
      ) : cases.length === 0 ? (
        <Card>
          <Empty
            tone="good"
            title="Nothing waiting"
            hint="Cases appear here once their automated checks finish."
          />
        </Card>
      ) : (
        <div className="space-y-4">
          {cases.map((c) => (
            <CaseCard key={c.case_id} item={c} onDecide={decide} />
          ))}
        </div>
      )}
    </div>
  );
}
