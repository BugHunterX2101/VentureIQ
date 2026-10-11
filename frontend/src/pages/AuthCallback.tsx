import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { setToken } from "../lib/api";
import { useAuth } from "../lib/auth";

/** Where Google sends the visitor back.
 *
 *  The API puts our session token in the URL fragment, which never reaches a
 *  server. We read it, store it, wipe it from the address bar, then continue.
 */
export default function AuthCallback() {
  const navigate = useNavigate();
  const { refresh } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const ran = useRef(false);

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;
    const params = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    const token = params.get("token");
    const next = params.get("next") || "/dashboard";
    const failed = params.get("error");
    window.history.replaceState({}, "", window.location.pathname);

    if (failed || !token) {
      setError(
        { access_denied: "You cancelled the Google sign-in.",
          expired_state: "That sign-in link expired. Please try again.",
          unverified_email: "Google hasn't verified that email address.",
          account_disabled: "That account is disabled." }[failed ?? ""] ??
          "Sign-in didn't complete. Please try again.",
      );
      return;
    }
    setToken(token);
    void refresh().then(() => navigate(next, { replace: true }));
  }, [navigate, refresh]);

  return (
    <div className="grid min-h-screen place-items-center bg-plane px-5 text-ink">
      {error ? (
        <div className="card card-lit max-w-[420px] p-6 text-center">
          <div className="text-[17px] font-bold">Couldn't sign you in</div>
          <p className="mt-1.5 text-[14px] text-ink-secondary">{error}</p>
          <button className="btn btn-primary mt-4" onClick={() => navigate("/login", { replace: true })}>
            Back to sign in
          </button>
        </div>
      ) : (
        <div className="flex items-center gap-2.5 text-[14px] text-ink-secondary">
          <svg className="animate-spin" width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
            <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" opacity="0.2" />
            <path d="M22 12a10 10 0 0 1-10 10" stroke="var(--color-brand)" strokeWidth="3" strokeLinecap="round" />
          </svg>
          Signing you in…
        </div>
      )}
    </div>
  );
}
