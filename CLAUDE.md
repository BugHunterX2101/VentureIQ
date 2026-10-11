# CLAUDE.md

Guidance for Claude Code (and future you) when working in this repository.

## What this project is

**VentureIQ: An Agentic AI and RAG-Powered Intelligent Startup Investment Platform** —
a B.E. (Computer Science and Business Systems) dissertation project, BMS College of
Engineering / VTU, 2025–2026. Team: Devansh Sangwan, Paras, Vedit Agrawal, Dimple
Hirwani. Guide: Dr. Gururaja H.S.

The source of truth for scope and design is `VentureIQ_report (2).pdf` at the repo
root (the Phase-I synopsis). Read it before making architectural changes — this
CLAUDE.md and `docs/` summarize it, but the PDF is authoritative if they ever diverge.

**One-line pitch:** existing platforms (AngelList/Wellfound, Crunchbase, PitchBook,
Gust, Carta) each solve one piece of startup investing — fundraising, data
aggregation, market intelligence, deal flow, or cap-table admin — but none of them
*verify* what founders self-report or give investors an explainable, data-driven score
before they commit money. VentureIQ's bet is a single platform that verifies startup
claims against independent sources, scores startups on four explainable dimensions,
detects fraud, and matches investors to startups — instead of trusting a pitch deck.

## Current state of the repo

**A working MVP.** Backend and frontend both run; `README.md` has the two-command
quick start and a table of exactly what is real vs. mocked vs. simulated. Run
`./start.sh` from the repo root to bring up both servers.

- `backend/` — FastAPI + SQLAlchemy + scikit-learn. SQLite by default (set
  `VIQ_DATABASE_URL` for Postgres). `scripts/bootstrap.py` rebuilds the DB, loads
  the real seed datasets, trains both models, and scores all 9,287 startups in
  ~80 seconds. It is idempotent — re-run it freely.
- `frontend/` — Vite + React 19 + TypeScript + Tailwind v4, light and dark themes.
  Public pages: Landing, Discover, StartupDetail, Model, Marketplace, Register (the
  agentic registration), Login. Signed-in pages: Overview, Feed, Saved, Alerts,
  Onboarding (mandate), MyCompanies, Account (profile + KYC), Reviews (the KYC
  queue, reviewers only). Charts are hand-built SVG; the 3D scenes are
  three.js/react-three-fiber, lazy-loaded. Each route renders inside an error
  boundary, so one broken page never blanks the app.
- `backend/tests/` — pytest, 99 tests (`pytest -m "not network"` for the offline 89).
- The growth model is genuinely trained, not stubbed: gradient boosting on 1,896
  labelled YC companies, **AUROC 0.741** on a held-out split, beating logistic
  regression (0.721) and random forest (0.732). Metrics are exposed in the UI at
  `/model` on purpose — a product that tells investors to distrust unverified
  claims has to publish its own numbers too.
- Enrichment, source by source (all behind the same `SourceAdapter` interface, with
  every record's provenance stored and shown in the UI):
  - **Real:** company websites, RDAP (domain age), DNS, GitHub (orgs and founders),
    the MCA Company Master Data (36.7 lakh companies imported from data.gov.in into
    `backend/registry.db`), GST taxpayer register (identity and status, via a
    RapidAPI vendor), and founder LinkedIn profiles (via a RapidAPI aggregator —
    third-party scraped data, labelled as such and used only to corroborate a
    founder's own claim).
  - **Simulated, and labelled:** GST turnover (needs per-pull taxpayer consent), the
    identity decision in KYC (needs a licensed provider; a human reviewer stands in),
    and the marketplace's money movement (escrow is a state machine).
- Agentic registration (`app/onboarding/`): a founder gives a website, email, name
  and stage; the agent plans which sources to query from what it finds, streams its
  trace, and reconciles everything into a per-field ledger (verified / auto-filled /
  your input / conflict). Only an independent source can mark a field verified.
- Documents (`app/documents/`): Tesseract OCR on uploaded certificates and
  statements; the CIN is checked against the MCA registry, the GSTIN's check digit
  validated. OCR repairs are accepted only when a check digit or the registry agrees.
- Accounts: email + password (bcrypt, JWT) and Google OAuth; investor and founder
  roles with ownership enforced server-side; KYC gates the marketplace. Repeated
  failed sign-ins are throttled per account and per caller (in-process, so a
  multi-worker deployment wants this in Redis instead).
- Explainability (`app/ml/explain.py`): exact Shapley values from
  `shap.TreeExplainer` for both trained models, grouped into features a reader
  recognises. `shap` costs ~200 MB resident, so it is behind `VIQ_ENABLE_SHAP`
  and every caller falls back cleanly when it is off.
- Paid API budgets: LinkedIn and GST lookups are cached in `backend/cache.db` and
  capped per month, so repeat lookups never spend quota.

Below is the original design documentation, still current.
- `VentureIQ_report (2).pdf` — the dissertation synopsis (30 pages). Contains the
  literature review, problem definition, objectives, requirement spec, system design
  (5 layers), and methodology this whole project is built from.
- `docs/DATA_SCHEMA.md` — full entity/field schema for every layer (startup profile,
  financials, founders, documents, enrichment, fraud signals, investor profiles,
  behavioral events, AI scores, marketplace/compliance), plus how the seed datasets map
  onto it.
- `docs/BUILD_PLAN.md` — phased build order and, more importantly, the **specific
  problems this project will hit** (regulatory scope of the marketplace layer, data
  sources that can't be bulk-collected, lack of labeled Indian outcome data, cold-start
  ML, running 5 storage systems as a 4-person team, heterogeneous explainability,
  multi-year evaluation horizon) with concrete mitigations for each. Read this before
  estimating any timeline or promising a feature in a review.
- `data/raw/` — real, downloaded (not fabricated) seed datasets: ~7,000 Indian startup
  funding records (2015–2021) from public GitHub mirrors of the Kaggle "Indian Startup
  Funding" dataset, plus 6,151 Y Combinator companies (global, with outcome labels:
  Active/Inactive/Acquired/Public) from the yc-oss/api project. See
  `data/raw/README.md` for exact provenance, licensing caveats, and why the "real"
  sources this project ultimately needs (MCA21, GSTN, LinkedIn, SEBI AIF registry)
  couldn't be bulk-collected the same way — that section explains real constraints
  (fees, consent requirements, ToS), not laziness.
- `docs/BUILD_PLAN.md` phases 1–6 are implemented; phase 7 (marketplace) is
  deliberately simulated only. Keep following that doc's ordering and its list of
  things not to build.

## System architecture (5 layers, per report §7)

1. **Infrastructure** — API Gateway (all traffic passes through it, no exceptions),
   Auth (JWT) & KYC, Notifications, Monitoring (Prometheus + ELK).
2. **Startup Data Pipeline** — stage-aware registration forms → OCR/document
   intelligence (LayoutLM-v3 + spaCy NER) → agentic enrichment (LinkedIn, MCA21, GSTN,
   GitHub — queried autonomously, not via a fixed script) → PostgreSQL (structured) +
   S3 (raw documents).
3. **AI Engine** — Feature Store → four *independently* trained scores (Growth
   Potential, Risk Level, Fraud Detection, Founder Credibility — deliberately not
   fused early; report §8.3 cites ablation evidence that early fusion underperforms) →
   SHAP-based explainability.
4. **Investor Pipeline** — structured onboarding (ticket size, stage, sector,
   geography, risk tolerance) solves cold start → Kafka behavioral event stream → LightFM
   collaborative filtering → Neo4j investor–startup network graph → personalized feed.
5. **Marketplace & Compliance** — listing engine, AI fair-value estimator, escrow,
   KYC, Right of First Refusal, Compliance-as-Code (SEBI/accredited-investor rules),
   append-only audit log. **This layer is a regulated financial product** — see
   `docs/BUILD_PLAN.md` Problem 1 before building anything here that touches real money.

## Technical stack

**What is installed and running today** (the pragmatic Phase 1–6 stack):
FastAPI · SQLAlchemy 2 · Pydantic v2 · SQLite · scikit-learn · TF-IDF+SVD vector
index in-process · React 19 + Vite + Tailwind v4. Behavioural events write
straight to Postgres/SQLite through a 202 fire-and-forget endpoint that keeps
Kafka's contract, so a producer can be dropped in front without touching callers.

**The report's target stack (§6.3)** — promote to these as volume justifies it,
per `docs/BUILD_PLAN.md` Problem 5:

| Component | Technology |
|---|---|
| Frontend | React, schema-driven dynamic forms (Zod, stage-aware conditional fields) |
| API layer | RESTful gateway with Auth + KYC middleware |
| Structured storage | PostgreSQL |
| Document storage | S3-compatible blob storage |
| Vector database | Pinecone or Weaviate (RAG knowledge base) |
| Graph database | Neo4j (investor–startup network, co-investment analysis) |
| Event streaming | Apache Kafka (real-time behavioral tracking) |
| ML / AI | Scikit-learn + PyTorch; SHAP for explainability; LayoutLM for document parsing |
| Fraud detection | Isolation Forest + TensorFlow Autoencoder (unsupervised) |
| Backend validation | Pydantic v2 (server-side re-validation of every client submission) |

Per `docs/BUILD_PLAN.md`, early phases may substitute lighter local equivalents
(Postgres+pgvector instead of Pinecone, `networkx` instead of Neo4j) before the data
volume justifies running the full stack — check that doc before assuming the table
above is what Phase 1 code should actually target.

## Working conventions for this repo

- **Don't add code that pretends the marketplace layer moves real money.** Escrow/KYC/
  RoFR should be built as a clearly-labeled simulation unless the team has confirmed a
  licensed payment/escrow partner — see `docs/BUILD_PLAN.md` Problem 1.
- **Never bulk-scrape LinkedIn, Crunchbase or GSTN.** Lookups are one company or
  founder at a time, cached, and budgeted. LinkedIn comes through a paid aggregator
  the team chose deliberately; keep its records labelled as third-party and use them
  only to corroborate a founder's own claim, never to verify a company field.
  GST returns and exact turnover stay simulated until there is a consented GSP flow.
  GitHub, RDAP, DNS, the MCA master data and the public GST register are fine to call
  for real, with caching (30-day TTL, retries with backoff, per report §8.1.3).
- **Scores append, they don't overwrite.** `score.is_current` marks the one row
  per startup that queries should see. Any new SQL that joins `score` must filter
  on it, or a rescored startup is counted twice in aggregates and sorted on an
  arbitrary old row.
- **Only independent evidence verifies.** In the onboarding ledger, mocked or locally
  computed evidence can support a value but must never mark it verified. Keep that
  rule when adding sources (`app/onboarding/ledger.py`).
- **Keep secrets out of git.** `backend/.env`, `registry.db`, `cache.db`,
  `artifacts/jwt_secret.txt` and `artifacts/uploads/` are gitignored; keep it so.
- **Keep the four AI Engine scores independent.** Don't refactor them into one joint
  model without re-reading why the report deliberately keeps them separate (§8.3).
- **Any new data source or dataset** should get a row added to `data/raw/README.md`
  (or a new `data/<name>/README.md`) documenting provenance and license — don't drop
  unattributed CSVs/JSON into the repo.
- **Any new entity/field** should be added to `docs/DATA_SCHEMA.md` first — that file
  is the schema contract other layers are built against.
- This is an academic dissertation repo, not a production fintech company yet. When a
  design decision trades off "impressive for the dissertation" against "legally/
  operationally real," default to building the real thing at small scale and being
  explicit in the report about what's simulated — reviewers will ask, and "we built a
  correct simulation and documented the real requirements" is a better answer than
  overclaiming.
