import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AnimatePresence, m } from "motion/react";
import { api, type RegistryCompany } from "../lib/api";
import { Badge } from "./primitives";

/** Companies from India's MCA registry that match a query.
 *
 *  Registry rows are legal facts (name, CIN, status, incorporation), not
 *  VentureIQ profiles: they carry no scores until someone registers them.
 */
export function useRegistrySearch(q: string, limit = 6) {
  const [items, setItems] = useState<RegistryCompany[]>([]);
  const [meta, setMeta] = useState<{ companies: number; complete: boolean } | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) {
      setItems([]);
      return;
    }
    let live = true;
    setLoading(true);
    const t = setTimeout(() => {
      api
        .registrySearch(term, { limit })
        .then((r) => {
          if (!live) return;
          setItems(r.items);
          setMeta(r.registry);
        })
        .catch(() => live && setItems([]))
        .finally(() => live && setLoading(false));
    }, 250);
    return () => {
      live = false;
      clearTimeout(t);
    };
  }, [q, limit]);

  return { items, meta, loading };
}

export function RegistryRow({
  c,
  action,
}: {
  c: RegistryCompany;
  action: React.ReactNode;
}) {
  const active = c.status === "Active";
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 px-4 py-3">
      <div className="min-w-0 flex-1 basis-[240px]">
        <div className="truncate text-[14px] font-bold">{titleName(c.name)}</div>
        <div className="tnum mt-0.5 truncate text-[12px] text-ink-muted">
          {c.cin} · {[c.city, c.state].filter(Boolean).join(", ") || "—"}
          {c.registered ? ` · since ${c.registered.slice(0, 4)}` : ""}
          {c.industry ? ` · ${c.industry}` : ""}
        </div>
      </div>
      <Badge tone={active ? "good" : "warning"}>{c.status ?? "Unknown"}</Badge>
      {action}
    </div>
  );
}

export function titleName(name: string) {
  return name.toLowerCase().replace(/\b([a-z])/g, (x) => x.toUpperCase()).replace(/\b(Llp|Opc|Pvt)\b/g, (x) => x.toUpperCase());
}

/** Discover panel: "not on VentureIQ yet, but registered in India". */
export function RegistryPanel({ q }: { q: string }) {
  const { items, meta } = useRegistrySearch(q, 6);
  return (
    <AnimatePresence>
      {items.length > 0 && (
        <m.section
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0 }}
          className="card overflow-hidden"
          aria-label="Matches in the MCA company registry"
        >
          <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-line px-4 py-3">
            <div>
              <h2 className="text-[15px] font-bold">In India's company registry</h2>
              <p className="text-[12.5px] text-ink-muted">
                Registered with the MCA{meta ? ` · ${meta.companies.toLocaleString("en-IN")} companies searchable` : ""}.
                Not scored until the founder registers.
              </p>
            </div>
          </div>
          <div className="divide-y divide-grid">
            {items.map((c) => (
              <RegistryRow
                key={c.cin}
                c={c}
                action={
                  c.startup_id ? (
                    <Link to={`/startup/${c.startup_id}`} className="btn h-8 px-3 text-[12.5px]">
                      View profile
                    </Link>
                  ) : (
                    <Link
                      to={`/register?cin=${encodeURIComponent(c.cin)}&name=${encodeURIComponent(titleName(c.name))}`}
                      className="btn btn-primary h-8 px-3 text-[12.5px]"
                    >
                      Claim & register
                    </Link>
                  )
                }
              />
            ))}
          </div>
        </m.section>
      )}
    </AnimatePresence>
  );
}
