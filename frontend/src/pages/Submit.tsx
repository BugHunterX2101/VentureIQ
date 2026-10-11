import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type Stage } from "../lib/api";
import { STAGE_LABEL } from "../lib/format";
import { Badge, Card, SectionHeader } from "../components/primitives";

const SECTORS = [
  "FinTech", "Enterprise Software", "AI / ML", "HealthTech", "E-Commerce",
  "Consumer Internet", "EdTech", "Logistics & Mobility", "AgriTech",
  "ClimateTech", "PropTech", "Gaming & Media", "Food & Beverage", "Industrials",
];

const STAGES: Stage[] = ["idea", "seed", "series_a", "series_b_plus", "growth"];

/** Stage-aware registration.
 *
 *  The financial block is hidden entirely at idea stage and required from seed
 *  onward. This mirrors the server's Pydantic rules exactly — asking a
 *  pre-revenue founder for burn-rate payback is pointless, and accepting a
 *  seed-stage submission with no burn rate leaves the risk model blind.
 */
export default function Submit() {
  const navigate = useNavigate();
  const [stage, setStage] = useState<Stage>("seed");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [form, setForm] = useState<Record<string, string>>({
    legal_name: "",
    sector: "FinTech",
    sub_vertical: "",
    hq_city: "",
    hq_state: "",
    website: "",
    founded_date: "",
    employee_count: "",
    one_liner: "",
    long_description: "",
    cin: "",
    gstin: "",
  });

  const [fin, setFin] = useState<Record<string, string>>({
    revenue: "",
    prior_year_revenue: "",
    burn_rate_monthly: "",
    cash_balance: "",
    cac: "",
    ltv: "",
    tam_usd: "",
    sam_usd: "",
    active_users: "",
    total_funding_usd: "",
  });

  const [founders, setFounders] = useState([
    { name: "", role: "Co-Founder & CEO", linkedin_url: "", github_username: "" },
  ]);

  const needsFinancials = stage !== "idea";
  const set = (k: string, v: string) => setForm((f) => ({ ...f, [k]: v }));
  const setF = (k: string, v: string) => setFin((f) => ({ ...f, [k]: v }));

  const num = (v: string) => (v.trim() === "" ? null : Number(v));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);

    const payload: any = {
      legal_name: form.legal_name,
      stage,
      sector: form.sector,
      sub_vertical: form.sub_vertical || null,
      hq_city: form.hq_city || null,
      hq_state: form.hq_state || null,
      website: form.website || null,
      founded_date: form.founded_date || null,
      employee_count: num(form.employee_count),
      one_liner: form.one_liner || null,
      long_description: form.long_description || null,
      cin: form.cin || null,
      gstin: form.gstin || null,
      founders: founders
        .filter((f) => f.name.trim())
        .map((f) => ({
          name: f.name,
          role: f.role || null,
          linkedin_url: f.linkedin_url || null,
          github_username: f.github_username || null,
        })),
    };

    if (needsFinancials) {
      payload.financials = Object.fromEntries(
        Object.entries(fin).map(([k, v]) => [k, num(v)]),
      );
    }

    try {
      const created = await api.createStartup(payload);
      navigate(`/startup/${created.startup_id}`);
    } catch (err) {
      setError(String(err instanceof Error ? err.message : err));
      setSubmitting(false);
    }
  }

  return (
    <div className="max-w-3xl mx-auto space-y-5 animate-in">
      <div>
        <h1 className="text-[28px] font-extrabold tracking-tight leading-tight">
          Register a startup
        </h1>
        <p className="text-[13.5px] text-ink-muted mt-1.5 leading-relaxed">
          The form adapts to your stage — you'll only be asked for metrics that exist at your
          stage. Everything you submit is re-validated server-side and then cross-checked
          against external registries before it is scored.
        </p>
      </div>

      <form onSubmit={submit} className="space-y-4">
        <Card className="p-5">
          <SectionHeader eyebrow="Step 1" title="Stage" description="This determines which fields you'll be asked for." />
          <div className="flex flex-wrap gap-2">
            {STAGES.map((st) => (
              <button
                key={st}
                type="button"
                onClick={() => setStage(st)}
                className={`btn ${stage === st ? "btn-primary" : ""}`}
              >
                {STAGE_LABEL[st]}
              </button>
            ))}
          </div>
          {stage === "idea" && (
            <p className="text-[12px] text-ink-muted mt-3">
              Idea stage: financial metrics are skipped entirely. Your score will lean on
              founder credibility and market signals.
            </p>
          )}
        </Card>

        <Card className="p-5">
          <SectionHeader eyebrow="Step 2" title="Company" />
          <div className="grid sm:grid-cols-2 gap-3.5">
            <div className="sm:col-span-2">
              <label className="eyebrow block mb-1.5">Legal name *</label>
              <input
                required
                minLength={2}
                className="field"
                value={form.legal_name}
                onChange={(e) => set("legal_name", e.target.value)}
                placeholder="Acme Technologies Private Limited"
              />
            </div>
            <div>
              <label className="eyebrow block mb-1.5">Sector *</label>
              <select
                className="field cursor-pointer"
                value={form.sector}
                onChange={(e) => set("sector", e.target.value)}
              >
                {SECTORS.map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="eyebrow block mb-1.5">Sub-vertical</label>
              <input
                className="field"
                value={form.sub_vertical}
                onChange={(e) => set("sub_vertical", e.target.value)}
                placeholder="Payments infrastructure"
              />
            </div>
            <div>
              <label className="eyebrow block mb-1.5">HQ city</label>
              <input
                className="field"
                value={form.hq_city}
                onChange={(e) => set("hq_city", e.target.value)}
                placeholder="Bangalore"
              />
            </div>
            <div>
              <label className="eyebrow block mb-1.5">HQ state</label>
              <input
                className="field"
                value={form.hq_state}
                onChange={(e) => set("hq_state", e.target.value)}
                placeholder="Karnataka"
              />
            </div>
            <div>
              <label className="eyebrow block mb-1.5">Founded</label>
              <input
                type="date"
                className="field"
                value={form.founded_date}
                onChange={(e) => set("founded_date", e.target.value)}
              />
            </div>
            <div>
              <label className="eyebrow block mb-1.5">Employees</label>
              <input
                type="number"
                min={0}
                className="field"
                value={form.employee_count}
                onChange={(e) => set("employee_count", e.target.value)}
              />
            </div>
            <div>
              <label className="eyebrow block mb-1.5">Website</label>
              <input
                className="field"
                value={form.website}
                onChange={(e) => set("website", e.target.value)}
                placeholder="https://"
              />
            </div>
            <div>
              <label className="eyebrow block mb-1.5">
                CIN <span className="normal-case text-ink-muted">(verified via MCA21)</span>
              </label>
              <input
                className="field"
                value={form.cin}
                onChange={(e) => set("cin", e.target.value)}
                placeholder="U72900KA2021PTC123456"
              />
            </div>
            <div className="sm:col-span-2">
              <label className="eyebrow block mb-1.5">One-liner</label>
              <input
                maxLength={280}
                className="field"
                value={form.one_liner}
                onChange={(e) => set("one_liner", e.target.value)}
                placeholder="What you do, in one sentence"
              />
            </div>
            <div className="sm:col-span-2">
              <label className="eyebrow block mb-1.5">Description</label>
              <textarea
                rows={4}
                className="field resize-y"
                value={form.long_description}
                onChange={(e) => set("long_description", e.target.value)}
                placeholder="The problem, your solution, and why now. This text is embedded and fed to the growth model — it carries real predictive weight."
              />
            </div>
          </div>
        </Card>

        {needsFinancials && (
          <Card className="p-5">
            <SectionHeader
              eyebrow="Step 3"
              title="Financials"
              description="Burn rate and cash balance are required from seed onward — runway is derived from them and is the single largest input to your risk score."
              action={<Badge tone="warning">Compared with GST turnover (simulated)</Badge>}
            />
            <div className="grid sm:grid-cols-3 gap-3.5">
              {[
                { k: "revenue", l: "Annual revenue (USD)" },
                { k: "prior_year_revenue", l: "Prior year revenue" },
                { k: "total_funding_usd", l: "Total raised" },
                { k: "burn_rate_monthly", l: "Monthly burn *", req: true },
                { k: "cash_balance", l: "Cash balance *", req: true },
                { k: "active_users", l: "Active users" },
                { k: "cac", l: "CAC" },
                { k: "ltv", l: "LTV" },
                { k: "tam_usd", l: "TAM (USD)" },
                { k: "sam_usd", l: "SAM (USD)" },
              ].map((f) => (
                <div key={f.k}>
                  <label className="eyebrow block mb-1.5">{f.l}</label>
                  <input
                    type="number"
                    min={0}
                    step="any"
                    required={f.req}
                    className="field tnum"
                    value={fin[f.k]}
                    onChange={(e) => setF(f.k, e.target.value)}
                  />
                </div>
              ))}
            </div>
          </Card>
        )}

        <Card className="p-5">
          <SectionHeader
            eyebrow={needsFinancials ? "Step 4" : "Step 3"}
            title="Founders"
            description="GitHub handles are verified against the live public API. LinkedIn URLs are recorded but enrichment there is mocked pending a consented integration."
            action={
              <button
                type="button"
                className="btn text-[12.5px]"
                onClick={() =>
                  setFounders((f) => [
                    ...f,
                    { name: "", role: "Co-Founder", linkedin_url: "", github_username: "" },
                  ])
                }
              >
                Add founder
              </button>
            }
          />
          <div className="space-y-3.5">
            {founders.map((f, i) => (
              <div key={i} className="grid sm:grid-cols-4 gap-2.5 items-end">
                <div>
                  <label className="eyebrow block mb-1.5">Name</label>
                  <input
                    className="field"
                    value={f.name}
                    onChange={(e) =>
                      setFounders((arr) =>
                        arr.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)),
                      )
                    }
                  />
                </div>
                <div>
                  <label className="eyebrow block mb-1.5">Role</label>
                  <input
                    className="field"
                    value={f.role}
                    onChange={(e) =>
                      setFounders((arr) =>
                        arr.map((x, j) => (j === i ? { ...x, role: e.target.value } : x)),
                      )
                    }
                  />
                </div>
                <div>
                  <label className="eyebrow block mb-1.5">LinkedIn</label>
                  <input
                    className="field"
                    value={f.linkedin_url}
                    onChange={(e) =>
                      setFounders((arr) =>
                        arr.map((x, j) => (j === i ? { ...x, linkedin_url: e.target.value } : x)),
                      )
                    }
                  />
                </div>
                <div className="flex gap-2">
                  <div className="flex-1">
                    <label className="eyebrow block mb-1.5">GitHub</label>
                    <input
                      className="field"
                      placeholder="username"
                      value={f.github_username}
                      onChange={(e) =>
                        setFounders((arr) =>
                          arr.map((x, j) =>
                            j === i ? { ...x, github_username: e.target.value } : x,
                          ),
                        )
                      }
                    />
                  </div>
                  {founders.length > 1 && (
                    <button
                      type="button"
                      className="btn px-2.5"
                      onClick={() => setFounders((arr) => arr.filter((_, j) => j !== i))}
                      aria-label="Remove founder"
                    >
                      ×
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </Card>

        {error && (
          <Card className="border-critical-line! bg-critical-tint! p-4">
            <p className="text-[13px] text-critical-text">
              <span className="font-medium">Validation failed:</span> {error}
            </p>
          </Card>
        )}

        <div className="flex flex-wrap items-center gap-3">
          <button type="submit" className="btn btn-primary" disabled={submitting}>
            {submitting ? "Scoring…" : "Submit & score"}
          </button>
          <p className="max-w-md text-[12px] leading-relaxed text-ink-muted">
            On submit, your profile is validated server-side, scored across four dimensions,
            and indexed for peer benchmarking.
          </p>
        </div>
      </form>
    </div>
  );
}
