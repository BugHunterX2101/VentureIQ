import {
  BrowserRouter,
  Navigate,
  Outlet,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import { lazy, Suspense, useEffect } from "react";
import { LazyMotion, m } from "motion/react";
import { Shell } from "./components/Shell";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { ToastProvider } from "./components/ui/Toast";
import { AuthProvider, useAuth } from "./lib/auth";
import { InvestorProvider } from "./lib/investor-context";
import { ThemeProvider } from "./lib/theme";

// Animation features load after first paint.
const motionFeatures = () =>
  import("./components/ui/motion-features").then((r) => r.default);

// Route-level code splitting: the landing page carries the animation library,
// and app screens shouldn't pay for it.
const Landing = lazy(() => import("./pages/Landing"));
const Overview = lazy(() => import("./pages/Overview"));
const Discover = lazy(() => import("./pages/Discover"));
const StartupDetail = lazy(() => import("./pages/StartupDetail"));
const Feed = lazy(() => import("./pages/Feed"));
const Alerts = lazy(() => import("./pages/Alerts"));
const Model = lazy(() => import("./pages/Model"));
const Submit = lazy(() => import("./pages/Submit"));
const Register = lazy(() => import("./pages/Register"));
const Login = lazy(() => import("./pages/Login"));
const AuthCallback = lazy(() => import("./pages/AuthCallback"));
const Saved = lazy(() => import("./pages/Saved"));
const MyCompanies = lazy(() => import("./pages/MyCompanies"));
const Reviews = lazy(() => import("./pages/Reviews"));
const Account = lazy(() => import("./pages/Account"));
const Marketplace = lazy(() => import("./pages/Marketplace"));
const Onboarding = lazy(() => import("./pages/Onboarding"));

function PageFallback() {
  return (
    <div className="space-y-4" aria-busy="true" aria-label="Loading">
      <div className="skeleton h-10 w-72" />
      <div className="skeleton h-[140px]" />
      <div className="skeleton h-[360px]" />
    </div>
  );
}

/** Each route fades up on entry. Enter-only: an exit animation would hold the
 *  next page back, which reads as slowness in a data tool. */
/** Founders have no deal feed of their own; send them to their companies. */
function RoleHome() {
  const { user } = useAuth();
  if (user?.role === "founder") return <Navigate to="/my-companies" replace />;
  return <Overview />;
}

/** Investor-only areas. Public browsing stays open to everyone. */
function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <div className="skeleton h-[60vh]" />;
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(location.pathname)}`} replace />;
  return <>{children}</>;
}

function RouteFade() {
  const { pathname } = useLocation();
  return (
    <m.div
      key={pathname}
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.32, ease: [0.16, 1, 0.3, 1] }}
    >
      <Outlet />
    </m.div>
  );
}

function AppLayout() {
  const { pathname } = useLocation();
  return (
    <Shell>
      {/* Keyed by route so a failed page recovers on the next navigation
          instead of staying broken for the rest of the session. */}
      <ErrorBoundary key={pathname} label={pathname}>
        <Suspense fallback={<PageFallback />}>
          <RouteFade />
        </Suspense>
      </ErrorBoundary>
    </Shell>
  );
}

/** Route changes start at the top of the page, except in-page hash links. */
function ScrollToTop() {
  const { pathname, hash } = useLocation();
  useEffect(() => {
    if (!hash) window.scrollTo(0, 0);
  }, [pathname, hash]);
  return null;
}

export default function App() {
  return (
    <BrowserRouter>
      <ThemeProvider>
        <LazyMotion features={motionFeatures}>
          <ToastProvider>
            <AuthProvider>
              <InvestorProvider>
              <ScrollToTop />
              <Routes>
                <Route
                  path="/"
                  element={
                    <ErrorBoundary label="landing">
                      <Suspense
                        fallback={<div className="min-h-screen bg-plane" />}
                      >
                        <Landing />
                      </Suspense>
                    </ErrorBoundary>
                  }
                />
                <Route element={<AppLayout />}>
                  <Route path="/dashboard" element={<RequireAuth><RoleHome /></RequireAuth>} />
                  <Route path="/discover" element={<Discover />} />
                  <Route path="/startup/:id" element={<StartupDetail />} />
                  <Route path="/feed" element={<RequireAuth><Feed /></RequireAuth>} />
                  <Route path="/alerts" element={<RequireAuth><Alerts /></RequireAuth>} />
                  <Route path="/model" element={<Model />} />
                  <Route path="/register" element={<Register />} />
                  <Route path="/saved" element={<RequireAuth><Saved /></RequireAuth>} />
                  <Route path="/my-companies" element={<RequireAuth><MyCompanies /></RequireAuth>} />
                  <Route path="/reviews" element={<RequireAuth><Reviews /></RequireAuth>} />
                  <Route path="/account" element={<RequireAuth><Account /></RequireAuth>} />
                  <Route path="/marketplace" element={<Marketplace />} />
                  <Route path="/submit" element={<Submit />} />
                  <Route path="/onboarding" element={<RequireAuth><Onboarding /></RequireAuth>} />
                </Route>
                <Route path="/login" element={<Login />} />
                <Route path="/auth/callback" element={<AuthCallback />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
              </InvestorProvider>
            </AuthProvider>
          </ToastProvider>
        </LazyMotion>
      </ThemeProvider>
    </BrowserRouter>
  );
}
