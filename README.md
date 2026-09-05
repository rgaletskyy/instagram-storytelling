# instagram-marketing-agent

Turns local images and a markdown brief into ready-to-post Instagram story slides.

Give it a topic brief (`content/input/topic.md`) naming a product SKU plus some product photos, and it
looks the SKU up in the catalogue, describes the images, writes a slide-by-slide story script, generates
a 9:16 background per slide — compositing your real product photo rather than inventing packaging — lays the copy out in HTML around whatever is in that background, screenshots
it in a headless browser, reviews the finished set against the brand guidelines, lays out again any slide
that came back with an issue, and saves the project to `content/output/`.

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

# review slides someone else made, instead of generating any
uv run instagram-marketing-agent --verify-content          # reads content/input/
uv run instagram-marketing-agent --verify-content ~/slides # ...or any folder

# as an MCP server (stdio)
uv run python -m instagram_marketing_agent.server
```

## Models

| Job | Model |
|---|---|
| Describe images / video frames | `claude-sonnet-5` (configurable, see below) |
| Write the campaign script | `claude-opus-5` |
| Generate a slide background | `gemini-3.1-flash-image` |
| Lay the slide out in HTML (sees the background) | `claude-sonnet-5` |
| Review the finished slides | `claude-sonnet-5` |
| Regenerate a slide background | `gemini-3-pro-image` |
| Transcribe extracted audio | `gemini-3.5-transcribe` |

## Choosing the description model

The model that reads your photos is the one setting you can swap without
touching the code. Put it in `.env`:

```bash
DESCRIBE_MODEL=deepseek-v4-flash-vision-exp
DEEPSEEK_API_KEY=sk-...
```

Anything starting with `deepseek` goes to DeepSeek's chat-completions endpoint
(`DEEPSEEK_BASE_URL`, default `https://api.deepseek.com`); any other id is a
Claude model. Unset, it stays on `claude-sonnet-5`.

**Only the description pass moves.** Writing the script, laying a slide out and
verifying the render stay on Claude: they depend on its typed-output API, which
DeepSeek has no equivalent for. DeepSeek's vision model is asked for JSON in the
prompt instead, and a reply that will not parse fails the run rather than
falling back to a description with the reference flags dropped — those flags
decide which real photograph gets attached, and losing them silently is what
puts an invented label on the packaging.

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

## Reviewing content made by hand

`--verify-content` goes the other way: instead of generating slides it reads
finished ones. Drop the images an SMM manager built into `content/input/` and
run it -- each is described with the same pass that reads campaign input, then
judged against `slide-design-guidelines.md` and `smm_composition_rules.md`. The
same review is `verify_content` over MCP, and it takes a single image as
readily as a folder.

**A generated campaign ends with this same review.** Slides are no longer
checked one at a time as they render; the finished set is reviewed together,
and any slide the review raises an *issue* about is laid out again with those
issues fed back in — over the background it already has, so a layout complaint
never turns into a different photograph. Suggestions are recorded and left
alone. `script.json` keeps the review as it stood before those fixes, plus
`fixed_slides`. `--no-verify` skips the whole step.

It returns one entry per file with the issues found and the improvements
suggested, plus one entry for the set read in filename order. That last pass is
where the storytelling rules bite -- arc, momentum, one idea across the
sequence -- so a single post is reviewed on its own merits and never against a
structure it was never meant to have. Each finding names the section it comes
from. The artboard is read off each image's proportions; `format` overrides it.

## Subjects come from photographs, not from words

An image prompt describes the **scene**: the setting, the action, the light, the framing and
what to leave out. It never describes what the dog, the owner or the product *look like* —
no breed, coat, eye colour, hair, clothing or label wording.

Appearance comes from real photographs attached to the generation, picked from your input
photos and from the frames already sampled out of a supplied video.

**The catalogue photo of a SKU always wins for the packaging.** It is shot straight with the
label sharp; a video frame catches a bottle at an angle or half out of focus. A frame is
used for a product only when that SKU has no catalogue photo. A scene showing several
products gets a packshot for each — given one, the model invents the rest and then copies
its invention onto all of them. A subject described in
words is a subject the model reinvents: a different dog on every slide, a fictional label
on every bottle.

## Decorative element library

`src/resources/png/` holds the 194 outline PNGs catalogued in section 9 of the design
guidelines. They ship as dark outline art and the guidelines require recolouring before
use, so on first run they are tinted into the brand palette under `.decor-cache/`
(gitignored) and the layout step references them as `decor/<colour>/<file>.png`.

Colours: turquoise, pink, brown, white, grey — the tokens from section 2.1.

The tint is baked in Python rather than done with a CSS mask, because headless Chromium
does not render `mask-image`. Without the folder the app behaves exactly as before, drawing
its own accents in CSS.

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
