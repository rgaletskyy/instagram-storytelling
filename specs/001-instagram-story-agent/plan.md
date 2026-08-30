# Implementation Plan: Instagram Story Telling Agent

**Branch**: `001-instagram-story-agent` | **Date**: 2026-08-27 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-instagram-story-agent/spec.md`

## Summary

Turn a Ukrainian topic brief plus local product photos into a saved folder of ready-to-post Instagram story slides. The brief names a product SKU inline; that SKU is looked up in a static spreadsheet, the images are described by Sonnet, Opus writes a slide-by-slide script constrained by the brand's story-telling rules, Gemini generates a 9:16 background per slide, and ffmpeg burns the overlay text on. The same workflow is reachable three ways — an MCP server over stdio for chat clients, an MCP client, and a code-callable module.

The design leans on three findings from Phase 0 that remove most of the code this would otherwise need: MCP v2's `Client(server)` gives an in-memory client with no subprocess, so the "MCP client" and "Python module" requirements collapse into a few lines each; Gemini's Interactions API takes `aspect_ratio="9:16"` natively, so no cropping logic is needed; and ffmpeg's `drawtext textfile=` sidesteps the escaping rules that Cyrillic overlay copy would otherwise trip. Full details in [research.md](./research.md).

## Technical Context

**Language/Version**: Python 3.14.6 (`.venv`, uv-managed)

**Primary Dependencies**: `mcp` 2.1 · `anthropic` 1.x · `google-genai` 2.19+ · `playwright` 1.62 (+ Chromium) · `pydantic` 2.13 · `openpyxl` 3.1 · `pillow` 12.3 · ffmpeg (external, **video input only**)

**Storage**: Filesystem only. Input `content/input/`, output `content/output/<slug>-<timestamp>/`, catalogue `src/resources/products.xlsx`. No database.

**Testing**: pytest 9.1.1 with the markers already declared in `pyproject.toml` (`unit`, `contract`, `integration`, `slow`); `asyncio_mode = "auto"` is set.

**Target Platform**: Local macOS (darwin 24.6.0), single user, stdio transport.

**Project Type**: Single Python package with an MCP server front end.

**Performance Goals**: SC-002 targets a 5-slide campaign under 5 minutes, with slides generated concurrently (FR-010). The layout and verification passes added in R9/R10 push a verified run to roughly 5 minutes; `--no-verify` returns it to about 2 minutes.

**Constraints**: Slides 1080×1920, text confined to `y = 250…1670` (SC-004). Product URL in the script, never in an image (FR-008a). 3–7 slides. **Minimum code** — the user's explicit instruction, restated in the spec's first Assumption.

**Scale/Scope**: 11 MCP tools, 2 resources, 1 prompt; 10 source modules; one user, one campaign at a time.

### Models (pinned — [research.md](./research.md) R1, R2)

| Job | Model |
|---|---|
| Describe image / video frames | `claude-sonnet-5` |
| Generate campaign script | `claude-opus-5` |
| Generate background | `gemini-3.1-flash-image` |
| Regenerate background | `gemini-3-pro-image` |
| Transcribe audio | `gemini-3.5-transcribe` **(substituted — see below)** |
| Lay out a slide (sees the background) | `claude-sonnet-5` |
| Verify a rendered slide | `claude-sonnet-5` |

## Constitution Check

*GATE: must pass before Phase 0, re-checked after Phase 1.*

`.specify/memory/constitution.md` is **the unedited template** — every principle is still a `[PRINCIPLE_N_NAME]` placeholder. There are no ratified principles to gate against, so no gate can fail and none is waived.

In their place, the operative constraint is the user's explicit instruction, carried into the spec's Assumptions: **keep the code to a minimum.** The design is checked against it directly:

| Check | Result |
|---|---|
| No abstraction without a second caller | Pass — one concrete implementation per tool, no strategy/factory layers |
| No configuration framework | Pass — env vars and module constants only |
| Reuse what is installed | Pass — one new dependency (`openpyxl`), no new HTTP or job-queue layer |
| No speculative extension points | Pass — `validate_slide` is deferred, not stubbed behind an interface |
| Thinnest client for FR-015 | Pass — in-memory `Client(server)`, no subprocess or transport code |

**Post-Phase-1 re-check**: still passing. The design added no layer beyond the nine modules below; `client.py` and `cli.py` are each a handful of lines because the MCP v2 in-memory client does the work.

### Deviations recorded

| Deviation | From | Why |
|---|---|---|
| `gemini-3.5-transcribe` replaces `gemini-3.1-flash-lite-image` for audio | `requirements.md` | The specified model generates images and cannot accept audio input. Not implementable as written ([research.md](./research.md) R2). |
| ~~System font instead of Bitter + Noto Sans~~ **RESOLVED** | `story-design-guidelines.md` **MUST** | Browser rendering loads Bitter and Noto Sans from Google Fonts, so the mandated typefaces are now used ([research.md](./research.md) R9). |
| ~~ffmpeg draws the overlay text~~ **SUPERSEDED** | `requirements.md` | `drawtext` stamps text at a fixed position over the subject and cannot see the image. Slides now render as HTML in a browser; ffmpeg is video-only ([research.md](./research.md) R9). |

## Project Structure

### Documentation (this feature)

```text
specs/001-instagram-story-agent/
├── plan.md              # This file
├── research.md          # Phase 0 — model IDs, SDK surfaces, ffmpeg technique
├── data-model.md        # Phase 1 — Pydantic entities
├── quickstart.md        # Phase 1 — run + 9 validation scenarios
├── contracts/
│   └── mcp-tools.md     # Phase 1 — tool/resource/prompt signatures
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 — NOT created by /speckit-plan
```

### Source Code (repository root)

```text
src/
├── instagram_story_agent/          # package name already set in pyproject.toml
│   ├── __init__.py
│   ├── config.py                   # paths, env keys, model IDs, font path, canvas constants
│   ├── models.py                   # Product, SlideSpec, CampaignScript, MediaDescription, Campaign
│   ├── products.py                 # SKU regex + openpyxl lookup + HTML strip
│   ├── llm.py                      # Anthropic (describe, script, layout, verify) + Gemini (image, transcribe)
│   ├── ffmpeg.py                   # extract_audio, extract_frames (video only)
│   ├── slide_html.py               # Playwright screenshot of a slide document
│   ├── workflow.py                 # create_story_campaign, regenerate_slide, save_project
│   ├── server.py                   # MCPServer: 11 tools, 2 resources, 1 prompt
│   ├── client.py                   # in-memory Client(server) -> run_campaign  (FR-015)
│   └── cli.py                      # main() — the console script in pyproject.toml
└── resources/                      # already present
    ├── products.xlsx
    ├── slide-design-guidelines.md
    └── story-telling-rules.md

tests/
├── unit/                           # SKU regex, HTML strip, wrap, filter build, slide ordering
├── contract/                       # tool schemas via in-memory Client(server)
└── integration/                    # live keys, end-to-end campaign

content/
├── input/                          # topic.md + images (already populated)
└── output/                         # <slug>-<YYYYMMDD-HHMMSS>/
```

**Structure Decision**: Single package, flat — no `models/ services/ lib/` split. Nine modules, one responsibility each, matching the tool list in [contracts/mcp-tools.md](./contracts/mcp-tools.md). `src/instagram_story_agent/` is not a new choice: `pyproject.toml` already declares it in `[tool.hatch.build.targets.wheel]` and points the `instagram-story-agent` console script at `instagram_story_agent.cli:main`. `src/resources/` stays where it is because `requirements.md` references those paths directly.

`server.py` holds only registration and argument marshalling; the logic lives in `workflow.py`, so the module path (FR-015) and the chat path (FR-013) run the same code rather than two parallel implementations.

## Complexity Tracking

No constitution violations to justify — the constitution is an unfilled template with no ratified principles. Deviations from `requirements.md` and the design guidelines are recorded in the Constitution Check section above, each with its cause and reversibility.

## Phase status

- [x] Phase 0 — [research.md](./research.md): 8 findings, 0 open NEEDS CLARIFICATION
- [x] Phase 1 — [data-model.md](./data-model.md), [contracts/mcp-tools.md](./contracts/mcp-tools.md), [quickstart.md](./quickstart.md)
- [x] Phase 2 — [tasks.md](./tasks.md)
- [x] Phase 3 — implemented; amended by R9/R10 (browser rendering + verification)
