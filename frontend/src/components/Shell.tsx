import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { m } from "motion/react";
import { useAuth } from "../lib/auth";
import { useInvestor } from "../lib/investor-context";
import { ThemeToggle } from "./ui/ThemeToggle";

type NavEntry = { to: string; label: string; icon: ReactNode; end?: boolean };

const Icon = {
  home: (
    <path d="M3 11l9-7 9 7v9a1 1 0 01-1 1h-5v-6H9v6H4a1 1 0 01-1-1v-9z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
  ),
  search: (
    <>
      <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="2" />
      <path d="M20 20l-3.5-3.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </>
  ),
  feed: <path d="M4 6h16M4 12h16M4 18h10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />,
  alert: (
    <>
      <path d="M12 4l9 16H3l9-16z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
      <path d="M12 10v4M12 17h.01" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </>
  ),
  model: <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />,
  bookmark: <path d="M6 4h12v16l-6-4-6 4V4z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />,
  market: (
    <>
      <path d="M4 9h16l-1.2 10a2 2 0 01-2 1.8H7.2a2 2 0 01-2-1.8L4 9z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
      <path d="M9 9V6a3 3 0 016 0v3" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </>
  ),
  plus: <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />,
  user: (
    <>
      <circle cx="12" cy="8" r="4" stroke="currentColor" strokeWidth="2" />
      <path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </>
  ),
  shield: (
    <>
      <path d="M12 3l8 3v6c0 4.4-3.1 7.9-8 9-4.9-1.1-8-4.6-8-9V6l8-3z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
      <path d="M9 12l2 2 4-4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </>
  ),
};

const svg = (d: ReactNode) => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden className="shrink-0">
    {d}
  </svg>
);

const NAV: NavEntry[] = [
  { to: "/dashboard", label: "Home", icon: svg(Icon.home), end: true },
  { to: "/discover", label: "Discover", icon: svg(Icon.search) },
  { to: "/feed", label: "My feed", icon: svg(Icon.feed) },
  { to: "/saved", label: "Saved", icon: svg(Icon.bookmark) },
  { to: "/alerts", label: "Alerts", icon: svg(Icon.alert) },
  { to: "/marketplace", label: "Marketplace", icon: svg(Icon.market) },
  { to: "/model", label: "Model", icon: svg(Icon.model) },
];

const NAV_SECONDARY: NavEntry[] = [
  { to: "/register", label: "Register a startup", icon: svg(Icon.plus) },
  { to: "/onboarding", label: "Investor profile", icon: svg(Icon.user) },
];

export function Logo({ size = 28, to = "/" }: { size?: number; to?: string }) {
  return (
    <Link to={to} className="flex shrink-0 items-center gap-2.5 text-ink" aria-label="VentureIQ home">
      <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden>
        <rect width="32" height="32" rx="8" fill="var(--color-brand)" />
        <path d="M9 11l7 11 7-11" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="16" cy="8.6" r="1.8" fill="#fff" />
      </svg>
      <span className="text-[18px] font-extrabold tracking-tight">VentureIQ</span>
    </Link>
  );
}

// Only a compliance reviewer sees the KYC queue; the API enforces it too.
const REVIEW_ENTRY: NavEntry = { to: "/reviews", label: "KYC queue", icon: svg(Icon.shield) };

function useNav(): NavEntry[] {
  const { user } = useAuth();
  const base =
    user?.role === "founder"
      ? // Founders live in their own companies, not an investor deal feed.
        [
          { to: "/my-companies", label: "My companies", icon: svg(Icon.bookmark), end: true },
          NAV[1],
          NAV[5],
          NAV[6],
        ]
      : NAV;
  return user?.is_reviewer ? [...base, REVIEW_ENTRY] : base;
}

function NavList({
  items,
  onNavigate,
  group,
}: {
  items: NavEntry[];
  onNavigate?: () => void;
  group: string;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      {items.map((n) => (
        <NavLink key={n.to} to={n.to} end={n.end} onClick={onNavigate} className="nav-item group">
          {({ isActive }) => (
            <>
              {/* The highlight slides between items instead of blinking. */}
              {isActive ? (
                <m.span
                  layoutId={`nav-active-${group}`}
                  className="absolute inset-0 -z-10 rounded-[10px] bg-brand-tint"
                  transition={{ type: "spring", stiffness: 500, damping: 38 }}
                />
              ) : (
                <span className="absolute inset-0 -z-10 rounded-[10px] bg-raised opacity-0 transition-opacity group-hover:opacity-100" />
              )}
              {n.icon}
              {n.label}
            </>
          )}
        </NavLink>
      ))}
    </div>
  );
}

function MandateCard() {
  const { current } = useInvestor();
  const pref = current?.preference;
  if (!pref) return null;
  return (
    <div className="rounded-xl border border-line bg-plane p-3.5">
      <div className="eyebrow mb-2">Your mandate</div>
      <div className="flex flex-wrap gap-1.5">
        {pref.preferred_sectors.slice(0, 4).map((s) => (
          <span key={s} className="rounded-full border border-line bg-surface px-2 py-0.5 text-[11.5px] font-semibold text-ink-secondary">
            {s}
          </span>
        ))}
      </div>
    </div>
  );
}

function Sidebar() {
  const nav = useNav();
  return (
    <aside className="fixed inset-y-0 left-0 z-40 hidden w-[240px] flex-col gap-5 border-r border-line bg-surface px-3.5 py-4 lg:flex">
      <div className="px-2 pb-1">
        <Logo />
      </div>
      <nav aria-label="Primary" className="isolate">
        <NavList items={nav} group="side" />
      </nav>
      <div className="px-3 pt-1">
        <div className="eyebrow">Workspace</div>
      </div>
      <nav aria-label="Secondary" className="isolate -mt-3">
        <NavList items={NAV_SECONDARY} group="side" />
      </nav>
      <div className="mt-auto">
        <MandateCard />
      </div>
    </aside>
  );
}

/** Global search. ⌘K / Ctrl+K focuses it; Enter opens Discover with the query. */
function GlobalSearch() {
  const navigate = useNavigate();
  const ref = useRef<HTMLInputElement>(null);
  const [q, setQ] = useState("");

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        ref.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <form
      role="search"
      className="relative w-full max-w-[640px]"
      onSubmit={(e) => {
        e.preventDefault();
        navigate(q.trim() ? `/discover?q=${encodeURIComponent(q.trim())}` : "/discover");
      }}
    >
      <svg
        className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-ink-muted"
        width="17"
        height="17"
        viewBox="0 0 24 24"
        fill="none"
        aria-hidden
      >
        {Icon.search}
      </svg>
      <input
        ref={ref}
        value={q}
        onChange={(e) => setQ(e.target.value)}
        aria-label="Search companies"
        placeholder="Search companies, sectors and descriptions"
        className="field h-11 bg-plane pl-10 pr-14"
      />
      <kbd className="tnum pointer-events-none absolute right-3 top-1/2 hidden -translate-y-1/2 rounded-md border border-line-strong bg-surface px-1.5 py-0.5 text-[11px] text-ink-muted sm:block">
        ⌘K
      </kbd>
    </form>
  );
}

function AccountMenu() {
  const { user, signOut } = useAuth();
  const { current } = useInvestor();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);

  if (!user) {
    return (
      <div className="flex items-center gap-2">
        <Link to="/login" className="hidden text-[13.5px] font-semibold text-ink-secondary hover:text-ink sm:block">
          Sign in
        </Link>
        <Link to="/login?mode=signup" className="btn btn-primary text-[13px]">
          Create account
        </Link>
      </div>
    );
  }

  const initials = user.name.split(" ").map((p) => p[0]).slice(0, 2).join("").toUpperCase();

  return (
    <div className="relative">
      <button
        className="flex items-center gap-2 rounded-full border border-line-strong bg-surface py-1 pl-1 pr-2.5 transition-colors hover:border-ink-disabled"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="grid h-8 w-8 place-items-center rounded-full bg-panel text-[12px] font-bold text-panel-ink">
          {initials}
        </span>
        <span className="hidden max-w-[130px] truncate text-[13px] font-semibold sm:block">{user.name}</span>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden className="text-ink-muted">
          <path d="M6 9l6 6 6-6" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
        </svg>
      </button>
      {open && (
        <>
          <button className="fixed inset-0 z-40 cursor-default" aria-label="Close menu" onClick={() => setOpen(false)} />
          <div role="menu" className="overlay-panel absolute right-0 z-50 mt-2 w-[248px] rounded-xl p-1.5">
            <div className="border-b border-line px-3 py-2.5">
              <div className="truncate text-[13.5px] font-bold">{user.name}</div>
              <div className="truncate text-[12px] text-ink-muted">{user.email}</div>
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                <span className="chip capitalize">{user.role}</span>
                {current?.firm_name && <span className="chip">{current.firm_name}</span>}
                {user.role === "investor" && !user.has_mandate && <span className="chip chip-brand">Set your mandate</span>}
              </div>
            </div>
            {user.role === "investor" && (
              <>
                <MenuLink to="/saved" onClick={() => setOpen(false)}>
                  Saved companies <span className="tnum ml-auto text-ink-muted">{user.watchlist_count}</span>
                </MenuLink>
                <MenuLink to="/onboarding" onClick={() => setOpen(false)}>
                  {user.has_mandate ? "Edit mandate" : "Set your mandate"}
                </MenuLink>
              </>
            )}
            {user.role === "founder" && (
              <>
                <MenuLink to="/my-companies" onClick={() => setOpen(false)}>My companies</MenuLink>
                <MenuLink to="/register" onClick={() => setOpen(false)}>Register a company</MenuLink>
              </>
            )}
            {user.is_reviewer && (
              <MenuLink to="/reviews" onClick={() => setOpen(false)}>KYC review queue</MenuLink>
            )}
            <MenuLink to="/account" onClick={() => setOpen(false)}>Account &amp; KYC</MenuLink>
            <button
              role="menuitem"
              className="flex w-full items-center rounded-lg px-3 py-2 text-left text-[13.5px] font-medium text-ink-secondary transition-colors hover:bg-raised hover:text-ink"
              onClick={() => {
                signOut();
                setOpen(false);
                navigate("/");
              }}
            >
              Sign out
            </button>
          </div>
        </>
      )}
    </div>
  );
}

function MenuLink({ to, children, onClick }: { to: string; children: ReactNode; onClick: () => void }) {
  return (
    <Link
      role="menuitem"
      to={to}
      onClick={onClick}
      className="flex items-center rounded-lg px-3 py-2 text-[13.5px] font-medium text-ink-secondary transition-colors hover:bg-raised hover:text-ink"
    >
      {children}
    </Link>
  );
}

function MobileDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const nav = useNav();
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[60] lg:hidden">
      <div className="absolute inset-0 bg-scrim" onClick={onClose} />
      <m.div
        initial={{ x: -300 }}
        animate={{ x: 0 }}
        transition={{ type: "spring", stiffness: 380, damping: 36 }}
        className="absolute inset-y-0 left-0 flex w-[280px] max-w-[85vw] flex-col gap-5 bg-surface px-3.5 py-4 shadow-[var(--shadow-pop)]"
      >
        <div className="flex items-center justify-between px-2">
          <Logo />
          <button className="btn h-10 w-10 p-0" aria-label="Close navigation" onClick={onClose}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
              <path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </button>
        </div>
        <nav aria-label="Primary" className="isolate">
          <NavList items={nav} onNavigate={onClose} group="drawer" />
        </nav>
        <nav aria-label="Secondary" className="isolate border-t border-line pt-4">
          <NavList items={NAV_SECONDARY} onNavigate={onClose} group="drawer" />
        </nav>
        <div className="mt-auto">
          <MandateCard />
        </div>
      </m.div>
    </div>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const [drawer, setDrawer] = useState(false);
  const location = useLocation();

  useEffect(() => setDrawer(false), [location.pathname]);

  return (
    <div className="min-h-screen bg-plane">
      <Sidebar />
      <MobileDrawer open={drawer} onClose={() => setDrawer(false)} />

      <div className="lg:pl-[240px]">
        <header className="sticky top-0 z-30 h-16 border-b border-line bg-header backdrop-blur-md">
          <div className="flex h-16 items-center gap-3 px-4 sm:px-6">
            <button
              className="btn h-10 w-10 shrink-0 p-0 lg:hidden"
              aria-label="Open navigation"
              aria-expanded={drawer}
              onClick={() => setDrawer(true)}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
                <path d="M4 7h16M4 12h16M4 17h16" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              </svg>
            </button>
            <GlobalSearch />
            <div className="ml-auto flex shrink-0 items-center gap-2">
              <ThemeToggle />
              <AccountMenu />
            </div>
          </div>
        </header>

        <main className="mx-auto max-w-[1400px] px-4 py-6 sm:px-6 lg:py-7">{children}</main>

        <footer className="border-t border-line">
          <div className="mx-auto flex max-w-[1400px] flex-wrap items-center justify-between gap-3 px-4 py-5 text-[12.5px] text-ink-muted sm:px-6">
            <span>VentureIQ — B.E. dissertation prototype, BMS College of Engineering</span>
            <span>Marketplace flows are simulated · Some enrichment sources are mocked</span>
          </div>
        </footer>
      </div>
    </div>
  );
}
