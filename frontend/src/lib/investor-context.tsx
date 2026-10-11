import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api, type Investor } from "./api";
import { useAuth } from "./auth";

interface Ctx {
  investors: Investor[];
  current: Investor | null;
  setCurrentId: (id: string) => void;
  refresh: () => Promise<void>;
  /** Fire a behavioural event for the active investor. No-ops if none. */
  track: (
    eventType: string,
    startupId?: string,
    value?: Record<string, unknown>,
  ) => void;
}

const InvestorContext = createContext<Ctx>({
  investors: [],
  current: null,
  setCurrentId: () => {},
  refresh: async () => {},
  track: () => {},
});

const STORAGE_KEY = "viq.investor";

export function InvestorProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const [investors, setInvestors] = useState<Investor[]>([]);
  const [currentId, setCurrentIdState] = useState<string | null>(null);

  // The active investor is the one this account owns — no switching between
  // other people's profiles.
  const refresh = useCallback(async () => {
    if (!user?.investor_id) {
      setInvestors([]);
      setCurrentIdState(null);
      return;
    }
    try {
      const mine = await api.investor(user.investor_id);
      setInvestors([mine]);
      setCurrentIdState(mine.investor_id);
      localStorage.setItem(STORAGE_KEY, mine.investor_id);
    } catch {
      setInvestors([]);
      setCurrentIdState(null);
    }
  }, [user?.investor_id]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const setCurrentId = useCallback((id: string) => {
    setCurrentIdState(id);
    localStorage.setItem(STORAGE_KEY, id);
  }, []);

  const current = useMemo(
    () => investors.find((i) => i.investor_id === currentId) ?? investors[0] ?? null,
    [investors, currentId],
  );

  const track = useCallback(
    (eventType: string, startupId?: string, value?: Record<string, unknown>) => {
      if (!current) return;
      void api.track({
        investor_id: current.investor_id,
        startup_id: startupId,
        event_type: eventType,
        event_value: value,
      });
    },
    [current],
  );

  return (
    <InvestorContext.Provider value={{ investors, current, setCurrentId, refresh, track }}>
      {children}
    </InvestorContext.Provider>
  );
}

export function useInvestor() {
  return useContext(InvestorContext);
}
