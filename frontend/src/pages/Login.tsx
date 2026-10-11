import { useEffect, useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { m } from "motion/react";
import { api, type PlatformStats } from "../lib/api";
import { useAuth } from "../lib/auth";
import { compactNum, compactUsd } from "../lib/format";
import { Logo } from "../components/Shell";
import { NumberTicker } from "../components/ui/effects";
import { ThemeToggle } from "../components/ui/ThemeToggle";

/** Sign in or create an account.
 *
 *  Investors get an investor profile on sign-up so the feed has a mandate to
 *  work with; founders get an account that owns the companies they register.
 */
export default function Login() {
  const [params] = useSearchParams();
  const location = useLocation() as { state?: { from?: string } };
  const navigate = useNavigate();
  const { signIn, signUp } = useAuth();

  const [mode, setMode] = useState<"signin" | "signup">(
    params.get("mode") === "signup" ? "signup" : "signin",
  );
  const [role, setRole] = useState<"investor" | "founder">(
    params.get("role") === "founder" ? "founder" : "investor",
  );
  const [f, setF] = useState({ email: "", password: "", name: "", firm_name: "" });
  const [investorType, setInvestorType] = useState("angel");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [google, setGoogle] = useState(false);
  const [stats, setStats] = useState<PlatformStats | null>(null);

  useEffect(() => {
    api.authProviders().then((p) => setGoogle(p.google)).catch(() => {});
    api.stats().then(setStats).catch(() => {});
    // A failed Google round-trip comes back as #error=…
    const hash = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    const failed = hash.get("error");
    if (failed) {
      const detail = hash.get("detail");
      const known: Record<string, string> = {
        access_denied:
          "You cancelled the Google sign-in, or this Google project only allows its listed test users.",
        expired_state: "That sign-in attempt expired. Try again.",
        exchange_failed: "Google refused the sign-in.",
        unverified_email: "Google hasn't verified that email address.",
        account_disabled: "That account is disabled.",
        no_code: "Google didn't return an authorisation code.",
      };
      setError(`${known[failed] ?? "Google sign-in didn't complete."}${detail ? ` (${detail})` : ` [${failed}]`}`);
      window.history.replaceState({}, "", window.location.pathname + window.location.search);
    }
  }, []);

  const next = params.get("next") || location.state?.from || "/dashboard";
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setF((p) => ({ ...p, [k]: e.target.value }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      let user;
      if (mode === "signin") {
        user = await signIn(f.email, f.password);
      } else {
        user = await signUp({
          email: f.email,
          password: f.password,
          name: f.name,
          role,
          investor_type: role === "investor" ? investorType : undefined,
          firm_name: role === "investor" ? f.firm_name || null : null,
        });
      }
      const landing = user.role === "founder" ? (mode === "signup" ? "/register" : "/my-companies") : next;
      navigate(landing, { replace: true });
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  const signingUp = mode === "signup";

  return (
    <div className="relative min-h-screen overflow-x-clip bg-plane text-ink">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-[420px]"
        style={{ background: "radial-gradient(900px 400px at 60% -10%, var(--color-hero-glow) 0%, transparent 70%)" }}
      />

      <header className="relative mx-auto flex h-[72px] max-w-[1240px] items-center gap-4 px-5 sm:px-8">
        <Logo />
        <div className="ml-auto flex items-center gap-3">
          <Link to="/discover" className="hidden text-[13.5px] font-semibold text-ink-secondary hover:text-ink sm:block">
            Browse companies
          </Link>
          <ThemeToggle />
        </div>
      </header>

      <div className="relative mx-auto grid max-w-[1240px] items-stretch gap-6 px-5 pb-16 pt-4 sm:px-8 lg:grid-cols-[minmax(0,470px)_minmax(0,1fr)]">
        {/* ── the form ─────────────────────────────────────────────────── */}
        <m.div
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
          className="card card-lit p-6 sm:p-8"
        >
          <div className="eyebrow mb-2">{signingUp ? "Create your account" : "Welcome back"}</div>
          <h1 className="text-[26px] font-extrabold leading-tight tracking-tight sm:text-[30px]">
            {signingUp ? "Join VentureIQ" : "Sign in"}
          </h1>
          <p className="mt-1.5 text-[14px] leading-relaxed text-ink-secondary">
            {signingUp
              ? "A minute to set up. You can add your mandate straight after."
              : "Your feed, alerts and saved companies are behind this."}
          </p>

          {signingUp && (
            <div className="mt-6 grid grid-cols-2 gap-2.5" role="group" aria-label="Account type">
              {(["investor", "founder"] as const).map((r) => (
                <button
                  key={r}
                  type="button"
                  aria-pressed={role === r}
                  onClick={() => setRole(r)}
                  className={`relative isolate rounded-xl border p-3.5 text-left transition-colors ${
                    role === r ? "border-brand" : "border-line-strong hover:border-ink-disabled"
                  }`}
                >
                  {role === r && (
                    <m.span
                      layoutId="role-pick"
                      className="absolute inset-0 -z-10 rounded-xl bg-brand-tint"
                      transition={{ type: "spring", stiffness: 500, damping: 38 }}
                    />
                  )}
                  <span className={`block text-[14px] font-bold capitalize ${role === r ? "text-brand-text" : ""}`}>
                    {r}
                  </span>
                  <span className="mt-0.5 block text-[12px] leading-snug text-ink-muted">
                    {r === "investor" ? "Find and track companies" : "Register your startup"}
                  </span>
                </button>
              ))}
            </div>
          )}

          {google && (
            <>
              <a className="btn mt-5 h-11 w-full rounded-xl text-[14.5px]" href={api.googleSignInUrl(role, next)}>
                <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden>
                  <path fill="#4285F4" d="M23.5 12.3c0-.8-.1-1.6-.2-2.3H12v4.5h6.5a5.6 5.6 0 0 1-2.4 3.7v3h3.9c2.3-2.1 3.5-5.2 3.5-8.9z" />
                  <path fill="#34A853" d="M12 24c3.2 0 5.9-1.1 7.9-2.9l-3.9-3c-1.1.7-2.4 1.1-4 1.1-3.1 0-5.7-2.1-6.6-4.9H1.4v3.1A12 12 0 0 0 12 24z" />
                  <path fill="#FBBC05" d="M5.4 14.3a7.2 7.2 0 0 1 0-4.6V6.6H1.4a12 12 0 0 0 0 10.8l4-3.1z" />
                  <path fill="#EA4335" d="M12 4.8c1.8 0 3.3.6 4.6 1.8l3.4-3.4A12 12 0 0 0 1.4 6.6l4 3.1C6.3 6.9 8.9 4.8 12 4.8z" />
                </svg>
                Continue with Google
              </a>
              <div className="divider-label my-5 text-[12px]">or use your email</div>
            </>
          )}

          <form onSubmit={submit} className={google ? "space-y-4" : "mt-6 space-y-4"}>
            {signingUp && (
              <div>
                <label htmlFor="name" className="mb-1.5 block text-[13px] font-bold">Your name</label>
                <input id="name" className="field h-11 w-full" required minLength={2} value={f.name} onChange={set("name")} autoComplete="name" />
              </div>
            )}
            <div>
              <label htmlFor="email" className="mb-1.5 block text-[13px] font-bold">Email</label>
              <input id="email" type="email" className="field h-11 w-full" required value={f.email} onChange={set("email")} autoComplete="email" placeholder="you@company.com" />
            </div>
            <div>
              <label htmlFor="password" className="mb-1.5 block text-[13px] font-bold">Password</label>
              <input
                id="password"
                type="password"
                className="field h-11 w-full"
                required
                minLength={signingUp ? 8 : undefined}
                value={f.password}
                onChange={set("password")}
                autoComplete={signingUp ? "new-password" : "current-password"}
                placeholder={signingUp ? "At least 8 characters" : ""}
              />
            </div>

            {signingUp && role === "investor" && (
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <label htmlFor="itype" className="mb-1.5 block text-[13px] font-bold">Investor type</label>
                  <select id="itype" className="field h-11 w-full" value={investorType} onChange={(e) => setInvestorType(e.target.value)}>
                    <option value="angel">Angel</option>
                    <option value="vc_fund">VC fund</option>
                    <option value="family_office">Family office</option>
                  </select>
                </div>
                <div>
                  <label htmlFor="firm" className="mb-1.5 block text-[13px] font-bold">
                    Firm <span className="font-medium text-ink-muted">optional</span>
                  </label>
                  <input id="firm" className="field h-11 w-full" value={f.firm_name} onChange={set("firm_name")} autoComplete="organization" />
                </div>
              </div>
            )}

            {error && (
              <div role="alert" className="rounded-xl border border-critical-line bg-critical-tint px-4 py-3 text-[13px] leading-snug text-critical-text">
                {error}
              </div>
            )}

            <button className="btn btn-primary h-12 w-full rounded-xl text-[15px]" disabled={busy}>
              {busy ? "Working…" : signingUp ? "Create account" : "Sign in"}
            </button>
          </form>

          <p className="mt-5 border-t border-line pt-4 text-[13.5px] text-ink-secondary">
            {signingUp ? "Already have an account? " : "New here? "}
            <button
              className="font-semibold text-brand-text hover:underline"
              onClick={() => {
                setMode(signingUp ? "signin" : "signup");
                setError(null);
              }}
            >
              {signingUp ? "Sign in" : "Create an account"}
            </button>
          </p>
        </m.div>

        {/* ── what the account is for ──────────────────────────────────── */}
        <m.aside
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.08, ease: [0.16, 1, 0.3, 1] }}
          className="panel relative hidden overflow-hidden rounded-[20px] p-7 lg:flex lg:flex-col"
        >
          <div aria-hidden className="dot-grid absolute inset-0 opacity-[0.18]" />
          <div
            aria-hidden
            className="pointer-events-none absolute -right-24 -top-24 h-[380px] w-[380px] rounded-full"
            style={{ background: "radial-gradient(circle, color-mix(in srgb, var(--color-brand) 45%, transparent), transparent 70%)" }}
          />
          <div className="relative flex min-h-0 flex-1 flex-col">
            <div className="text-[13px] font-bold tracking-[0.1em] text-panel-muted">
              {role === "founder" ? "FOR FOUNDERS" : "FOR INVESTORS"}
            </div>
            <h2 className="mt-2 max-w-[440px] text-[26px] font-extrabold leading-tight tracking-tight">
              {role === "founder"
                ? "Register once. We verify the rest against public records."
                : "Deal flow you can check, not just read."}
            </h2>

            <ul className="mt-6 space-y-4 text-[14.5px] leading-relaxed text-panel-muted">
              {(role === "founder"
                ? [
                    ["Four fields to start", "The agent reads your site, domain records, GitHub and the MCA registry."],
                    ["Prove it with a document", "Upload your incorporation certificate; we check it against the registry."],
                    ["See what investors see", "Your four scores, and anything flagged for review."],
                  ]
                : [
                    ["A feed matched to your mandate", "Sectors, stages and cheque size, sharpened by what you open and save."],
                    ["A watchlist that is yours", "Private notes and a pipeline stage on every company."],
                    ["Alerts scoped to you", "Fraud and anomaly flags in the sectors you invest in."],
                  ]
              ).map(([title, body]) => (
                <li key={title} className="flex gap-3">
                  <svg className="mt-0.5 shrink-0 text-panel-accent" width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
                    <path d="M5 12l4.5 4.5L19 7" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  <span>
                    <b className="text-panel-ink">{title}</b>
                    <span className="block">{body}</span>
                  </span>
                </li>
              ))}
            </ul>

            <div className="mt-auto grid grid-cols-3 gap-3 border-t border-panel-line pt-5">
              {[
                { value: stats?.scored, label: "companies scored", format: compactNum },
                { value: stats?.verified, label: "registry-verified", format: compactNum },
                { value: stats?.total_tracked_funding_usd, label: "capital tracked", format: compactUsd },
              ].map((s) => (
                <div key={s.label}>
                  <NumberTicker value={s.value} format={s.format} className="tnum block text-[22px] font-semibold text-panel-ink" />
                  <div className="text-[11.5px] text-panel-muted">{s.label}</div>
                </div>
              ))}
            </div>
            <p className="mt-4 text-[11.5px] leading-relaxed text-panel-muted">
              Browsing companies, scores and the model report stays open to everyone. KYC checks run here;
              the identity decision itself needs a licensed provider, so a person reviews it.
            </p>
          </div>
        </m.aside>
      </div>
    </div>
  );
}
