# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
uv sync --extra dev                 # install, incl. pytest/ruff
uv run playwright install chromium  # slides are rendered in headless Chromium

uv run pytest                                   # all tests
uv run pytest -m unit                           # no network
uv run pytest tests/unit/test_workflow.py::test_name
uv run ruff check . && uv run ruff format .

uv run instagram-marketing-agent --slides 5     # story campaign from content/input/
uv run python -m instagram_marketing_agent.server  # MCP server over stdio
uv run image-index --limit 1                    # catalogue the Drive image library
uv run authorize-drive                          # mint GOOGLE_OAUTH_REFRESH_TOKEN
```

Pytest markers (`pyproject.toml`): `unit`, `contract`, `integration` (live credentials + real Drive), `slow` (real image generation). Test modules set `pytestmark` at the top. `asyncio_mode = "auto"`, so async tests need no decorator.

Needs `ANTHROPIC_API_KEY` and `GEMINI_API_KEY` in `.env` (loaded by `config.load_dotenv`, no python-dotenv dependency). ffmpeg only for video; it is found on `PATH` or in the gitignored `.tools/`.

## Architecture

Package `src/instagram_marketing_agent/`. Three entry surfaces share one implementation:

- `workflow.py` — all pipeline logic (campaigns, lifestyle sets, `verify_content`, `regenerate_slide`).
- `server.py` — MCP server built on `mcp.server.MCPServer` (SDK v2; `fastmcp` does not exist there). Registration and marshalling only. Anticipated exceptions (`ValueError`, `FileNotFoundError`, `RuntimeError`, `FFmpegMissingError`) are converted to `ToolError` by `_reporting` so the client sees the message.
- `client.py` (MCP client) and `cli.py` (console script).

`config.py` holds every path, model ID, format/artboard constant and env var name — keep magic values there.

`llm/` is a package with a single import surface (`llm/__init__.py`). Callers use `llm.generate_script(...)` etc., and tests monkeypatch attributes on `llm` itself (`monkeypatch.setattr(llm, "generate_image", fake)`), so **workflow code must call through `llm.<name>`, not import the function directly**, or patches stop applying. Underscored names are re-exported with the redundant `as` form deliberately. Claude does understanding/writing (typed outputs); Gemini does image generation and transcription; `describe` alone can be routed to DeepSeek via `DESCRIBE_MODEL` (`llm/deepseek.py`).

### Campaign pipeline (`workflow.create_campaign`)

brief (`content/input/topic.md`) → SKUs extracted and looked up in `products.xlsx` (`products.py`) → project dir created in `content/output/` → input images/videos described (video: ffmpeg frames + transcript written under `<project>/source/`) → `llm.generate_script` → per slide in parallel: Gemini background with reference photos attached, then Claude lays out HTML over it (`slide_html.py`) and Playwright screenshots it → whole finished set reviewed together (`verify_content`) → slides with *issues* re-laid-out over the same background (`fix_flagged_slides`) → `script.json` saved. Story and post formats run the identical pipeline; only `CanvasFormat` differs. Lifestyle (`create_lifestyle_content`) reuses the building blocks but stops at images — no copy, no layout pass.

Slide failures are collected rather than aborting the campaign; a failed review is logged and the slides are kept.

### Rules that drive design decisions

- **Subjects come from photographs, not words.** Image prompts describe the scene only — never breed, coat, clothing or label text. Appearance comes from attached reference photos; the catalogue packshot always wins for packaging (`product_references`, `subject_references`, `_guard_prompts`).
- **Skip rather than invent.** A lifestyle product with no obtainable packshot is skipped and reported; a DeepSeek describe reply that won't parse fails the run rather than dropping reference flags.
- **One `cast` per set** — a single person description carried into every human-featuring prompt and enforced by the verifier.
- Brand/design rules are data, not code: `src/resources/slide-design-guidelines.md`, `smm_composition_rules.md`, `lifestyle-content-brief.md` are fed into prompts. Decorative PNGs in `src/resources/png/` are tinted into `.decor-cache/` in Python (headless Chromium doesn't render `mask-image`).

### Image library indexer (`image_index.py`, `drive.py`, `authorize_drive.py`)

Separate from campaigns. Reads `src/resources/images_index/index_inventory.xlsx` (sheet `Повний список`; the Drive link is the cell's hyperlink, the text is just "Відкрити"), downloads and describes each image/video, and writes `images_index.xlsx` in Ukrainian. Resumable and additive — saved every 10 rows, already-indexed detection is by filename only. Video uploads screenshots to a Drive folder beside the clip, which needs OAuth credentials (`GOOGLE_OAUTH_*` in `.env`); see README for the Google Cloud setup.

### Product search / RAG (`src/infrastructure`, `src/domain`, `src/routines`)

Separate top-level packages, not part of `instagram_marketing_agent`; layout follows the "Code structure" section of `specs/hd-marketing-rag.md`, behaviour follows `specs/search-service.md`. `routines/indexer.py` (`uv run rag-index`) embeds the spreadsheets in `src/resources/indices/` into the Firestore database `healthydoggo`; `domain.search_service.SearchService.find_similar` asks TypeSafe's Jev one `choice` question with each collection as an option (probability threshold 0.3; probabilities sum to 1, so a query searches one to three collections), then runs a cosine `find_nearest` (top 5) on each selected collection. Errors are the spec's `InvalidArgument` / `EmbeddingError` / `DataSourceError` in `domain/contracts.py`, raised by the clients. Embeddings are 1536-d (Firestore caps vector indexes at 2048), and gemini-embedding-2 takes query/document prefixes in the text instead of `task_type`.

### Search API (`src/api`)

FastAPI over `SearchService`, spec `specs/api.md`. Built by a factory: `uv run uvicorn api.app:create_app --factory`. One endpoint, `POST /searchcontext`. Private by IAM, not network (ingress all, no VPC): Cloud Run admits only the portal's service account; the API itself verifies the end user's Google ID token from `X-User-Token` (`api/auth.py`, audience `USER_TOKEN_AUDIENCE`, allowlist `ALLOWED_USERS`, fail-closed at startup) and logs every call and refusal as JSON with the user's email. Tests fake `auth.verify_google_id_token` and pass a fake service to `create_app`. `Dockerfile`/`.dockerignore`/`.gcloudignore` are for this service; deploy steps are in README "Search API".

## Local-only data

Gitignored and absent in a fresh clone: `content/input|output/*`, `src/resources/products.xlsx` (falls back to committed `products.sample.xlsx`), `src/resources/images_index/`, `.tools/`, `.decor-cache/`.

`specs/` holds design notes: `mcp-server.md` (original brief), `hd-marketing-rag.md`, `search-service.md` and `api.md` (the RAG service and its API).
