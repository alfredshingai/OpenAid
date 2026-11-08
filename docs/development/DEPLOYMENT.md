# Deploying OpenAid (Vercel + managed PostGIS)

The platform deploys as **one Vercel project**: the React frontend is built
statically and the FastAPI API runs as a Python serverless function behind
the same domain (`/api/*` is routed to the function — no CORS needed).
The database is a managed **PostgreSQL + PostGIS** (Neon or Supabase free
tiers both support PostGIS).

```
 Browser ──► Vercel (static SPA) ──► /api/* ──► FastAPI function ──► Neon PostGIS
```

## One-time setup

### 1. Create the database (Neon CLI — automated)

The repo is wired for the Neon CLI (`neon.ts` declares the Postgres
service; `.claude/skills/neon-postgres/` + `.mcp.json` carry the agent
skill and MCP server):

```bash
npm i -g neon@latest
neon auth                                      # browser sign-in
neon init -y --org-id <org> --project-id <proj> --branch production --services postgres
neon deploy                                    # writes .env.local (gitignored)
```

`neon deploy` pulls `DATABASE_URL` (pooled — used by the app runtime) and
`DATABASE_URL_UNPOOLED` (direct — used for schema migrations) into
`.env.local`, which `openaid_core.config` loads automatically and
normalises to the psycopg driver scheme.

Manual alternative:

1. Sign up at https://neon.tech → create a project → copy the pooled
   connection string, e.g.
   `postgresql://USER:PASSWORD@ep-xxx-pooler.region.aws.neon.tech/neondb?sslmode=require`
2. Enable PostGIS (once, from any SQL console / psql):
   ```sql
   CREATE EXTENSION IF NOT EXISTS postgis;
   ```
3. Apply the schema from your machine (repo root):
   ```bash
   # Windows (Git Bash)
   DATABASE_URL="postgresql+psycopg://USER:PASSWORD@ep-xxx.../neondb?sslmode=require" \
     .venv/Scripts/python.exe -m alembic -c backend/alembic.ini upgrade head
   ```
4. Optional — load the real baseline data (requires a downloaded
   crisis-baseline-kit bundle; see README):
   ```bash
   DATABASE_URL="postgresql+psycopg://..." \
     .venv/Scripts/python.exe -m openaid_core.seed.cbk \
     --bundle-dir /tmp/cbk/ken-baseline-2026-11-01 --country KEN
   ```

> **Pooled vs direct** (per `.claude/skills/neon-postgres/`): the API and
> seeds use the pooled URL; Alembic migrations use `DATABASE_URL_UNPOOLED`.

### 2. Import the repo into Vercel

1. Push `main` to GitHub (already done).
2. https://vercel.com/new → import `alfredshingai/OpenAid` → framework
   detection is overridden by `vercel.json` (static build + Python
   function) — no build settings needed.
3. Environment variables (Project → Settings → Environment Variables):

   | Name | Value | Notes |
   | --- | --- | --- |
   | `DATABASE_URL` | `postgresql+psycopg://USER:PASSWORD@ep-xxx.../neondb?sslmode=require` | the `+psycopg` scheme is required |
   | `OPENAID_SECRET_KEY` | long random string | token signing (`python -c "import secrets; print(secrets.token_urlsafe(48))"`) |
   | `OPENAID_RATE_LIMIT_PER_MINUTE` | `300` | optional; 0 disables |
   | `OPENAID_CORS_ORIGINS` | `*` | same-origin by design; tighten later |

4. Deploy. Check `https://<project>.vercel.app/health` → `{"status": "ok"}`.

> **First request is slow.** Serverless cold start compiles the Python
> environment; subsequent requests are fast. Neon's autosuspend adds ~1 s
> after idle — expected on the free tier.

## CLI alternative

```bash
npm i -g vercel
vercel login
vercel --prod            # from the repo root; env vars set via dashboard or `vercel env add`
```

## Upgrading

Schema changes land as Alembic migrations on `main`. After pulling, apply
them to the cloud DB exactly as in step 1.3 — the API does not auto-migrate.

## Notes & limits

- The serverless function is **read-mostly by design**: ingestion endpoints
  exist but large imports are better run from a workstation against the
  cloud DB (same commands as above).
- Neon free tier: ~0.5 GB storage, autosuspend after idle. Kenya + Eswatini
  baseline (~45k rows incl. facilities) fits comfortably.
- Secrets live only in Vercel env vars; `.env` files are gitignored.
- The PoC (`poc/`) and the governance test suite never run on Vercel — CI
  covers them on GitHub Actions.
