# VentureIQ — Data Schema

Field-level schema for every entity implied by the report (`VentureIQ_report (2).pdf`).
This is the contract between the Startup Pipeline, Investor Pipeline, AI Engine, and
Marketplace layers described in `docs/BUILD_PLAN.md`. Nothing here is implemented yet —
this is the design to build `backend/` models against.

Legend: **PK** primary key · **FK** foreign key · 🔒 not self-reported (must come from
enrichment/verification) · 🧮 derived/computed, never user-entered.

---

## 1. Startup

### 1.1 `startup` (core profile)
| Field | Type | Notes |
|---|---|---|
| `startup_id` | UUID **PK** | |
| `legal_name` | string | as filled by founder |
| `cin` | string, nullable | Corporate Identification Number — 🔒 confirmed against MCA21 |
| `gstin` | string, nullable | 🔒 confirmed against GSTN |
| `stage` | enum(`idea`,`seed`,`series_a`,`series_b_plus`,`growth`) | drives which fields below are shown (Zod/Pydantic conditional schema) |
| `sector` | enum/taxonomy | needs a fixed taxonomy — reuse the `Sector` values seen in the seed CSVs (`data/raw/cleaned_dataset.csv`, `startup_funding2021.csv`) as the v1 taxonomy |
| `sub_vertical` | string | free text or child of `sector` |
| `founded_date` | date | |
| `hq_city` | string | |
| `hq_state` | string | |
| `registered_address` | string | 🔒 confirmed against MCA21 |
| `website` | url | |
| `one_liner` | string | |
| `long_description` | text | feeds RAG embedding + FinBERT/LayoutLM text signal |
| `employee_count` | int | self-reported, cross-checked via LinkedIn company page + GST filings headcount proxy |
| `status` | enum(`active`,`acquired`,`shut_down`,`ipo`) 🧮 | training/eval label, mirrors `status` field in `yc_companies_all.json` |
| `created_at`, `updated_at` | timestamp | |

### 1.2 `startup_financials` (stage-conditional, versioned — one row per submission/quarter)
| Field | Type | Notes |
|---|---|---|
| `financial_id` | UUID **PK** | |
| `startup_id` | FK | |
| `as_of_date` | date | |
| `revenue` | decimal, nullable | null for idea-stage |
| `burn_rate_monthly` | decimal, nullable | null for idea-stage |
| `runway_months` | decimal 🧮 | = cash_balance / burn_rate_monthly |
| `cash_balance` | decimal | |
| `cac` | decimal, nullable | customer acquisition cost |
| `ltv` | decimal, nullable | |
| `tam_usd` | decimal | |
| `sam_usd` | decimal | |
| `active_users` | int, nullable | |
| `mrr` / `arr` | decimal, nullable | |
| `gst_reported_revenue` | decimal 🔒 | pulled via GSTN cross-check, compared to `revenue` — >20% deviation raises a fraud flag (per report §8.1.2) |

### 1.3 `founder`
| Field | Type | Notes |
|---|---|---|
| `founder_id` | UUID **PK** | |
| `startup_id` | FK | |
| `name` | string | |
| `role` | string | CEO/CTO/etc |
| `linkedin_url` | url | |
| `github_username` | string, nullable | |
| `linkedin_employment_history` | jsonb 🔒 | via LinkedIn (consented pull / licensed data partner, not scraped — see `data/raw/README.md`) |
| `prior_exits` | int 🔒 | |
| `domain_experience_years` | decimal 🔒 | |
| `github_commit_count_90d` | int 🔒 | via GitHub REST API |
| `github_contributor_count` | int 🔒 | |
| `linkedin_endorsement_count` | int 🔒 | |

### 1.4 `startup_document`
| Field | Type | Notes |
|---|---|---|
| `document_id` | UUID **PK** | |
| `startup_id` | FK | |
| `doc_type` | enum(`pitch_deck`,`cap_table`,`financial_statement`,`incorporation_cert`,`other`) | |
| `s3_key` | string | raw file in blob storage |
| `ocr_text` | text | Tesseract/PaddleOCR output |
| `layoutlm_entities` | jsonb | spaCy NER + LayoutLM-v3 structured extraction: company names, dates, amounts, table cells |
| `extraction_confidence` | float | |
| `deviation_flags` | jsonb | fields where extracted value differs >20% from form value |
| `uploaded_at` | timestamp | |

### 1.5 `enrichment_record` (agentic — one row per source call)
| Field | Type | Notes |
|---|---|---|
| `enrichment_id` | UUID **PK** | |
| `startup_id` | FK | |
| `source` | enum(`linkedin`,`mca21`,`gstn`,`github`,`whois`, plus onboarding: `website`,`dns`,`email`,`corpus`,`sector_model`,`github_org`,`linkedin_company`,`cin_check`,`gstin_check`,`city_state`) | `whois` is a live RDAP lookup |
| `is_mock` | bool | true only for consent-/fee-gated stand-ins; never counts as verification |
| `query_params` | jsonb | |
| `raw_response` | jsonb | cached for 30 days per report §8.1.3 |
| `status` | enum(`success`,`failed`,`cached_fallback`) | |
| `retrieved_at` | timestamp | |
| `retry_count` | int | exponential backoff, 5 retries max |

### 1.6 `fraud_signal` (AI-generated, one row per detector run)
| Field | Type | Notes |
|---|---|---|
| `signal_id` | UUID **PK** | |
| `startup_id` | FK | |
| `detector` | enum(`isolation_forest`,`autoencoder`) | |
| `anomaly_score` | float 🧮 | |
| `reconstruction_error` | float, nullable 🧮 | autoencoder only |
| `flagged_fields` | jsonb | e.g. `["revenue_vs_gstn", "burn_rate_industry_norm"]` |
| `reviewed_by_human` | bool | report §8.1.5 — algorithms flag, humans decide |
| `run_at` | timestamp | |

### 1.6b `startup_document` (filled by the OCR layer)
`layoutlm_entities` holds the extracted fields, `deviation_flags` the checks run
against the MCA registry and the profile, and `extraction_confidence` the OCR
confidence. See `app/documents/`.

### 1.7 `onboarding_session` (agentic registration, before a `startup` exists)
| Field | Type | Notes |
|---|---|---|
| `session_id` | UUID **PK** | |
| `status` | enum(`running`,`ready`,`submitted`) | |
| `inputs` | jsonb | what the founder typed: website, work email, name, stage; optional CIN, GSTIN, GST consent |
| `evidence` | jsonb | field → list of `{source, label, kind, value, note}`; `kind` ∈ `network`,`dataset`,`local`,`mock` |
| `overrides` | jsonb | founder edits and conflict resolutions (`accept` / `keep`) |
| `tool_results` | jsonb | per-step summary, payload, timing, and agent facts |
| `events` | jsonb | the streamed trace (plans, reasons, findings) — kept for audit |
| `startup_id` | FK, nullable | set on submit |
| `created_at` / `updated_at` | timestamp | |

Field statuses derived from `evidence` (not stored): `verified` (an independent
source agrees — live lookup or public dataset), `fetched`, `claimed`,
`conflict`, `disputed` (founder kept a value a source contradicts → a
`fraud_signal` rule row on submit), `missing`. Mocked and locally computed
evidence can support a value but never verify it.

### 1.8 `company` (India company registry — separate file `backend/registry.db`)
Imported from MCA Company Master Data; read-only reference data, not a startup profile.
| Field | Type | Notes |
|---|---|---|
| `cin` | text **PK** | CIN, or LLPIN for LLPs (`is_llp`) |
| `name` | text | registered name (FTS5-indexed as `company_fts`) |
| `status` | text | Active, Strike Off, Under liquidation, … — non-Active is flagged at registration |
| `class`, `category`, `sub_category` | text | |
| `authorized_capital`, `paidup_capital` | float (INR) | |
| `registered` | date | incorporation date → `founded_year` evidence |
| `state`, `roc`, `address` | text | registered office |
| `city` | text 🧮 | parsed from `address` |
| `nic_code`, `industry` | text | |
| `listed` | text | |

A `startup` is linked to a registry company by `startup.cin`.

---

## 1b. Accounts

### `app_user`
| Field | Type | Notes |
|---|---|---|
| `user_id` | UUID **PK** | |
| `email` | text, unique | lower-cased on write |
| `password_hash` | text | bcrypt; null for future OAuth-only accounts |
| `name` | text | |
| `role` | enum(`investor`,`founder`) | re-read from here on every request, never trusted from the token |
| `auth_provider`, `provider_subject` | text | seam for Google/LinkedIn OAuth |
| `investor_id` | FK, nullable | investors own exactly one profile |
| `is_active`, `created_at`, `last_login_at` | | |

### `kyc_case`
| Field | Type | Notes |
|---|---|---|
| `case_id` | UUID **PK** | |
| `user_id` | FK | one case per attempt; the newest is authoritative |
| `investor_id` | FK, nullable | mirrors the decision onto `investor.kyc_status` |
| `pan`, `legal_name` | text | as submitted |
| `document_path`, `document_type` | text | the ID document, read by OCR |
| `checks` | jsonb | each automated check with `passed` / `failed` / `review` |
| `status` | enum(`submitted`,`passed_checks`,`failed_checks`,`verified`,`rejected`) | only a human moves it to `verified` |
| `reviewer_note`, `reviewed_by`, `decided_at` | | written to the audit log too |

### `offer` (marketplace — SIMULATED)
| Field | Type | Notes |
|---|---|---|
| `offer_id` | UUID **PK** | |
| `listing_id`, `investor_id`, `user_id` | FK | |
| `amount`, `equity_pct`, `message` | | |
| `status` | enum(`offered`,`rofr_window`,`declined`,`settled_simulated`) | no money moves at any transition |
| `compliance` | jsonb | every rule evaluated for this offer, with its verdict |
| `rofr_expires_at` | timestamp | settlement is refused until it passes |

### `watchlist_item`
| Field | Type | Notes |
|---|---|---|
| `item_id` | UUID **PK** | |
| `user_id`, `startup_id` | FK | unique together |
| `note` | text | private to the user |
| `stage` | enum(`watching`,`contacted`,`passed`) | |
| `created_at` | timestamp | saving also writes a `save` behavioural event |

---

## 2. Investor

### 2.1 `investor`
| Field | Type | Notes |
|---|---|---|
| `investor_id` | UUID **PK** | |
| `investor_type` | enum(`angel`,`vc_fund`,`family_office`) | |
| `firm_name` | string, nullable | |
| `sebi_registration_no` | string, nullable 🔒 | for `vc_fund` — cross-check against SEBI AIF registry |
| `kyc_status` | enum(`pending`,`verified`,`rejected`) | |
| `accredited_investor` | bool | SEBI accredited-investor rule flag |

### 2.2 `investor_preference` (structured onboarding — report Fig. "Structured Investor Onboarding")
| Field | Type | Notes |
|---|---|---|
| `investor_id` | FK | |
| `ticket_size_min`, `ticket_size_max` | decimal | |
| `stage_preference` | enum[] | |
| `preferred_sectors` | enum[] | |
| `geographic_preference` | string[] | |
| `risk_tolerance` | enum(`low`,`medium`,`high`) | |

### 2.3 `behavioral_event` (Kafka stream → `event_log` table, report §8.2.2)
| Field | Type | Notes |
|---|---|---|
| `event_id` | UUID **PK** | |
| `investor_id` | FK | |
| `startup_id` | FK | |
| `event_type` | enum(`view`,`save`,`dismiss`,`time_spent`,`document_view`,`interest_expressed`) | |
| `event_value` | jsonb | e.g. `{"seconds": 42}` for `time_spent` |
| `occurred_at` | timestamp | |

### 2.4 `network_edge` (Neo4j — co-investment graph, report §8.2.4)
| Field | Type | Notes |
|---|---|---|
| `(:Investor)-[:CO_INVESTED_WITH {round_id, date}]->(:Investor)` | graph edge | |
| `(:Investor)-[:INVESTED_IN {amount, round_stage, date}]->(:Startup)` | graph edge | |
| `(:Startup)-[:SAME_SECTOR]->(:Startup)` | graph edge | for RAG benchmarking neighbor lookup |

---

## 3. AI Output

### 3.1 `score` (one row per startup per scoring run — 4 independent + 1 composite)
| Field | Type | Notes |
|---|---|---|
| `score_id` | UUID **PK** | |
| `startup_id` | FK | |
| `growth_potential_score` | float 0–100 🧮 | revenue trajectory, user growth, TAM% captured, FinBERT market-claim sentiment |
| `risk_level_score` | float 0–100 🧮 | burn/runway, RAG-retrieved competitive density, regulatory flag |
| `fraud_likelihood_score` | float 0–100 🧮 | from `fraud_signal` |
| `founder_credibility_score` | float 0–100 🧮 | exits, domain years, LinkedIn/GitHub signals |
| `composite_score` | float 0–100 🧮 | weighted aggregate — weights are a v1 config, not learned jointly (report §8.3: combining too early hurts, per Maarouf et al. ablation) |
| `shap_top_features` | jsonb | per dimension: `{method, features[]}`. `method` names what produced the attribution — `shap:<model>` for exact Shapley values from a trained tree model, `rules` for an additive rule composition. Each feature carries `contribution` in score points, `direction`, a readable `label`, and, for SHAP rows, the raw `shap_value` in the model's own units (log-odds for growth, path length for the isolation forest) |
| `rationale` | jsonb | generated plain-English text per score |
| `confidence` | string | `high` / `low` — low when the peer cohort is below `min_cohort_size` |
| `cohort_size` | int | peers the percentile read is based on |
| `model_version` | string | |
| `computed_at` | timestamp | |
| `is_current` | bool | scoring appends rather than overwrites, so a startup keeps its history; exactly one row per startup is current. **SQL that joins this table must filter on it**, or a rescored startup is counted several times in aggregates and sorted on an arbitrary old row |

### 3.1b `mentorship_offer`
Someone offering time rather than money, and the founder's answer. Deliberately
outside the marketplace: advice is not a security, so no KYC, accreditation or
right-of-first-refusal applies. Visibility is the founder's, taken at the moment
they accept.

| Field | Type | Notes |
|---|---|---|
| `offer_id` | UUID **PK** | |
| `startup_id` | FK | |
| `mentor_user_id` | FK → `app_user` | unique together with `startup_id`: one live offer per pair |
| `message` | text | the mentor's pitch — visible only to the two parties, never on the public profile |
| `focus_areas` | jsonb | from a fixed list (Go-to-market, Hiring, Pricing, …) so a founder can triage a queue |
| `hours_per_month` | int | what they are committing to |
| `status` | string | `offered` → `accepted` \| `declined`, or `withdrawn` by the mentor |
| `public` | bool | **the consent gate.** An accepted mentor appears on the company's public profile only when this is true; the founder can flip it at any time |
| `founder_note` | text | private reply |
| `created_at` / `decided_at` | timestamp | |

### 3.2 `match_recommendation`
| Field | Type | Notes |
|---|---|---|
| `investor_id` | FK | |
| `startup_id` | FK | |
| `lightfm_score` | float 🧮 | collaborative filtering |
| `network_score` | float 🧮 | Neo4j graph proximity |
| `rag_similar_startups` | UUID[] | top-10 nearest neighbors from Pinecone, same stage+sector, ≤24mo old |
| `rank` | int | final position in personalized feed |

---

## 4. Marketplace & Compliance

| Entity | Key fields |
|---|---|
| `listing` | `listing_id`, `startup_id`, `ask_amount`, `fair_value_estimate` 🧮, `status`(`open`,`matched`,`closed`) |
| `transaction` | `transaction_id`, `listing_id`, `investor_id`, `amount`, `escrow_status`(`held`,`released`,`refunded`), `ownership_pct` 🧮 |
| `kyc_record` | `investor_id`/`startup_id`, `document_type`, `verification_status`, `verified_at` |
| `cap_table_entry` | `startup_id`, `holder_id`, `share_class`, `shares`, `pct_ownership` 🧮, `as_of_date` |
| `audit_log` | `actor_id`, `action`, `entity_type`, `entity_id`, `before`, `after`, `timestamp` — append-only, report §7 Layer 5 |

---

## 5. Mapping seed data → schema (what `data/raw/` actually gives you today)

| Seed column | Maps to |
|---|---|
| `Startup Name` / `Company/Brand` | `startup.legal_name` |
| `Industry Vertical` / `Sector` | `startup.sector` |
| `SubVertical` | `startup.sub_vertical` |
| `City Location` / `HeadQuarter` | `startup.hq_city` |
| `Investors Name` / `Investor` | seed for `investor.firm_name` (dedupe needed — same firm spelled differently across rows) |
| `Amount in USD` / `Amount($)` | seed for a synthetic `funding_round` fact table (not modeled above yet — add if you need round history) |
| `Founders` (2021 file only) | seed for `founder.name` |
| `Stage` (2021 file only) | `startup.stage` |
| `status` (YC json) | `startup.status` — **the only field in any seed source that is an actual outcome label** |
| everything else (🔒 fields) | **not present in any seed dataset** — these only exist once the agentic enrichment layer is actually built and pointed at live sources |

The practical implication: seed data is enough to prototype the schema, the forms, the
sector taxonomy, and a first-pass growth/outcome model (via the YC `status` labels). It
is **not** enough to prototype fraud detection or founder-credibility scoring, because
those need the 🔒 fields, which need the enrichment layer built first. See
`docs/BUILD_PLAN.md` §Problem 3.
