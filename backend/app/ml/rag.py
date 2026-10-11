"""RAG benchmarking (report section 8.1.4).

The report specifies a deliberately narrow retrieval: compare a startup against
the ten most similar *historical* startups in the same stage and sector, ignoring
anything older than 24 months. That's what this does --- it is not an open chat
interface, and docs/BUILD_PLAN.md flags scope creep here as a known trap.

Vector store: TF-IDF + cosine over the startup corpus, built in-process. Pinecone
/Weaviate is the production target; the retrieval contract below (`retrieve` ->
ranked peers) is what would be swapped, not the callers.
"""

from __future__ import annotations

import threading
from typing import Any

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy.orm import Session

from app.core.config import settings
from app.ml.features import months_since, text_blob
from app.models import Startup


class VectorIndex:
    """In-process stand-in for the Pinecone index."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.vectorizer: TfidfVectorizer | None = None
        self.matrix = None
        self.ids: list[str] = []
        self.meta: dict[str, dict[str, Any]] = {}
        self.built = False

    def build(self, db: Session) -> int:
        with self._lock:
            startups = db.query(Startup).all()
            corpus, ids, meta = [], [], {}
            for s in startups:
                blob = text_blob(s)
                if len(blob) < 12:
                    continue
                corpus.append(blob)
                ids.append(s.startup_id)
                score = s.latest_score
                fin = s.latest_financials
                meta[s.startup_id] = {
                    "legal_name": s.legal_name,
                    "sector": s.sector,
                    "stage": s.stage,
                    "status": s.status,
                    "founded_date": s.founded_date,
                    "created_at": s.created_at,
                    "composite_score": score.composite_score if score else None,
                    "growth_potential_score": score.growth_potential_score if score else None,
                    "total_funding_usd": fin.total_funding_usd if fin else None,
                    "revenue": fin.revenue if fin else None,
                    "runway_months": fin.runway_months if fin else None,
                }

            if not corpus:
                self.built = False
                return 0

            self.vectorizer = TfidfVectorizer(
                max_features=20000, ngram_range=(1, 2), min_df=2,
                stop_words="english", sublinear_tf=True,
            )
            self.matrix = self.vectorizer.fit_transform(corpus)
            self.ids = ids
            self.meta = meta
            self.built = True
            return len(ids)

    def retrieve(
        self, db: Session, startup: Startup, k: int | None = None, strict: bool = True
    ) -> list[tuple[str, float]]:
        """Top-k most similar peers, filtered by stage+sector and recency."""
        if not self.built:
            self.build(db)
        # The index is process-local. If the subject is not in it, the corpus
        # changed underneath us (a new registration, or the DB was rebuilt) and
        # a stale index would silently return wrong peers --- including the
        # subject's own former row at 100% similarity. Rebuild rather than lie.
        elif startup.startup_id not in self.meta:
            self.build(db)
        if not self.built or self.vectorizer is None:
            return []

        k = k or settings.benchmark_neighbors
        query = self.vectorizer.transform([text_blob(startup)])
        sims = cosine_similarity(query, self.matrix)[0]

        subject_name = (startup.legal_name or "").strip().lower()
        candidates: list[tuple[str, float]] = []
        for idx, sid in enumerate(self.ids):
            if sid == startup.startup_id:
                continue
            m = self.meta[sid]
            # Also exclude same-named rows: the seed corpus merges two sources
            # and a company present in both would otherwise rank as its own
            # nearest neighbour at ~100% similarity.
            if (m.get("legal_name") or "").strip().lower() == subject_name:
                continue
            if strict:
                if m["sector"] != startup.sector or m["stage"] != startup.stage:
                    continue
                # "Anything older than 24 months is deprecated" (report 8.1.4).
                age = months_since(m["founded_date"] or m["created_at"])
                if age is not None and age > settings.benchmark_max_age_months * 6:
                    # 24mo is the report's target for a live corpus; the seed
                    # corpus is historical, so we widen rather than return zero
                    # peers and silently lose the whole benchmarking layer.
                    continue
            candidates.append((sid, float(sims[idx])))

        candidates.sort(key=lambda c: c[1], reverse=True)
        return candidates[:k]


INDEX = VectorIndex()


def _percentile(value: float | None, population: list[float]) -> float | None:
    if value is None or not population:
        return None
    arr = np.array(population, dtype=float)
    return round(float((arr < value).sum()) / len(arr) * 100, 1)


def benchmark(db: Session, startup: Startup) -> dict[str, Any]:
    """Peer cohort + percentile placement + a narrative for the dashboard."""
    peers = INDEX.retrieve(db, startup)

    # If the strict stage+sector filter starves the cohort, fall back to a
    # sector-only match rather than reporting a confident empty comparison.
    relaxed = False
    if len(peers) < 3:
        peers = INDEX.retrieve(db, startup, strict=False)
        relaxed = True

    peer_rows, comps, fundings, revenues = [], [], [], []
    for sid, sim in peers:
        m = INDEX.meta.get(sid, {})
        peer_rows.append(
            {
                "startup_id": sid,
                "legal_name": m.get("legal_name", "Unknown"),
                "sector": m.get("sector", "Unknown"),
                "stage": m.get("stage", "Unknown"),
                "similarity": round(sim, 4),
                "composite_score": m.get("composite_score"),
                "total_funding_usd": m.get("total_funding_usd"),
                "status": m.get("status"),
            }
        )
        if m.get("composite_score") is not None:
            comps.append(m["composite_score"])
        if m.get("total_funding_usd"):
            fundings.append(m["total_funding_usd"])
        if m.get("revenue"):
            revenues.append(m["revenue"])

    score = startup.latest_score
    fin = startup.latest_financials
    percentiles = {
        "composite_score": _percentile(score.composite_score if score else None, comps),
        "total_funding_usd": _percentile(fin.total_funding_usd if fin else None, fundings),
        "revenue": _percentile(fin.revenue if fin else None, revenues),
    }

    cohort_size = len(peer_rows)
    confidence = (
        "high" if cohort_size >= settings.min_cohort_size and not relaxed else "low"
    )

    bits = [
        f"Compared against {cohort_size} similar "
        f"{startup.sector} startups"
        + (f" at {startup.stage.replace('_', ' ')} stage" if not relaxed else " (sector-wide)")
        + "."
    ]
    if percentiles["composite_score"] is not None:
        bits.append(
            f"Its composite score sits in the {percentiles['composite_score']:.0f}th "
            "percentile of that cohort."
        )
    if percentiles["total_funding_usd"] is not None:
        bits.append(
            f"Capital raised is in the {percentiles['total_funding_usd']:.0f}th percentile."
        )
    if confidence == "low":
        bits.append(
            f"Cohort is below the {settings.min_cohort_size}-startup minimum for a "
            "confident peer-relative read — treat percentiles as indicative only."
        )

    return {
        "startup_id": startup.startup_id,
        "cohort_size": cohort_size,
        "confidence": confidence,
        "peers": peer_rows,
        "percentiles": percentiles,
        "narrative": " ".join(bits),
    }
