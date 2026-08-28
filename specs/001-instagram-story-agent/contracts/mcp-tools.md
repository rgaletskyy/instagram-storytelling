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
async def generate_image(prompt: str, out_path: str) -> str
```
Gemini image model from config, `aspect_ratio="9:16"`, `image_size="2K"`. Returns the written path (FR-008).
**The caller must not put a URL in `prompt`** (FR-008a).
Inside a campaign the workflow additionally passes the user's product photograph as a reference on slides flagged `shows_product`, so the real container is reproduced rather than invented (FR-008b).

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
async def describe_video(video_path: str, frame_count: int = 8) -> str
```
ffmpeg extracts 5–10 frames → `describe_image` per frame → merged with the transcript (FR-004).

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

Both are served verbatim.

---

## Prompts

| Name | Arguments | Purpose |
|---|---|---|
| `story_campaign` | `topic: str`, `slide_count: int = 5` | Guides a chat client through a campaign: read both resources, then call `create_story_campaign`. |

---

## Python module contract (FR-015)

`src/instagram_story_agent/client.py` uses the in-memory client — no subprocess ([../research.md](../research.md) R4):

```python
from instagram_story_agent.client import run_campaign
campaign = await run_campaign(topic=None, slide_count=5)
```

`run_campaign` opens `Client(server)` against the same `MCPServer` object and calls `create_story_campaign`, so the module and the chat path exercise identical code.
