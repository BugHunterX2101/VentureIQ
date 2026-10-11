"""Application configuration.

Dev defaults to SQLite so the whole stack runs with zero setup. Set
VIQ_DATABASE_URL to a Postgres DSN to promote to the stack described in the
report (docs/BUILD_PLAN.md Problem 5 explains why we stage this rather than
running five storage systems from day one).
"""

from pathlib import Path

from pydantic_settings import BaseSettings

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent
DATA_RAW = REPO_ROOT / "data" / "raw"
ARTIFACTS = BACKEND_DIR / "artifacts"


class Settings(BaseSettings):
    app_name: str = "VentureIQ API"
    version: str = "0.1.0"

    database_url: str = f"sqlite:///{BACKEND_DIR / 'ventureiq.db'}"

    # Enrichment. GitHub is the one source we can legitimately call for real
    # (public API, no consent flow). The rest ship as mock adapters --- see
    # data/raw/README.md for why MCA21/GSTN/LinkedIn cannot be bulk-collected.
    github_token: str | None = None
    # data.gov.in API key for the MCA company master data (free registration).
    # Without one the public sample key is used: 10 records per call, enough
    # for single-CIN lookups but not for the bulk registry import.
    data_gov_in_key: str | None = None
    # RapidAPI key for founder LinkedIn profiles. Without it the LinkedIn
    # adapter stays mocked; see app/enrichment/linkedin.py for provenance.
    rapidapi_key: str | None = None
    linkedin_api_host: str = "linkedin-scraper27.p.rapidapi.com"
    linkedin_api_path: str = "/profile/detail"
    linkedin_api_param: str = "username"
    # GST taxpayer search vendor (optional). Public register data only; returns
    # and turnover stay consent-gated and mocked.
    # A GST vendor can have its own key; otherwise the shared RapidAPI key is used.
    gst_return_status_api_key: str | None = None
    gst_api_host: str | None = None
    gst_api_path: str = "/free/gstin/{gstin}"
    gst_api_param: str | None = None
    # Paid quota: cache profiles hard, and stop before the monthly cap.
    cache_db_path: str = str(BACKEND_DIR / "cache.db")
    linkedin_cache_days: int = 90
    rapidapi_monthly_budget: int = 45

    # Auth. Set VIQ_JWT_SECRET in deployment; locally a secret is generated
    # into backend/artifacts/ on first use so logins survive restarts.
    jwt_secret: str | None = None
    # Google sign-in. The redirect URI must match the one registered in the
    # Google Cloud console exactly, including the scheme and port.
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str = "http://localhost:8000/api/auth/google/callback"
    frontend_url: str = "http://localhost:5173"
    jwt_expire_minutes: int = 60 * 24 * 7
    # The MCA registry lives in its own file so scripts/bootstrap.py (which
    # rebuilds the main database) never wipes a multi-lakh import.
    registry_db_path: str = str(BACKEND_DIR / "registry.db")
    enrichment_cache_days: int = 30
    enrichment_max_retries: int = 5

    # Fraud detection: a startup whose form value and extracted/enriched value
    # differ by more than this fraction gets flagged (report section 8.1.2).
    deviation_threshold: float = 0.20

    # RAG benchmarking: compare against N most-similar startups, same stage and
    # sector, no older than this (report section 8.1.4).
    benchmark_neighbors: int = 10
    benchmark_max_age_months: int = 24

    # Below this cohort size the peer-relative scores are not trustworthy and
    # we mark the score low-confidence (docs/BUILD_PLAN.md Problem 4).
    min_cohort_size: int = 20

    # Shapley attributions for the two trained models. `shap` pulls in numba,
    # which costs roughly 200 MB of resident memory the first time it is
    # imported --- more than a 512 MB instance can spare on top of the models
    # and the retrieval index. Turn it off there (VIQ_ENABLE_SHAP=false) and
    # scores still compute; they report the prediction instead of decomposing it.
    enable_shap: bool = True

    # Deployed frontends: set VIQ_CORS_ORIGINS='["https://your-app.vercel.app"]'.
    # The regex additionally lets Vercel preview URLs through.
    cors_origin_regex: str | None = r"https://.*\.vercel\.app"
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
    ]

    # backend/.env, wherever the server is started from. See .env.example.
    model_config = {"env_prefix": "VIQ_", "env_file": BACKEND_DIR / ".env", "extra": "ignore"}


settings = Settings()
ARTIFACTS.mkdir(parents=True, exist_ok=True)
