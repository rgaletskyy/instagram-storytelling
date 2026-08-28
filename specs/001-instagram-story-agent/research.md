# Phase 0 Research: Instagram Story Telling Agent

**Date**: 2026-08-27 · **Feature**: [spec.md](./spec.md)

All findings below were verified against the installed packages or live vendor docs, not recalled.

---

## R1. Claude model IDs and SDK surface

**Decision**: `claude-sonnet-5` for image/frame description; `claude-opus-5` for script generation. Anthropic Python SDK **1.0.0** is installed.

**Rationale**: `requirements.md` asks for "latest sonnet" for description and "latest claude opus" for the script. Verified current IDs via the bundled `claude-api` reference: exact strings are `claude-sonnet-5` and `claude-opus-5`, with **no date suffix**.

**Constraints that change the code**:

- `anthropic` 1.x is built on `httpx2`, not `httpx`. `pyproject.toml` currently pins `anthropic>=0.40` (a 0.x pin) while 1.0.0 is installed — the pin must be raised to `>=1.0`.
- Thinking: use `thinking={"type": "adaptive"}`. `budget_tokens` is **removed** on both models and returns a 400.
- Assistant prefill is removed on both models (400). Use `output_config={"format": ...}` for structured script output instead.
- Vision input is base64 blocks: `{"type": "image", "source": {"type": "base64", "media_type": ..., "data": ...}}`, image block before the text block.

**Alternatives considered**: Haiku 4.5 for description (cheaper) — rejected, `requirements.md` explicitly specifies Sonnet, and description quality drives the whole script.

---

## R2. Gemini model IDs — one requirement is not implementable as written

**Decision**:

| Job | Model | Source |
|---|---|---|
| Generate slide background | `gemini-3.1-flash-image` (Nano Banana 2) | as specified |
| Regenerate slide background | `gemini-3-pro-image` (Nano Banana Pro) | as specified |
| Transcribe extracted audio | **`gemini-3.5-transcribe`** | **substituted** |

**Rationale**: The first two IDs in `requirements.md` are correct and GA. The third is not: `requirements.md` says "Use gemini-3.1-flash-lite-image to transcribe audio into text", but `gemini-3.1-flash-lite-image` (Nano Banana 2 Lite) is an **image-generation** model and does not accept audio input. Google ships a dedicated speech-to-text model, `gemini-3.5-transcribe`, which is the correct target. `gemini-3.5-flash` / `gemini-3.7-flash` also accept audio and are the fallback if the dedicated model is unavailable on the key.

**This is a deliberate deviation from `requirements.md` and is flagged for the user.** Everything else in that section is honoured verbatim.

**Alternatives considered**: Claude for transcription — rejected, Claude models do not accept audio input at all.

---

## R3. Gemini SDK is the Interactions API, not `generate_content`

**Decision**: Use `client.interactions.create(...)` from `google-genai` **2.19.0** (installed).

**Rationale**: `generate_content` is now documented as the *legacy* surface. The current call shape is:

```python
from google import genai
client = genai.Client()
interaction = client.interactions.create(
    model="gemini-3.1-flash-image",
    input="<prompt>",
    response_format={"type": "image", "mime_type": "image/jpeg",
                     "aspect_ratio": "9:16", "image_size": "2K"},
)
image_bytes = base64.b64decode(interaction.output_image.data)
```

**Why this matters here**: `response_format.aspect_ratio: "9:16"` is native. The design guidelines require a 1080×1920 portrait artboard, so the backgrounds come out already in the right aspect at 2K and need only a downscale — no cropping logic to write.

Audio goes through the Files API first: `client.files.upload(file=...)` → pass `{"type": "audio", "uri": ..., "mime_type": ...}` → read `interaction.output_text`.

Note: all generated images carry a SynthID watermark.

---

## R4. MCP Python SDK v2 — FastMCP is gone

**Decision**: Build on `mcp.server.MCPServer` and `mcp.Client`. Installed version is **2.1.0**; `pyproject.toml` pins `mcp>=1.2` and must be raised to `>=2.1`.

**Rationale**: Verified by introspecting the installed package. `mcp.server.fastmcp` **does not exist** in v2 — any `from mcp.server.fastmcp import FastMCP` code is dead on this install. Confirmed signatures:

```python
MCPServer(name=..., title=..., description=..., version=...)
@mcp.tool(name=None, title=None, description=None, structured_output=None, ...)
@mcp.resource(uri, *, name=None, mime_type=None, ...)
@mcp.prompt(name=None, title=None, description=None, ...)
mcp.run(transport="stdio")            # synchronous, not a coroutine
```

**Key simplification for the client and the Python module**: `mcp.Client.__init__` accepts `Server | MCPServer | Transport | StdioServerParameters | str`. Passing the **`MCPServer` object itself** gives an in-memory client with no subprocess and no transport wiring:

```python
from mcp import Client
async with Client(server) as client:
    result = await client.call_tool("create_story_campaign", {...})
```

This collapses FR-015 (programmatic entry point) and the MCP client requirement into a few lines each, and lets the whole workflow be tested without spawning a process. The stdio path (`StdioServerParameters`) remains available for real chat clients.

**Alternatives considered**: hand-rolling the low-level `mcp.server.lowlevel.Server` — rejected, `MCPServer` generates input schemas from type hints and is far less code.

---

## R5. Rendering with ffmpeg — decided by the user

**Decision**: All slide rendering goes through **ffmpeg** `drawtext` / `drawbox`, per `requirements.md`. **ffmpeg is not currently installed on this machine** and becomes a hard prerequisite (`brew install ffmpeg`).

The user was offered Pillow (already a dependency, fewer lines) and explicitly chose ffmpeg for everything.

**Two techniques that keep the filter code small**:

1. **`textfile=` instead of `text=`.** `drawtext` can read its string from a file. This sidesteps ffmpeg's escaping rules entirely — `:`, `'`, `%`, `\` and `,` all need escaping in an inline `text=`, and the copy here is Ukrainian Cyrillic with punctuation. Writing each overlay to a temp `.txt` and pointing `textfile=` at it removes that whole class of bug.
2. **One `drawtext` per text block, not per line.** `drawtext` renders embedded newlines from a `textfile` and honours `line_spacing`, so a pre-wrapped multi-line block is a single filter rather than one filter per line.

**Remaining gap**: ffmpeg has no text-measurement API, so line wrapping must be computed before the filter is built. Measurement will use `PIL.ImageFont.getlength()` (Pillow 12.3.0 is already installed) purely to decide where to break lines — **all drawing is still ffmpeg**. This keeps the wrap helper to a few lines instead of a hand-tuned character-count heuristic.

**Filter shape per slide**: `scale` to 1080×1920 → `drawbox` for the scrim/card → `drawtext` per text block, positioned inside the safe band `y = 250…1670`.

---

## R6. Fonts — accepted deviation

**Decision**: Render with a system font (`/System/Library/Fonts/Supplemental/Arial Bold.ttf`), path configurable via env.

**Rationale**: `story-design-guidelines.md` states **MUST**: Bitter (headings) + Noto Sans (body), "never substitute system fonts". Neither file is in the repo. The user chose the system-font fallback for now over vendoring the `.ttf` files.

**This is a known, accepted violation of a MUST in the design guidelines.** Both fonts are SIL OFL licensed and can be dropped into `src/resources/fonts/` later; the only change required is the font-path constant, because `drawtext` takes `fontfile=` either way.

---

## R7. Product catalogue

**Decision**: Read `src/resources/products.xlsx` with **openpyxl** (read-only mode). **openpyxl is not installed** and is a new dependency.

**Rationale**: Verified the real sheet by unzipping it. Header row:

| Column | Field |
|---|---|
| `Артикул` | SKU — the lookup key |
| `Название (UA)` | product name (shortened for overlays) |
| `Цена` | price |
| `Фото` | main image URL |
| `Ссылка` | product page URL → the CTA link sticker (FR-006a) |
| `Описание товара (UA)` | description, contains HTML markup |

Two consequences: the description field holds escaped HTML (`&lt;p&gt;&lt;strong&gt;…`) and must be unescaped and stripped to plain text before it reaches a prompt; and SKUs are matched **case-insensitively after trimming**, since they are typed by hand into the brief.

**SKU extraction (FR-001a)**: the brief names the SKU inline — `content/input/topic.md` currently reads `…Face It up (BO-FIU150)`. Catalogue SKUs match `[A-Z]{2,4}-[A-Z0-9-]+`. Extract with that regex, then validate each candidate against the sheet and silently drop non-matches, so ordinary uppercase words in the brief cannot produce phantom lookups.

**Alternatives considered**: `pandas` — rejected, a heavy dependency for one sheet read. Converting the sheet to CSV — rejected, it would drift from the file the user maintains.

---

## R8. Parallel slide generation (FR-010)

**Decision**: `asyncio.gather` over per-slide coroutines, with `return_exceptions=True`.

**Rationale**: The work is network-bound (one image-generation call per slide) plus a short subprocess per render, so asyncio fits without threads. `return_exceptions=True` is what satisfies FR-016 and SC-003 — a failed slide is reported by index while the rest of the campaign still lands, instead of one exception discarding the run. ffmpeg is invoked with `asyncio.create_subprocess_exec`.

---

## R9. Slides render as HTML in a browser, not as an ffmpeg overlay (supersedes R5, R6)

**Decision**: Compose each slide as an HTML/CSS document and screenshot it with Playwright + Chromium at 1080x1920. ffmpeg is now used **only** for video input.

**Rationale**: The first implementation burnt text on with `drawtext`. It worked, but produced a flat grey band stamped at a fixed position, frequently across the dog's face -- the subject the story is about. `drawtext` has no notion of what is in the image, no text wrapping, no real typography.

Laying the slide out in CSS fixes all three at once:

- The layout model **sees the background image** and places copy in a calm region, avoiding the eyes, face and product (FR-009a). A filter chain cannot do this at any complexity.
- Real typography: weights, letter-spacing, gradient scrims, rounded cards, accent colours -- the vocabulary the design guidelines are written in.
- **The font deviation in R6 is resolved.** The page loads Bitter and Noto Sans from Google Fonts, so the guidelines' mandated typefaces are used rather than substituted. `document.fonts.ready` is awaited before the screenshot, otherwise the capture lands on fallback fonts.

**Consequences**:

- New dependency: `playwright` 1.62 plus a ~95MB Chromium download (`playwright install chromium`).
- `drawtext`, and therefore a libfreetype ffmpeg build, is **no longer needed**. The `.tools/` binary is only required if video input is used; Homebrew's ffmpeg is now sufficient.
- An images-only campaign needs no ffmpeg at all -- `require_ffmpeg()` is called lazily, only when a video is present.
- The document is loaded over `file://` rather than `set_content`, because `set_content` has no base URL and the relative `background.jpg` reference would silently fail.

**Alternatives considered**: Pillow (the original R5 alternative) -- rejected now for the same reason as ffmpeg: it draws where it is told and cannot reason about the image. Templated HTML with fixed slots -- rejected, it reintroduces the fixed-position problem the pivot exists to solve.

---

## R10. Verification is a model looking at the rendered slide

**Decision**: After rendering, `claude-sonnet-5` views the slide image alongside the design guidelines and the copy it should show, and returns a structured `SlideVerdict`. A failed slide is re-laid-out once with the issues fed back in.

**Rationale**: The rendering step is generative, so its output cannot be trusted by construction -- the only way to know a slide is acceptable is to look at it. Programmatic checks can confirm dimensions but not "the headline sits on the dog's face" or "white text on a white tile wall".

Two implementation details that matter:

- **`max_tokens` must be generous (8000).** Adaptive thinking shares the budget; at 2000 the verdict was truncated and `parsed_output` came back `None`.
- **A missing verdict must fail, not pass.** The first version returned `passed=True` when the model returned nothing, which made a broken verifier indistinguishable from a clean run. It now returns `passed=False` carrying the `stop_reason`.

The design guidelines (~32K chars) are sent as a cached system prompt, so the per-slide cost of re-sending them is small.

**Alternatives considered**: pixel-level assertions for the safe band -- kept as a cheap complement but insufficient alone; a second opinion from Opus -- rejected as cost for little gain at this stage.

---

## R11. The product is photographed, not imagined

**Decision**: Pass the user's own product photograph to Gemini as a reference image on any slide that features the product, with an explicit fidelity instruction. Slides are flagged `shows_product` by the script model, and input photos are flagged `shows_product` by the description step.

**Rationale**: Left to itself the image model produced a white pump bottle of roughly the right silhouette carrying an entirely fictional label -- no brand name, no product text, a generic fruit motif. Plausible, and wrong in exactly the way that matters for a brand campaign.

Gemini's Interactions API accepts input images alongside the prompt, so the real packshot is supplied and the model relights and places it rather than inventing it. Verified against the real `BO-FIU150` photo: the Q mark, "BOTANIQA / exclusively for Pets", "FACE IT UP SHAMPOO", the melon splash and the claims line all survive into the generated scene.

Two supporting changes:

- The **script prompt no longer describes packaging**. For product slides it describes the setting and how the product sits in it, because the label comes from the photograph. Describing the label in words is what invited the model to redraw it.
- **`describe_image` became `inspect_image`**, returning `{description, shows_product}`. One call still, now structured, so the workflow knows which of the supplied photos is a usable packshot. `describe_image` remains as a thin wrapper for the MCP tool.

**Caveat**: fine print on the label is still slightly garbled in generated scenes ("FOAMING FACE WASH" can come back as "FORMINC FREE WASH"). Image models remain weak at small text. At story scale on a phone it reads correctly; for a hero packshot, composite the real photo rather than generating it.

**Note on the model**: `GEMINI_IMAGE_MODEL` is set to `gemini-3-pro-image` (Nano Banana Pro), which Google documents as the strongest for brand consistency and reference adherence -- the right trade for product fidelity.

---

## R12. The requested slide count has to be enforced

**Decision**: `fit_to_count()` trims the script to exactly the requested length -- one slide per narrative role, CTA last -- and raises before any image is generated if too few usable slides came back.

**Rationale**: Asked for five slides, the script model returned **six, with the hook duplicated**. The prompt said "exactly 5"; that was not enough, and nothing downstream checked. The only validation was the 3-7 bound, which six satisfies.

Enforcing it costs nothing: script generation runs before any image call, so a failure here is instant and free.

---

## Resolved unknowns

Every NEEDS CLARIFICATION raised in Technical Context is closed above. No open questions remain.
