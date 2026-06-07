# HONESTY.md

> Mandatory disclosure for the hackathon. This file lives at the root of your repository. Judges cross-check it against your code and your technical video.
>
> **The deal:** disclosed shortcuts are **not** penalized — that is the entire point of this file. Hidden ones are. Undisclosed pre-built code is heavily penalized, each undisclosed mock carries a small penalty, and a faked demo is heavily penalized. Telling the truth here costs you nothing.

---

## 1. Team — who did what
Judges compare this against `git shortlog -sn`, so keep it honest.

| Member | GitHub handle | Main contributions |
|---|---|---|
| Rong-Jet Cheong | Rong-Jet | Backend (API, Data Parser, Database) |
| Marlon Müller | FaultierFlash | Frontend (Design, Graphs, Hosting) |
| Daniel Ritter | imperator-divinus | Data analysis (Algorithms, Research) |
| Sanjit Srinivasan | sanjit-srini1007 | Business Research, Pitch Deck, Video Scripting |

---

## 2. What is fully working
Features that run end-to-end on the live app, with real data and real logic. Be specific: name the feature, what input it takes, what output it produces.

- Data upload for TikTok, Youtube, Instagram
- Detailed Analysis with detailed analytics
- Live hosting on semi-scalable infrastructure

---

## 3. What is mocked, stubbed, or hardcoded
Every shortcut. Examples: a login that accepts any password, a payment that always succeeds, an "AI" that is an if/else, a database that is an in-memory dictionary, fake JSON returned instead of a real API call.

**Undisclosed mocks carry a small penalty each. Anything you list here = free.**

| What is faked | Where (file:line or folder) | Why we mocked it | What the real version would do |
|---|---|---|---|
| opt-in Synthetic Data for populating comparison | somewhere in the depths of our SQL | We don't have the user base to compare individuals against, so we decided on giving a comparison | More users would give more data |

If nothing is mocked, write: *"Nothing is mocked — every feature listed above uses real logic and real data."*

---

## 4. External APIs, services & data sources
Everything the project calls or pretends to call. Mark each as real or mocked.

| Service / API / dataset | Used for | Real call or mocked? | Auth (sandbox / test key / none) |
|---|---|---|---|
| YoutubeAPI | Enrichment of Youtube Data | Real call | public API |
| Render |  |  |  |
| Render |  |  |  |


---

## 5. Pre-existing code
Anything written **before** kickoff that we brought into this project: prior personal projects, forked open-source code, templates, boilerplate, internal libraries.

**Undisclosed pre-built code is heavily penalized. Anything you list here = free.**

| Item | Source (URL or description) | Roughly how much | License |
|---|---|---|---|
|  |  |  |  |
|  |  |  |  |

If none, write: *"All code in this repo was written during the hackathon window."*

---

## 6. Known limitations & next steps
What we would build next, and the weak spots we already know about. Naming these honestly is a strength, not a flaw.

- 
- 
- 
