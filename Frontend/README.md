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

Browser calls to these backend endpoints go through `src/lib/api.ts`:

```text
POST /api/query
POST /api/imports
GET /api/imports/{import_id}
```

Set `PUBLIC_API_URL` to the backend origin, for example:

```sh
PUBLIC_API_URL=http://127.0.0.1:8000
```

Leave `PUBLIC_API_URL` empty to use the local Astro mock API routes during UI-only development.

When `PUBLIC_API_URL` is set, the Astro upload helper requires `AWS_ACCESS_KEY_ID`,
`AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, and `S3_BUCKET`; otherwise it fails before
registering a mock upload with the real backend.

The upload helper routes remain same-origin because the Python backend accepts
completed S3 object metadata but does not generate browser upload URLs:

```text
GET /api/uploader-info
POST /api/upload-url
PUT /api/mock-s3-upload
POST /api/population
```

`POST /api/population` is frontend-only mock analytics; it is not part of the
v5 backend API contract.

## Contract Notes

- Send the LDiHK demo identity only as `Authorization: Bearer <LDiHKID>`.
- Do not send `ldihk_id`, `user_id`, or `person_id` in JSON bodies.
- Upload ZIP objects under `uploads/<LDiHKID>/<filename>.zip`.
- Query `dataset: "youtube_usage"` only for the current backend.
- Use `estimated_watch_seconds`, not `watch_seconds`.
