# Prospect Playground

Scheduled lead pipeline and internal dashboard for an NIL agency. Prototype.

## Prerequisites

- Python 3.11
- PostgreSQL 15
- Node.js 18+ with [pnpm](https://pnpm.io/) (via Corepack)
- [uv](https://docs.astral.sh/uv/)

## Setup

1. Copy environment variables and fill in real values:

   ```bash
   cp .env.example .env
   cp frontend/.env.example frontend/.env.local
   ```

2. Create a PostgreSQL 15 database and set `DATABASE_URL` in `.env`.

3. Install Python dependencies and run the initial migration:

   ```bash
   uv sync
   uv run alembic upgrade head
   ```

4. Install frontend dependencies:

   ```bash
   cd frontend
   pnpm install
   ```

5. Type-check the backend:

   ```bash
   uv run mypy backend/
   ```

## Environment variables

Set these in the repo-root `.env`. The backend rejects unknown keys (`extra = "forbid"`), so do not put `API_URL` there.

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | SQLAlchemy connection string, `postgresql+psycopg://USER:PASSWORD@localhost:5432/prospect_playground` |
| `ANTHROPIC_API_KEY` | Claude API key for policy diffs, staff extraction, logo vision, and score rationales |
| `CONTACT_EMAIL` | Email included in the crawler User-Agent |
| `TARGET_STATES` | Comma-separated US state codes to collect (default `VA`) |
| `PROPUBLICA_SEARCH_URL` | ProPublica Nonprofit Explorer search endpoint |
| `PROPUBLICA_ORGANIZATION_URL` | ProPublica org detail endpoint; use `{ein}` as the placeholder |
| `WATCHLIST_PATH` | Path to `watchlist.yaml` (relative to process cwd) |
| `WATCHLIST_HASHES_PATH` | Path to stored policy page hashes |
| `DIRECTORIES_PATH` | Path to `directories.yaml` (relative to process cwd) |
| `GOOGLE_PLACES_API_KEY` | Google Places API (New) key for `youth_orgs` and brand resolution |
| `GOOGLE_PLACES_SEARCH_URL` | Places `places:searchText` endpoint |
| `GOOGLE_PLACES_GRID` | `south,west,north,east,step_degrees` search grid |

Frontend only, in `frontend/.env.local`:

| Variable | Purpose |
| --- | --- |
| `API_URL` | FastAPI origin, usually `http://127.0.0.1:8000` |

## Running the pipeline

From the repo root:

```bash
uv run python -m backend.scheduler
```

That command runs every collector once (nonprofit 990, policy monitor, youth orgs, sponsor logos, staff directories), then deduplicates and scores, then keeps an in-process APScheduler running:

- `nonprofit_990` — monthly
- `policy_monitor` — daily
- `youth_orgs` — quarterly
- `sponsor_logos` — quarterly
- `staff_directory` — monthly

A failure in one job is logged and does not stop the others.

The API and dashboard are separate processes:

```bash
uv run uvicorn backend.api.main:app --host 127.0.0.1 --port 8000
cd frontend && pnpm dev
```

Open `http://localhost:3000`. Manual collector runs are on `/sources` (POST `/sources/{name}/run`). CSV export is on `/leads`.

```bash
uv run pytest
```

## Adding a watched policy URL

Edit `backend/watchlist.yaml`. Each item needs three keys:

```yaml
- jurisdiction: VA
  url: https://example.edu/athletics/nil-policy
  category: nil_policy
```

`category` is `nil_policy`, `eligibility`, or `compliance`. Use only pages you are allowed to fetch. Do not add LinkedIn, Instagram, Facebook, or X URLs. After the first fetch the collector stores a content hash; the next change can write a `policy_events` row.

## Adding a staff directory URL

Edit `backend/directories.yaml`. Each item needs:

```yaml
- name: Example University Athletics
  url: https://example.edu/athletics/staff
  org_type: college
  pattern: table
  city: Richmond
  state: VA
```

`org_type` must be a schema org type (`college`, `high_school`, `school_district`, and so on). `pattern` is `table`, `definition_list`, or `cards` — the first structured parser to try. Replace the example.com placeholders before relying on this collector.
