"""Bulk founder seeding for the imported corpus.

The seed CSVs mostly lack founder names, and none of them carry the enrichment
fields (prior exits, domain years, GitHub activity) that founder credibility
scores on. Without this step every seeded startup gets the same "no founder data"
score of 25, which makes that whole dimension dead weight in the composite.

So: create founder rows and populate them with the values the *mock* LinkedIn
and GitHub adapters would have returned, and write matching EnrichmentRecord
rows with `is_mock=True` so the provenance is visible in the UI. This is the
bulk equivalent of running the agentic loop over the corpus --- doing it per
startup through the real async loop would take hours for 9k companies and hit
GitHub's rate limit immediately.

These founders are deliberately anonymous. The companies in the corpus are
real, so attaching an invented human name --- and a linkedin.com/in/... link
that goes nowhere --- would state something false about a real company on its
own profile page. The modelled signals stay, under a name no one can mistake
for a person, and the UI labels the block.

Live registrations go through the real path in enrichment/agent.py, where the
founder gives their own name and GitHub is checked for real.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.enrichment.adapters import _seed_for
from app.models import EnrichmentRecord, Founder, Startup

ROLES_SECONDARY = ["CTO", "COO", "Co-Founder & CTO", "Co-Founder", "Chief Product Officer"]


def seed_founders(db: Session, batch_size: int = 1000) -> dict[str, int]:
    startups = db.query(Startup).all()
    n_founders = 0
    n_records = 0

    for i, s in enumerate(startups):
        if s.founders:
            continue

        rng = _seed_for("founders", s.legal_name)
        team = s.employee_count or 0

        # Bigger teams skew toward more co-founders.
        if team > 100:
            count = rng.choices([1, 2, 3], weights=[15, 45, 40])[0]
        elif team > 15:
            count = rng.choices([1, 2, 3], weights=[25, 50, 25])[0]
        else:
            count = rng.choices([1, 2, 3], weights=[40, 45, 15])[0]

        # A company that reached growth stage or exited is more likely to have
        # had experienced founders --- this correlation is what makes founder
        # credibility carry real signal instead of being uniform noise.
        seasoned = s.status in {"acquired", "public"} or s.stage in {"series_b_plus", "growth"}

        linkedin_payload: dict = {}
        github_payload: dict = {}

        for j in range(count):
            # Deliberately NOT a human name. These companies are real, and we
            # did not collect who founded them; inventing "Meera Pillai,
            # Co-Founder of Byju's" states something false about a real
            # company and hangs a dead linkedin.com/in/... link off it. The
            # modelled credibility signals below are still useful, so they
            # stay --- attached to an unmistakably synthetic person.
            name = f"Founder {j + 1} (modelled)"
            has_li = rng.random() > (0.08 if seasoned else 0.22)
            has_gh = rng.random() > (0.45 if seasoned else 0.62)

            if seasoned:
                exits = rng.choices([0, 1, 2], weights=[52, 35, 13])[0]
                years = round(rng.uniform(5.0, 24.0), 1)
            else:
                exits = rng.choices([0, 1, 2], weights=[80, 17, 3])[0]
                years = round(rng.uniform(1.0, 14.0), 1)

            commits = int(rng.lognormvariate(3.6, 1.1)) if has_gh else 0
            followers = int(rng.lognormvariate(3.2, 1.4)) if has_gh else 0
            endorsements = rng.randint(0, 420) if has_li else 0

            f = Founder(
                startup_id=s.startup_id,
                name=name,
                role="Co-Founder & CEO" if j == 0 else rng.choice(ROLES_SECONDARY),
                # No URL and no handle: both would be fabrications pointing at
                # a profile that does not exist. A company whose founders we
                # really did verify (a live registration) is the only one that
                # gets these, and it scores higher for it.
                linkedin_url=None,
                github_username=None,
                prior_exits=exits,
                domain_experience_years=years,
                linkedin_endorsement_count=endorsements,
                github_commit_count_90d=commits,
                github_followers=followers,
                github_contributor_count=rng.randint(1, 40) if has_gh else None,
                linkedin_employment_history=(
                    {
                        "roles": [
                            {
                                "company": f"Prior Co {chr(65 + k)}",
                                "title": rng.choice(
                                    ["Engineer", "Product Manager", "VP Engineering",
                                     "Co-Founder", "Director", "Consultant"]
                                ),
                                "years": round(rng.uniform(0.8, 6.0), 1),
                            }
                            for k in range(rng.randint(1, 4))
                        ]
                    }
                    if has_li
                    else None
                ),
            )
            db.add(f)
            n_founders += 1

            if has_li:
                linkedin_payload[name] = {
                    "prior_exits": exits,
                    "domain_experience_years": years,
                    "endorsement_count": endorsements,
                    "profile_matches_claim": True,
                }
            if has_gh:
                github_payload[name] = {
                    "login": name,
                    "followers": followers,
                    "public_repos": f.github_contributor_count,
                }

        # Provenance rows, so the UI can show these values came from mocked
        # sources rather than verified ones.
        if linkedin_payload:
            db.add(
                EnrichmentRecord(
                    startup_id=s.startup_id,
                    source="linkedin",
                    is_mock=True,
                    status="success",
                    query_params={"legal_name": s.legal_name, "bulk_seed": True},
                    raw_response={
                        "_mock": True,
                        "_why_mock": "bulk-seeded; LinkedIn scraping breaks ToS",
                        "founders": linkedin_payload,
                    },
                )
            )
            n_records += 1
        if github_payload:
            db.add(
                EnrichmentRecord(
                    startup_id=s.startup_id,
                    source="github",
                    is_mock=True,
                    status="success",
                    query_params={"legal_name": s.legal_name, "bulk_seed": True},
                    raw_response={
                        "_mock": True,
                        "_why_mock": "bulk-seeded to avoid GitHub rate limits; live path is real",
                        "founders": github_payload,
                    },
                )
            )
            n_records += 1

        if (i + 1) % batch_size == 0:
            db.commit()

    db.commit()
    return {"founders": n_founders, "enrichment_records": n_records}
