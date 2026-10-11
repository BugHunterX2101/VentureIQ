import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api, getToken, setToken, type AuthUser } from "./api";

/** Who is signed in, if anyone.
 *
 *  The token lives in localStorage and is attached to every API call by
 *  `api.ts`. The user object is always re-fetched from /auth/me on load, so a
 *  tampered or expired token resolves to signed-out rather than a fake session.
 */
interface Ctx {
  user: AuthUser | null;
  loading: boolean;
  signIn: (email: string, password: string) => Promise<AuthUser>;
  signUp: (body: {
    email: string;
    password: string;
    name: string;
    role: "investor" | "founder";
    investor_type?: string;
    firm_name?: string | null;
  }) => Promise<AuthUser>;
  signOut: () => void;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<Ctx>({
  user: null,
  loading: true,
  signIn: async () => {
    throw new Error("no provider");
  },
  signUp: async () => {
    throw new Error("no provider");
  },
  signOut: () => {},
  refresh: async () => {},
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      setUser(await api.me());
    } catch {
      setToken(null);
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const signIn = useCallback(async (email: string, password: string) => {
    const r = await api.login(email, password);
    setToken(r.access_token);
    setUser(r.user);
    return r.user;
  }, []);

  const signUp = useCallback<Ctx["signUp"]>(async (body) => {
    const r = await api.register(body);
    setToken(r.access_token);
    setUser(r.user);
    return r.user;
  }, []);

  const signOut = useCallback(() => {
    setToken(null);
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ user, loading, signIn, signUp, signOut, refresh }),
    [user, loading, signIn, signUp, signOut, refresh],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return useContext(AuthContext);
}
