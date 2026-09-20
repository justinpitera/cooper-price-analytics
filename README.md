# Cooper Price Analytics

A data analyst portfolio project examining published hospital charges at Cooper University Hospital and Cooper University Hospital Cape Regional in New Jersey.

**Primary question:** Within a carefully defined group of Cooper outpatient services, how much do published negotiated dollar charges vary across payer-plan combinations, and how much of the file supports that comparison?

The intended audience is a hospital pricing or contracting analyst looking for services to investigate. The deliverable will be a SQL analysis, a small dashboard, and a short findings memo with coverage and limitations. Published charges are not patient out-of-pocket estimates; Cooper explains this distinction on its [pricing and transparency page](https://www.cooperhealth.org/patients-and-visitors/financial-and-insurance-information/pricing-and-transparency).

## Current status

**Completed:** full-file structural and field profiling, a saved audit artifact, parser regression tests, and local PostgreSQL and Metabase configuration.

**Planned:** transformation and database loading, validated SQL comparisons, dashboard, and findings memo. The repository does not yet contain a finished pricing analysis.

### What the audit established

These observations describe the local snapshots identified by SHA-256 in [profile_summary.json](docs/profile_summary.json).

| Measure | Cooper | Cape Regional |
| --- | ---: | ---: |
| Source update date | 2026-06-23 | 2026-07-01 |
| Charge records | 25,654 | 13,702 |
| Charge columns | 395 | 350 |
| Payer-plan combinations in headers | 42 | 37 |
| Negotiated-dollar cells populated | 27.43% | 27.43% |
| Records repeating a candidate service key, after its first occurrence | 1,143 | 2,439 |

The percentage denominator is all source rows × payer-plan combinations within each file. Blank dollar cells can have percentage or algorithm charges, so this is dollar coverage, not a missing-data error rate. The repeated keys mean codes and service attributes alone cannot safely be used as a unique row ID. See the [data profile](docs/data_profile.md) for definitions and limitations.

## Analysis scope

Start with **Cooper outpatient facility services with a primary CPT code and no drug measurement fields or NDC code**. Compare positive negotiated dollar charges only within the same source service row and compatible payment basis. The first pass will use entries marked `fee schedule`; review notes and modifiers before including a row. Keep all excluded data for coverage reporting.

Answer three questions:

1. What share of the selected cohort has at least two comparable payer-plan dollar amounts?
2. Which eligible service rows have the largest dollar spread and highest maximum/minimum ratio? Show the number of plans and distinct payers behind each result.
3. How do eligible negotiated amounts compare with the same row's gross and discounted cash charges?

**Extension:** compare facilities only after validating one-to-one service matches, payer-plan mappings, and payment basis. Shared codes or payer names alone do not establish equivalence.

See [analysis_plan.md](docs/analysis_plan.md) for the proposed table grain, metric formulas, exclusions, and completion criteria. This project will not infer hospital profitability, actual patient savings, service volume, quality of care, or statewide price levels from these two files.

## Reproduce the audit

Run commands from the repository root. The project environment uses Python 3.14 and `uv`; Docker is needed only for the database/dashboard stage. The profiler itself uses Python's standard library.

```bash
uv sync --locked
mkdir -p data/raw
```

Download the two machine-readable files linked under **Chargemaster Machine Readable File** on Cooper's [source page](https://www.cooperhealth.org/patients-and-visitors/financial-and-insurance-information/pricing-and-transparency):

| Download | Save as |
| --- | --- |
| [Cooper University Hospital CSV](https://request.cooperhealth.org/financial/210634462_Cooper-University-Hospital_standardcharges.csv) | `data/raw/cooper.csv` |
| [Cape Regional CSV](https://request.cooperhealth.org/financial/210662542_Cooper-University-Hospital-Cape-Regional_standardcharges.csv) | `data/raw/cape_regional.csv` |

Raw files are excluded from Git. Record the actual download time for any new snapshots; the original copies' download times were not recorded. These URLs can change in place. A new download may produce different results; compare hashes before treating it as the same snapshot.

```bash
uv run python scripts/profile_raw_data.py --output data/processed/profile_summary.json
uv run python -m unittest discover -s tests -v
```

The committed baseline is `docs/profile_summary.json`. New runs go into ignored `data/processed/` so you can compare before replacing the baseline. The report records source URLs, hashes, metadata, per-column coverage, numeric checks, payer-plan inventories, categories, and duplicate-key checks. `profiled_at_utc` will differ between runs even for identical inputs.

The profiler fails on unreadable files, unsupported headers, or CSV parsing errors. Wrong-width records are counted in the report and cause a nonzero exit; field statistics exclude those records. Other quality observations require review even when the command succeeds. This is an analytical audit, not a CMS compliance certification.

## Local database and dashboard

The profiler works without these services. Start PostgreSQL and Metabase together:

```bash
cp .env.example .env
# Review local credentials before the first database startup.
docker compose up -d
```

PostgreSQL is exposed on `127.0.0.1:5432`. Default local credentials and database name are in `.env.example`. Images are pinned to the digests inspected during this review; upgrade deliberately. Changing credentials in `.env` does not change credentials already stored in an existing database volume.

Project tables must use the **`analytics` schema**. Metabase's application tables use `public` in the same database. These namespaces keep table names separate; they do not provide security isolation. The init SQL creates `analytics` on a fresh volume. For an existing volume, apply the same idempotent script:

```bash
docker compose exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < docker/postgres/init/001_analytics.sql
```

Metabase starts after PostgreSQL passes its health check. For database-only work, use `docker compose up -d postgres`.

Open `http://localhost:3000`. When adding the analysis database in Metabase, use host `postgres`, port `5432`, the configured database credentials, and restrict schema discovery to `analytics`. Inside Docker, `localhost` points to the Metabase container. A loader and analysis tables still need to be implemented before charts can be built.

The named volume persists database and Metabase application data. Use `docker compose stop` to stop services while retaining it. Do not delete the volume to apply the schema script. Compose file changes take effect when services are recreated; editing the file alone does not reconfigure already running containers.

## Repository guide

| Path | Purpose |
| --- | --- |
| [docs/data_profile.md](docs/data_profile.md) | Measured observations and unresolved data issues |
| [docs/profile_summary.json](docs/profile_summary.json) | Generated baseline audit, including snapshot hashes |
| [docs/analysis_plan.md](docs/analysis_plan.md) | Proposed model, comparison rules, and milestones |
| [docs/project_review.md](docs/project_review.md) | Review findings, fixes, and remaining work |
| [scripts/profile_raw_data.py](scripts/profile_raw_data.py) | Full-file profiler |
| [tests/test_profile_raw_data.py](tests/test_profile_raw_data.py) | Parser and interpretation regression checks |
| [compose.yml](compose.yml) | Local PostgreSQL and Metabase |

Python handles ingestion and validation; PostgreSQL will hold the analysis logic; Metabase will present the results. Polars and psycopg are installed for the planned loading stage, but that stage is not implemented yet.
