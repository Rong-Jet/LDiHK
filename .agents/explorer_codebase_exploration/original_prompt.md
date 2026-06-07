## 2026-06-07T05:07:42Z

You are the codebase explorer. Your working directory is c:\dev\temp\LDiHK\.agents\explorer_codebase_exploration.
Your task is to explore the c:\dev\temp\LDiHK\backend directory and extract all necessary details to compile the system architecture report.
Specifically, you must:
1. Identify and document all Flask endpoints, including their methods, input payloads, URL parameters, authentication checks, and response structures. Look at app.py, http_boundary.py, imports_api.py, query_api.py, etc.
2. Extract the complete PostgreSQL database schema from db.py, models, and migration scripts. Pay close attention to: users, imports, source_files, usage_events, subscriptions, youtube_videos, enrichment_jobs. Document all columns, types, keys, and foreign key relations.
3. Map out the Data Ingestion Pipeline:
   - How does a user initiate a ZIP upload?
   - How is a pre-signed URL created for S3 upload?
   - How is the import registered?
   - How does the background ingestion worker (backend/ingestion/worker.py) poll, download the ZIP from S3, parse it, and persist it to database tables?
   - Detail the parsing logic inside the different parsers (e.g. watch_history, search_history, subscriptions, comments_live_chat, likes_playlists). Identify which table each parser writes to.
4. Map out the Enrichment Pipeline:
   - How are video IDs gathered?
   - How are enrichment jobs queued and tracked?
   - How does the YoutubeDurationEnrichmentWorker poll, fetch metadata/durations from the YouTube Data API, and update the database?
5. Map out the Wellness Engine & Biomarkers:
   - Study the POST /api/query endpoint (likely in query_api.py).
   - Extract the mathematical and SQL definitions of:
     - Volume (V_t)
     - Sleep Delay (C_t)
     - Fragmentation (F_t)
   - Detail the exact SQL queries used for these calculations, including which columns/tables are queried and any timezone/grouping logic.
6. Map out Authentication & Request Scoping:
   - How are Bearer tokens (LDiHK IDs) validated?
   - How is the user identity checked and used to restrict access to their own data?

Write your comprehensive findings to c:\dev\temp\LDiHK\.agents\explorer_codebase_exploration\analysis.md and a summary handoff to c:\dev\temp\LDiHK\.agents\explorer_codebase_exploration\handoff.md.
Ensure no changes are made to files under the repository path c:\dev\temp\LDiHK.
