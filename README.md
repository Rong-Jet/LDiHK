# LDiHK

## Quick Start

Set up the local Python environment:

```sh
uv venv .venv
uv sync
```

Run the tests:

```sh
uv run python -m unittest discover -s backend/tests
```

Process the local Google Takeout export:

```sh
uv run python backend/scripts/process_youtube_usage.py
```

This writes:

```text
data/processed/users/local_user/youtube_usage.v1.json
```

Start the read-only API:

```sh
uv run flask --app backend.app run
```

Available endpoints:

```text
GET http://127.0.0.1:5000/health
GET http://127.0.0.1:5000/api/users/local_user/youtube-usage
```

If `uv` cannot write to its default cache in a restricted environment, prefix commands with:

```sh
uv --cache-dir .uv-cache ...
```

## Technical Diagram

```mermaid
flowchart LR
  subgraph Ingestion["Ingestion"]
    IG["Instagram usage data"]
    YT["YouTube usage data"]
    TT["TikTok / Douyin usage data"]
    RAW["Raw usage data"]
    IG --> RAW
    YT --> RAW
    TT --> RAW
  end

  subgraph Preprocessing["Preprocessing"]
    direction TB

    CLEAN["Clean and validate data"] --> STRUCTURE["Convert to structured format"] --> STANDARD["Standardized data structure"]
    STANDARD --> DB[("SQL database")]
    DB --> AI["AI analysis / augmentation"]
    AI --> FEATURES["Derived metrics and risk signals"]
  end

  subgraph Dashboard["Analysis Dashboard"]
    TEMPORAL["Temporal usage graph"]
    POP["Population comparison"]
    HEALTHY["Comparison with healthy / average usage"]
    RISK["Risk-factor trends over time"]
    CORR["Correlation analysis across groups"]
  end

  RAW --> CLEAN
  FEATURES --> TEMPORAL
  FEATURES --> POP
  FEATURES --> HEALTHY
  FEATURES --> RISK
  FEATURES --> CORR
```
