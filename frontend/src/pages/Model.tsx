import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { compactNum } from "../lib/format";
import { HBarChart } from "../components/charts";
import { Badge, Card, SectionError, SectionHeader, SkeletonRows, Stat } from "../components/primitives";

/** Model transparency page.
 *
 *  The product's entire argument is that investors should not accept a score on
 *  faith. That has to apply to our own model too — so its real held-out metrics,
 *  its training population, and its known limitations are all in the UI rather
 *  than buried in a notebook.
 */
export default function Model() {
  const [m, setM] = useState<any>(null);
  const [health, setHealth] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.modelMetrics().then(setM).catch((e) => setErr(String(e)));
    api.health().then(setHealth).catch(() => {});
  }, []);

  if (err)
    return (
      <Card>
        <SectionError
          message={err}
          onRetry={() => {
            setErr(null);
            api.modelMetrics().then(setM).catch((e) => setErr(String(e?.message ?? e)));
          }}
        />
      </Card>
    );
  if (!m) return <SkeletonRows n={3} height={110} />;

  const best = m.comparison?.[m.chosen_model];
  const rows = Object.entries(m.comparison ?? {}) as [string, any][];

  return (
    <div className="space-y-5 animate-in">
      <div>
        <h1 className="text-[28px] font-extrabold tracking-tight leading-tight">
          Model transparency
        </h1>
        <p className="text-[13.5px] text-ink-muted mt-1.5 max-w-2xl leading-relaxed">
          Held-out performance of the growth-potential model, the population it was trained
          on, and what it cannot do. Published here because a platform that asks investors to
          distrust unverified claims has to hold its own model to the same standard.
        </p>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Stat
          label="AUROC (held out)"
          value={best?.auroc?.toFixed(3) ?? "—"}
          sub="Ranking quality — 0.5 is a coin flip"
          accent="var(--color-brand)"
        />
        <Stat
          label="Balanced accuracy"
          value={best ? `${(best.balanced_accuracy * 100).toFixed(1)}%` : "—"}
          sub="Corrects for class imbalance"
        />
        <Stat
          label="Training rows"
          value={compactNum(m.n_labelled)}
          sub={`${compactNum(m.n_positive)} positive · ${compactNum(m.n_negative)} negative`}
        />
        <Stat
          label="Precision / recall"
          value={best ? `${(best.precision * 100).toFixed(0)} / ${(best.recall * 100).toFixed(0)}%` : "—"}
          sub="At the 0.5 decision threshold"
        />
      </div>

      <Card className="p-5">
        <SectionHeader
          eyebrow="Model selection"
          title="Candidate comparison"
          description="Three classifiers trained on the same fused feature set (structured metadata concatenated with a dense text embedding of the company description). The best AUROC wins."
        />
        <div className="overflow-x-auto">
          <table className="data-table min-w-[560px]">
            <thead>
              <tr>
                <th className="col-sticky text-left">Model</th>
                <th className="text-right">AUROC</th>
                <th className="text-right">Bal. acc</th>
                <th className="text-right">Precision</th>
                <th className="text-right">Recall</th>
                <th className="text-right">F1</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {rows.map(([name, v]) => (
                <tr
                  key={name}
                  className={name === m.chosen_model ? "bg-row-selected" : ""}
                >
                  <td className="col-sticky whitespace-nowrap">
                    <span className="text-ink">{name.replace(/_/g, " ")}</span>
                    {name === m.chosen_model && (
                      <Badge tone="brand">
                        <span className="ml-1">selected</span>
                      </Badge>
                    )}
                  </td>
                  <td className="tnum text-right text-ink">{v.auroc.toFixed(4)}</td>
                  <td className="tnum text-right text-ink-secondary">
                    {v.balanced_accuracy.toFixed(4)}
                  </td>
                  <td className="tnum text-right text-ink-secondary">
                    {v.precision.toFixed(3)}
                  </td>
                  <td className="tnum text-right text-ink-secondary">
                    {v.recall.toFixed(3)}
                  </td>
                  <td className="tnum text-right text-ink-secondary">{v.f1.toFixed(3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="grid lg:grid-cols-2 gap-4">
        <Card className="p-5">
          <SectionHeader eyebrow="Training data" title="What it learned from" />
          <dl className="space-y-3 text-[12.5px]">
            <div>
              <dt className="text-ink-muted mb-0.5">Source</dt>
              <dd className="text-ink-secondary">{m.trained_on}</dd>
            </div>
            <div>
              <dt className="text-ink-muted mb-0.5">Positive class</dt>
              <dd className="text-ink-secondary">{m.positive_class}</dd>
            </div>
            <div>
              <dt className="text-ink-muted mb-0.5">Excluded</dt>
              <dd className="text-ink-secondary">{m.excluded}</dd>
            </div>
            <div>
              <dt className="text-ink-muted mb-0.5">Held-out split</dt>
              <dd className="text-ink-secondary tnum">{(m.test_size * 100).toFixed(0)}%</dd>
            </div>
          </dl>

          <div className="mt-4 pt-4 border-t border-line">
            <HBarChart
              data={[
                { label: "Acquired or public", value: m.n_positive },
                { label: "Inactive (failed)", value: m.n_negative },
              ]}
              valueFormat={compactNum}
              color="var(--color-series-1)"
            />
          </div>
        </Card>

        <Card className="p-5">
          <SectionHeader
            eyebrow="Explainability"
            title="How a score is explained"
            description="Four scores, two mechanisms — because they are four different kinds of model."
          />
          <dl className="space-y-3 text-[12.5px]">
            <div>
              <dt className="mb-0.5 text-ink-muted">Growth potential · fraud likelihood</dt>
              <dd className="leading-relaxed text-ink-secondary">
                Both are tree ensembles, so both get exact Shapley values from{" "}
                <code className="text-[11.5px]">shap.TreeExplainer</code> — no sampling and no
                surrogate model. The description's 96 latent dimensions are summed back into one
                feature, since a single latent dimension means nothing to a reader.
              </dd>
            </div>
            <div>
              <dt className="mb-0.5 text-ink-muted">Risk level · founder credibility</dt>
              <dd className="leading-relaxed text-ink-secondary">
                Additive rule compositions. Each term already is its own explanation, so they are
                reported directly rather than approximated by a second model.
              </dd>
            </div>
            <div>
              <dt className="mb-0.5 text-ink-muted">The honest caveat</dt>
              <dd className="leading-relaxed text-ink-secondary">
                Shapley values are additive in the model's own units — log-odds for the classifier,
                isolation path length for the anomaly detector — not in the 0–100 points on screen.
                Each contribution is that feature's share of the model's total move, converted to
                points. Every attribution names the mechanism that produced it.
              </dd>
            </div>
          </dl>
        </Card>

        <Card className="p-5">
          <SectionHeader eyebrow="Known limitations" title="What this model cannot tell you" />
          <div
            className="rounded-lg border p-3.5 mb-3"
            style={{
              borderColor: "var(--color-warning-line)",
              backgroundColor: "var(--color-warning-tint)",
            }}
          >
            <p className="text-[12.5px] text-ink-secondary leading-relaxed">{m.caveat}</p>
          </div>
          <ul className="space-y-2.5 text-[12.5px] text-ink-secondary">
            {[
              "Outcome labels resolve over years. Nothing here validates a live prediction — only historical held-out data.",
              "Fraud detection is unsupervised anomaly detection, not a trained fraud classifier. No labelled fraud dataset exists for Indian startups.",
              "Peer benchmarking degrades where a sector-and-stage cohort is thin; those scores are marked low-confidence rather than hidden.",
              "Brand-new companies have no co-investment network position, so the network signal correctly returns zero rather than guessing.",
            ].map((t, i) => (
              <li key={i} className="flex gap-2 leading-relaxed">
                <span className="text-ink-muted shrink-0">—</span>
                {t}
              </li>
            ))}
          </ul>
        </Card>
      </div>

      {health && (
        <Card className="p-5">
          <SectionHeader eyebrow="Runtime" title="System status" />
          <div className="flex flex-wrap gap-2.5">
            <Badge tone="good">API {health.status}</Badge>
            <Badge tone={health.growth_model_trained ? "good" : "critical"}>
              Growth model {health.growth_model_trained ? "loaded" : "missing"}
            </Badge>
            <Badge tone={health.fraud_model_trained ? "good" : "critical"}>
              Anomaly detector {health.fraud_model_trained ? "loaded" : "missing"}
            </Badge>
            <Badge tone="neutral">{compactNum(health.startups_indexed)} startups indexed</Badge>
          </div>
        </Card>
      )}
    </div>
  );
}
