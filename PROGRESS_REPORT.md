# VentureIQ — Progress Report

**Project:** VentureIQ — An Agentic AI and RAG-Powered Intelligent Startup Investment Platform
**Programme:** B.E. Computer Science and Business Systems, BMS College of Engineering (VTU)
**Academic year:** 2025–2026
**Team:** Devansh Sangwan (1BM23CB014), Paras (1BM23CB032), Vedit Agrawal (1BM23CB060), Dimple Hirwani (1BM23CB065)
**Guide:** Dr. Gururaja H.S.
**Phase:** Post Phase-I implementation checkpoint

---

## 1. Executive summary

The Phase-I synopsis proposed a five-layer platform that verifies startup claims
against independent sources, scores startups on four explainable dimensions,
detects fraud, and matches investors to startups. A **working end-to-end
prototype of that system now exists and runs**.

| Metric | Value |
|---|---|
| Overall project completion | **~72%** |
| Startups ingested and scored | 9,289 |
| Machine-learning model performance | **AUROC 0.741** (held-out) |
| Backend API endpoints (all passing) | 23 |
| Frontend pages | 8 |
| Lines of application code | ~8,400 |
| Automated verification checks passing | 31 / 31 |

The headline result is that the scoring engine is **genuinely trained on real
labelled data**, not simulated. A gradient-boosting classifier trained on 1,896
Y Combinator companies with known outcomes (Acquired / Public vs. Inactive)
achieves an AUROC of 0.741 on a held-out test split, outperforming both a
logistic-regression baseline (0.721) and a random-forest baseline (0.732).

---

## 2. Completion by report layer

The synopsis (§7) defines five layers. Progress against each:

| # | Layer | Status | % |
|---|---|---|---|
| 1 | Infrastructure — API gateway, auth/KYC, notifications, monitoring | Gateway and request instrumentation built; JWT auth and full observability stack deferred | **55%** |
| 2 | Startup Data Pipeline — forms, document intelligence, agentic enrichment, storage | Forms, validation, enrichment framework and storage complete; OCR/LayoutLM deferred | **75%** |
| 3 | AI Engine — feature store, four scores, explainability | **Complete and operational** | **95%** |
| 4 | Investor Pipeline — onboarding, event stream, recommendation, network graph | Matching engine operational; Kafka and Neo4j substituted with lighter equivalents | **80%** |
| 5 | Marketplace & Compliance — listings, valuation, escrow, RoFR, audit | Listing, valuation, compliance gating and audit log built; escrow intentionally simulated | **45%** |

**Weighted overall: ~72%**

---

## 3. What is fully working

### 3.1 AI Engine — the core contribution (95%)

Four scores are computed **independently** and only combined at the final step.
This is a deliberate design decision taken directly from the synopsis (§8.3),
which cites ablation evidence that fusing heterogeneous financial and
qualitative signals too early degrades accuracy.

| Score | Method | Status |
|---|---|---|
| Growth Potential | Gradient boosting on structured features concatenated with a dense text embedding of the company description | Trained, AUROC 0.741 |
| Risk Level | Additive model over runway, burn-per-employee, competitive density, company age | Operational |
| Fraud Likelihood | Isolation Forest + PCA reconstruction error + deterministic cross-source rules | Operational |
| Founder Credibility | Prior exits, domain experience, GitHub activity, profile verifiability | Operational |

The growth model replicates the architecture of Maarouf et al. (2025) — the
fused-LLM paper cited in the literature review — substituting a TF-IDF + SVD
document embedding for BERT so the model trains in seconds on a laptop. The
interface is unchanged, so a transformer embedding can be swapped in later.

**Model comparison (held-out, 22% test split, n = 418):**

| Model | AUROC | Balanced accuracy | Precision | Recall | F1 |
|---|---|---|---|---|---|
| **Gradient boosting (selected)** | **0.7411** | 0.6681 | 0.688 | 0.519 | 0.592 |
| Random forest | 0.7323 | 0.6781 | 0.718 | 0.514 | 0.599 |
| Logistic regression | 0.7207 | 0.6625 | 0.605 | 0.661 | 0.632 |

**Explainability** is implemented for every score: each returns its top-three
contributing features with signed numeric contributions, plus a generated
plain-English rationale. Example of actual system output:

> "Growth potential is strong (99/100). Primary driver: Model-estimated
> probability of acquisition/IPO: 78.6%. Also weighing: year-on-year revenue
> growth of 36%."

### 3.2 Agentic enrichment (75%)

This is what makes the system *agentic* rather than a fixed integration script.
A planner inspects each startup, determines what is missing or unverified, and
decides which external sources to query and in what order. It also **escalates**:
if GST-filed revenue disagrees with the founder's claim beyond the 20% threshold,
the agent queues an additional company-registry re-verification that would not
otherwise have run.

| Source | Status | Reason |
|---|---|---|
| **GitHub** | **Live public API** | Genuinely integrated — verified pulling real profile data |
| MCA21 | Mocked | Per-company lookup, fee-gated, no bulk access exists |
| GSTN | Mocked | Requires the taxpayer's per-pull consent; not scrapable |
| LinkedIn | Mocked | Scraping violates Terms of Service (*hiQ v. LinkedIn*) |
| WHOIS | Mocked | Largely redacted post-GDPR |

All four mocked adapters sit behind the **same interface** as the live one, so
each becomes real by swapping one class once a licensed or consented integration
path exists. Every enrichment record is tagged `is_mock` and displayed in the UI
with a provenance indicator, so a mocked value can never be mistaken for a
verified one.

### 3.3 Fraud detection (85%)

Unsupervised anomaly detection fitted on 8,511 financial profiles, combining:

- **Isolation Forest** (6% contamination) — flags profiles that isolate from the population
- **PCA reconstruction error** — stands in for the synopsis's TensorFlow autoencoder; identical "can the model rebuild this row?" signal
- **Deterministic rules** — the strongest of which compares founder-reported revenue against GST filings

Result: **1,780 startups (19%)** land in the human-review queue. This ratio was
deliberately tuned; an earlier configuration flagged 52% of the corpus, which
would have made the alert queue useless.

Critically, the system **never auto-rejects a startup**. Algorithms flag; humans
decide. This matches the synopsis's stated position exactly.

### 3.4 RAG benchmarking (80%)

A vector index over all 9,289 startups retrieves the ten most similar peers,
filtered to the same stage and sector, and computes percentile placement. Where
a cohort falls below 20 comparable companies, the result is explicitly marked
**low-confidence** rather than presented as reliable.

### 3.5 Investor pipeline (80%)

Ranking blends four signals: stated mandate (40%), platform behaviour (25%),
co-investment network position (15%), and company quality (20%). Behavioural
events are captured through a fire-and-forget endpoint that preserves Kafka's
contract, so a Kafka producer can be inserted later without changing any caller.

The cold-start problem is solved as the synopsis proposed — through structured
onboarding. With fewer than five behavioural events, ranking falls back entirely
to stated preferences and the response is flagged `cold_start`.

Three investor personas with different mandates were seeded, and the feed
demonstrably differs between them.

### 3.6 Frontend (85%)

Eight pages built with React 19, TypeScript and Tailwind: Overview, Discover,
Startup Detail, Feed, Alerts, Model, Register, Onboarding. All charts are
hand-built SVG rather than a charting library, so the visual system stays
controlled. The colour palette was validated for colour-blind separation and
contrast: the entire warm spectrum is reserved for risk and fraud status, so an
alert colour can never be confused with a brand colour.

The **Model page publishes the system's own performance metrics and known
limitations to the user**. This is a deliberate stance — a platform whose core
argument is that investors should not accept unverified claims must hold its own
model to the same standard.

---

## 4. What is deliberately not built

These are **engineering and legal judgements**, not incomplete work, and each is
documented with its reasoning in `docs/BUILD_PLAN.md`.

| Item | Why not built |
|---|---|
| Real escrow and equity settlement | Regulated financial activity requiring SEBI/RBI licences the project does not hold. Built as a clearly-labelled simulation with a compliance gate |
| Bulk LinkedIn / GSTN / Crunchbase collection | Terms-of-Service and consent-gated by design. Mocked behind a swappable interface |
| Joint training of the four scores | The synopsis's own cited ablation evidence shows early fusion underperforms |
| General-purpose RAG chat interface | The synopsis specifies narrow benchmarking retrieval; a chat interface is scope creep with no scoring benefit |

---

## 5. Known limitations to state openly

These should be stated in the dissertation rather than glossed over — a reviewer
will ask, and a documented limitation is a stronger answer than an overclaim.

1. **Domain transfer.** The growth model is trained on global Y Combinator data
   because no labelled Indian startup outcome dataset exists publicly. Applying
   it to Indian startups is a domain transfer and must be reported as such.
2. **Anomaly detection, not fraud classification.** No labelled fraud dataset
   exists for Indian startups, so the fraud layer detects deviation from normal
   patterns; it does not classify confirmed fraud.
3. **Evaluation horizon.** Startup outcomes resolve over years. Validation is
   against historical held-out data only; nothing here validates a live
   prediction.
4. **Derived financial profiles.** No public dataset contains startup P&L, so
   revenue, burn and runway are *derived from* real funding totals and real
   headcount. This is the single place synthetic values enter the system and it
   is documented in the loader and in `data/raw/README.md`.
5. **Cold network positions.** Brand-new companies have no co-investment history,
   so the network signal correctly returns zero rather than guessing — the same
   limitation the cited paper (arXiv:2511.23364) identifies in its own work.

---

## 6. Data foundation

All seed data is **real and downloaded**, never fabricated:

| Dataset | Records | Role |
|---|---|---|
| Indian startup funding (2015–2021) | ~7,000 rounds | Realistic Indian companies, sectors, cities, funding amounts |
| Y Combinator companies | 6,151 | **The only source of outcome labels anywhere in the seed data** — hence what the model trains on |

Provenance, licensing caveats, and the specific reasons the "real" verification
sources cannot be bulk-collected are documented in `data/raw/README.md`.

---

## 7. Engineering issues found and resolved

Recorded because they demonstrate the system was genuinely tested, not merely
assembled:

1. **Fraud detector flagged 52% of the corpus.** A detector that flags half the
   population produces noise, not a usable review queue. Base rate corrected;
   now 19%.
2. **Founder credibility was a flat 25.0 for every company** — no founder records
   existed, so the dimension contributed nothing to the composite. Fixed; the
   score now spans 29.6–100.
3. **Peer benchmarking returned each company as its own closest match** at 100%
   similarity, caused by a stale in-memory index. Proper invalidation and
   duplicate-name exclusion added.
4. **Null values rendered as the literal text "nan"** in company descriptions,
   originating from the source CSVs. A cleaning pass now covers all free-text fields.
5. **Y Combinator's taxonomy was unusable for investor matching** — a single "B2B"
   category covered 3,140 of 6,151 companies. Remapped onto a granular sector
   taxonomy with AI/ML detected from tags.

---

## 8. Remaining work to reach 100%

| Task | Layer | Est. effort | Adds |
|---|---|---|---|
| OCR + document intelligence for pitch decks | 2 | 2–3 weeks | +8% |
| JWT authentication and role-based access | 1 | 1 week | +5% |
| Manual outcome labelling of 300–500 Indian startups | 3 | 2 weeks | +4% |
| Promote to PostgreSQL + pgvector | — | 1 week | +3% |
| Kafka producer in front of the event endpoint | 4 | 1 week | +3% |
| Neo4j co-investment graph | 4 | 1–2 weeks | +3% |
| User Acceptance Testing with real investors | — | 2 weeks | +2% |

Recommended order: document intelligence first (it is the largest visible gap in
Layer 2), then authentication, then the labelled Indian evaluation set — the
last of these materially strengthens the dissertation's empirical claims.

---

## 9. How to demonstrate the system

```bash
./start.sh          # brings up API on :8000 and UI on :5173
```

Suggested five-minute walkthrough for a review:

1. **Overview** — 9,289 startups scored; score distribution; live alert feed
2. **Discover** — filter by sector, stage, minimum score; hide flagged companies
3. **Startup Detail** — the four score rings, the feature contributions behind
   each, the GST revenue cross-check, and source provenance indicators
4. **Run verification agent** — watch the agent plan its source calls, execute
   them, and rescore the company live
5. **Model** — the system publishing its own AUROC and its own limitations
6. **Feed** — switch between investor personas and observe the ranking change

---

*Prepared at the post-Phase-I implementation checkpoint. The authoritative scope
document remains `VentureIQ_report (2).pdf`; the engineering translation of it,
including the risks identified and mitigated, is `docs/BUILD_PLAN.md`.*
