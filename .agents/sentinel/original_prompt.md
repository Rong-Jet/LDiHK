## 2026-06-07T05:07:15Z

Evaluate the system architecture of the LDiHK repository and create a detailed technical report explaining how the services interact. Focus on the real Python Flask backend, database, background workers, and external integrations. Write the final report and diagram to the artifacts directory (not the source repository).

Working directory: c:\dev\temp\LDiHK
Integrity mode: development

## Requirements

### R1. Technical Architecture Report
Write a detailed report in Markdown format saved at `C:\Users\Fault\.gemini\antigravity\brain\5cc6ea2f-b65d-4022-98da-a780fced4616/system_architecture_report.md` covering:
- **Core Architecture Overview**: The relationships and communications between the Astro Frontend, Flask Backend, PostgreSQL Database, AWS S3 bucket, and Background Workers.
- **Data Ingestion Pipeline**: Detailed flow of how a YouTube Takeout ZIP upload is initiated, uploaded to S3 via pre-signed URL, queued, downloaded, parsed by specific parsers, and persisted to SQL tables.
- **Enrichment Pipeline**: Flow of how video IDs are gathered, how enrichment jobs are queued, and how the YoutubeDurationEnrichmentWorker fetches metadata and durations from the YouTube Data API to enrich the database.
- **Wellness Engine & Biomarkers**: Detailed logic of the `POST /api/query` endpoint, including the mathematical/SQL definitions of Volume ($V_t$), Sleep Delay ($C_t$), and Fragmentation ($F_t$).
- **Authentication & Request Scoping**: Explain how Bearer tokens (LDiHK IDs) are validated and used to filter queries so users can only access their own data.

### R2. System Architecture Diagram
Include a detailed Mermaid.js flowchart in the report that maps out:
- Component boundaries (Client, Flask API, PostgreSQL, S3, Background Workers, YouTube API).
- API request pathways (Upload initialization, Import registration, Polling status, Biomarker query).
- Asynchronous data processing flows (Ingestion worker polling, S3 download, database insertion, enrichment queuing, API fetching).
- Where API calls come together and what happens on which service.

## Verification Plan

### Independent Audit
An independent agent-as-judge audit will verify the report and diagram against the following criteria:
- All core Flask endpoints from the codebase are accurately documented.
- The PostgreSQL database schema tables (`users`, `imports`, `source_files`, `usage_events`, `subscriptions`, `youtube_videos`, `enrichment_jobs`) are explained.
- The data flow transitions (from S3 to local parser to DB tables) are fully mapped.
- Volume, Sleep Delay, and Fragmentation calculations are explicitly explained with their database schema columns.

## Acceptance Criteria

### Technical Completeness
- [ ] Technical report is saved in the artifacts directory as `system_architecture_report.md`.
- [ ] Report covers the Core Architecture, Ingestion Pipeline, Enrichment Pipeline, Wellness Engine, and Authentication.
- [ ] The Mermaid.js diagram is valid syntax and renders correctly, visually tracking the entire sequence from ZIP upload to dashboard queries.
- [ ] Zero changes are made to any files under the repository path `c:\dev\temp\LDiHK`.
