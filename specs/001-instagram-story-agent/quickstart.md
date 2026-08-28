# Quickstart & Validation: Instagram Story Telling Agent

**Feature**: [spec.md](./spec.md) · **Contract**: [contracts/mcp-tools.md](./contracts/mcp-tools.md)

How to run the feature and confirm it satisfies the spec. Implementation belongs in `tasks.md`, not here.

---

## Prerequisites

**1. Chromium for Playwright** — slides render in a browser ([research.md](./research.md) R9):

```bash
uv run playwright install chromium
```

**1b. ffmpeg — only needed for video input.** Images-only campaigns need none. Homebrew's build is fine now that no `drawtext` filter is required:

```bash
brew install ffmpeg      # optional; only if you feed the workflow a video
```

**2. Dependencies.** Three pins in `pyproject.toml` are wrong for what is installed, and one package is missing:

| Package | Pinned | Installed | Action |
|---|---|---|---|
| `anthropic` | `>=0.40` | 1.0.0 | raise to `>=1.0` (1.x is httpx2-based) |
| `mcp` | `>=1.2` | 2.1.0 | raise to `>=2.1` (`FastMCP` no longer exists) |
| `google-genai` | `>=2.3.0` | 2.19.0 | raise to `>=2.19` (Interactions API) |
| `openpyxl` | — | absent | **add** — required to read the catalogue |
| `playwright` | — | absent | **add** — renders slides; also needs `playwright install chromium` |

```bash
uv sync
```

**3. Credentials.** `cp .env.example .env` and fill in `ANTHROPIC_API_KEY` and `GEMINI_API_KEY`.

---

## Run it

Input is already in place: `content/input/topic.md` plus four images.

```bash
# Python module (FR-015)
uv run python -c "
import asyncio
from instagram_story_agent.client import run_campaign
c = asyncio.run(run_campaign(slide_count=5))
print(c['output_dir']); print(c['failed_slides'])
"

# or the CLI entry point
uv run instagram-story-agent --slides 5
```

### As an MCP server in a chat client

```bash
uv run python -m instagram_story_agent.server      # stdio
```

Register in the client config as command `uv`, args `["run","python","-m","instagram_story_agent.server"]`, cwd = repo root.

---

## Validation scenarios

Each maps to spec acceptance criteria. Run in order — 1 and 2 need no API keys.

### V1 — Catalogue lookup (FR-005, FR-001a)
```bash
uv run python -c "
from instagram_story_agent.products import extract_skus, get_products
brief = open('content/input/topic.md').read()
skus = extract_skus(brief); print('skus:', skus)
found, missing = get_products(skus); print('missing:', missing)
for p in found: print(p.sku, '|', p.name[:40], '|', p.price, '|', p.product_url)
"
```
**Expect**: `skus: ['BO-FIU150']`, `missing: []`, one row printed with a non-empty `product_url`.
**Fails the spec if**: the description still contains `&lt;p&gt;` or raw HTML tags (R7).

### V2 — Slide count is bounded (US1 scenario 4)
Request 2 slides and 9 slides.
**Expect**: both rejected naming the 3–7 range, and **no** new directory under `content/output/`.

### V3 — End-to-end campaign (US1, FR-002, FR-010, FR-011)
Run the module command above with `slide_count=5`.
**Expect**: a new `content/output/<slug>-<YYYYMMDD-HHMMSS>/` holding `1.jpg`…`5.jpg` and `script.json`; `failed_slides` empty; existing `stories-20260826-001638/` untouched.
**Timing (SC-002)**: under 5 minutes.

### V4 — Script quality (FR-006, FR-006a, FR-007, SC-005)
Open `script.json`.
**Expect**: 5 entries each carrying `image_prompt`, `overlay_text`, `ig_notes`; `role` running hook → … → `cta` with exactly one `cta` last; `product_url` present; copy in Ukrainian, matching the brief's language.

### V5 — URL never reaches the imagery (FR-008a, SC-005a)
```bash
grep -c healthydoggo.com.ua content/output/<project>/script.json   # expect >= 1
python -c "
import json; s=json.load(open('content/output/<project>/script.json'))
assert not any('http' in x['image_prompt'] for x in s['slides']), 'URL leaked into an image prompt'
print('ok')
"
```
Then look at the five slides: **no URL text may appear in any image**.

### V6 — Safe zone and typography (FR-009, FR-009a, SC-004)
Overlay the band `y = 250…1670` on each slide.
**Expect**: all text inside it; nothing under the IG progress bar or the reply field; copy placed clear of the dog's face and the product; headings set in Bitter and body copy in Noto Sans (the R6 font deviation is resolved by browser rendering).

### V6b — Verification (FR-009b, FR-009c, SC-004a)
```bash
python -c "
import json; d=json.load(open('content/output/<project>/script.json'))
for v in d['verdicts']: print(v['index'], 'PASS' if v['passed'] else 'FAIL', v['issues'])
"
```
**Expect**: one verdict per slide. A failing verdict must name specific problems, and its slide must still be present on disk — verification flags, it does not delete.

### V7 — Single-slide revision (US3, FR-012, SC-007)
```bash
md5 content/output/<project>/*.jpg > /tmp/before.txt
# regenerate_slide(project_dir=..., slide_index=3, comment="коротший заголовок, світліший фон")
md5 content/output/<project>/*.jpg > /tmp/after.txt
diff /tmp/before.txt /tmp/after.txt
```
**Expect**: exactly one line differs — slide 3.

### V8 — Partial failure is survivable (FR-016, SC-003)
Force one slide to fail (revoke the Gemini key mid-run, or point one prompt at a bad model).
**Expect**: the run completes, the project is saved with the slides that succeeded, and `failed_slides` names the failed index and reason. **Not** an aborted run with nothing written.

### V9 — MCP surface (US2, FR-013, FR-014, SC-006)
```bash
npx @modelcontextprotocol/inspector uv run python -m instagram_story_agent.server
```
**Expect**: 10 tools listed (`validate_slide` absent by design), both `content://` resources readable, and `describe_image` returning prose for a file in `content/input/`.

---

## Tests

```bash
uv run pytest -m unit         # no network: SKU regex, HTML strip, layout/verify orchestration
uv run pytest -m contract     # tool schemas + in-memory Client against MCPServer
uv run pytest -m integration  # live keys; slow
```

The in-memory `Client(server)` from R4 is what makes contract tests cheap — no subprocess, no transport.
