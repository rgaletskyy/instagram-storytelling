# Phase 1 Data Model: Instagram Story Telling Agent

**Date**: 2026-08-27 · **Feature**: [spec.md](./spec.md) · **Research**: [research.md](./research.md)

All models are Pydantic v2 (`pydantic` 2.13.4 installed) in `src/instagram_story_agent/models.py`. The script model doubles as the structured-output schema for the Opus call, so there is one definition, not two.

---

## Product

Source: `src/resources/products.xlsx` (see [research.md](./research.md) R7). Satisfies FR-005.

| Field | Type | Notes |
|---|---|---|
| `sku` | `str` | from `Артикул`; the lookup key, matched case-insensitively after trim |
| `name` | `str` | from `Название (UA)` |
| `price` | `str` | from `Цена` — kept as text; it is display copy, never arithmetic |
| `image_url` | `str` | from `Фото` |
| `product_url` | `str` | from `Ссылка` — the CTA link sticker (FR-006a) |
| `description` | `str` | from `Описание товара (UA)`, HTML-unescaped and tag-stripped to plain text |

**Rules**

- A SKU with no row is not an error: it is collected into `Campaign.missing_skus` and reported (FR-016, spec edge case).
- `product_url` is carried into the script and **never** into an image prompt (FR-008a).

---

## SlideSpec

One entry of the generated script, produced by Opus. Satisfies FR-006.

| Field | Type | Notes |
|---|---|---|
| `index` | `int` | 1-based position in the sequence |
| `role` | `Literal["hook","tension","solution","proof","offer","cta"]` | the narrative job from `story-telling-rules.md` §2 |
| `image_prompt` | `str` | passed verbatim to Gemini; must not contain a URL (FR-008a) |
| `overlay_text` | `str` | the copy drawn onto the slide, in the brief's language |
| `ig_notes` | `str` | stickers / polls / link to add at posting time — notes only, never rendered |
| `shows_product` | `bool` | true when the product container appears; gates the packshot reference (FR-008b) |
| `has_human` | `bool` | true when a person is in frame; gates the cast description (FR-008e) |

**Rules**

- `index` is contiguous from 1 and unique.
- Ordering follows the rules file: `hook` first, `cta` last, at most one `cta`.
- `overlay_text` is wrapped and clamped to the safe band at render time, not here.

---

## SlideVerdict

The verifier's judgement on one rendered slide. Satisfies FR-009b.

| Field | Type | Notes |
|---|---|---|
| `index` | `int` | the slide judged |
| `passed` | `bool` | false when any guideline or copy check fails |
| `issues` | `list[str]` | specific, actionable problems; empty when passed |
| `notes` | `str` | the reviewer's reasoning |

**Rules**

- A verdict that cannot be produced is recorded as `passed=False` with the reason, never as a pass — a silent pass would hide a broken verifier.
- Failing a verdict does not drop the slide; it is delivered flagged (FR-009c).

---

## CampaignScript

The whole generated script; the structured-output schema for the Opus call. Saved as `script.json` beside the slides.

| Field | Type | Notes |
|---|---|---|
| `topic` | `str` | the brief, verbatim |
| `slides` | `list[SlideSpec]` | length 3–7 (spec assumption; `story-telling-rules.md` §2) |
| `products` | `list[Product]` | resolved catalogue entries |
| `product_url` | `str \| None` | convenience copy of the primary product's link for the CTA (FR-006a) |
| `cast` | `str` | the one person appearing across the campaign — age, build, hands, wardrobe. Slides are generated independently, so without it each invents a different owner (FR-008e) |

**Rules**

- `3 <= len(slides) <= 7`, validated before any image is generated so an out-of-range request fails fast with no partial project (US1 scenario 4).

---

## MediaDescription

A described input asset. Satisfies FR-003 and FR-004.

| Field | Type | Notes |
|---|---|---|
| `path` | `Path` | file under `content/input/` |
| `kind` | `Literal["image","video"]` | |
| `description` | `str` | Sonnet's description; for video, the merged frame descriptions plus transcript |
| `transcript` | `str \| None` | video only; `None` when the file has no audio track (spec edge case) |
| `shows_product` | `bool` | true when this photo is usable as a packshot reference (FR-008c) |

---

## Campaign

The run and its result. Satisfies FR-011.

| Field | Type | Notes |
|---|---|---|
| `topic` | `str` | |
| `script` | `CampaignScript` | |
| `slide_paths` | `list[Path]` | rendered `.jpg` files, in slide order (FR-017) |
| `output_dir` | `Path` | `content/output/<slug>-<YYYYMMDD-HHMMSS>/` |
| `missing_skus` | `list[str]` | SKUs named in the brief but absent from the catalogue |
| `failed_slides` | `list[tuple[int, str]]` | `(index, error)` per slide that did not render (FR-016, SC-003) |
| `verdicts` | `list[SlideVerdict]` | one per rendered slide (FR-009b, SC-004a) |
| `product_references` | `list[Path]` | packshots fed to image generation; persisted so a revision need not re-describe every input |

**Rules**

- `output_dir` is derived from a slug of the topic plus a timestamp, so two runs on one topic never collide (spec edge case).
- A campaign with a non-empty `failed_slides` is still saved; the successful slides are kept.

---

## Brand Rules (read-only)

Not a Pydantic model — two files read as text and injected as prompt context, and published verbatim as MCP resources (FR-014).

| Resource URI | File |
|---|---|
| `content://slide-design-guidelines.md` | `src/resources/slide-design-guidelines.md` |
| `content://story-telling-rules.md` | `src/resources/story-telling-rules.md` |

`story-telling-rules.md` is context for script generation (FR-007); `slide-design-guidelines.md` is context for rendering (FR-009).

---

## Flow

```
topic.md ──► extract SKUs ──► Product[]  ─────────┐
                                                  │
content/input/*.jpg|png ──► describe ──► MediaDescription[] ──► CampaignScript
content/input/*.mp4 ──► frames + audio ──► describe/transcribe ─┘        │
                                                                         │
                                     ┌───────────────────────────────────┘
                                     ▼   (asyncio.gather, per slide)
       product photo (shows_product) ─────┐
                                          ▼
                       image_prompt ──► Gemini ──► background .jpg
                                     ──► Sonnet (sees background) ──► HTML/CSS
                                     ──► Playwright screenshot ──► slide .jpg
                                     ──► Sonnet verify ──► SlideVerdict
                                          └─ fail? re-lay out once with issues
                                     ▼
                      content/output/<slug>-<ts>/{1..N}.jpg + script.json (+ verdicts)
```
