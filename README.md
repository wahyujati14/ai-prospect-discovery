# AI Multi-Platform Prospect Discovery API

FastAPI service that interprets natural-language prospect queries, searches public profiles across multiple platforms, extracts publicly published contact links, consolidates multi-platform identities, and returns verified prospects via `POST /prospect-discovery`.

## Live Deployment

| Item | URL |
|---|---|
| Live Service | `https://<your-deployed-domain>` |
| Discovery Endpoint | `https://<your-deployed-domain>/prospect-discovery` |
| Interactive Docs (Swagger) | `https://<your-deployed-domain>/docs` |

## Supported Platforms & Discovery Sources

| Platform | Discovery Method | Output Validation & Notes |
|---|---|---|
| **Google** | Serper API / Google Custom Search API / DuckDuckGo public index (`ddgs`) | Used as discovery engine; standalone personal/company websites are validated and never include generic `google.com/search` URLs. |
| **LinkedIn** | Targeted public index search (`site:linkedin.com/in`) + website cross-links | Canonicalized to `/in/<slug>` or `/company/<slug>`; `/jobs`, `/pulse`, and directory pages are rejected. |
| **X** | Targeted public index search (`site:x.com`, `site:twitter.com`) + website cross-links | Normalized to `https://x.com/<handle>`; status/search/intent paths stripped or filtered. |
| **YouTube** | Official YouTube Data API v3 (`YOUTUBE_API_KEY`) + public channel search (`/@handle`) | Verified `/@handle` and `/channel/<id>` URLs; `/watch` and `/shorts` links excluded. |
| **Instagram** | Public index search (`site:instagram.com`) + website cross-links | Canonicalized to `https://www.instagram.com/<handle>/`; `/p/` and `/reel/` URLs excluded. |
| **WhatsApp** | Public `wa.me` / `api.whatsapp.com/send` discovery + website HTML extraction | Normalized to `https://wa.me/<digits>` with 8–15 digit phone validation. |
| **Facebook** | Public page/profile search (`site:facebook.com`) + website cross-links | Rejects `/groups`, `/events`, `/marketplace`, and share dialogs. |
| **Email** | Extracted from public search snippets and standalone public websites | Validated format, filtered against asset/placeholder domains, formatted as `mailto:<email>`. |
| **Threads** | Public index search (`site:threads.net`) + website cross-links | Normalized to `https://www.threads.net/@<handle>`. |

### Platform Access Limitations & Compliance Notes

- **No Private Scraping or Auth Bypass**: LinkedIn, Instagram, Facebook, Threads, and X restrict unauthenticated direct profile HTML scraping via login walls and anti-bot controls. Per assessment rules, this engine never attempts to bypass login walls or scrape private pages. Instead, it discovers publicly indexed profile URLs via authorized search backends (`Serper`, `Google CSE`, or `ddgs`) and enriches multi-platform links from standalone public business/personal websites (`app/services/profile_extractor.py`).
- **Search Volume & Index Coverage**: Without `SERPER_API_KEY` or `GOOGLE_CSE_API_KEY`, the engine falls back to `ddgs` public search so the prototype works out of the box, though Google-backed search APIs yield higher recall on `site:linkedin.com/in` and `site:threads.net` queries.

## Architecture & Processing Pipeline

```text
POST /prospect-discovery
   │
   ├─► QueryService (LLM intent parsing + TTL cache)
   │      Extracts interest, audience, city/state/country, target_type
   │
   ├─► Platform Adapters (concurrent bounded execution via SearchService)
   │      Google, LinkedIn, X, YouTube (+ Data API v3), Instagram,
   │      WhatsApp, Facebook, Threads
   │
   ├─► Public Website Enrichment (SSRF-guarded HTML contact & social link parser)
   │      Extracts mailto:, tel:, wa.me, and cross-linked social profiles
   │
   ├─► DeduplicationService (entity resolution)
   │      Consolidates profiles sharing verified email/WhatsApp, handle, or name+location
   │
   ├─► RelevanceService (heuristic pre-filter + single batched LLM verification)
   │      Removes listicles/directories and verifies query relevance
   │
   └─► Pydantic ProspectDiscoveryResponse
```

## Project Structure

```text
ai-prospect-discovery/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── schemas.py
│   ├── services/
│   │   ├── query_service.py
│   │   ├── search_service.py
│   │   ├── prospect_service.py
│   │   ├── profile_extractor.py
│   │   ├── deduplication_service.py
│   │   ├── relevance_service.py
│   │   └── llm_service.py
│   ├── platforms/
│   │   ├── base.py
│   │   ├── google.py
│   │   ├── linkedin.py
│   │   ├── facebook.py
│   │   ├── instagram.py
│   │   ├── x_platform.py
│   │   ├── youtube.py
│   │   ├── whatsapp.py
│   │   └── threads.py
│   └── utils/
│       ├── validators.py
│       └── normalizers.py
├── tests/
│   └── test_prospect_discovery.py
├── .env.example
├── Dockerfile
├── Procfile
├── pytest.ini
├── requirements.txt
└── README.md
```

## Local Setup & Execution

### 1. Create virtual environment and install dependencies

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure environment variables

Copy `.env.example` to `.env` and set `GEMINI_API_KEY` (or `OPENAI_API_KEY`). Optionally set `SERPER_API_KEY`, `GOOGLE_CSE_API_KEY` + `GOOGLE_CSE_CX`, and `YOUTUBE_API_KEY` for higher discovery recall:

```bash
cp .env.example .env
```

### 3. Run the FastAPI server on port 4000

```bash
uvicorn app.main:app --host 0.0.0.0 --port 4000
```

Interactive OpenAPI docs: `http://localhost:4000/docs`

### 4. Run automated tests

```bash
pytest -v
```

## Practical Test Queries & Sample Usage

### Test Request

```bash
curl -X POST http://localhost:4000/prospect-discovery \
  -H "Content-Type: application/json" \
  -d '{"query": "Startup founders in London UK"}'
```

Supported assessment test queries verified by the query parser and discovery pipeline:
1. `Football lovers in Washington DC in USA`
2. `Digital marketing agency owners in New York USA`
3. `Startup founders in London UK`
4. `Cricket lovers in Ahmedabad India`
5. `Restaurant owners in Dubai UAE`

### Sample JSON Response Structure

```json
{
  "success": true,
  "query": "Football lovers in Washington DC in USA",
  "total_prospects": 2,
  "prospects": [
    {
      "name": "District Sports Soccer",
      "location": "Washington DC, USA",
      "social_link": [
        {
          "platform": "Google",
          "link": "https://districtsports.org/"
        },
        {
          "platform": "Instagram",
          "link": "https://www.instagram.com/districtsports/"
        },
        {
          "platform": "Facebook",
          "link": "https://www.facebook.com/DistrictSports"
        },
        {
          "platform": "Email",
          "link": "mailto:info@districtsports.org"
        }
      ]
    },
    {
      "name": "Screaming Eagles DC",
      "location": "Washington DC, USA",
      "social_link": [
        {
          "platform": "Google",
          "link": "https://www.screaming-eagles.com/"
        },
        {
          "platform": "X",
          "link": "https://x.com/ScreamingEagles"
        },
        {
          "platform": "Instagram",
          "link": "https://www.instagram.com/screamingeaglesdc/"
        }
      ]
    }
  ]
}
```

---

## LLM Platform & Model Research (Cost, Speed, and Accuracy)

### A. LLM Platform Comparison

Token pricing reflects published standard API rates per 1M tokens. Latency numbers below are **estimated** per-call durations for the short JSON prompts used in this pipeline (~350–1,800 input tokens).

| Criteria | Google Gemini (`gemini-2.5-flash`) | OpenAI (`gpt-4o-mini`) | OpenAI (`gpt-4.1-mini`) | Anthropic (`claude-haiku-4-5`) |
|---|---|---|---|---|
| **Provider** | Google AI / Vertex | OpenAI | OpenAI | Anthropic |
| **Model Name** | `gemini-2.5-flash` | `gpt-4o-mini` | `gpt-4.1-mini` | `claude-haiku-4-5` |
| **API Cost (Input / Output per 1M)** | \$0.30 / \$2.50 (Free tier in AI Studio) | \$0.15 / \$0.60 | \$0.40 / \$1.60 | \$1.00 / \$5.00 |
| **Response Speed (Est.)** | ~0.8s – 1.8s per step | ~1.1s – 2.3s per step | ~1.0s – 2.1s per step | ~1.0s – 2.0s per step |
| **Accuracy (Intent & Entity Filtering)** | High; reliable geographic disambiguation & listicle rejection | Good; solid intent extraction, slightly looser entity cleanup | High; strong instruction following | High; higher output token cost |
| **Context Window** | ~1,000,000 tokens | 128,000 tokens | ~1,047,576 tokens | 200,000 tokens |
| **JSON Support** | Native `responseMimeType: application/json` | Native `json_object` / Structured Outputs | Native `json_object` / Structured Outputs | Tool-use / JSON prefill |
| **Recommendation** | **Recommended Primary** | **Recommended Fallback / High-Volume Batch** | Strong alternative | Higher cost per request |

### B. Best Model Selection

`gemini-2.5-flash` is recommended as the primary model with `gpt-4o-mini` as automatic fallback:
1. **Query Understanding**: Accurately separates audience persona, core interest, and implicit state/country hierarchy (e.g., mapping `Washington DC` -> `District of Columbia, USA` and distinguishing `individual` enthusiasts from `business` owners).
2. **Prospect Relevance Filtering**: Effectively rejects SEO listicles (`"Top 15 Agencies..."`), job listings, and directory pages during candidate verification.
3. **Speed**: Because multi-platform search I/O already takes ~2–4 seconds, sub-2-second LLM steps keep total endpoint latency responsive.
4. **JSON Reliability & Cost**: Native JSON output avoids parsing failures while staying around two-tenths of a cent per uncached discovery run (and free within Google AI Studio development quotas).

### C. Cost Optimization Strategies Used

- **Two-Call Maximum Pipeline**: Instead of calling an LLM once per search result (which would trigger 20–40 LLM calls per request), each uncached request makes **at most 2 LLM calls**: (1) query intent extraction and (2) a single batched JSON verification call over the top deduplicated candidates (capped at 25 items, snippets trimmed to 280 chars).
- **Deterministic Validation First**: Profile URL canonicalization, `google.com/search` filtering, email/phone/WhatsApp validation, listicle regex rejection, and entity deduplication run in pure Python (`validators.py`, `normalizers.py`, `deduplication_service.py`) at zero token cost.
- **Layered Caching**: Both parsed query intents (`QueryService`) and final discovery responses (`ProspectDiscoveryService`) are cached in memory (`CACHE_TTL_SECONDS=1800`).

### D. Final LLM Recommendation Summary

- **Recommended Provider & Model**: Google Gemini — `gemini-2.5-flash`
- **Fallback Provider & Model**: OpenAI — `gpt-4o-mini`
- **Estimated Token Usage per Uncached Discovery Request**:
  - Call 1 (Query Understanding): ~300 input tokens, ~110 output tokens
  - Call 2 (Batched Relevance Evaluation for ~15–25 candidates): ~1,850 input tokens, ~450 output tokens
  - **Total**: ~2,150 input tokens / ~560 output tokens
- **Estimated API Cost per Discovery Request**:
  - `gemini-2.5-flash` (paid tier): `(2,150 * $0.30 + 560 * $2.50) / 1,000,000` ≈ **\$0.00205 per request** (\$0.00 within AI Studio free tier)
  - `gpt-4o-mini` (fallback): `(2,150 * $0.15 + 560 * $0.60) / 1,000,000` ≈ **\$0.00066 per request**
- **Expected End-to-End Response Time**: ~4.0s – 8.5s uncached (estimated across concurrent search + website contact enrichment + 2 LLM calls), **<10ms cached**.

## Deployment (Render / Railway / Docker)

```bash
docker build -t ai-prospect-discovery .
docker run -p 4000:4000 --env-file .env ai-prospect-discovery
```
