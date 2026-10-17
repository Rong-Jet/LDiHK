# LDiHK Frontend

Astro + React dashboard for the hosted YouTube Takeout demo.

## Quick Start

Install dependencies:

```sh
npm install
```

Configure local environment:

```sh
cp .env.example .env
```

Run the Astro dev server:

```sh
npm run dev
```

Astro serves the app at:

```text
http://localhost:4321
```

## Backend Integration

The authoritative API shape lives in
`./frontend-api-spec.md`. Do not duplicate endpoint schemas in
this README.

Set `PUBLIC_API_URL` to the backend origin, for example:

```sh
PUBLIC_API_URL=http://127.0.0.1:8000
```

`PUBLIC_*` values are compiled in at build time, so on Netlify set them with
the "Builds" scope and redeploy after changing them.

Set `PUBLIC_MOCK_API=false` to fail clearly instead of falling back to local
mock routes when live backend or upload config is missing. Set
`PUBLIC_MOCK_API=true` only for UI-only mock development; the UI then shows a
"Mock mode" banner on every console page.

Upload URLs come from the backend (`POST /api/uploads`), which keeps the
storage bucket inside its free tier, so the site needs no storage credentials.
The bucket's CORS rule must allow `PUT` with the `content-type` and
`if-none-match` headers from the site origin (see `docs/backend/deployment.md`).

Same-origin Astro helper routes:

```text
GET /api/uploader-info
POST /api/upload-url        (mock mode only)
PUT /api/mock-s3-upload     (mock mode only)
```

## Free-tier behaviour

- The backend on Render's free plan sleeps after 15 minutes. Every console
  page pings `GET /health` first and shows "Waking the server" until it
  answers (usually under a minute).
- Archives over 20 MB are slimmed in the browser before upload: videos,
  photos and other media are dropped so only history files are sent (limit
  200 MB after slimming). zip.js is loaded only when needed.
- Dates and hours are shown in the browser's timezone; the population
  benchmark uses UTC.

## Deploy on Netlify

`netlify.toml` (in this folder) builds with Node 22; the Netlify site's base
directory must be `Frontend`. In the Netlify site
settings, set `PUBLIC_API_URL` and `PUBLIC_MOCK_API=false` (Builds scope) and
the upload variables above (Functions scope), then trigger a deploy.

Deploy previews and branch deploys are forced into mock mode by
`netlify.toml`, so they never call the live backend or upload bucket. Only
merges to `main` (done by the project owner after testing) deploy to
production.

## Contract Notes

See `./frontend-api-spec.md` for identity, upload, query,
population, and import status contracts.
