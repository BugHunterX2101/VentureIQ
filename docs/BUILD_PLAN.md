# VentureIQ — Build Plan & Problems

Source of truth for scope is `VentureIQ_report (2).pdf` (the Phase-I dissertation
synopsis). That report describes a *5-layer* production platform: Infrastructure,
Startup Data Pipeline, AI Engine, Investor Pipeline, Marketplace & Compliance. Read
literally, this is roughly a funded startup's 18-month product roadmap. This doc is the
honest translation of that into something a 4-person B.E. team can actually build and
defend, plus the specific problems that will bite and how to handle each.

## Phased build order

The report's layers are the right *logical* architecture; build them in a different
*order* than numbered, so there's always something demoable and each phase produces
data the next phase needs.

**Phase 1 — Startup Data Pipeline MVP (weeks 1–4)**
Stage-aware registration form (React + Zod) → Postgres. OCR on uploaded pitch
decks/cap tables (Tesseract to start, LayoutLM-v3 later once there's a labeled sample
to fine-tune on). No enrichment yet, no scoring yet. Seed the sector taxonomy and
`startup`/`startup_financials` tables from `data/raw/*.csv` so the UI and DB aren't
empty during development.

**Phase 2 — Baseline scoring, no fraud/enrichment yet (weeks 4–7)**
Train a first Growth-Potential model on the YC `status` labels
(`data/raw/yc_companies_all.json` — Active/Inactive/Acquired/Public) plus structured
features from the Indian funding CSVs, mirroring the fused-LLM approach from Maarouf et
al. 2025 that the report cites: structured features + BERT embedding of
`long_description`/pitch text, concatenated, into a classifier. This gives a real,
demoable score before a single line of enrichment code exists, and gives the team a
number to compare against later (72–74% balanced accuracy is the paper's baseline —
don't expect to beat it with 1/100th the data).

**Phase 3 — Agentic enrichment, one source at a time (weeks 7–11)**
Build GitHub enrichment first (free, official API, generous rate limits, no consent
flow needed for public data) → founder credibility score becomes real. Then MCA21
lookup (per-CIN, manual-fee-aware, cached 30 days) → registration verification. Defer
GSTN and LinkedIn — both need a consent/licensing story before they can touch a single
real founder's data (see Problem 2 below); build them behind a feature flag against
mocked responses so the rest of the pipeline (deviation flags, fraud signals) can be
built and tested without waiting on that legal work.

**Phase 4 — Fraud detection (weeks 11–13)**
Isolation Forest + autoencoder over the feature store. Train on the (larger) YC/global
data first since there's no labeled Indian fraud data at all (Problem 3) — treat this
explicitly as anomaly detection against "normal" patterns, not fraud classification,
and say so in the dissertation rather than overclaiming.

**Phase 5 — Investor pipeline (weeks 13–17)**
Structured onboarding → cold-start recommendations immediately. Kafka behavioral
tracking + LightFM collaborative filtering once there's enough synthetic/simulated
investor interaction volume to train on (real usage during a UAT period, or a
simulated-user script if UAT can't generate enough events in time).

**Phase 6 — RAG benchmarking (weeks 17–19)**
Pinecone/Weaviate index over the startup corpus built in Phases 1–2. This is the
easiest layer to over-scope — cap it at "retrieve top-10 similar startups, same
stage+sector, ≤24 months old" exactly as the report specifies, and use it to generate
the SHAP-style rationale text, not as a general chat interface.

**Phase 7 — Marketplace & compliance (weeks 19–22, mostly simulated)**
Listing engine, fair-value estimator, matching — real. Escrow, KYC, RoFR, actual money
movement — **simulate, don't implement**, unless the team secures a partnership with a
licensed payment aggregator/escrow provider. See Problem 1.

Each phase should end with something running end-to-end, even if downstream layers are
stubbed — that's what makes the mid-project review and final demo survivable.

---

## Problems, ranked by how much they can derail the timeline

### Problem 1 — The marketplace layer is a regulated financial product, not a feature
Escrow, RoFR, and secondary transfer of equity stakes fall under SEBI/RBI-regulated
activity (merchant banking, payment aggregation, possibly AIF-adjacent activity
depending on structure). A student project cannot legally hold client money in escrow
or execute real equity transfers without the underlying licenses. **Mitigation:**
scope this layer as a *simulated* transaction flow for the dissertation (mock escrow
state machine, no real payment rails), and say so explicitly in the report rather than
implying production-readiness — reviewers in fintech-adjacent depts will ask about this
directly, and "we built a compliant simulation and documented what real licensing would
require" is a strong answer, "we integrated a payment gateway" for real equity
transactions is not something to actually attempt.

### Problem 2 — Three of the five "verification" data sources aren't bulk-accessible
Detailed in `data/raw/README.md`. MCA21 is per-company and fee-gated beyond basic
fields, GSTN requires the taxpayer's consent per pull (account-aggregator model, not a
scrape), LinkedIn scraping breaks ToS and is actively litigated. **Mitigation:** design
the agentic enrichment layer's interface (a source adapter with `verify(startup_id) ->
EnrichmentRecord`) so each source is swappable — ship with GitHub (free, real) and
mocked adapters for MCA21/GSTN/LinkedIn that return realistic-looking fixture data, and
be upfront in the dissertation that going live on those three needs either paid API
access (e.g. a licensed KYC/AA data partner) or manual verification in a pilot.

### Problem 3 — There is no labeled Indian startup outcome/fraud dataset
The paper VentureIQ's own scoring design is modeled on (Maarouf et al. 2025) trained on
20,172 Crunchbase companies with known IPO/acquisition/funding outcomes. Nothing close
to that exists publicly for India — the seed CSVs in `data/raw/` have funding *events*,
not outcomes (nobody's labeled "this startup failed" at scale). **Mitigation:**
pretrain/structure the model on the global YC dataset (which does have a `status`
label), fine-tune or at minimum sanity-check on whatever labeled India subset the team
can hand-curate (the 222 India-located YC companies is a start, ~200 rows is thin —
budget time to manually label outcomes for e.g. 300–500 of the Indian funding-CSV
companies using public news/LinkedIn "closed"/"acquired by" signals as ground truth).
Report the accuracy honestly against this small eval set rather than presenting it as
equivalent to the paper's number.

### Problem 4 — Cold-start and small-N break the ML components in predictable ways
- LightFM collaborative filtering needs interaction volume the platform won't have
  until real investors use it — the structured-preference cold start (report §6.1.2)
  is not optional, it's load-bearing for the entire pilot period.
- Isolation Forest/autoencoder fraud detection needs enough "normal" examples per
  sector/stage to know what's normal — with a few hundred startups split across a dozen
  sectors and four stages, some buckets will have single-digit counts. Either pool
  across sectors for the anomaly model (losing some precision) or explicitly flag
  low-confidence scores when the reference cohort is under some minimum size (e.g. 20).
- Node2Vec-style network features (report cites arXiv:2511.23364 on this exact
  limitation) can't represent brand-new startups with no investment history — that
  paper's own limitations section says this; VentureIQ's `network_score` should
  degrade gracefully to 0/null rather than error for first-time listings.

### Problem 5 — Five storage systems (Postgres, S3, Pinecone/Weaviate, Neo4j, Kafka) is a lot for one dissertation team to run reliably
Each is independently reasonable; running all five in sync, with monitoring
(Prometheus/ELK per report §7 Layer 1), is a lot of operational surface for four
people alongside coursework. **Mitigation:** `docker-compose` everything locally from
day one so the whole stack is one command for any team member; in Phase 1–2, consider
substituting a Postgres table + pgvector extension for Pinecone and a simple
`networkx` graph for Neo4j, and only promote to the "real" dedicated systems in Phase
5–6 once the data volume/team bandwidth justifies it. This isn't cutting the
architecture from the report — it's sequencing when each piece becomes load-bearing.

### Problem 6 — Explainability across four *different kinds* of model
SHAP is well-defined for tree ensembles and reasonably tractable for small neural nets
(KernelExplainer/DeepExplainer), but "explain an Isolation Forest anomaly score" and
"explain a growth classifier's probability" are different problems being surfaced as
one uniform "SHAP rationale" in the report (§8.3). **Mitigation:** use
`TreeExplainer`-compatible variants for the tree-based fraud detector, a
gradient/kernel explainer for the neural growth/risk models, and be explicit in the
write-up that "explainability" means a per-model-appropriate top-3-features text
summary, not one shared mechanism — that's a more defensible (and more accurate)
claim than implying a single SHAP pipeline handles all four heterogeneous scores.

**Built** (`backend/app/ml/explain.py`): the mitigation held, and it turned out
better than expected — both trained models are tree ensembles (gradient boosting
for growth, isolation forest for fraud), so both get *exact* Shapley values from
`TreeExplainer` rather than a sampled approximation. Two things the write-up must
still say plainly:

- The remaining two scores, risk and founder credibility, have no model to
  explain. They are additive rule compositions whose terms already are the
  explanation, and they report those terms instead. Four scores, two mechanisms;
  every attribution carries a `method` field naming which one produced it.
- Shapley values are additive in the model's own output — log-odds for the
  classifier, isolation path length for the anomaly detector — not in the 0–100
  points the interface draws. Each contribution is that feature's share of the
  model's total move away from its base rate, rescaled to points. Exact in
  aggregate, monotone per feature, and **not** itself a Shapley value in score
  space. Claiming otherwise is the kind of thing a reviewer will ask about.

Cost worth knowing before deploying: `shap` pulls in numba, ~200 MB resident on
first use. It sits behind `VIQ_ENABLE_SHAP` so a small instance can run without
it (scores still compute; they just report the prediction undecomposed).

### Problem 7 — Evaluating "did this recommendation/score turn out to be right?" takes years
Startup success/failure resolves on a multi-year timescale; a one-semester (or even
one-year) dissertation project cannot show real-world validation of its own
predictions. **Mitigation:** validate against the *historical* labeled data (YC
`status`, hand-labeled Indian subset) using standard train/test splits — that's what
the cited papers do too — and be explicit that live-cohort validation is future work,
not a claim the dissertation can make.

---

## What to *not* build for the dissertation, even though the report mentions it
- Real payment rails / actual escrow of investor funds (Problem 1)
- Bulk LinkedIn/GSTN integration (Problem 2) — mock these, ship GitHub/MCA21 for real
- A fully general RAG chat interface — the report specifies a narrow benchmarking
  retrieval, not an open Q&A assistant; scope creep here eats weeks for no score benefit
- Training the four AI Engine scores jointly / end-to-end — the report itself (§8.3,
  citing the Maarouf ablation) says independent scoring outperforms early fusion
