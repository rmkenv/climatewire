# ClimateWire — Dashboard

Live climate hazard intelligence dashboard for the ClimateWire pipeline.

## Stack

- **Next.js 14** (Pages Router)
- **React-Leaflet** — interactive dark map
- **SWR** — auto-refreshing data fetch from GitHub raw
- **Recharts** — stats
- **Tailwind CSS** — layout
- **IBM Plex + Fraunces** — typography

## Data source

Reads directly from your `climatewire` repo's `data/` directory via GitHub raw URLs. No database, no backend — free forever.

## Local dev

```bash
npm install
cp .env.example .env.local
# Edit .env.local with your GitHub repo path
npm run dev
```

## Deploy to Vercel

1. Push this directory to a new GitHub repo (e.g. `climatewire-app`)
2. Import in [vercel.com/new](https://vercel.com/new)
3. Add environment variable:
   ```
   GITHUB_RAW_BASE = https://raw.githubusercontent.com/rmkenv/climatewire/main/data
   ```
   Replace `rmkenv/climatewire` with your actual repo.
4. Deploy — done.

The map auto-refreshes every 15 minutes to pick up new articles from your daily GitHub Actions runs.
