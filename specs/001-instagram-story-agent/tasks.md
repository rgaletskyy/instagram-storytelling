---

description: "Task list template for feature implementation"
---

# Tasks: Instagram Story Telling Agent

**Input**: Design documents from `/specs/001-instagram-story-agent/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/mcp-tools.md](./contracts/mcp-tools.md)

**Tests**: The spec does not request TDD, so tests are kept to the minimum that earns its place: pure-function tests for the two areas Phase 0 flagged as bug-prone (SKU/HTML parsing, ffmpeg filter escaping) plus one contract test using the in-memory MCP client. Everything else is validated manually through [quickstart.md](./quickstart.md) V1–V9.

**Organization**: Tasks are grouped by user story so each can be implemented and tested independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

Single project. Package at `src/instagram_story_agent/`, tests at `tests/`, brand resources already at `src/resources/`, content at `content/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Make the environment able to run the feature at all. Three dependency pins are wrong for what is installed and one package is missing — see [quickstart.md](./quickstart.md) Prerequisites.

- [X] T001 Install ffmpeg (`brew install ffmpeg`) and confirm `ffmpeg -version` prints — it is absent on this machine and every render task depends on it
- [X] T002 Fix dependency pins in `pyproject.toml`: `anthropic>=1.0`, `mcp>=2.1`, `google-genai>=2.19`, and add `openpyxl>=3.1`
- [X] T003 Run `uv sync` and verify `openpyxl` imports in the `.venv`
- [X] T004 [P] Create package skeleton: `src/instagram_story_agent/__init__.py` and empty `tests/unit/`, `tests/contract/`, `tests/integration/` with `__init__.py`
- [X] T005 [P] Copy `.env.example` to `.env` and populate `ANTHROPIC_API_KEY` and `GEMINI_API_KEY`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Constants and data shapes every story reads.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T006 Create `src/instagram_story_agent/config.py` with repo paths (`content/input`, `content/output`, `src/resources`), env key names, pinned model IDs from [plan.md](./plan.md) (`claude-sonnet-5`, `claude-opus-5`, `gemini-3.1-flash-image`, `gemini-3-pro-image`, `gemini-3.5-transcribe`), canvas constants (1080×1920, safe band `y=250..1670`, 72 px margin), and `FONT_PATH` defaulting to `/System/Library/Fonts/Supplemental/Arial Bold.ttf` (overridable by env — the accepted deviation in [research.md](./research.md) R6)
- [X] T007 Create `src/instagram_story_agent/models.py` with the five Pydantic v2 entities from [data-model.md](./data-model.md): `Product`, `SlideSpec`, `CampaignScript`, `MediaDescription`, `Campaign`, including the 3–7 `slides` length validator on `CampaignScript`
- [X] T008 Create `src/instagram_story_agent/ffmpeg.py` with an `async _run(*args)` helper over `asyncio.create_subprocess_exec` that raises with captured stderr on non-zero exit, plus a startup check that ffmpeg is on PATH

**Checkpoint**: Foundation ready — user story implementation can now begin

---

## Phase 3: User Story 1 - Generate a complete story campaign from local content (Priority: P1) 🎯 MVP

**Goal**: Brief plus images in `content/input/` become a saved project folder of rendered slides and a script in `content/output/`, runnable from code with no MCP involved.

**Independent Test**: Run the CLI against the existing `content/input/` (topic naming `BO-FIU150` plus four images) and confirm a new `content/output/<slug>-<timestamp>/` appears with 5 slides and `script.json`. Covers [quickstart.md](./quickstart.md) V1–V6, V8.

### Implementation for User Story 1

- [X] T009 [P] [US1] Implement `extract_skus(brief: str) -> list[str]` in `src/instagram_story_agent/products.py` using the `[A-Z]{2,4}-[A-Z0-9-]+` pattern from [research.md](./research.md) R7, returning candidates for validation against the sheet
- [X] T010 [US1] Implement `get_products(skus) -> tuple[list[Product], list[str]]` in `src/instagram_story_agent/products.py` reading `src/resources/products.xlsx` with openpyxl read-only, mapping `Артикул`/`Название (UA)`/`Цена`/`Фото`/`Ссылка`/`Описание товара (UA)`, matching SKUs case-insensitively after trim, HTML-unescaping and tag-stripping the description, and returning unmatched SKUs rather than raising (FR-005)
- [X] T011 [P] [US1] Implement `describe_image(path) -> str` in `src/instagram_story_agent/llm.py` using `AsyncAnthropic` with `claude-sonnet-5`, a base64 image block placed before the text block, and `thinking={"type": "adaptive"}` (FR-003)
- [X] T012 [US1] Implement `generate_script(topic, descriptions, products, slide_count) -> CampaignScript` in `src/instagram_story_agent/llm.py` using `claude-opus-5` with `src/resources/story-telling-rules.md` as system context and `output_config={"format": ...}` bound to the `CampaignScript` schema — no assistant prefill, it returns 400 on this model (FR-006, FR-007)
- [X] T013 [US1] Implement `generate_image(prompt, out_path, model)` in `src/instagram_story_agent/llm.py` using `genai.Client().interactions.create` with `response_format={"type":"image","mime_type":"image/jpeg","aspect_ratio":"9:16","image_size":"2K"}`, decoding `interaction.output_image.data` (FR-008)
- [X] T014 [US1] Implement `transcribe_audio(audio_path) -> str` in `src/instagram_story_agent/llm.py` via `client.files.upload` then `interactions.create` with `gemini-3.5-transcribe`, returning `""` when there is no audio (FR-004; substitution rationale in [research.md](./research.md) R2)
- [X] T015 [P] [US1] Add `extract_audio(video, out)` and `extract_frames(video, out_dir, count)` to `src/instagram_story_agent/ffmpeg.py` (FR-004)
- [X] T016 [US1] Add `wrap_text(text, font_size, max_width) -> str` to `src/instagram_story_agent/ffmpeg.py` measuring with `PIL.ImageFont.getlength` and returning newline-joined lines — measurement only, drawing stays in ffmpeg ([research.md](./research.md) R5)
- [X] T017 [US1] Implement `render_slide(background, overlay_text, out_path)` in `src/instagram_story_agent/ffmpeg.py`: `scale=1080:1920` → `drawbox` scrim → a single `drawtext` using **`textfile=`** (not `text=`) written to a temp file to avoid escaping the Cyrillic copy, with `line_spacing`, `fontfile=FONT_PATH`, and y clamped to the safe band (FR-009, SC-004)
- [X] T018 [US1] Implement `describe_inputs(input_dir) -> list[MediaDescription]` in `src/instagram_story_agent/workflow.py` fanning out over images, and for any video extracting frames → `describe_image` per frame → `transcribe_audio`, merged into one description (FR-003, FR-004)
- [X] T019 [US1] Implement `create_story_campaign(topic=None, slide_count=5) -> Campaign` in `src/instagram_story_agent/workflow.py`: read `content/input/topic.md` when topic is None → `extract_skus` → `get_products` → `describe_inputs` → `generate_script` → per-slide `generate_image` + `render_slide` under `asyncio.gather(..., return_exceptions=True)` → `save_project` (FR-001, FR-001a, FR-002, FR-010)
- [X] T020 [US1] Add fail-fast validation to `create_story_campaign` in `src/instagram_story_agent/workflow.py` rejecting `slide_count` outside 3–7 **before** any generation call, so no partial project directory is created (US1 scenario 4, [quickstart.md](./quickstart.md) V2)
- [X] T021 [US1] Add the URL guard in `src/instagram_story_agent/workflow.py`: assert no `SlideSpec.image_prompt` contains a URL before it reaches `generate_image`, while `product_url` is written into `script.json` (FR-006a, FR-008a, SC-005a)
- [X] T022 [US1] Implement `save_project(campaign) -> Path` in `src/instagram_story_agent/workflow.py` writing `content/output/<topic-slug>-<YYYYMMDD-HHMMSS>/` with `1.jpg`…`N.jpg` and `script.json`, keeping slides that succeeded and recording `failed_slides` as `(index, error)` (FR-011, FR-016, FR-017, SC-003)
- [X] T023 [US1] Implement `main()` in `src/instagram_story_agent/cli.py` with a `--slides` argument (default 5) calling `create_story_campaign` and printing the output directory plus any failed slides — this is the FR-015 programmatic entry point and needs no MCP server

**Checkpoint**: User Story 1 fully functional and testable via `uv run instagram-story-agent --slides 5`

---

## Phase 4: User Story 2 - Drive the same workflow from an AI chat (Priority: P2)

**Goal**: The same workflow reachable over stdio from Claude or any MCP chat client, with both brand documents readable as resources.

**Independent Test**: `npx @modelcontextprotocol/inspector uv run python -m instagram_story_agent.server` lists 10 tools and 2 resources, and `describe_image` returns prose for a file in `content/input/`. Covers [quickstart.md](./quickstart.md) V9.

> Built on `mcp.server.MCPServer` — **`mcp.server.fastmcp` does not exist in the installed v2 SDK** ([research.md](./research.md) R4). `server.py` holds registration and marshalling only; all logic stays in the US1 modules.

### Implementation for User Story 2

- [X] T024 [US2] Create `src/instagram_story_agent/server.py` instantiating `MCPServer(name="instagram-story-agent", version="0.1.0")` with a `python -m` entry calling `mcp.run(transport="stdio")` — note `run()` is synchronous, not a coroutine
- [X] T025 [US2] Register the workflow tools in `src/instagram_story_agent/server.py` with `@mcp.tool()`: `create_story_campaign`, `save_project`, delegating to `workflow.py` with the signatures in [contracts/mcp-tools.md](./contracts/mcp-tools.md)
- [X] T026 [P] [US2] Register the content tools in `src/instagram_story_agent/server.py`: `get_product`, `describe_image`, `generate_image`, `generate_storytelling_script`, `render_story_slide`
- [X] T027 [P] [US2] Register the video tools in `src/instagram_story_agent/server.py`: `transcribe_video` (extract audio → transcribe) and `describe_video` (frames → describe each → merge with transcript)
- [X] T028 [US2] Register both resources in `src/instagram_story_agent/server.py` with `@mcp.resource(uri)`: `content://story-design-guidelines.md` and `content://story-telling-rules.md`, served verbatim as `text/markdown` (FR-014)
- [X] T029 [US2] Register the `story_campaign` prompt in `src/instagram_story_agent/server.py` with `@mcp.prompt()` taking `topic` and `slide_count`, instructing the client to read both resources before calling `create_story_campaign`
- [X] T030 [US2] Create `src/instagram_story_agent/client.py` with `async run_campaign(topic=None, slide_count=5)` opening `Client(server)` against the in-memory `MCPServer` object and calling `create_story_campaign` — no subprocess, no transport wiring ([research.md](./research.md) R4)

**Checkpoint**: User Stories 1 and 2 both work independently

---

## Phase 5: User Story 3 - Revise one slide after review (Priority: P3)

**Goal**: Redo a single slide from a written comment, leaving every other slide byte-identical.

**Independent Test**: Generate a campaign, md5 the slides, regenerate slide 3 with a comment, md5 again — exactly one line differs. Covers [quickstart.md](./quickstart.md) V7.

### Implementation for User Story 3

- [X] T031 [US3] Implement `regenerate_slide(project_dir, slide_index, comment) -> Path` in `src/instagram_story_agent/workflow.py`: load `script.json`, revise that slide's `image_prompt`/`overlay_text` from the comment, regenerate with **`gemini-3-pro-image`**, re-render, and overwrite only `<index>.jpg` (FR-012)
- [X] T032 [US3] Persist the revised `SlideSpec` back into `script.json` in `src/instagram_story_agent/workflow.py`, rewriting only that entry so the other slide records are unchanged
- [X] T033 [US3] Register `regenerate_slide` as a tool in `src/instagram_story_agent/server.py` per [contracts/mcp-tools.md](./contracts/mcp-tools.md)

**Checkpoint**: All user stories independently functional

---

## Phase 7: Browser Rendering & Verification (amendment)

**Why**: The ffmpeg `drawtext` overlay stamped a flat band at a fixed position, frequently across the dog's face. Slides are now laid out as HTML/CSS with the background in view and screenshotted in headless Chromium, and every rendered slide is verified. See [research.md](./research.md) R9 and R10.

**Independent Test**: Run a campaign and confirm each slide places its copy clear of the subject, uses Bitter + Noto Sans, and carries a verdict in `script.json`.

- [X] T042 Add `playwright>=1.62` to `pyproject.toml` and install Chromium with `uv run playwright install chromium`
- [X] T043 Create `src/instagram_story_agent/slide_html.py` rendering a slide document at 1080×1920 via Playwright, loading it over `file://` so the relative `background.jpg` resolves, and awaiting `document.fonts.ready` before the screenshot
- [X] T044 Add `SlideVerdict` to `src/instagram_story_agent/models.py` and a `verdicts` field to `Campaign`
- [X] T045 Add Bitter + Noto Sans via Google Fonts and `SCREENSHOT_QUALITY` to `src/instagram_story_agent/config.py`, removing the now-unused `FONT_PATH`
- [X] T046 Implement `generate_slide_html(slide, background, issues)` in `src/instagram_story_agent/llm.py` — the layout model sees the background image and places copy clear of the subject, with the design guidelines sent as a cached system prompt
- [X] T047 Implement `verify_slide(image, slide)` in `src/instagram_story_agent/llm.py` returning a `SlideVerdict`; a missing verdict must fail rather than silently pass, and `max_tokens` must leave room beside adaptive thinking
- [X] T048 Rewire `_build_slide` in `src/instagram_story_agent/workflow.py` to background → HTML → screenshot → verify, retrying once with the reported issues as feedback and keeping the best attempt
- [X] T049 Strip `render_slide`, `build_filter` and `wrap_text` from `src/instagram_story_agent/ffmpeg.py`, and call `require_ffmpeg()` lazily so an images-only campaign needs no ffmpeg
- [X] T050 Register `validate_slide` in `src/instagram_story_agent/server.py` and switch `render_story_slide` to the HTML path
- [X] T051 Add `--no-verify` to `src/instagram_story_agent/cli.py` and print flagged slides
- [X] T052 [P] Add `tests/unit/test_slide_html.py` covering fence stripping and the screenshot dimensions
- [X] T053 [P] Replace the drawtext tests in `tests/unit/test_ffmpeg.py`, and extend `tests/unit/test_workflow.py` with the verify/retry/skip paths
- [X] T054 Update `tests/contract/test_server.py` for 11 tools, `validate_slide` now present

**Checkpoint**: Slides are designed rather than stamped, and every one carries a verdict

---

## Phase 8: Product Fidelity & Slide Count (amendment)

**Why**: Image generation was inventing the packaging — a right-shaped bottle with a fictional label and no brand name. The real product photo is now supplied as a reference. Separately, the script model returned six slides for a request of five. See [research.md](./research.md) R11 and R12.

**Independent Test**: Run a campaign and confirm the container on product slides matches `content/input/` photography, and that the slide count equals what was requested.

- [X] T055 Add `shows_product` to `SlideSpec` and `MediaDescription`, and `product_references` to `Campaign`, in `src/instagram_story_agent/models.py`
- [X] T056 Replace `describe_image` with `inspect_image` in `src/instagram_story_agent/llm.py`, returning `{description, shows_product}` so packshots are identifiable; keep `describe_image` as a wrapper for the MCP tool
- [X] T057 Give `generate_image` a `references` parameter in `src/instagram_story_agent/llm.py`, passing image blocks to Gemini with an explicit product-fidelity instruction
- [X] T058 Stop the script prompt from describing packaging in `src/instagram_story_agent/llm.py`: product slides describe the setting, and mark `shows_product`
- [X] T059 Add `product_references()` to `src/instagram_story_agent/workflow.py` and pass packshots only to slides with `shows_product`
- [X] T060 Persist `product_references` in `script.json` so `regenerate_slide` reuses them instead of re-describing every input
- [X] T061 Add `fit_to_count()` to `src/instagram_story_agent/llm.py` enforcing the requested slide count, one slide per role, CTA last, failing before any image is generated
- [X] T062 [P] Extend `tests/unit/test_workflow.py` with reference selection, the packshot reaching only product slides, and slide-count enforcement

**Checkpoint**: The real product appears on product slides, and a campaign is exactly as long as requested

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T034 [P] Add unit tests in `tests/unit/test_products.py` for `extract_skus` (must find `BO-FIU150` in the real `content/input/topic.md` and reject ordinary uppercase words) and for the HTML strip (must leave no `&lt;p&gt;` or tags)
- [X] T035 [P] Add unit tests in `tests/unit/test_ffmpeg.py` for `wrap_text` line breaking and for the built filter string — assert the `textfile=` form is used and no unescaped `:` or `'` reaches an inline `text=`
- [X] T036 [P] Add a contract test in `tests/contract/test_server.py` using `Client(server)` in memory: 10 tools listed, `validate_slide` absent, both `content://` resources readable
- [X] T037 Add the ffmpeg-missing preflight error to `src/instagram_story_agent/cli.py` and `server.py` so a missing binary reports a clear install instruction instead of a subprocess traceback
- [X] T038 [P] Update `pyproject.toml` `description` — it currently says "Turns a Drive folder of assets…", describing a Drive-based design this feature does not implement
- [X] T039 Run `uv run ruff check --fix src tests` and resolve remaining lint under the configured `E,F,I,UP,B,SIM` rules
- [X] T040 Walk [quickstart.md](./quickstart.md) V1–V9 end to end and record results, including the SC-002 timing for a 5-slide campaign
- [X] T041 Note the two accepted deviations in `README.md`: `gemini-3.5-transcribe` substituted for the image model named in `requirements.md`, and the system-font fallback in place of Bitter + Noto Sans

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies. T001 (ffmpeg) blocks every render and video task
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational only. Self-contained — no MCP
- **User Story 2 (Phase 4)**: Depends on Foundational, and calls US1's `workflow.py`/`llm.py` functions
- **User Story 3 (Phase 5)**: Depends on Foundational; reuses US1's `generate_image` and `render_slide`, and T033 needs `server.py` from US2
- **Polish (Phase 6)**: Depends on the stories being delivered

### User Story Dependencies

- **US1 (P1)**: Independent. Delivers the whole workflow behind a CLI
- **US2 (P2)**: Thin registration layer over US1. Independently testable via the MCP Inspector, but has nothing to expose without US1
- **US3 (P3)**: Needs a saved project from US1 to revise. T031–T032 are independent of US2; only T033 (tool registration) touches `server.py`

This is the one place the stories are not fully independent, and it is inherent: US2 and US3 expose and refine what US1 produces.

### Within Each User Story

- Models before services; services before registration
- Same-file tasks are sequential (no `[P]`): T009→T010 in `products.py`, T011→T012→T013→T014 in `llm.py`, T015→T016→T017 in `ffmpeg.py`, T018→T019→T020→T021→T022 in `workflow.py`

### Parallel Opportunities

- T004, T005 in Setup
- T009, T011, T015 open the three US1 modules simultaneously
- T026, T027 register disjoint tool groups (coordinate if editing one file)
- T034, T035, T036, T038 in Polish

---

## Parallel Example: User Story 1

```bash
# Open the three independent modules at once (different files):
Task: "Implement extract_skus in src/instagram_story_agent/products.py"
Task: "Implement describe_image in src/instagram_story_agent/llm.py"
Task: "Add extract_audio and extract_frames in src/instagram_story_agent/ffmpeg.py"

# Then continue sequentially within each file:
#   products.py : T010
#   llm.py      : T012 -> T013 -> T014
#   ffmpeg.py   : T016 -> T017
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1 Setup — **T001 first**; nothing renders without ffmpeg
2. Phase 2 Foundational
3. Phase 3 User Story 1
4. **STOP and VALIDATE**: `uv run instagram-story-agent --slides 5` against the existing `content/input/`, then walk V1–V6 and V8
5. This alone satisfies the spec's primary value — a saved campaign from a brief and images

### Incremental Delivery

1. Setup + Foundational → foundation ready
2. US1 → validate → **MVP**, usable from code
3. US2 → validate with the MCP Inspector → usable from Claude chat
4. US3 → validate with the md5 comparison → single-slide revision

### Parallel Team Strategy

US1 is most of the work and is best kept with one owner, split by module (`products.py` / `llm.py` / `ffmpeg.py` in parallel, then `workflow.py`). US2 can start as soon as US1's `workflow.py` signatures are settled, before its bodies are finished.

---

## Notes

- `[P]` = different files, no dependencies
- Tests are deliberately minimal (T034–T036), covering only the parsing and escaping that Phase 0 flagged as bug-prone; [quickstart.md](./quickstart.md) V1–V9 is the real acceptance pass
- `validate_slide` is **not** a task — deferred by `requirements.md` and excluded in the spec's Assumptions
- Commit after each task or logical group; stop at any checkpoint to validate a story independently
