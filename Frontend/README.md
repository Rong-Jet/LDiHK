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
`../docs/backend/frontend-api-spec.md`. Do not duplicate endpoint schemas in
this README.

Set `PUBLIC_BACKEND_API_URL` or `PUBLIC_API_URL` to the backend origin, for
example:

```sh
PUBLIC_BACKEND_API_URL=http://127.0.0.1:8000
```

Set `PUBLIC_MOCK_API=false` to fail clearly instead of falling back to local
mock routes when live backend or S3 upload config is missing. Set
`PUBLIC_MOCK_API=true` only for UI-only mock development.

When a backend origin is set, the Astro upload helper requires
`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, and `S3_BUCKET`;
otherwise it fails before registering an import with the real backend.

Same-origin Astro helper routes:

```text
GET /api/uploader-info
POST /api/upload-url
PUT /api/mock-s3-upload
```

`PUT /api/mock-s3-upload` is mock-only and must not be used for live imports.

## Contract Notes

See `../docs/backend/frontend-api-spec.md` for identity, upload, query,
population, and import status contracts.
