# Contract: MCP Server Surface

**Feature**: [../spec.md](../spec.md) · **Transport**: stdio · **SDK**: `mcp` 2.1.0 (`MCPServer`, see [../research.md](../research.md) R4)

Registered with `@mcp.tool()` / `@mcp.resource(uri)` / `@mcp.prompt()`. Input schemas are generated from type hints, so the signatures below **are** the wire contract. Satisfies FR-013 and FR-014.

Anticipated failures (bad slide count, missing file, ffmpeg absent) are raised as `ToolError` so the message reaches the client; anything else is treated as a crash and its text withheld by the SDK.

Server identity: `MCPServer(name="instagram-story-agent", version="0.1.0")`, run with `mcp.run(transport="stdio")`.

---

## Tools

### `create_story_campaign`
The entry point; runs the whole workflow (FR-001, FR-010, FR-011).

```python
async def create_story_campaign(
    topic: str | None = None,   # defaults to content/input/topic.md
    slide_count: int = 5,       # 3..7
    verify: bool = True,        # run the verification pass on each slide
) -> dict
```
Returns `{output_dir, slides: [path], script: {...}, missing_skus: [...], failed_slides: [[index, error]], verdicts: [{index, passed, issues, notes}]}`.
Errors: `slide_count` outside 3–7 → rejected before any generation, no partial project.

### `create_post_campaign`
```python
async def create_post_campaign(
    topic: str | None = None,
    slide_count: int = 5,
    verify: bool = True,
) -> dict
```
Identical to `create_story_campaign` but on a **1:1 square artboard** (1080×1080) for an Instagram feed post. Same pipeline, same brand rules, same return shape; only the format differs. A feed post carries none of the story UI, so the safe area is the margin rather than `y = 250…1670`.

Both campaign tools return a `format` field naming the artboard used, and the format is persisted in `script.json` so `regenerate_slide` re-renders at the right size.

### `create_lifestyle_content`
```python
async def create_lifestyle_content(
    topic: str | None = None,
    image_count: int = 3,
    verify: bool = True,
) -> dict
```
Lifestyle product photography for **every** SKU named in the brief — `image_count` is per product, so three SKUs at 3 each yields nine frames. Returns `{output_dir, format, images_per_product, sets, skipped, images, missing_skus, failed_images, verdicts}`, where each entry of `sets` carries its own `sku`, `product`, `packshot`, `images`, `shots` and `verdicts`.

Reuses SKU lookup, product-referenced generation and verification, but has **no script or layout step** — `content://lifestyle-content-brief.md` §10 makes baked-in text an automatic reject, so a frame is the finished deliverable. Frames are 4:5, normalised to 1080×1350 per §9. The packshot comes from the catalogue image URL. A product whose image cannot be obtained is **skipped** and listed in `skipped` with the reason (FR-008d); a photo from `content/input/` is a fallback only when the brief names a single product.

### `get_product`
```python
def get_product(skus: list[str]) -> dict
```
Returns `{products: [Product], missing: [sku]}`. Fields per [../data-model.md](../data-model.md). A missing SKU is reported, not raised (FR-005).

### `generate_storytelling_script`
```python
async def generate_storytelling_script(
    topic: str,
    descriptions: list[str],
    products: list[dict],
    slide_count: int = 5,
) -> dict
```
Returns a `CampaignScript`. Uses `claude-opus-5` with `story-telling-rules.md` as context (FR-006, FR-007).

### `generate_image`
```python
async def generate_image(
    prompt: str, out_path: str, references: list[str] | None = None
) -> str
```
Gemini image model from config, `aspect_ratio="9:16"`, `image_size="2K"`. Returns the written path (FR-008).
**The caller must not put a URL in `prompt`** (FR-008a).
Pass `references` — paths to real product photographs — on any image showing the product, so the real container is reproduced rather than invented (FR-008b). The campaign workflow does this automatically for slides flagged `shows_product`; step-by-step callers must pass them explicitly.

### `render_story_slide`
```python
async def render_story_slide(
    background_path: str,
    overlay_text: str,
    out_path: str,
    role: str = "solution",
    slide_index: int = 1,
) -> str
```
Lays the slide out as HTML/CSS with the background in view, then screenshots it at 1080×1920 in headless Chromium. Copy is placed around the subject and kept inside `y = 250…1670` (FR-009, FR-009a).

### `validate_slide`
```python
async def validate_slide(
    image_path: str,
    overlay_text: str,
    role: str = "solution",
    slide_index: int = 1,
) -> dict
```
Views the rendered slide and returns a `SlideVerdict` — `{index, passed, issues, notes}` — judged against the design guidelines and the copy it should display (FR-009b).

### `regenerate_slide`
```python
async def regenerate_slide(
    project_dir: str,
    slide_index: int,
    comment: str,
) -> str
```
Re-runs prompt → `gemini-3-pro-image` → render for one slide only; other slides are untouched (FR-012, SC-007).

### `describe_image`
```python
async def describe_image(image_path: str) -> str
```
`claude-sonnet-5`, base64 image block (FR-003).

### `transcribe_video`
```python
async def transcribe_video(video_path: str) -> str
```
ffmpeg extracts the audio track → `gemini-3.5-transcribe` (FR-004; substitution explained in [../research.md](../research.md) R2).
Returns `""` when the file carries no audio track.

### `describe_video`
```python
async def describe_video(video_path: str, frame_count: int = 10) -> str
```
ffmpeg samples frames evenly across the clip → `describe_image` per frame → merged with the transcript (FR-004). `frame_count` is clamped to 5–10; the rate is derived from the clip's duration so a long video is covered end to end, not just its opening seconds (FR-004a).

### `save_project`
```python
def save_project(campaign: dict) -> str
```
Writes slides + `script.json` to `content/output/<slug>-<YYYYMMDD-HHMMSS>/`, returns the directory (FR-011).

---

## Resources

| URI | MIME | Backing file |
|---|---|---|
| `content://story-design-guidelines.md` | `text/markdown` | `src/resources/story-design-guidelines.md` |
| `content://story-telling-rules.md` | `text/markdown` | `src/resources/story-telling-rules.md` |
| `content://lifestyle-content-brief.md` | `text/markdown` | `src/resources/lifestyle-content-brief.md` |

Both are served verbatim.

---

## Prompts

| Name | Arguments | Purpose |
|---|---|---|
| `story_campaign` | `topic: str`, `slide_count: int = 5` | Guides a chat client through a campaign. Covers both routes: the one-shot `create_story_campaign`, and the atomic tools (`get_product`, `describe_image`, `generate_storytelling_script`, `generate_image`, `render_story_slide`, `validate_slide`, `regenerate_slide`) for building a story step by step, with the constraints that are easy to get wrong. |

---

## Python module contract (FR-015)

`src/instagram_story_agent/client.py` uses the in-memory client — no subprocess ([../research.md](../research.md) R4):

```python
from instagram_story_agent.client import run_campaign
campaign = await run_campaign(topic=None, slide_count=5)
```

`run_campaign` opens `Client(server)` against the same `MCPServer` object and calls `create_story_campaign`, so the module and the chat path exercise identical code.
