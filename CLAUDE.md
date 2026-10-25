# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Layout

Three live parts, each with its own toolchain, all serving HealthyDoggo's SMM managers:

| Part | Where | Toolchain | Spec |
|---|---|---|---|
| Product search (RAG) + Search API | `infrastructure/`, `search-api/src/domain`, `routines/`, `search-api/src/api` | uv, repo root | `specs/marketing-content-rag.md`, `content-search-service.md`, `search-api.md` |
| Marketing portal | `portal/` | npm (Next.js 16) | `specs/marketing-portal.md` |
| Marketing MCP | `marketing-mcp/` | separate uv project | `specs/marketing-mcp.md` |

The legacy `src/instagram_marketing_agent/` package and its `image-index` routine have been removed. Its self-contained pieces live on in `infrastructure/` and do import: `ffmpeg.py`, `deepseek.py`, `drive.py` (Drive download/upload over OAuth, `GOOGLE_OAUTH_*`), `anthropic.py` (Anthropic client, image preparation, cast rules) and `gemini.py` (Gemini client).

## Commands

```bash
# repo root: RAG + API
uv sync --extra dev
uv run pytest                                   # tests/unit only has RAG/API tests now
uv run pytest tests/unit/test_api.py::test_name
uv run ruff check . && uv run ruff format .
uv run rag-index                                # embed src/resources/indices/ into Firestore
uv run uvicorn api.app:create_app --factory     # search API

# marketing-mcp/ (run from that directory)
uv sync && uv run pytest
uv run python src/mcp-server.py                       # HTTP on :8080/mcp, needs auth env
MCP_TRANSPORT=stdio uv run python src/mcp-server.py   # local client, no auth

# portal/
npm run dev | npm test | npm run typecheck | npm run lint | npm run build
```

Root pytest: markers `unit`, `contract`, `integration`, `slow` (`pyproject.toml`); test modules set `pytestmark` at the top; `asyncio_mode = "auto"` in both Python projects. Local settings come from `.env`, read by `infrastructure/env.py` (no python-dotenv; real env vars win, no-op on Cloud Run).

## Architecture

### Product search / RAG (`infrastructure/`, `search-api/src/domain`, `routines/`)

Layout follows the "Code structure" section of `specs/marketing-content-rag.md`, behaviour follows `specs/content-search-service.md`. `routines/vector_indexer/indexer.py` embeds the spreadsheets in `src/resources/indices/` into the Firestore database `healthydoggo`. `domain.content_search_service.SearchService.find_similar` asks TypeSafe's Jev one `choice` question with each collection as an option (probability threshold 0.3; probabilities sum to 1, so a query searches one to three collections), then runs a cosine `find_nearest` on each selected collection: content pre-filtered by `type` and optional `hasDog`, products by optional `productSku` (which also forces products to be searched regardless of Jev). Filters are equality only and each filter combination needs its own composite vector index. Top-k is `TOP_K` (5 products, 10 messages, 15 content). Errors are the spec's `InvalidArgument` / `EmbeddingError` / `DataSourceError` in `domain/contracts.py`, raised by the clients. Embeddings are 1536-d (Firestore caps vector indexes at 2048), and gemini-embedding-2 takes query/document prefixes in the text instead of `task_type`.

### Content insights (`specs/instagram-insights-rag.md`, `content-insights-service.md`)

Instagram post/reel/story insights in BigQuery, dataset `instagram_insights`, table `organic` (one row per media, merged by `id`; partitioned by month on `timestamp` with a required partition filter, so every statement bounds `timestamp`). Written by `routines/insights_sync` (`uv run insights-sync`, weekly, posts and reels of the last 30 days) and by the story webhook `search-api/src/webhook` (a separate public FastAPI app, `webhook.app:create_app`, checking Meta's `X-Hub-Signature-256`), both through `routines/insights_sync/rows.py`. Read by `domain.content_insights_service` behind `POST /searchContentInsights` on the search API. `infrastructure/instagram_meta_client.py` is the Graph API over Facebook Login (`graph.facebook.com`), `infrastructure/bigquery_client.py` the table; metric lists per media product type follow `specs/meta/insights.md`, and a request with an unsupported metric fails as a whole.

### Search API (`search-api/src/api`)

FastAPI over `SearchService`, built by the `create_app` factory; one endpoint, `POST /searchcontent`. Private by IAM, not network (ingress all, no VPC): Cloud Run admits only allowed service accounts (`roles/run.invoker`). Two kinds of caller, both in `api/auth.py`, fail-closed at startup, every call and refusal logged as JSON with the caller's email:
- **Portal** — forwards the end user's Google ID token in `X-User-Token` (audience `USER_TOKEN_AUDIENCE`, allowlist `ALLOWED_USERS`).
- **Service callers** (the MCP) — no user token; their own service-account ID token is verified against the API's URL (`SERVICE_TOKEN_AUDIENCE`) and the account must be in `SERVICE_CALLERS` (set both variables or neither).

Tests fake `auth.verify_google_id_token` and pass a fake service to `create_app`. The root `Dockerfile`/`.dockerignore`/`.gcloudignore` are for this service; deploy steps are in README "Search API".

### Marketing portal (`portal/`)

`portal/AGENTS.md` says to read the bundled docs in `portal/node_modules/next/dist/docs/` before writing Next.js code. NextAuth v4 with Google, allowlist `ALLOWED_USERS`; the JWT session cookie holds the user's Google ID token + refresh token, kept out of the `session` callback so the browser never sees them. `/api/search` (route handler) is the only path to the API: it adds `X-User-Token` and, when `API_AUDIENCE` is set, a metadata-server service token. `npm test` is node:test on `src/lib/*.test.ts`.

### Marketing MCP (`marketing-mcp/`)

FastMCP 4 server in `src/mcp-server.py` (hyphenated, so run as a script and tests load it by path; `pythonpath = ["src"]`), tools under `src/tools/`, each exporting the function plus `NAME`/`DESCRIPTION`. Only `search_knowledge_base`, `search_content_insights`, `generate_image` and `generate_slide` exist; the spec's copy, script and validation tools are still to come.

- **Outbound:** both tools call the search API over HTTP (`API_URL`, `/searchcontent` and `/searchContentInsights`) through `src/tools/search_api.py`, as the server's own service account (metadata-server ID token when `API_AUDIENCE` is set), with no user token, and return the API's JSON as is; API errors (and an insights `errorCode`) become tool errors.
- **Images:** `generate_image` takes each product's `imageUrl` from `/searchcontent` (exact `productSku`, else the closest product by name), downloads it and any `sampleUrls` anonymously (Drive share links rewritten to `drive.usercontent.google.com`), and calls Gemini's interactions API (`GEMINI_API_KEY`, `src/tools/image_generation_service.py`); it returns MCP image content.
- **Slides:** `generate_slide` has Claude (`ANTHROPIC_API_KEY`) write the slide as HTML over the downloaded background, per `marketing-mcp/src/resources/slide-design-guidelines.md` and the decor PNGs beside it, then screenshots it in Playwright's headless Chromium (`src/tools/slide_html_service.py`). The page is served from memory under a fake origin; only its background, the tinted decor and Google Fonts load, JavaScript is off. The Docker image installs Chromium; Cloud Run needs `--memory=2Gi`; tests that render skip without `playwright install chromium`.
- **Inbound:** Claude Desktop reaches it as a remote connector from Anthropic's side, so Cloud Run IAM can't gate it. Over HTTP, `src/auth.py` is the gate: FastMCP's Google OAuth proxy, subclassed to refuse any email that is unverified or not in `ALLOWED_USERS`. The server won't start without `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `MCP_BASE_URL`, `MCP_JWT_SIGNING_KEY`, `ALLOWED_USERS`. Proxy state is stored encrypted in a separate Firestore database (`AUTH_FIRESTORE_DATABASE`, default `mcp-auth`), never the knowledge-base one, so it survives restarts and works across instances. `stateless_http=True` for the same reason. Stdio skips auth.

## Local-only data

Gitignored and absent in a fresh clone: `.env`, `content/input|output/*`, `src/resources/indices/` (the spreadsheets `rag-index` reads), `src/resources/products.xlsx`, `src/resources/images_index/`, `.tools/`, `.decor-cache/`. The brand rule documents (`slide-design-guidelines.md`, `smm_composition_rules.md`) and the decor PNGs live in `marketing-mcp/src/resources/`; `infrastructure/anthropic.py` reads the documents from there.
