import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { m } from "motion/react";
import { api, type KycCase, type KycStatus } from "../lib/api";
import { relativeTime } from "../lib/format";
import { Badge, Card, SectionError, SkeletonRows } from "../components/primitives";
import { useToast } from "../components/ui/Toast";
import { useAuth } from "../lib/auth";

const STATUS_TONE: Record<string, "good" | "warning" | "serious" | "neutral" | "brand"> = {
  verified: "good",
  passed_checks: "brand",
  submitted: "neutral",
  failed_checks: "serious",
  rejected: "serious",
};

const CHECK_TONE: Record<string, { mark: string; className: string }> = {
  passed: { mark: "✓", className: "text-good-text" },
  failed: { mark: "✕", className: "text-serious" },
  review: { mark: "•", className: "text-warning-text" },
};

/** Your account, and the KYC case that gates the marketplace. */
export default function Account() {
  const { user, refresh } = useAuth();
  const toast = useToast();
  const fileRef = useRef<HTMLInputElement>(null);

  const [kyc, setKyc] = useState<KycStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pan, setPan] = useState("");
  const [legalName, setLegalName] = useState("");
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");
  const [passwords, setPasswords] = useState({ current_password: "", new_password: "" });

  const load = useCallback(async () => {
    try {
      setKyc(await api.kycStatus());
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    if (user) {
      setName(user.name);
      setLegalName((v) => v || user.name);
    }
  }, [user]);

  async function submitKyc(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const c: KycCase = await api.kycSubmit(pan.trim().toUpperCase(), legalName, fileRef.current?.files?.[0]);
      toast({
        title: c.status === "failed_checks" ? "Some checks didn't pass" : "KYC submitted",
        body: c.what_this_means,
        tone: c.status === "failed_checks" ? "warning" : "good",
      });
      await load();
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function saveProfile(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.updateMe({
        name,
        ...(passwords.new_password ? passwords : {}),
      });
      setPasswords({ current_password: "", new_password: "" });
      await refresh();
      toast({ title: "Account updated", tone: "good" });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const c = kyc?.case ?? null;

  return (
    <div className="animate-in space-y-5">
      <div>
        <div className="eyebrow mb-1">Account</div>
        <h1 className="text-[28px] font-extrabold leading-tight tracking-tight">{user?.name}</h1>
        <p className="mt-1 text-[14px] text-ink-secondary">
          {user?.email} · <span className="capitalize">{user?.role}</span>
        </p>
      </div>

      {error && (
        <Card className="p-5"><SectionError message={error} onRetry={() => void load()} /></Card>
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        {/* ── KYC ─────────────────────────────────────────────────────── */}
        <Card className="p-5">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <h2 className="text-[17px] font-bold">Identity (KYC)</h2>
              <p className="mt-0.5 text-[12.5px] text-ink-muted">Required before any marketplace activity.</p>
            </div>
            {c && <Badge tone={STATUS_TONE[c.status] ?? "neutral"}>{c.status.replace(/_/g, " ")}</Badge>}
          </div>

          {kyc === null ? (
            <div className="mt-4"><SkeletonRows n={2} height={40} /></div>
          ) : c ? (
            <div className="mt-4 space-y-3">
              <p className="text-[13.5px] leading-relaxed text-ink-secondary">{c.what_this_means}</p>
              <ul className="space-y-2">
                {c.checks.map((check, i) => {
                  const tone = CHECK_TONE[check.status] ?? CHECK_TONE.review;
                  return (
                    <li key={i} className="flex items-start gap-2 text-[12.5px]">
                      <span className={`mt-0.5 font-bold ${tone.className}`}>{tone.mark}</span>
                      <span>
                        <span className="font-semibold">{check.check.replace(/_/g, " ")}</span>
                        <span className="block text-ink-muted">{check.detail}</span>
                      </span>
                    </li>
                  );
                })}
              </ul>
              <div className="flex flex-wrap items-center gap-2 border-t border-line pt-3 text-[12px] text-ink-muted">
                <span>Submitted {relativeTime(c.submitted_at)}</span>
                {c.reviewer_note && <span>· Reviewer: {c.reviewer_note}</span>}
              </div>
              {c.status !== "verified" && (
                <button className="btn h-9" onClick={() => setKyc({ ...kyc, case: null })}>
                  Submit again
                </button>
              )}
            </div>
          ) : (
            <form onSubmit={submitKyc} className="mt-4 space-y-3.5">
              <div>
                <label htmlFor="pan" className="mb-1.5 block text-[13px] font-bold">PAN</label>
                <input id="pan" required className="field tnum h-11 w-full uppercase" value={pan}
                       onChange={(e) => setPan(e.target.value)} placeholder="ABCDE1234F" maxLength={10} />
              </div>
              <div>
                <label htmlFor="legal" className="mb-1.5 block text-[13px] font-bold">Name as printed</label>
                <input id="legal" required className="field h-11 w-full" value={legalName}
                       onChange={(e) => setLegalName(e.target.value)} />
              </div>
              <div>
                <label htmlFor="doc" className="mb-1.5 block text-[13px] font-bold">
                  ID document <span className="font-medium text-ink-muted">optional, PDF or image</span>
                </label>
                <input id="doc" ref={fileRef} type="file" accept=".pdf,.png,.jpg,.jpeg"
                       className="field h-11 w-full py-2 text-[13px]" />
                <p className="mt-1 text-[12px] text-ink-muted">
                  We read it and compare the PAN and name with this account.
                </p>
              </div>
              <button className="btn btn-primary h-11" disabled={busy}>
                {busy ? "Checking…" : "Submit for review"}
              </button>
            </form>
          )}

          <p className="mt-4 border-t border-line pt-3 text-[11.5px] leading-relaxed text-ink-muted">
            {kyc?.note ??
              "Identity verification is not performed here: a licensed provider would do it."}
          </p>
        </Card>

        {/* ── profile ─────────────────────────────────────────────────── */}
        <div className="space-y-5">
          <Card className="p-5">
            <h2 className="text-[17px] font-bold">Profile</h2>
            <form onSubmit={saveProfile} className="mt-4 space-y-3.5">
              <div>
                <label htmlFor="nm" className="mb-1.5 block text-[13px] font-bold">Name</label>
                <input id="nm" className="field h-11 w-full" value={name} onChange={(e) => setName(e.target.value)} minLength={2} />
              </div>
              <div className="grid gap-3.5 sm:grid-cols-2">
                <div>
                  <label htmlFor="cur" className="mb-1.5 block text-[13px] font-bold">Current password</label>
                  <input id="cur" type="password" className="field h-11 w-full" value={passwords.current_password}
                         onChange={(e) => setPasswords((p) => ({ ...p, current_password: e.target.value }))}
                         autoComplete="current-password" />
                </div>
                <div>
                  <label htmlFor="new" className="mb-1.5 block text-[13px] font-bold">New password</label>
                  <input id="new" type="password" className="field h-11 w-full" value={passwords.new_password}
                         onChange={(e) => setPasswords((p) => ({ ...p, new_password: e.target.value }))}
                         minLength={8} autoComplete="new-password" />
                </div>
              </div>
              <button className="btn btn-primary h-11" disabled={busy}>Save changes</button>
            </form>
          </Card>

          {user?.role === "investor" && (
            <Card className="p-5">
              <h2 className="text-[17px] font-bold">Mandate</h2>
              <p className="mt-0.5 text-[13px] text-ink-secondary">
                {user.has_mandate
                  ? "Your feed is ranked against this."
                  : "Set this and your feed stops guessing."}
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Link to="/onboarding" className="btn btn-primary h-9">
                  {user.has_mandate ? "Edit mandate" : "Set your mandate"}
                </Link>
                <Link to="/saved" className="btn h-9">
                  Saved companies <span className="tnum ml-1.5 text-ink-muted">{user.watchlist_count}</span>
                </Link>
              </div>
            </Card>
          )}

          <m.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            <Card className="p-5">
              <h2 className="text-[17px] font-bold">Marketplace access</h2>
              <p className="mt-1 text-[13px] leading-relaxed text-ink-secondary">
                {kyc?.marketplace_unlocked
                  ? "Your KYC is verified, so you can make offers within the platform's rules."
                  : "Offers stay locked until a reviewer verifies your KYC case."}
              </p>
              <Link to="/marketplace" className="btn mt-3 h-9">Open the marketplace</Link>
            </Card>
          </m.div>
        </div>
      </div>
    </div>
  );
}
