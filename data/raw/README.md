# Raw seed datasets

These are **bootstrap / prototyping** datasets only — real enough to build and test
pipelines against, not a substitute for the verified, agentic-enrichment data
VentureIQ is meant to produce in production (see `docs/DATA_SCHEMA.md` and
`docs/BUILD_PLAN.md` for why the "real" sources — MCA21, GSTN, LinkedIn — can't be
bulk-collected the same way).

| File | Rows | Period | Source | License / reuse notes |
|---|---|---|---|---|
| `startup_funding_modified.csv` | 3,008 | 2015–2019 | Mirror of the well-known Kaggle "Indian Startup Funding" dataset (originally sudalairajkumar), re-hosted at [blaine12100/Indian-Startup-Funding-Analysis](https://github.com/blaine12100/Indian-Startup-Funding-Analysis) | Community re-upload of a Kaggle CC0-ish dataset; treat as research/prototyping only, re-verify before any commercial use |
| `cleaned_dataset.csv` | 2,840 | 2018–2021 | [iameberedavid/Indian-Start-Up-Funding-Analysis](https://github.com/iameberedavid/Indian-Start-Up-Funding-Analysis) | Same caveat — student EDA repo, no explicit license |
| `startup_funding2021.csv` | 1,209 | 2021 | Same repo as above | Includes `Founders` and `Stage` — useful for Founder Credibility Score prototyping |
| `yc_companies_all.json` | 6,151 | 2005–2026 (all YC batches) | [yc-oss/api](https://github.com/yc-oss/api) — unofficial, auto-updated daily from YC's public Algolia index, MIT-licensed repo | Global, not India-specific, but has **outcome labels** (`status`: Active / Inactive / Acquired / Public) — closest public analogue to the labeled dataset used in Maarouf et al. 2025 (the fused-LLM paper VentureIQ's report cites) |
| `yc_companies_india.json` | 222 | subset of above | Filtered where `all_locations` or `regions` contains "India" | Small — useful for spot checks, not enough alone to train a model |

## India's company registry (bulk, stored outside the repo)

| Dataset | Rows | Updated | Source | License |
|---|---|---|---|---|
| MCA "Registrars of Companies (RoC)-wise Company Master Data" | 36,74,314 | 22 Jul 2026 | Ministry of Corporate Affairs via [data.gov.in](https://www.data.gov.in/resource/registrars-companies-roc-wise-company-master-data) (resource `4dbe5667-7b6b-41d7-82af-211562424d9a`) | [Government Open Data License – India](https://www.data.gov.in/Godl) — attribution required |

Fields: CIN/LLPIN, registered name, status, class, category, authorised and
paid-up capital, registration date, state, RoC, registered office address,
NIC code, industrial classification. No financials and no people.

This is too big for git. `backend/scripts/import_mca_registry.py` downloads it
into `backend/registry.db` (gitignored, separate from the main database so
`bootstrap.py` never wipes it) with a full-text name index. It needs a free
data.gov.in API key in `VIQ_DATA_GOV_IN_KEY`; the public sample key returns
10 rows per call and is rate-limited, which is only enough for single-CIN
lookups. The registry replaces the MCA21 mock during registration.

It is a registry of *companies*, not startups: most rows are traditional
businesses. Records are searchable and claimable, but are not scored or listed
in Discover as startups until a founder registers them.

## Live sources queried at registration time (nothing stored in bulk)

The agentic registration flow (`backend/app/onboarding/`) queries these one
company at a time, only for the company being registered:

| Source | What is read | Access / terms |
|---|---|---|
| The company's own website | Homepage (and `/about` if thin): title, meta description, schema.org `Organization` JSON-LD, outbound profile links | URL supplied by the founder; `robots.txt` honoured; public addresses only; 1.5 MB cap |
| RDAP via [rdap.org](https://rdap.org) | Domain registration date and registrar | Public registry data (ICANN RDAP); registrant personal data is redacted and not used |
| DNS-over-HTTPS ([dns.google](https://developers.google.com/speed/public-dns/docs/doh/json)) | MX records for the website and email domains | Public DNS |
| GitHub REST API | Org profile, public repos; founder user profiles | Public API, 60 req/h unauthenticated (`VIQ_GITHUB_TOKEN` raises it to 5,000) |
| data.gov.in MCA master data API | One company by exact CIN or registered name, when it isn't in the local import | Open government data (GODL-India) |
| RapidAPI `gst-return-status` | One GSTIN: legal name, status, registration date, constitution, state, PAN | Public GST taxpayer register, resold by jamku.app. Free tier 20/min, 1,000/day; it withholds turnover band and filing history ("Available in Paid Version"), which are then reported as unavailable, never shown |
| RapidAPI `linkedin-scraper27` | One founder's profile: headline, roles, years of experience, education | Paid third-party aggregator of scraped LinkedIn data. Needs `VIQ_RAPIDAPI_KEY`; without it the LinkedIn adapter stays mocked |

On the LinkedIn provider: it is an aggregator, not LinkedIn's own API, so
records are stored with a `_provenance` note saying so. It is used to
corroborate a founder's own claim — is this profile the person they say, does it
list this company — and never to mark a *company* field verified. A profile has
no structured "exit" field either, so prior exits stay unknown unless the
founder wrote them into a role description, where they are kept as
self-reported.

Responses are stored per startup as `enrichment_record` rows on submission.

## Why not more / why not the "real" sources

- **Crunchbase**: bulk CSV export requires an Enterprise/Applications Access
  contract; Pro tier caps CSV export at 1,000 rows/month. Scraping violates ToS.
- **MCA21 (company master data)**: `data.gov.in` exposes only a thin catalog
  entry; the actual MCA portal requires per-company lookup, registration, and a
  per-document fee for anything beyond basic fields — there is no bulk/free
  download, which is exactly the friction VentureIQ's "Agentic Enrichment"
  layer is designed to work around one company at a time, not a firehose.
- **GSTN**: no public bulk dataset; GST return data is private to the taxpayer
  and their authorized users (banks/lenders via account-aggregator consent
  flows). Cross-verifying claimed revenue against GSTN requires the startup's
  explicit consent per transaction, not a scrape.
- **LinkedIn / GitHub founder history**: scraping LinkedIn breaks its ToS and
  is the subject of ongoing litigation (hiQ v. LinkedIn); GitHub's API is fine
  for public repo/commit data but rate-limited and only covers technical
  founders. VentureIQ's founder-credibility enrichment should call these
  per-founder at verification time via official APIs (GitHub REST/GraphQL API,
  LinkedIn only via a consented OAuth flow or a licensed data partner such as
  Proxycurl), not as a pre-scraped bulk table.
- **SEBI AIF/VC fund registry**: SEBI publishes the list on its site but not as
  a downloadable CSV; would need a one-time respectful scrape of the SEBI
  intermediary search pages (low row count, ~2,000 funds, refreshed rarely) —
  a good v1.1 task, not done in this pass.

## Regenerating / refreshing

```bash
# Indian funding CSVs (community mirrors of the Kaggle dataset)
curl -sL -o startup_funding_modified.csv \
  https://raw.githubusercontent.com/blaine12100/Indian-Startup-Funding-Analysis/master/startup_funding_modified.csv
curl -sL -o cleaned_dataset.csv \
  https://raw.githubusercontent.com/iameberedavid/Indian-Start-Up-Funding-Analysis/main/cleaned_dataset.csv
curl -sL -o startup_funding2021.csv \
  https://raw.githubusercontent.com/iameberedavid/Indian-Start-Up-Funding-Analysis/main/startup_funding2021.csv

# YC companies (updates daily upstream)
curl -sL -o yc_companies_all.json https://yc-oss.github.io/api/companies/all.json
```

## Suggested next real-data steps (not done here)

1. Kaggle API (`kaggle datasets download -d nikitagajbhiye30/indian-startup-funding-dataset-20102025`)
   for the largest (2010–2025) mirror — needs a free Kaggle account + API token.
2. One-time scrape of the SEBI AIF intermediary list (~2k rows, refresh quarterly).
3. `data.gov.in` API key (free registration) for the Company Master Data
   *catalog* metadata — still not bulk company records, but useful for
   validating CIN formats and registrar/state reference lists.
