# Cooper Price Analytics

My first data analysis project: exploring published hospital prices at Cooper University Hospital in New Jersey. Cape Regional's data is also loaded for later exploration.

**The question:** For the same outpatient service at Cooper, how much do listed prices vary between insurance plans?

Python loads the CSV files, PostgreSQL stores the data and runs SQL, and Metabase displays tables and charts. Data loading is built; the first analysis query is a starting point. The dashboard and written findings are still to do.

## Get started

You need [uv](https://docs.astral.sh/uv/getting-started/installation/) for Python and [Docker Compose](https://docs.docker.com/compose/install/) for the database. Run these commands in the project folder.

### 1. Get the data

Download these files and save them with the names below. If they're already in `data/raw/`, keep your existing copies.

| Download | Save as |
| --- | --- |
| [Cooper CSV](https://request.cooperhealth.org/financial/210634462_Cooper-University-Hospital_standardcharges.csv) | `data/raw/cooper.csv` |
| [Cape Regional CSV](https://request.cooperhealth.org/financial/210662542_Cooper-University-Hospital-Cape-Regional_standardcharges.csv) | `data/raw/cape_regional.csv` |

These are public files from [Cooper's pricing page](https://www.cooperhealth.org/patients-and-visitors/financial-and-insurance-information/pricing-and-transparency). New downloads may contain updated data. The CSVs stay on your computer and are excluded from Git.

### 2. Start the tools and load the data

```bash
uv sync --locked
# First setup only: copy the settings if you don't already have .env.
cp -n .env.example .env
docker compose up -d --wait
uv run python scripts/load_data.py
```

The loader creates the tables, checks both files, and imports them. This can take a few minutes. Running it again with the same files won't duplicate the data. A failed import rolls back that file.

### 3. Open Metabase

Go to **http://localhost:3000** and finish its setup. Add a PostgreSQL database using these defaults (or your values from `.env`):

| Setting | Value |
| --- | --- |
| Host | `postgres` |
| Port | `5432` |
| Database | `cooper` |
| Username | `cooper` |
| Password | `cooperpass` |
| Schema, if asked | `analytics` |

Use `postgres` as the host because Metabase runs inside Docker. The separate `metabase` database stores dashboard settings; the hospital data is in `cooper`.

### 4. Run your first queries

In Metabase, open **New → SQL query** and choose the Cooper database. Paste in each file's contents and run it:

1. [sql/check_load.sql](sql/check_load.sql) — compare loaded row counts with expected counts. Each actual/expected pair should match.
2. [sql/price_spread.sql](sql/price_spread.sql) — explore the difference between the lowest and highest listed plan prices for each selected service.

For the saved CSV versions, expect **39,356 service rows** and **1,584,442 service/plan rows** across both hospitals. Many plan prices are blank; those rows are kept so we can measure how much data is available.

**Your next step:** pick one result from `price_spread.sql`. Understand its service description, minimum price, maximum price, and plan count before making a chart. A ratio of `3` means the highest listed price is three times the lowest.

## Where things live

| File or folder | Purpose |
| --- | --- |
| `data/raw/` | Original CSV downloads |
| `data/processed/` | Generated reports and local backups |
| `scripts/load_data.py` | Load CSVs into PostgreSQL; calls the profiler first |
| `scripts/profile_raw_data.py` | Check file structure, blanks, numbers, and repeated codes |
| `sql/schema.sql` | Define the tables; setup and the loader run this automatically |
| `sql/check_load.sql` | Check how many rows were loaded |
| `sql/price_spread.sql` | First analysis query; start reading SQL here |
| [docs/data_notes.md](docs/data_notes.md) | Table meanings, comparison rules, and next steps |
| `docs/profile_summary.json` | Saved detailed data report; reference only |
| `compose.yml` and `docker/` | Start PostgreSQL and Metabase |

## A few things to know

- Published prices **aren't a patient's bill**. Insurance coverage and other factors affect what someone pays.
- The query compares selected outpatient CPT services (CPT is a procedure code system). Review notes and payment terms before treating price differences as findings.
- A blank price means missing, not free. The same procedure code can appear on different service rows.
- Stop the tools with `docker compose stop`; start again with `docker compose up -d --wait`. Your database is saved. **`docker compose down -v` deletes the saved databases and dashboards.**
- If loading says “connection refused,” check `docker compose ps` and wait for PostgreSQL to be healthy. Changing `.env` credentials doesn't change an existing database's password.

To check the CSVs without starting the database:

```bash
uv run python scripts/profile_raw_data.py --output data/processed/profile_summary.json
```
