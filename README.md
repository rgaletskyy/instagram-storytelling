# instagram-marketing-agent

Turns local images and a markdown brief into ready-to-post Instagram story slides.

Give it a topic brief (`content/input/topic.md`) naming a product SKU plus some product photos, and it
looks the SKU up in the catalogue, describes the images, writes a slide-by-slide story script, generates
a 9:16 background per slide — compositing your real product photo rather than inventing packaging — lays the copy out in HTML around whatever is in that background, screenshots
it in a headless browser, checks the result against the brand guidelines, and saves the project to
`content/output/`.

Reachable three ways: an MCP server over stdio (for Claude and other AI chats), an MCP client, and a
code-callable module.

## Prerequisites

- Python 3.11+ (3.14 in `.venv`)
- Chromium for Playwright — slides are laid out in HTML and screenshotted
- `ANTHROPIC_API_KEY` and `GEMINI_API_KEY` in `.env`
- **ffmpeg only if you feed it video**; images-only campaigns need none

```bash
uv sync --extra dev
uv run playwright install chromium
cp .env.example .env   # then fill in the two keys
```

Put your source photos and a `topic.md` brief in `content/input/`; results land in
`content/output/`. Both folders are gitignored — only the app's own code is tracked.

Photos may be JPEG, PNG, WebP or **HEIC** straight off a phone; HEIC is converted and
oversized images are downscaled before they reach the vision API. Video (`.mov`, `.mp4`)
is sampled for frames and transcribed, and needs ffmpeg. Sampling takes up to 10 frames
spread across the whole clip.

A campaign keeps what it read from a video, under `<project>/source/<clip>/`:

```
source/IMG_1923/
  frame_01.jpg … frame_08.jpg   the sampled frames
  transcript.txt                 what was said
  frames.md                      the per-frame descriptions
```

## Usage

```bash
# from code
uv run instagram-marketing-agent --slides 5                # 9:16 story
uv run instagram-marketing-agent --slides 5 --format post  # 1:1 square feed post
uv run instagram-marketing-agent --slides 5 --no-verify    # skip the design review pass
uv run instagram-marketing-agent --lifestyle               # 3 lifestyle product photos (4:5)
uv run instagram-marketing-agent --lifestyle 6             # ...or however many

# as an MCP server (stdio)
uv run python -m instagram_marketing_agent.server
```

## Models

| Job | Model |
|---|---|
| Describe images / video frames | `claude-sonnet-5` |
| Write the campaign script | `claude-opus-5` |
| Generate a slide background | `gemini-3.1-flash-image` |
| Lay the slide out in HTML (sees the background) | `claude-sonnet-5` |
| Verify the rendered slide | `claude-sonnet-5` |
| Regenerate a slide background | `gemini-3-pro-image` |
| Transcribe extracted audio | `gemini-3.5-transcribe` |

## Formats

| Format | Artboard | Aspect | Safe area |
|---|---|---|---|
| `story` (default) | 1080×1920 | 9:16 | `y = 250…1670` — Instagram's UI covers the bands |
| `post` | 1080×1080 | 1:1 | the 72px margin; a feed post has no UI over it |
| `lifestyle` | 1080×1350 | 4:5 | none — lifestyle frames carry no copy |

Stories and posts run the same pipeline and the same brand rules; only the artboard
differs. Over MCP that is `create_story_campaign` vs `create_post_campaign`.

## Lifestyle content

A second workflow generates lifestyle product photography rather than a story. Write a
brief in `content/input/topic.md` naming the product SKU and the scene you want, then run
`--lifestyle` (or call `create_lifestyle_content` over MCP). Defaults to 3 images.

The count is **per product**: a brief naming three SKUs produces three sets. Frames are
named `{sku}-{index}-{role}.jpg`.

It reuses the campaign building blocks — SKU lookup, product-referenced generation,
verification — but stops at images: `src/resources/lifestyle-content-brief.md` makes text
baked into the picture an automatic reject, so there is no layout pass and copy is applied
later in design.

The packshot is downloaded from the catalogue's image URL. **A product whose image cannot
be obtained is skipped**, and reported under `skipped` with the reason — generating it
would produce a plausible bottle carrying an invented label, which is worse than no frame.

Around a sixth of the catalogue has no image URL. A photo in `content/input/` is accepted
as a fallback only when the brief names a single product: with several SKUs there is no way
to tell which one a loose photo depicts, and guessing puts the wrong packaging on a frame.

## One person per set

A campaign or lifestyle set defines a single `cast` — one person, described once by age,
build, hands and wardrobe. Every image that features a human carries that description, and
the verifier rejects a frame showing a different person or a second one. Without it each
image is generated independently and invents its own owner, so the same story ends up with
a different pair of hands on every slide.

## Product catalogue

`src/resources/products.xlsx` holds the product data and is **not** in version control. A
`products.sample.xlsx` with a few rows is committed so a fresh clone runs; drop your own
`products.xlsx` alongside it and the app picks it up automatically.

Columns read: `Артикул` (SKU, the lookup key), `Название (UA)`, `Цена`, `Фото`, `Ссылка`,
`Описание товара (UA)`.

SKUs are named inline in the brief — `content/input/topic.md` — for example
`... Face It up (BO-FIU150)`.

## Product fidelity

Any slide that features the product is generated with your own product photograph supplied as a
reference, so the real container, branding and label artwork appear. Put a clear packshot in
`content/input/`; the description step detects it automatically. Without one the image model will
invent plausible but fictional packaging.

Fine print on a generated label can still come out slightly garbled — image models are weak at small
text. It reads correctly at story scale; for a hero packshot, composite the real photo instead.

## Known deviations

Two places where the implementation knowingly differs from the source documents:

1. **Audio transcription model.** `requirements.md` specifies `gemini-3.1-flash-lite-image` for
   transcription. That model (Nano Banana 2 Lite) generates images and does not accept audio input, so it
   cannot do the job as written. Substituted Google's dedicated `gemini-3.5-transcribe`.

2. ~~**Fonts.**~~ **Resolved.** Slides render in a headless browser, so the page loads Bitter and Noto Sans
   from Google Fonts and the guidelines' mandated typefaces are used directly. This needs network access at
   render time.

See `specs/001-instagram-marketing-agent/` for the full spec, plan, and research.
